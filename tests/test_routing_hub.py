"""中枢里和路由相关的几件事：没办成就加强、后台对比、很快又问一样的问题、首问后的校准、Codex 模型元数据。"""

import asyncio
from types import SimpleNamespace

from super_aide.engines import hub as hub_module
from super_aide.engines.base import Event
from super_aide.engines.hub import Conversation, EngineHub
from super_aide.router import Decision, Task
from super_aide.router.judge import Verdict


def decision(model="claude-opus-5-5", effort="medium", engine="claude") -> Decision:
    return Decision(engine=engine, model=model, effort=effort, reason="", mode="ask", kind="qa_factual",
                    domain="general")


class FakeRouter:
    def __init__(self, stronger=None, candidate=None):
        self.calls, self.stronger, self.candidate = [], stronger, candidate

    def record(self, *a, **k):
        self.calls.append(("record", a[2], a[3]))

    def record_duel(self, served, candidate, task, verdict):
        self.calls.append(("duel", candidate.model, verdict))

    def escalate(self, d, task=None):
        return self.stronger

    def observe(self, d, seconds, cost=None):
        self.calls.append(("observe", seconds, cost))

    def duel_candidate(self, d):
        return self.candidate

    def count_duel(self):
        self.calls.append(("count",))


def fake_hub(router=None, engines=None, **extra) -> SimpleNamespace:
    events = []
    hub = SimpleNamespace(router=router or FakeRouter(), engines=engines or {}, conversations={}, _last={},
                          events=events, _emit=lambda key, ev: events.append(ev), **extra)
    return hub


def conv(question="这是什么意思", text="屏幕上的字", app="chrome.exe", started=1000.0) -> Conversation:
    c = Conversation(key="k", mode="ask", task=Task("ask", question, "text"), decision=decision())
    c.question, c.situation, c.started = question, {"text": text, "app": app}, started
    return c


def test_reasking_the_same_thing_marks_the_last_answer_bad():
    hub = fake_hub()
    EngineHub._check_reask(hub, conv(started=1000))
    EngineHub._check_reask(hub, conv("这是什么意思？", started=1100))
    assert ("record", False, "reask") in hub.router.calls


def test_a_different_screen_or_much_later_is_not_a_reask():
    hub = fake_hub()
    EngineHub._check_reask(hub, conv(text="第一个报错：找不到文件 a.txt", started=1000))
    EngineHub._check_reask(hub, conv(text="另一个完全不同的报错：权限不够，拒绝访问注册表", started=1100))
    EngineHub._check_reask(hub, conv(text="另一个完全不同的报错：权限不够，拒绝访问注册表", started=1100 + 3600))
    EngineHub._check_reask(hub, conv(app="Code.exe", started=1100 + 3700))
    assert hub.router.calls == []


def test_escalation_switches_the_session_and_tells_the_card():
    stronger = decision(effort="high")
    stronger.via = "escalated"
    switched = []

    async def switch(session, mode, model, effort):
        switched.append((model, effort))
        return "new-session"

    hub = fake_hub(FakeRouter(stronger=stronger), {"claude": SimpleNamespace(switch=switch)})
    c = conv()
    c.session, c.escalate = "old-session", True
    asyncio.run(EngineHub._escalate(hub, c))
    assert switched == [("claude-opus-5-5", "high")] and c.session == "new-session"
    assert c.decision is stronger and not c.escalate
    assert [e.type for e in hub.events] == ["route", "status"]
    asyncio.run(EngineHub._escalate(hub, c))  # 已经加强过：没有新的失败就不再换
    assert len(switched) == 1


