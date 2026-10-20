"""判断模型（decision/）：接口格式、出错就退回原来的做法、各件事怎么用它的答案，以及路由、经验、中枢怎么接上。"""

import asyncio
import json
import time
from types import SimpleNamespace

from super_aide.config import Config
from super_aide.decision import Answer, Decider
from super_aide.decision import checks
from super_aide.decision import client as client_module
from super_aide.decision.client import endpoint, parse
from super_aide.engines.hub import Conversation, EngineHub
from super_aide.experience import recall
from super_aide.experience.store import Store
from super_aide.router import Decision, EngineRouter, Task


def configured(tmp_path) -> Decider:
    cfg = Config(decision_url="https://example.com", decision_key="sk-test", decision_model="jev-test")
    return Decider(cfg, log_path=tmp_path / "checks.jsonl")


class FakeDecider:
    """按题目的键给定好的答案；没给的题不答（= 判断不了）。"""

    def __init__(self, **answers):
        self.answers, self.asked = answers, []

    def ready(self):
        return True

    def ask(self, purpose, state, questions, budget=1.5, think=False, legacy=None):
        self.asked.append((purpose, state, questions))
        if not all(q in self.answers for q in questions):
            return None
        return {q: self.answers[q] for q in questions}


def noul(p):
    return Answer("noul", p)


# ---------- 接口 ----------

def test_endpoint_accepts_a_base_url_or_the_full_path():
    assert endpoint("https://a.dev") == "https://a.dev/v1/systemone"
    assert endpoint("https://a.dev/v1/") == "https://a.dev/v1/systemone"
    assert endpoint("https://a.dev/v1/decisions") == "https://a.dev/v1/decisions"
    assert endpoint(" https://a.dev:58043/v1/systemone ") == "https://a.dev:58043/v1/systemone"


def test_parse_reads_all_three_types():
    data = {"answers": {
        "team": {"type": "choice", "choice": "billing", "confidence": 0.98, "probabilities": {"billing": 0.99, "tech": 0.01}},
        "urgent": {"type": "noul", "noul": 0.01},
        "level": {"type": "score", "score": 1.4, "probabilities": {"0": 0.1, "1": 0.4, "2": 0.5}, "confidence": 0.3},
    }}
    a = parse(data)
    assert a["team"].value == "billing" and a["team"].probabilities["tech"] == 0.01 and a["team"].confidence == 0.98
    assert a["urgent"].value == 0.01 and a["urgent"].confidence is None
    assert a["level"].value == 1.4


def test_not_configured_means_no_call(tmp_path, monkeypatch):
    d = Decider(Config(), log_path=tmp_path / "c.jsonl")
    monkeypatch.setattr(d, "_post", lambda *a: (_ for _ in ()).throw(AssertionError("不该联网")))
    assert not d.ready() and d.ask("x", "s", {"q": {"type": "noul", "instructions": "i"}}) is None


def test_answers_are_logged_without_the_state(tmp_path, monkeypatch):
    d = configured(tmp_path)
    sent = []
    monkeypatch.setattr(d, "_post", lambda state, q, budget, think: sent.append((state, think))
                        or {"answers": {"q": {"type": "noul", "noul": 0.9}}})
    answers = d.ask("followup", "屏幕上的秘密内容", {"q": {"type": "noul", "instructions": "i"}}, legacy=False)
    assert answers["q"].value == 0.9 and sent == [("屏幕上的秘密内容", False)]
    row = json.loads((tmp_path / "checks.jsonl").read_text(encoding="utf-8"))
    assert row["purpose"] == "followup" and row["legacy"] is False and row["answers"]["q"]["value"] == 0.9
    assert "秘密" not in (tmp_path / "checks.jsonl").read_text(encoding="utf-8")


def test_two_failures_bench_it_and_a_test_brings_it_back(tmp_path, monkeypatch):
    d = configured(tmp_path)
    monkeypatch.setattr(d, "_post", lambda *a: {"answers": {}})  # 少了答案也算失败
    q = {"q": {"type": "noul", "instructions": "i"}}
    assert d.ask("x", "s", q) is None and d.ready()
    assert d.ask("x", "s", q) is None and not d.ready()
    monkeypatch.setattr(d, "_post", lambda *a: {"answers": {"q": {"type": "noul", "noul": 0.97}}})
    assert d.test() == {"ok": True, "ms": d.test()["ms"]} and d.ready()


def test_slow_service_does_not_hold_up_the_question(tmp_path, monkeypatch):
    d = configured(tmp_path)
    monkeypatch.setattr(d, "_post", lambda *a: time.sleep(1.0) or {"answers": {"q": {"type": "noul", "noul": 1}}})
    t = time.perf_counter()
    assert d.ask("x", "s", {"q": {"type": "noul", "instructions": "i"}}, budget=0.2) is None
    assert time.perf_counter() - t < 0.6


def test_test_reports_errors_in_plain_words(tmp_path, monkeypatch):
    assert Decider(Config()).test()["error"]
    d = configured(tmp_path)
    monkeypatch.setattr(d, "_post", lambda *a: {"answers": {"q": {"type": "choice", "choice": "x"}}})
    assert "Jev" in d.test()["error"]


