"""安卓端路由移植的对照数据：用桌面版的 Python 实现算一批用例，Kotlin 的测试（RouterParityTest）逐条比对。

桌面版的路由逻辑改了而这里没重新生成，CI 的 --check 会失败（提醒安卓端跟着改）。
用法：uv run python scripts/android/gen_fixtures.py [--check]
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from super_aide.config import EFFORTS  # noqa: E402
from super_aide.router import catalog, judge, report  # noqa: E402
from super_aide.router.catalog import Profile  # noqa: E402
from super_aide.router.evidence import Evidence, Outcome, transfer  # noqa: E402
from super_aide.router.policy import EngineRouter, Scored, noninferior, superior  # noqa: E402

OUT = ROOT / "android" / "core" / "src" / "test" / "resources" / "parity" / "router.json"


def scored(rng: random.Random, i: int) -> dict:
    tier = rng.randrange(3)
    return {
        "engine": rng.choice(["claude", "openai"]), "model": f"m{tier}-{i % 3}", "tier": tier,
        "effort": rng.choice(EFFORTS), "alpha": round(rng.uniform(0.2, 30), 6), "beta": round(rng.uniform(0.05, 20), 6),
        "real": round(rng.uniform(0, 12), 6), "cost": round(rng.uniform(0.005, 0.4), 6), "prior": round(rng.uniform(0.2, 0.99), 6),
        "order": i % 4,
    }


def to_py(s: dict) -> Scored:
    p = Profile(engine=s["engine"], id=s["model"], tier=s["tier"], efforts=tuple(EFFORTS), skill=0.8, price=(1.0, 1.0), order=s["order"])
    return Scored(p, s["effort"], s["alpha"], s["beta"], s["real"], s["cost"], s["prior"])


def build() -> dict:
    rng = random.Random(20261019)
    out: dict = {}

    out["erf"] = [[x, math.erf(x)] for x in [i / 37 - 5 for i in range(371)] + [-31.0, 31.0, 1.4999, 1.5, 1.5001]]

    pairs = []
    for i in range(300):
        c, r = scored(rng, i), scored(rng, i + 1)
        pc, pr = to_py(c), to_py(r)
        pairs.append({"c": c, "r": r, "noninferior": noninferior(pc, pr), "superior": superior(pc, pr),
                      "mean": pc.mean, "var": pc.var})
    out["pairs"] = pairs

    rows = []
    for (oe, ok, ot, e, t) in itertools.product(range(5), (True, False), range(3), range(5), range(3)):
        for same_model in (True, False):
            for same_engine in (True, False):
                rows.append({"o_engine": "a", "o_model": "x" if same_model else "y", "o_eidx": oe, "ok": ok, "o_tier": ot,
                             "engine": "a" if same_engine else "b", "model": "x", "tier": t, "eidx": e,
                             "k": transfer("a", "x" if same_model else "y", oe, ok, ot, "a" if same_engine else "b", "x", t, e)})
    out["transfer"] = rows

    # 证据：一批结果 → gather（按"现在"的时刻）→ 对每个配置 counts
    now = 1_792_400_000.0
    kinds = [("qa_factual", "general"), ("qa_factual", "ui_help"), ("translation", "screen_text"), ("agentic", "chat")]
    outcomes = []
    for i in range(400):
        kind, domain = rng.choice(kinds)
        outcomes.append({"t": now - rng.uniform(0, 200 * 86400), "mode": rng.choice(["ask", "act"]), "kind": kind, "domain": domain,
                         "engine": rng.choice(["claude", "openai"]), "model": rng.choice(["m0-0", "m1-0", "m2-0", "m1-1"]),
                         "effort": rng.choice(EFFORTS), "y": rng.choice([0.0, 0.5, 1.0, 1.0]), "w": rng.choice([0.1, 0.3, 0.7, 1.0]),
                         "source": "test"})
    ev = Evidence(Path("/nonexistent/outcomes.jsonl"))
    ev.items = [Outcome(**o) for o in outcomes]
    tiers = {"m0-0": 0, "m1-0": 1, "m1-1": 1, "m2-0": 2}
    counts = []
    for mode, (kind, domain) in itertools.product(["ask", "act"], kinds):
        buckets = ev.gather(mode, kind, domain, None, now=now)
        for engine, model, eidx in itertools.product(["claude", "openai"], tiers, range(5)):
            s, f = Evidence.counts(buckets, engine, model, tiers[model], eidx, lambda e, m: tiers[m])
            counts.append({"mode": mode, "kind": kind, "domain": domain, "engine": engine, "model": model, "eidx": eidx, "s": s, "f": f})
    out["evidence"] = {"now": now, "outcomes": outcomes, "tiers": tiers, "counts": counts}

    # 参照和降级：给定一批候选，桌面版的 _reference / _pick 选谁
    picks = []
    for i in range(120):
        cands = [scored(rng, i * 10 + j) for j in range(rng.randrange(2, 9))]
        py = [to_py(s) for s in cands]
        fake = SimpleNamespace(_best=EngineRouter._best, _score=lambda view, engines, py=py: py)
        fake._reference = lambda scored, fake=fake: EngineRouter._reference(fake, scored)
        chosen, ref, default, confidence, _ = EngineRouter._pick(fake, None, [])
        picks.append({"candidates": cands, "chosen": py.index(chosen), "ref": py.index(ref), "default": py.index(default),
                      "confidence": confidence})
    out["picks"] = picks

    judged = []
    for text in ['{"a":"ok","b":"bad","better":"a","why":"B 错了"}', '前面有字 {"a": "ok", "b": "ok", "better": "same", "why": "都对"} 后面',
                 '{"a":"bad","b":"ok","better":"b"}', '{"a":"ok","b":"ok","better":"b","why":"x"}', "没有 JSON", '{"a":"maybe"}']:
        for flip in (False, True):
            v = judge.parse(text, flip)
            judged.append({"text": text, "flip": flip, "verdict": None if v is None else [v.candidate, v.served]})
    out["judge"] = judged

    # 路由表现：一批决策和结果信号 → 桌面版 report 的任务统计
    records = []
    t0 = now - 50 * 86400
    for i in range(160):
        t = t0 + i * 6 * 3600 + rng.uniform(0, 3000)
        task = f"task{i}"
        arm_model, effort = rng.choice(["m0-0", "m1-0", "m2-0"]), rng.choice(EFFORTS)
        ref = rng.choice([f"{arm_model} · {effort}", "m0-0 · high"])
        records.append({"t": t, "type": "decision", "mode": "ask", "kind": "qa_factual", "domain": "general", "band": 0,
                        "engine": "claude", "model": arm_model, "effort": effort, "via": rng.choice(["router", "router", "escalated"]),
                        "task": task, "cost": round(rng.uniform(0.01, 0.2), 4), "ref": ref, "ref_cost": round(rng.uniform(0.05, 0.3), 4)})
        for _ in range(rng.randrange(0, 3)):
            records.append({"t": t + rng.uniform(1, 600), "type": "outcome", "task": task,
                            "source": rng.choice(["status_ok", "status_fail", "feedback", "reask", "negative_followup"]),
                            "success": rng.choice([0.0, 1.0])})
        if rng.random() < 0.2:
            records.append({"t": t + 900, "type": "outcome", "task": task, "source": "duel", "success": rng.choice([0.0, 0.5, 1.0])})
            records.append({"t": t + 901, "type": "outcome", "task": task, "source": "duel_ref", "success": rng.choice([0.5, 1.0])})
    records.sort(key=lambda r: r["t"])
    tasks, duels = report.tasks_and_duels(records)
    window = report.WINDOW_DAYS * 86400
    periods = {name: report._period(tasks, duels, a, b) for name, (a, b) in
               {"current": (now - window, now + 1), "previous": (now - 2 * window, now - window)}.items()}
    out["report"] = {"now": now, "records": records, "periods": periods,
                     "verdict": report.verdict(periods["current"])}

    # 经验库：分词、压缩、报错行，以及一批经验 + 情况 → 桌面版 recall 想起哪几条
    import tempfile
    from super_aide.experience import recall as xrecall
    from super_aide.experience.store import Store as XStore
    texts = ["ModuleNotFoundError: No module named 'torch'", "微信转账一直提示失败，怎么回事", "AutoTokenizer.from_pretrained 报错",
             "pip install 超时了 Read timed out", "蓝牙耳机连不上 HUAWEI FreeBuds", "error 0x80070643 安装失败", "这个页面怎么设置深色模式？",
             "Wi-Fi 一直显示已连接但不可上网", "a", "我", "用户名或密码错误 login failed (401)"]
    out_tokens = [{"text": t, "tokens": xrecall.tokens(t), "compact": xrecall.compact(t), "errors": xrecall.error_lines(t)} for t in texts]
    lessons = [
        {"id": "L1", "title": "Python 找不到模块先看环境", "when": "运行脚本报找不到模块", "advice": "先确认用的是哪个解释器",
         "triggers": ["找不到模块", "No module named", "导入失败", "ModuleNotFoundError"], "errors": ["ModuleNotFoundError"], "apps": [], "domains": []},
        {"id": "L2", "title": "微信转账失败多半是限额", "when": "微信转账提示失败", "advice": "先看零钱和银行卡的单日限额",
         "triggers": ["转账失败", "转账提示失败", "限额", "transfer failed"], "errors": [], "apps": ["com.tencent.mm"], "domains": []},
        {"id": "L3", "title": "pip 超时换国内镜像", "when": "pip 安装超时", "advice": "加 -i 清华镜像",
         "triggers": ["Read timed out", "pip 超时", "下载慢", "镜像"], "errors": ["Read timed out"], "apps": [], "domains": ["pypi.org"]},
        {"id": "L4", "title": "蓝牙耳机连不上先删配对", "when": "已配对的耳机连不上", "advice": "删除配对再重新配对",
         "triggers": ["连不上", "蓝牙耳机", "配对", "bluetooth"], "errors": [], "apps": ["com.android.settings"], "domains": []},
    ]
    situations = [
        {"question": "运行报 ModuleNotFoundError 怎么办"}, {"question": "微信转账一直提示失败", "app": "com.tencent.mm"},
        {"question": "转账失败了"}, {"question": "pip install 很慢", "errors": "ReadTimeoutError: Read timed out."},
        {"question": "耳机连不上", "app": "com.android.settings"}, {"question": "你好"}, {"question": "蓝牙耳机配对不上了"},
        {"question": "下载慢", "url": "https://pypi.org/project/torch"},
    ]
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "lessons.json"
        path.write_text(json.dumps({"version": 1, "lessons": lessons}, ensure_ascii=False), encoding="utf-8")
        store = XStore(path)
        recalled = [{"situation": sit, "ids": [x.id for x in xrecall.recall(store, xrecall.Situation(**sit))]} for sit in situations]
    out["experience"] = {"tokens": out_tokens, "lessons": lessons, "recall": recalled}

    ids = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-4-6", "claude-opus-4-5-20251101",
           "claude-haiku-4-5-20251001", "claude-sonnet-4-20250514", "claude-fable-5-1", "gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna",
           "deepseek-flash", "gpt-5.6-terra", "qwen-max", "o4-mini"]
    out["catalog"] = [{"id": i, "tier": catalog.tier_of(i), "version": catalog.claude_version(i), "efforts": list(catalog.claude_efforts(i))}
                      for i in ids]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = json.dumps(build(), ensure_ascii=False, indent=None, separators=(",", ":")) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("对照数据过期了：运行 uv run python scripts/android/gen_fixtures.py，再跑安卓端的 RouterParityTest", file=sys.stderr)
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"写好了：{OUT.relative_to(ROOT)}（{len(text) // 1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