def test_failed_turn_and_thumbs_down_ask_for_escalation():
    hub = fake_hub(_browser_problem=lambda c: "")
    c = conv()
    EngineHub._learn_from_turn(hub, c, {"ok": False, "error": "没完成：缺少权限"})
    assert c.escalate
    c2 = conv()
    EngineHub._learn_from_turn(hub, c2, {"ok": False, "error": "429 rate limit"})  # 和能力无关：不加强
    assert not c2.escalate
    c3 = conv()
    hub.lessons = SimpleNamespace(failed=lambda ids: None)
    EngineHub._bad_turn(hub, c3)
    assert c3.escalate


def test_first_turn_calibrates_and_schedules_a_duel():
    created = []
    candidate = decision("claude-sonnet-5-5", "low")
    hub = fake_hub(FakeRouter(candidate=candidate),
                   loop=SimpleNamespace(create_task=lambda coro: (created.append(coro), coro.close())),
                   _duel=lambda *a: hub_module.asyncio.sleep(0))
    c = conv()
    c.first = ("这是什么意思", "消息", [])
    EngineHub._after_first_turn(hub, c, {"ok": True, "seconds": 12, "cost": 0.05}, "回答")
    assert ("observe", 12.0, 0.05) in hub.router.calls and ("count",) in hub.router.calls and len(created) == 1
    hub.router.calls.clear()
    EngineHub._after_first_turn(hub, c, {"ok": False, "seconds": 12}, "回答")  # 没答好：不校准、不对比
    assert hub.router.calls == []


class FakeSession:
    def __init__(self, text="候选的回答", ok=True, error=""):
        self.text, self.ok, self.error, self.closed = text, ok, error, False

    async def send(self, message, images):
        yield Event("new_message")
        yield Event("delta", self.text)
        yield Event("done", data={"ok": self.ok, "error": self.error})

    async def close(self):
        self.closed = True


def run_duel(monkeypatch, session, verdict=Verdict(1.0, 1.0)):
    monkeypatch.setattr(hub_module, "DUEL_DELAY", 0)
    opened = []

    async def open_(mode, model, effort, **kw):
        opened.append((mode, model, effort, kw))
        return session

    async def judge(question, c, served, candidate):
        return verdict

    hub = fake_hub(engines={"claude": SimpleNamespace(open=open_)}, _duel_lock=asyncio.Lock(), _judge=judge)
    c = conv()
    c.first = ("这是什么意思", "首问的消息", [])
    asyncio.run(EngineHub._duel(hub, c, c.decision, decision("claude-sonnet-5-5", "low"), "你看到的回答"))
    return hub, opened


def test_duel_answers_in_background_without_screen_tools_and_records_both(monkeypatch):
    session = FakeSession()
    hub, opened = run_duel(monkeypatch, session)
    assert opened == [("duel", "claude-sonnet-5-5", "low", {"rewarm": False})]  # 后台模式：不看实时界面、不留预热进程
    assert hub.router.calls == [("duel", "claude-sonnet-5-5", Verdict(1.0, 1.0))] and session.closed


def test_duel_infra_errors_are_not_counted_but_real_failures_are(monkeypatch):
    hub, _ = run_duel(monkeypatch, FakeSession(ok=False, error="429 rate limit"))
    assert hub.router.calls == []
    hub, _ = run_duel(monkeypatch, FakeSession(ok=False, error="模型拒绝回答"))
    assert hub.router.calls == [("record", False, "duel")]


def test_a_candidate_that_cannot_even_open_counts_against_it(monkeypatch):
    class Broken:
        def __init__(self, message):
            self.message = message

        async def send(self, message, images):
            raise RuntimeError(self.message)
            yield  # noqa: unreachable - 让它成为异步生成器

        async def close(self):
            pass

    hub, _ = run_duel(monkeypatch, Broken("model not found: claude-haiku-5-5"))
    assert hub.router.calls == [("record", False, "duel")]  # 不然每天的对比次数都耗在它身上
    hub, _ = run_duel(monkeypatch, Broken("connection reset"))
    assert hub.router.calls == []


