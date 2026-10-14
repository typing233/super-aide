"""路由表现（设置 → 可路由的模型 → 路由表现）：路由在线学习，越用越会挑更省的配置，可"省了"的同时任务质量有没有变差，
要拿记录说话。数据都在 decisions.jsonl（每次决策和之后的结果信号）里，这里只读不改。

- 任务：每次提问的那个决策（服务出错换了配置接着做的，算同一个任务，以最后用的为准；后台对比不算任务）。
- 出问题：这个任务之后收到了明确的"没办好"信号——没办成、👎、追问说"不对"、很快又问了一样的、转交没办成。
  "正常结束"几乎说明不了答得好不好，所以不把它当成"没问题"的证据，只是没有坏信号。
- 省下：所选配置的估算花费（美元 + 耗时折算，和路由决策用的同一把尺子）比"一直用最可靠的配置"少多少。只是估算。
- 守没守住：换成便宜配置的任务里出问题的比例，和用最可靠配置的任务比。降级的门槛（非劣效检验）要是没守住，
  这两个数会拉开；路由自己也会因为这些失败退回更可靠的配置。
- 后台对比：便宜的配置在后台把同一个问题再答一遍，被评成和你看到的那份一样好的次数。
- 学到的：现在每类任务实际会用的配置，和最可靠的那个不一样的（router.learned）。

升级前的记录没有任务 id、没有参照的花费：按时间和配置对上结果，花费从当时的候选里找。
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from .. import paths
from ..i18n import tr

log = logging.getLogger(__name__)

WINDOW_DAYS = 30
WEEKS = 8
LEARNED_DAYS = 90       # 学到的：最近这么久出现过的任务类型
#: 结果信号里算"出问题"的（y < 0.5 时）
PROBLEM_SOURCES = {"status_fail", "feedback", "negative_followup", "reask", "delegate_result"}
#: 算一个任务的决策（escalated 是同一个任务里加强，duel 是后台对比）
TASK_VIAS = {"router", "rules", "pinned", "llmrouter"}
OLD_MATCH_S = 2 * 3600  # 没有任务 id 的旧记录：结果离决策最多这么久才算它的
MIN_TASKS = 5           # 少于这么多次不下结论
MIN_DOWNGRADED = 5      # 换成便宜配置的少于这么多次，质量还看不出来
QUALITY_GAP = 0.05      # 便宜配置出问题的比例比最可靠的高出这么多以内，算"没变差"


def read(path: Path | None = None) -> list[dict]:
    path = path or paths.ROUTER / "decisions.jsonl"
    out = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("type") in ("decision", "outcome") and "t" in record:
            out.append(record)
    return out


def _arm(r: dict) -> str:
    return f"{r.get('model', '')} · {r.get('effort', '')}"


def _costs(r: dict) -> tuple[float, float, bool]:
    """→ (所选配置的估算花费, 最可靠的配置的估算花费, 是不是换成了更便宜的)。没有参照的花费时两个都是 0。"""
    if "ref_cost" in r:
        cost, ref_cost = float(r.get("cost") or 0), float(r.get("ref_cost") or 0)
        return cost, ref_cost, bool(r.get("ref")) and r["ref"] != _arm(r)
    # 旧记录：花费从当时的候选里找；那时降级的理由里写着"已证明和最可靠的配置（…）几乎一样"
    candidates = {c.get("arm"): float(c.get("cost") or 0) for c in r.get("candidates") or []}
    cost = candidates.get(_arm(r), 0.0)
    reason = str(r.get("reason") or "")
    if "已证明" in reason and "（" in reason:
        ref = reason.split("（", 1)[1].split("）", 1)[0]
        return cost, candidates.get(ref, 0.0), True
    return cost, cost, False


def tasks_and_duels(records: list[dict]) -> tuple[list[dict], list[dict]]:
    tasks: dict[str, dict] = {}
    old: list[tuple[dict, dict]] = []  # 没有任务 id 的旧决策 → 它的任务
    for r in records:
        if r.get("type") != "decision" or r.get("via") not in TASK_VIAS:
            continue
        key = r.get("task") or f"old-{r['t']}"
        task = tasks.get(key)
        if task is None:
            task = tasks[key] = {"t": float(r["t"]), "mode": r.get("mode", ""), "signals": []}
            if not r.get("task"):
                old.append((r, task))
        task["decision"] = r  # 换了配置接着做的：以最后用的为准
    duels: list[dict] = []
    last_duel: dict | None = None
    for o in records:
        if o.get("type") != "outcome":
            continue
        source = o.get("source", "")
        if source == "duel":
            last_duel = o
            continue
        if source == "duel_ref":  # 后台对比：先记候选（duel），紧接着记你看到的那份（duel_ref）
            if last_duel is not None and abs(float(o["t"]) - float(last_duel["t"])) < 30:
                duels.append({"t": float(o["t"]), "as_good": float(last_duel.get("success") or 0)
                              >= float(o.get("success") or 0)})
            last_duel = None
            continue
        task = tasks.get(o.get("task") or "") or _guess(o, old)
        if task is not None:
            task["signals"].append((source, float(o.get("success") or 0)))
    out = []
    for task in tasks.values():
        cost, ref_cost, downgraded = _costs(task["decision"])
        out.append({"t": task["t"], "mode": task["mode"], "downgraded": downgraded,
                    "saving": max(0.0, 1 - cost / ref_cost) if ref_cost > 0 else None,
                    "problem": any(s in PROBLEM_SOURCES and y < 0.5 for s, y in task["signals"]),
                    "kind": (task["decision"].get("mode", ""), task["decision"].get("kind", ""),
                             task["decision"].get("domain", ""), int(task["decision"].get("band") or 0))})
    return sorted(out, key=lambda x: x["t"]), duels


def _guess(o: dict, old: list[tuple[dict, dict]]) -> dict | None:
    """旧记录：结果之前最近的那个同类任务、同一个配置的决策（很快又问的"没答好"记在上一个任务上，正好是它）。"""
    t = float(o["t"])
    for r, task in reversed(old):
        if float(r["t"]) > t + 2:
            continue
        if t - float(r["t"]) > OLD_MATCH_S:
            return None
        if all(r.get(k) == o.get(k) for k in ("mode", "kind", "domain", "engine", "model")):
            return task
    return None


def _period(tasks: list[dict], duels: list[dict], start: float, end: float) -> dict:
    ts = [x for x in tasks if start <= x["t"] < end]
    down = [x for x in ts if x["downgraded"]]
    rest = [x for x in ts if not x["downgraded"]]
    savings = [x["saving"] for x in ts if x["saving"] is not None]
    ds = [d for d in duels if start <= d["t"] < end]

    def rate(group: list[dict]) -> float | None:
        return sum(x["problem"] for x in group) / len(group) if group else None

    return {"tasks": len(ts), "problems": sum(x["problem"] for x in ts), "problem_rate": rate(ts),
            "saving": sum(savings) / len(savings) if savings else None, "downgraded": len(down),
            "down_problem_rate": rate(down), "ref_problem_rate": rate(rest),
            "duels": len(ds), "duels_as_good": sum(d["as_good"] for d in ds)}


def _pct(x: float | None) -> int:
    return round((x or 0) * 100)


def verdict(cur: dict) -> str:
    """一句话结论：质量变没变差、省了多少。"""
    n = cur["tasks"]
    if n < MIN_TASKS:
        return tr("数据还少（{n} 次），多用一阵才看得出趋势。", n=n)
    if not cur["downgraded"]:
        return tr("一直用最可靠的配置：更省的配置还没证明一样能办成，所以还没换。后台对比在攒证据（{duels} 次里 {good} 次一样好）。",
                  duels=cur["duels"], good=cur["duels_as_good"])
    if cur["downgraded"] < MIN_DOWNGRADED:
        return tr("开始在部分任务上换用更省的配置（{n} 次），质量还要再看几次。", n=cur["downgraded"])
    down, ref = cur["down_problem_rate"] or 0, cur["ref_problem_rate"] or 0
    if down - ref <= QUALITY_GAP:
        return tr("质量没变差：换成更省配置的任务出问题的比例 {down}%，用最可靠配置的 {ref}%；平均省了约 {saving}%。",
                  down=_pct(down), ref=_pct(ref), saving=_pct(cur["saving"]))
    return tr("更省的配置出问题偏多（{down}% 对 {ref}%）：路由会根据这些失败自动退回更可靠的配置。",
              down=_pct(down), ref=_pct(ref))


def _week_start(now: float) -> datetime:
    day = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def build(router=None, records: list[dict] | None = None, now: float | None = None) -> dict:
    """设置页要的全部数字。router 给了就顺带算"学到的"（要在引擎线程里调用）。"""
    now = time.time() if now is None else now
    records = read() if records is None else records
    tasks, duels = tasks_and_duels(records)
    window = WINDOW_DAYS * 86400
    cur = _period(tasks, duels, now - window, now + 1)
    prev = _period(tasks, duels, now - 2 * window, now - window)
    monday = _week_start(now)
    weeks = []
    for i in range(WEEKS - 1, -1, -1):
        start = monday - timedelta(weeks=i)
        week = _period(tasks, duels, start.timestamp(), (start + timedelta(weeks=1)).timestamp())
        weeks.append({"start": start.date().isoformat(), **week})
    learned = []
    if router is not None:
        recent = [x["kind"] for x in tasks if x["t"] >= now - LEARNED_DAYS * 86400]
        kinds = {}
        for kind, _n in Counter(recent).most_common():  # 每类任务按最常见的难度档看
            kinds.setdefault(kind[:3], kind)
        try:
            learned = router.learned(list(kinds.values()))
        except Exception as e:  # noqa: BLE001 - 算不出来就不列
            log.warning("路由表现：算学到的配置失败：%s", e)
        for item in learned:
            item["label"] = tr(item["label"])
    return {"current": cur, "previous": prev, "weeks": weeks, "since": tasks[0]["t"] if tasks else None,
            "verdict": verdict(cur), "learned": learned, "window_days": WINDOW_DAYS}
