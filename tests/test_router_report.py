"""路由表现：越用越省的同时，任务质量有没有变差（设置 → 路由表现）。

一个任务的决策和之后的结果信号按任务 id 对上（升级前的旧记录没有 id，按时间和配置对上）；
"出问题"只看明确的坏信号；"省下"是所选配置比最可靠的配置少花多少（估算）；后台对比看便宜的配置答得一样好的次数。"""

import json

import pytest

from super_aide import paths
from super_aide.config import Config, EngineSettings, ModelEntry
from super_aide.router import EngineRouter, Task, report
from super_aide.router.judge import Verdict

DAY = 86400.0
NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def isolated_router_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ROUTER", tmp_path)


def decision(t, task, model="claude-opus-5-5", effort="high", ref="claude-opus-5-5 · high", cost=1.0, ref_cost=1.0,
             via="router", kind="qa_factual", domain="general"):
    return {"t": t, "type": "decision", "mode": "ask", "kind": kind, "domain": domain, "band": 0, "engine": "claude",
            "model": model, "effort": effort, "via": via, "task": task, "cost": cost, "ref": ref, "ref_cost": ref_cost}


def outcome(t, task, source, success, model="claude-opus-5-5", effort="high"):
    return {"t": t, "type": "outcome", "mode": "ask", "kind": "qa_factual", "domain": "general", "engine": "claude",
            "model": model, "effort": effort, "task": task, "source": source, "success": success}


def test_quality_and_savings_are_counted_per_task():
    t = NOW - DAY
    records = [
        decision(t, "a"), outcome(t + 5, "a", "status_ok", 1.0),
        decision(t, "b"), outcome(t + 5, "b", "status_fail", 0.0),                       # 没办成：出问题
        decision(t, "c", "claude-sonnet-5-5", "medium", cost=0.4),                      # 换成了更省的
        outcome(t + 5, "c", "status_ok", 1.0), outcome(t + 60, "c", "feedback", 1.0),
        decision(t, "d", "claude-sonnet-5-5", "medium", cost=0.4), outcome(t + 5, "d", "negative_followup", 0.0),
        decision(t, "e"), decision(t + 1, "e", "gpt-6-astra", "high", ref="gpt-6-astra · high"),  # 服务出错换了配置：同一个任务
        decision(t, "e", via="escalated"),                                              # 加强不算新任务
        outcome(t + 9, "x", "duel", 1.0), outcome(t + 9, "a", "duel_ref", 1.0),        # 后台对比：一样好
        outcome(t + 19, "x", "duel", 0.0), outcome(t + 19, "b", "duel_ref", 1.0),      # 后台对比：差一些
    ]
    r = report.build(records=records, now=NOW)
    cur = r["current"]
    assert cur["tasks"] == 5 and cur["problems"] == 2 and cur["problem_rate"] == pytest.approx(0.4)
    assert cur["downgraded"] == 2 and cur["down_problem_rate"] == pytest.approx(0.5)
    assert cur["ref_problem_rate"] == pytest.approx(1 / 3)
    assert cur["saving"] == pytest.approx((0.6 + 0.6) / 5)
    assert (cur["duels"], cur["duels_as_good"]) == (2, 1)
    assert r["previous"]["tasks"] == 0 and r["weeks"][-1]["tasks"] + r["weeks"][-2]["tasks"] == 5


def test_old_records_without_task_ids_are_matched_by_time_and_config():
    t = NOW - 2 * DAY
    old = {"t": t, "type": "decision", "mode": "ask", "kind": "qa_factual", "domain": "general", "band": 0,
           "engine": "claude", "model": "claude-opus-5-5", "effort": "high", "via": "router", "reason": "先保证办成",
           "candidates": [{"arm": "claude-opus-5-5 · high", "engine": "claude", "cost": 0.5}]}
    reask = {k: v for k, v in outcome(t + 120, "", "reask", 0.0).items() if k != "task"}
    stale = {k: v for k, v in outcome(t + 3 * 3600, "", "status_fail", 0.0).items() if k != "task"}  # 太久以后的不算它的
    r = report.build(records=[old, reask, stale, {"t": t, "mode": "ask"}], now=NOW)  # 最早的记录连 type 都没有
    assert r["current"]["tasks"] == 1 and r["current"]["problems"] == 1 and r["current"]["saving"] == 0


@pytest.mark.parametrize("cur, expected", [
    ({"tasks": 3}, "数据还少（3 次）"),
    ({"tasks": 40, "downgraded": 0, "duels": 10, "duels_as_good": 7}, "一直用最可靠的配置"),
    ({"tasks": 40, "downgraded": 3}, "开始在部分任务上换用更省的配置（3 次）"),
    ({"tasks": 40, "downgraded": 12, "down_problem_rate": 0.08, "ref_problem_rate": 0.1, "saving": 0.2}, "质量没变差：换成更省配置的任务出问题的比例 8%"),
    ({"tasks": 40, "downgraded": 12, "down_problem_rate": 0.3, "ref_problem_rate": 0.1, "saving": 0.2}, "更省的配置出问题偏多（30% 对 10%）"),
])
def test_verdicts(cur, expected):
    base = {"tasks": 0, "downgraded": 0, "duels": 0, "duels_as_good": 0, "down_problem_rate": None,
            "ref_problem_rate": None, "saving": None}
    assert report.verdict(base | cur).startswith(expected)


def test_a_router_that_learned_shows_what_it_changed():
    """真实的路由：后台对比一直一样好 → 一般问答换成更省的配置；决策记录里带着参照和花费，路由表现看得出省了多少。"""
    cfg = Config(claude=EngineSettings(models=[ModelEntry(m, True) for m in ("claude-opus-5-5", "claude-sonnet-5-5")]),
                 codex=EngineSettings(enabled=False))
    cfg.shadow_daily = 10_000
    r = EngineRouter(cfg, gui_official=False)
    for _ in range(70):
        task = Task("ask", "这是什么意思", "text")
        d = r.decide(task)
        c = r.duel_candidate(d)
        if c is not None:
            r.record_duel(d, c, task, Verdict(1.0, 1.0))
    later = [r.decide(Task("ask", "这是什么意思", "text")) for _ in range(3)]
    assert all(d.cost < d.ref_cost and d.task for d in later)
    logged = [json.loads(line) for line in (paths.ROUTER / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all("ref_cost" in x and x["task"] for x in logged if x["type"] == "decision")
    result = report.build(r)
    assert result["current"]["tasks"] == 73 and result["current"]["downgraded"] >= 3
    assert result["current"]["saving"] > 0 and result["current"]["duels"] > 0
    learned = result["learned"]
    assert learned and learned[0]["change"] == "cheaper" and learned[0]["label"] == "一般问答"
    assert learned[0]["saving"] > 0.15 and learned[0]["confidence"] >= 0.9


def test_a_fresh_router_has_nothing_learned():
    r = EngineRouter(Config(), gui_official=False)
    r.decide(Task("ask", "这是什么意思", "text"))
    assert report.build(r)["learned"] == []