def test_bench_expires(tmp_path, monkeypatch):
    d = configured(tmp_path)
    d._benched = time.time() - client_module.BENCH_S - 1
    assert d.ready()


# ---------- 各件事 ----------

def test_negative_followup_uses_the_model_and_falls_back_to_keywords():
    off = Decider(Config())
    assert checks.negative_followup(off, "怎么清 C 盘", "用磁盘清理", "不行的话还有别的办法吗？")  # 关键词：误判
    assert not checks.negative_followup(off, "装 torch 慢", "换清华源", "还是卡在 Collecting 不动")  # 关键词：漏判
    assert not checks.negative_followup(FakeDecider(q=noul(0.04)), "怎么清 C 盘", "用磁盘清理", "不行的话还有别的办法吗？")
    assert checks.negative_followup(FakeDecider(q=noul(0.97)), "装 torch 慢", "换清华源", "还是卡在 Collecting 不动")
    assert not checks.negative_followup(FakeDecider(q=noul(0.5)), "q", "a", "不行")  # 说不准：不当成信号
    assert checks.negative_followup(FakeDecider(), "q", "a", "没用")  # 判断不了：照关键词
    assert checks.negative_followup(FakeDecider(q=noul(0.0)), "", "", "没用")  # 没有上一轮：照关键词


def test_stop_reason_typed_text_goes_to_the_model_choices_stay_rules():
    fault = FakeDecider(q=noul(0.9))
    assert checks.stop_fault(fault, "复制表格", "", "你搞错了，不是这个窗口")  # 关键词里的"搞错了"原来判成改主意
    assert not checks.stop_fault(FakeDecider(q=noul(0.1)), "下载视频", "", "网太卡了")
    assert checks.stop_fault(FakeDecider(q=noul(0.1)), "x", "wrong", "")  # 只选了原因：照规则
    assert not checks.stop_fault(fault, "x", "not_assistant", "做错了")  # 明说不是助手的问题
    assert not fault.asked[1:]


def test_reask_needs_a_confident_yes():
    assert checks.reask(FakeDecider(q=noul(0.9)), "QQ 开机自启怎么关", "怎么关闭开机自启的 QQ", True, legacy=False)
    assert not checks.reask(FakeDecider(q=noul(0.6)), "把第一段加粗", "把第二段加粗", True, legacy=True)
    assert checks.reask(Decider(Config()), "a", "a", True, legacy=True)


def lesson(store, title, when, triggers):
    return store.add(title, when, "（做法）", triggers=triggers)


def test_understand_gives_kind_band_and_reviewed_lessons(tmp_path):
    store = Store(tmp_path / "l.json")
    pip = lesson(store, "pip 装包超时先查代理", "pip install 超时", ["pip install 超时"])
    git = lesson(store, "git push 被拒先拉取", "push 被拒绝", ["push 被拒绝"])
    fake = FakeDecider(difficulty=Answer("score", 1.7), kind=Answer("choice", "system", confidence=0.9),
                       lesson=Answer("choice", "2", {"1": 0.05, "2": 0.6, "none": 0.35}))
    u = checks.understand(fake, Task("ask", "公司网络装包十分钟都下不完", "text"), [git, pip])
    assert (u.kind, u.band) == ("system", 2) and [x.id for x in u.lessons] == [pip.id]
    _, state, questions = fake.asked[0]
    assert "公司网络装包" in state and set(questions) == {"difficulty", "kind", "lesson"}
    assert "git push 被拒先拉取" in questions["lesson"]["criteria"]["1"]  # 键是中性的编号，意思写在说明里

    none = FakeDecider(difficulty=Answer("score", 0.2), kind=Answer("choice", "general", confidence=0.3),
                       lesson=Answer("choice", "none", {"1": 0.2, "none": 0.8}))
    u = checks.understand(none, Task("ask", "pip 是什么", "text"), [pip])
    assert (u.kind, u.band, u.lessons) == ("", 0, [])  # 类型说不准不采信；同话题不同情况不给经验
    act = FakeDecider(difficulty=Answer("score", 0.9))
    u = checks.understand(act, Task("act", "打开记事本", "text"))
    assert (u.kind, u.band, u.lessons) == ("", 1, None) and "kind" not in act.asked[0][2]


def test_second_lesson_needs_its_own_evidence(tmp_path):
    store = Store(tmp_path / "l.json")
    a, b, c = (lesson(store, f"经验{i}", "w", ["t"]) for i in range(3))
    both = Answer("choice", "1", {"1": 0.5, "3": 0.35, "2": 0.05, "none": 0.1})
    assert [x.id for x in checks._kept(both, [a, b, c])] == [a.id, c.id]
    weak = Answer("choice", "1", {"1": 0.5, "3": 0.2, "none": 0.3})
    assert [x.id for x in checks._kept(weak, [a, b, c])] == [a.id]


# ---------- 路由、经验 ----------