def test_codex_model_metadata_reaches_the_router():
    updates = []
    effort = lambda v: SimpleNamespace(reasoning_effort=SimpleNamespace(value=v))  # noqa: E731
    listed = [SimpleNamespace(id="gpt-6-luna", description="Fast and affordable model for easier tasks.",
                              supported_reasoning_efforts=[effort("low"), effort("medium")],
                              default_reasoning_effort=SimpleNamespace(value="medium"), upgrade=None)]

    async def client(mode):
        async def models():
            return SimpleNamespace(data=listed)
        return SimpleNamespace(models=models)

    found = []
    cfg = SimpleNamespace(codex=SimpleNamespace(enabled=True), claude=SimpleNamespace(enabled=False),
                          dsh=SimpleNamespace(enabled=False))
    hub = fake_hub(SimpleNamespace(cfg=cfg, ready=None, update_models=lambda e, info: updates.append((e, info))),
                   {"codex": SimpleNamespace(client=client)},
                   models_found=SimpleNamespace(emit=lambda result: found.append(result)))
    asyncio.run(EngineHub._discover_models(hub))
    assert found[0]["found"] == {"codex": ["gpt-6-luna"]}
    assert updates == [("codex", {"gpt-6-luna": {"efforts": ["low", "medium"], "default": "medium",
                                                 "desc": "Fast and affordable model for easier tasks.", "upgrade": ""}})]


def test_reloading_codex_never_hands_out_the_process_being_closed(monkeypatch):
    """准备窗口改了服务地址：重连、预热、发现模型同时开始。正在关的旧进程不能交给别人（会报 Codex process is not running）。"""
    from super_aide.engines import codex

    class FakeClient:
        def __init__(self, n):
            self.n, self.closed = n, False
            self._client = SimpleNamespace()

        async def close(self):
            await asyncio.sleep(0.01)  # 关进程要一会儿
            self.closed = True

    started = []

    async def start(self, overrides):
        started.append(FakeClient(len(started)))
        return started[-1]

    async def no_hooks(self, mode):
        return ()

    monkeypatch.setattr(codex.CodexEngine, "_start", start)
    monkeypatch.setattr(codex.CodexEngine, "_hook_overrides", no_hooks)
    monkeypatch.setattr(codex.computer, "codex_overrides", lambda *a: ())
    monkeypatch.setattr(codex.experience, "codex_overrides", lambda: ())
    engine = codex.CodexEngine("", False)

    async def scenario():
        old = await engine.client("ask")
        reload = asyncio.create_task(engine.reload())
        await asyncio.sleep(0)  # 重连已经开始关旧进程
        fresh = await engine.client("ask")
        await reload
        return old, fresh

    old, fresh = asyncio.run(scenario())
    assert old.closed and fresh is not old and not fresh.closed
    assert asyncio.run(engine.client("ask")) is fresh  # 新起的留着用，没被一起关掉


def test_answers_that_looked_at_the_live_screen_are_not_dueled():
    """后台对比的会话没有看实时界面、圈位置的工具：用过它们的问答比出来是工具差，不是配置差。"""
    created = []
    hub = fake_hub(FakeRouter(candidate=decision("claude-sonnet-5-5", "low")),
                   loop=SimpleNamespace(create_task=lambda coro: (created.append(coro), coro.close())),
                   _duel=lambda *a: hub_module.asyncio.sleep(0))
    c = conv()
    c.first, c.live_ui = ("记事本的另存为在哪？圈给我看", "消息", []), True
    EngineHub._after_first_turn(hub, c, {"ok": True, "seconds": 20}, "在左上角的文件菜单里（框 1）")
    assert created == [] and ("count",) not in hub.router.calls


def test_screen_tools_mark_the_conversation():
    from super_aide.engines import computer

    assert computer.looks_at_screen("mcp__computer__point") and computer.looks_at_screen("mcp__computer__observe_window")
    assert not computer.looks_at_screen("Read") and not computer.looks_at_screen("mcp__memory__recall")
