"""先保证办成，再求快、求省：模型档案、降级要过非劣效检验、思考强度随证据升降、后台对比、改模型集不丢学习记录。"""

import json
import random

import pytest

from super_aide import paths
from super_aide.config import Config, EngineSettings, ModelEntry
from super_aide.router import EngineRouter, Task, catalog, judge
from super_aide.router.evidence import Outcome
from super_aide.router.judge import Verdict
from super_aide.router.policy import EFFORTS, Scored, noninferior, superior

QUESTION = Task("ask", "这是什么意思", "text")
CODEX_META = {
    "gpt-6-astra": {"efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
                    "desc": "Frontier intelligence for the most demanding work."},
    "gpt-6.1-sol": {"efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
                    "desc": "Latest workhorse model for coding and everyday work."},
    "gpt-6-luna": {"efforts": ["low", "medium", "high", "xhigh", "max"], "desc": "Fast and affordable model for easier tasks."},
}


@pytest.fixture(autouse=True)
def isolated_router_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ROUTER", tmp_path)


def six_models() -> Config:
    paths.ROUTER.mkdir(parents=True, exist_ok=True)
    (paths.ROUTER / "models.json").write_text(json.dumps({"codex": CODEX_META}), encoding="utf-8")
    return Config(claude=EngineSettings(models=[ModelEntry(m, True) for m in
                                                ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")]),
                  codex=EngineSettings(models=[ModelEntry(m, True) for m in ("gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna")]))


def router(cfg: Config | None = None, **kw) -> EngineRouter:
    cfg = cfg or six_models()
    cfg.shadow_daily = kw.pop("daily", 10_000)
    return EngineRouter(cfg, gui_official=kw.pop("gui_official", False))


def duel_rounds(r: EngineRouter, task: Task, n: int, bad: dict[str, float] | None = None, seed: int = 1) -> dict:
    """模拟 n 次提问：每次照路由的选择回答，再在后台对比一次。bad：模型 → 被评审判为有错的概率。"""
    rng, served = random.Random(seed), {}
    for _ in range(n):
        d = r.decide(task)
        served[(d.model, d.effort)] = served.get((d.model, d.effort), 0) + 1
        c = r.duel_candidate(d)
        if c is not None:
            score = lambda model: 0.0 if rng.random() < (bad or {}).get(model, 0.0) else 1.0  # noqa: E731
            r.record_duel(d, c, task, Verdict(score(c.model), score(d.model)))
    return served


# ---------- 模型档案 ----------

def test_tiers_from_names_and_codex_descriptions():
    assert [catalog.tier_of(m) for m in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")] == [0, 1, 2]
    assert [catalog.tier_of(m) for m in ("gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna")] == [0, 1, 2]
    assert catalog.tier_of("gpt-7", "Frontier intelligence for the most demanding work.") == 0
    assert catalog.tier_of("gpt-7", "Fast and affordable model for easier tasks.") == 2
    assert catalog.tier_of("some-new-model") == 1  # 不认识的不能一上来就和旗舰平起平坐


def test_legal_efforts_come_from_metadata_and_the_cap():
    cfg = Config(claude=EngineSettings(models=[ModelEntry("claude-opus-4-6", True), ModelEntry("claude-haiku-4-5", True),
                                               ModelEntry("claude-opus-5-5", True, "high")]),
                 codex=EngineSettings(models=[ModelEntry("gpt-5.5", True)]))
    profiles = catalog.build(cfg, {"codex": {"gpt-5.5": {"efforts": ["low", "medium", "high", "xhigh"]}}})
    efforts = {p.id: p.efforts for e in profiles.values() for p in e}
    assert "max" not in efforts["gpt-5.5"]  # Codex 说它只到 xhigh：不会把 max 发过去
    assert "xhigh" not in efforts["claude-opus-4-6"]
    assert efforts["claude-haiku-4-5"] == ("high",)  # 不支持 effort 的模型不调强度
    assert efforts["claude-opus-5-5"][-1] == "high"  # 设置里的上限


def test_older_generation_starts_lower():
    cfg = Config(claude=EngineSettings(models=[ModelEntry("claude-opus-5-5", True), ModelEntry("claude-opus-4-8", True)]),
                 codex=EngineSettings(models=[ModelEntry("gpt-6-sol", True), ModelEntry("gpt-6.1-sol", True)]))
    meta = {"codex": {"gpt-6-sol": {"desc": "Previous generation workhorse model."},
                      "gpt-6.1-sol": {"desc": "Latest workhorse model for coding and everyday work."}}}
    skill = {p.id: p.skill for e in catalog.build(cfg, meta).values() for p in e}
    assert skill["claude-opus-4-8"] < skill["claude-opus-5-5"]
    assert skill["gpt-6-sol"] < skill["gpt-6.1-sol"]


def test_update_models_persists_metadata():
    cfg = Config(codex=EngineSettings(models=[ModelEntry("gpt-6-luna", True)]))
    r = router(cfg)
    assert r.profiles["codex"][0].tier == 2  # 名字就看得出
    r.update_models("codex", {"gpt-6-luna": {"efforts": ["low", "medium"], "desc": "Fast and affordable."}})
    assert router(cfg).profiles["codex"][0].efforts == ("low", "medium")


# ---------- 先保证办成 ----------

def test_cold_start_never_picks_a_cheaper_tier():
    r = router()
    tasks = [QUESTION, Task("ask", "翻译一下", "foreign", context="Revenue grew 12% year over year. " * 30),
             Task("ask", "这个报错怎么解决", "error", errors="Traceback (most recent call last):\nKeyError: 'x'"),
             Task("act", "帮我把深色模式打开", "text", "SystemSettings.exe"),
             Task("act", "修好失败的测试", "text", "Code.exe")]
    for task in tasks:
        d = r.decide(task)
        assert d.model in ("claude-opus-5-5", "gpt-6-astra"), (task.question, d.model)


def test_weak_successes_never_downgrade():
    """"正常结束"说明不了答得对不对：两百次也不足以换成便宜的配置。"""
    r = router()
    for _ in range(200):
        r.record(r.decide(QUESTION), QUESTION, True, "status_ok")
    d = r.decide(QUESTION)
    assert (d.model, d.effort) == ("claude-opus-5-5", "medium")


def test_cheaper_config_is_chosen_only_after_it_proves_itself():
    r = router()
    served = duel_rounds(r, QUESTION, 10)
    assert set(served) == {("claude-opus-5-5", "medium")}  # 证据不够：一直用最可靠的
    duel_rounds(r, QUESTION, 60)
    d = r.decide(QUESTION)
    assert (d.model, d.effort) != ("claude-opus-5-5", "medium")  # 后台对比一直一样好：换成更快更省的
    assert "已证明" in d.reason


def test_cheaper_config_that_is_sometimes_worse_is_never_chosen():
    r = router()
    bad = {"claude-sonnet-5-5": 1 / 6, "claude-haiku-5-5": 1 / 3, "gpt-6.1-sol": 1 / 6, "gpt-6-luna": 1 / 3,
           "claude-opus-5-5": 0.0}
    served = duel_rounds(r, QUESTION, 150, bad)
    assert all(model not in bad or bad[model] == 0 for model, _ in served)


def test_a_failure_raises_effort_for_that_task_type_only():
    r = router()
    error = Task("ask", "这个报错怎么解决", "error", errors="Traceback: RuntimeError: x")
    before, general = r.decide(error), r.decide(QUESTION)
    r.record(before, error, False, "negative_followup")
    after = r.decide(error)
    assert after.model == before.model and EFFORTS.index(after.effort) == EFFORTS.index(before.effort) + 1
    assert "没办成过" in after.reason
    assert r.decide(QUESTION).effort == general.effort  # 别的类型不受影响


def test_act_failures_do_not_change_who_answers_questions():
    r = router()
    act = Task("act", "帮我修好它", "error", "Code.exe")
    before = r.decide(QUESTION)
    for _ in range(3):
        r.record(r.decide(act), act, False, "status_fail")
    after = r.decide(QUESTION)
    assert (after.engine, after.model, after.effort) == (before.engine, before.model, before.effort)


def test_browser_failures_do_not_flip_dev_tasks():
    """实测过的问题：一次浏览器操作失败，开发任务也全换了引擎。"""
    r = router()
    browser, dev = Task("act", "帮我订票", "text", "msedge.exe"), Task("act", "修好测试", "text", "Code.exe")
    before = r.decide(dev)
    for _ in range(3):
        r.record(r.decide(browser), browser, False, "status_fail")
    after = r.decide(dev)
    assert (after.engine, after.model, after.effort) == (before.engine, before.model, before.effort)


def test_escalate_goes_stronger_on_the_same_engine():
    r = router()
    error = Task("ask", "这个报错怎么解决", "error", errors="Traceback: RuntimeError: x")
    d = r.decide(error)
    r.record(d, error, False, "status_fail")
    up = r.escalate(d, error)
    assert up.engine == d.engine and up.via == "escalated"
    assert EFFORTS.index(up.effort) > EFFORTS.index(d.effort) or up.model != d.model
    small = r.escalate(r.decide(error).__class__(engine="claude", model="claude-haiku-5-5", effort="max",
                                                 reason="", mode="ask", kind="code_fix", domain="explain_error"))
    assert small is not None and small.model != "claude-haiku-5-5"  # 到顶了就换更强的模型
    top = r.decide(error).__class__(engine="claude", model="claude-opus-5-5", effort="max", reason="", mode="ask",
                                    kind="code_fix", domain="explain_error")
    assert r.escalate(top) is None


# ---------- 后台对比 ----------

def test_duel_candidates_only_in_ask_mode_and_within_budget():
    r = router(daily=2)
    d = r.decide(QUESTION)
    c = r.duel_candidate(d)
    assert c is not None and c.via == "duel" and (c.engine, c.model, c.effort) != (d.engine, d.model, d.effort)
    assert r.duel_candidate(r.decide(Task("act", "修好测试", "text", "Code.exe"))) is None
    ui = Task("ask", "这个按钮在哪", "dialog")
    assert r.duel_candidate(r.decide(ui)) is None  # 要看实时界面、圈位置的问题不比
    r.count_duel()
    r.count_duel()
    assert r.duels_left() == 0 and r.duel_candidate(d) is None
    off = six_models()
    off.shadow_eval = False
    assert EngineRouter(off, gui_official=False).duel_candidate(d) is None


def test_judge_verdicts():
    ok_same = '{"a": "ok", "b": "ok", "better": "same", "why": "都对"}'
    assert judge.parse(ok_same, flip=False) == Verdict(1.0, 1.0, "都对")
    # 不翻转时 A 是你看到的那份、B 是候选
    worse = '{"a": "ok", "b": "bad", "better": "a", "why": "B 漏了关键一步"}'
    assert judge.parse(worse, flip=False) == Verdict(0.0, 1.0, "B 漏了关键一步")
    assert judge.parse(worse, flip=True) == Verdict(1.0, 0.0, "B 漏了关键一步")
    weaker = '回答：{"a": "ok", "b": "ok", "better": "a", "why": "A 更完整"}'
    assert judge.parse(weaker, flip=False) == Verdict(0.5, 1.0, "A 更完整")
    assert judge.parse("看不懂", flip=False) is None
    assert judge.parse('{"a": "fine", "b": "ok", "better": "a"}', flip=False) is None
    text = judge.prompt("这是什么", "屏幕上的字", "我看到的回答", "后台的回答", flip=True)
    assert text.index("后台的回答") < text.index("我看到的回答")


def test_noninferiority_math():
    def s(alpha, beta):
        return Scored(profile=None, effort="high", alpha=alpha, beta=beta, real=alpha + beta, cost=0, prior=0.5)

    assert noninferior(s(40, 0.2), s(40, 0.2)) > 0.9  # 两边都很有把握、一样好
    assert noninferior(s(3, 0.1), s(40, 0.2)) < 0.9   # 只有先验那点信息：不够
    assert noninferior(s(30, 3), s(40, 0.2)) < 0.5    # 一成失败率：明显更差
    assert superior(s(40, 0.2), s(3, 1)) > 0.7 > superior(s(3, 0.1), s(3, 0.12))


# ---------- 记录 ----------

def test_disabling_a_model_keeps_what_was_learned():
    cfg = six_models()
    r = router(cfg)
    duel_rounds(r, QUESTION, 20)
    learned = sum(1 for o in r.evidence.items if o.model == "claude-sonnet-5-5")
    assert learned
    next(m for m in cfg.claude.models if m.id == "claude-sonnet-5-5").enabled = False
    r.rebuild()
    assert all(d.model != "claude-sonnet-5-5" for d in [r.decide(QUESTION)])
    r.record(r.decide(QUESTION), QUESTION, True, "feedback")  # 停用期间继续学别的模型
    next(m for m in cfg.claude.models if m.id == "claude-sonnet-5-5").enabled = True
    assert sum(1 for o in router(cfg).evidence.items if o.model == "claude-sonnet-5-5") == learned


def test_migrates_old_outcomes():
    """升级前学到的（decisions.jsonl 里的结果）不丢。"""
    paths.ROUTER.mkdir(parents=True, exist_ok=True)
    old = [{"type": "decision", "mode": "act", "kind": "agentic", "domain": "browser", "engine": "claude"},
           {"type": "outcome", "mode": "act", "kind": "agentic", "domain": "browser", "engine": "claude",
            "model": "claude-opus-5-5", "effort": "medium", "success": False, "source": "status_fail", "t": 1.0},
           {"type": "outcome", "mode": "act", "kind": "code_fix", "domain": "dev", "engine": "claude",
            "model": "claude-opus-5-5", "effort": "high", "success": True, "source": "delegate_result",
            "arm": "codex|gpt-6-astra|e=-|t=1", "t": 2.0}]
    (paths.ROUTER / "decisions.jsonl").write_text("\n".join(json.dumps(x) for x in old), encoding="utf-8")
    items = router().evidence.items
    assert [(o.engine, o.model, o.effort, o.y) for o in items] == [
        ("claude", "claude-opus-5-5", "medium", 0.0), ("codex", "gpt-6-astra", "high", 1.0)]
    assert len(router().evidence.items) == 2  # 只迁移一次


def test_outcomes_keep_task_vectors():
    np = pytest.importorskip("numpy")
    vec = np.ones(8, dtype=np.float32) / np.sqrt(8)
    r = router()
    d = r.decide(Task("ask", "这是什么意思", "text", vec=vec))
    r.record(d, QUESTION, True, "feedback")
    again = router().evidence.items[-1]
    assert isinstance(again, Outcome) and float(again.vec @ vec) == pytest.approx(1.0, abs=1e-3)


def test_observed_latency_calibrates_speed():
    r = router()
    d = r.decide(QUESTION)
    slow = catalog.latency_s(r._profile(d.engine, d.model), d.effort, "ask") * 3
    for _ in range(20):
        r.observe(d, slow)
    assert r._factor("speed", "claude", "ask") == pytest.approx(3.0, rel=0.05)
    assert r._factor("speed", "codex", "ask") == pytest.approx(3.0, rel=0.05)  # 没测过的引擎按测过的平均算
    assert r.decide(QUESTION).engine == "claude"  # 两边的相对快慢不变