def test_router_takes_the_kind_and_only_raises_the_band(tmp_path, monkeypatch):
    monkeypatch.setattr("super_aide.paths.ROUTER", tmp_path)
    r = EngineRouter(Config(), gui_official=False)
    plain = r.describe(Task("ask", "帮我回一下这封邮件，委婉拒绝", "text"))
    assert (plain.kind, plain.domain) == ("qa_factual", "general")
    hinted = r.describe(Task("ask", "帮我回一下这封邮件，委婉拒绝", "text", kind_hint="writing", band_hint=2))
    assert (hinted.kind, hinted.domain, hinted.band) == ("creative", "writing", 2)
    long = "这段报错 Traceback Error error: def class {" * 200
    assert r.describe(Task("ask", long, "text", band_hint=0)).band == r.describe(Task("ask", long, "text")).band
    act = r.describe(Task("act", "打开记事本", "text", foreground="notepad.exe", kind_hint="writing"))
    assert (act.kind, act.domain) == ("agentic", "desktop")  # 操作模式的类型看前台程序，不看判断模型


def test_loose_recall_lets_one_trigger_through_for_review(tmp_path):
    store = Store(tmp_path / "l.json")
    lesson(store, "端口被占用先查进程", "启动服务报端口被占用", ["端口被占用", "Address already in use", "端口冲突"])
    situation = recall.Situation(question="npm start 说端口被占用了")
    assert recall.recall(store, situation) == []
    assert [x.title for x in recall.recall(store, situation, loose=True)] == ["端口被占用先查进程"]


# ---------- 中枢 ----------

def hub_with(decider, store) -> SimpleNamespace:
    events = []
    hub = SimpleNamespace(decider=decider, lessons=store, semantic=None, events=events, _embed_used=0,
                          _emit=lambda key, ev: events.append(ev))
    for name in ("_understand", "_candidates", "_reviewed", "_remember", "_give", "_recall"):
        setattr(hub, name, getattr(EngineHub, name).__get__(hub))
    return hub


def conv(question, mode="ask") -> Conversation:
    return Conversation(key="k", mode=mode, task=Task(mode, question, "text"))


def test_first_turn_sets_hints_and_gives_only_reviewed_lessons(tmp_path):
    store = Store(tmp_path / "l.json")
    port = lesson(store, "端口被占用先查进程", "启动服务报端口被占用", ["端口被占用", "端口冲突"])
    fake = FakeDecider(difficulty=Answer("score", 1.2), kind=Answer("choice", "error", confidence=0.8),
                       lesson=Answer("choice", "1", {"1": 0.9, "none": 0.1}))
    hub, c = hub_with(fake, store), conv("npm start 说端口被占用了")
    found = hub._understand(c, recall.Situation(question=c.task.question))
    assert [x.id for x in found] == [port.id] and c.turn_lessons == [port.id]
    assert (c.task.kind_hint, c.task.band_hint) == ("error", 1)


def test_first_turn_falls_back_to_strict_recall_when_the_model_is_down(tmp_path):
    store = Store(tmp_path / "l.json")
    lesson(store, "端口被占用先查进程", "启动服务报端口被占用", ["端口被占用", "端口冲突"])
    hub, c = hub_with(FakeDecider(), store), conv("npm start 说端口被占用了")  # 判断不了
    assert hub._understand(c, recall.Situation(question=c.task.question)) == []  # 只对上一个提示词：严格对法不给
    assert (c.task.kind_hint, c.task.band_hint) == ("", -1)


def test_followup_negative_check_escalates_the_next_turn():
    class Router:
        calls = []

        def record(self, d, task, ok, source):
            self.calls.append((ok, source))

    hub = SimpleNamespace(router=Router(), lessons=SimpleNamespace(failed=lambda ids: None))
    hub._bad_turn = EngineHub._bad_turn.__get__(hub)
    c = conv("这个报错怎么解决")
    c.decision = Decision(engine="claude", model="m", effort="medium", reason="", mode="ask")
    EngineHub._negative_followup(hub, c)
    assert Router.calls == [(False, "negative_followup")] and c.escalate and c.negative


def test_reask_is_judged_in_the_background():
    async def run():
        class Router:
            calls = []

            def record(self, d, task, ok, source):
                self.calls.append(source)

        hub = SimpleNamespace(router=Router(), _last={}, decider=FakeDecider(q=noul(0.92)),
                              loop=asyncio.get_running_loop())
        hub._judge_reask = EngineHub._judge_reask.__get__(hub)

        def c(question, started):
            x = conv(question)
            x.decision = Decision(engine="claude", model="m", effort="medium", reason="", mode="ask")
            x.situation, x.started = {"text": "开机启动项", "app": "Taskmgr.exe"}, started
            return x

        EngineHub._check_reask(hub, c("怎么关闭开机自启的 QQ", 1000))
        EngineHub._check_reask(hub, c("QQ 开机自启怎么关", 1060))  # 字面不像：原来的做法认不出
        await asyncio.sleep(0.2)
        return Router.calls

    assert asyncio.run(run()) == ["reask"]
