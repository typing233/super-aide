"""模型服务出错（限流、过载、断网……）时换引擎接着做；给你看的报错是一句人话（2026-10-10 实测：Codex 一直 429，
路由还是每次都交给它，操作次次秒失败，结果提示是一行英文 "exceeded retry limit, last status: 429 Too Many Requests"）。
也在这里：评审拿到提问时间和完整一点的屏幕内容、"很快又问了一样的"不把不同的事当成重问、启动入口的单实例快速检查。"""

import asyncio
import json
from types import SimpleNamespace

from super_aide import launch
from super_aide.engines import hub as hub_module
from super_aide.engines.base import Event, friendly_text
from super_aide.engines.hub import Conversation, EngineHub
from super_aide.router import Decision, Task, judge

LIMITED = "exceeded retry limit, last status: 429 Too Many Requests"


class Router:
    def __init__(self, engines):
        self.order, self.unavailable, self.decided = list(engines), set(), []

    def decide(self, task):
        engine = next(e for e in self.order if e not in self.unavailable)
        self.decided.append(engine)
        return Decision(engine=engine, model=f"{engine}-model", effort="high", reason="", mode=task.mode)

    def mark_unavailable(self, engine):
        self.unavailable.add(engine)

    def available(self):
        return [e for e in self.order if e not in self.unavailable]

    def sideline(self, engine, model, kind):
        if not [e for e in self.available() if e != engine]:
            return False
        self.unavailable.add(engine)
        return True


class Session:
    """ok：答完；limited：做了一步以后服务报 429。"""

    def __init__(self, script="ok"):
        self.script, self.closed, self.sent = script, False, []

    async def send(self, text, images):
        self.sent.append(text)
        if self.script == "limited":
            yield Event("status", "正在运行 Get-ChildItem")
            yield Event("delta", "写了一半")
            yield Event("error", LIMITED)
            yield Event("done", data={"ok": False, "reason": "failed", "error": LIMITED})
            return
        yield Event("new_message")
        yield Event("delta", "已完成：建好了")
        yield Event("done", data={"ok": True})

    async def close(self):
        self.closed = True


class Engine:
    def __init__(self, session):
        self.session = session

    async def open(self, mode, model, effort):
        return self.session


class Hub:
    _first_turn, _open, _turn = EngineHub._first_turn, EngineHub._open, EngineHub._turn
    _sideline, _hand_over, _emit_route = EngineHub._sideline, EngineHub._hand_over, EngineHub._emit_route
    is_busy, _drop_sessions = EngineHub.is_busy, EngineHub._drop_sessions

    def __init__(self, engines):
        self.engines, self.router, self.conversations, self.gui = engines, Router(engines), {}, "ours"
        self.loop, self.events, self.saved = asyncio.get_running_loop(), [], []

    def _emit(self, key, ev):
        self.events.append(ev)

    def _recall(self, conv, situation):
        return []

    def _vector(self, question, text):
        return None

    def _notes(self, conv):
        return []

    def _save_history(self, conv, done, answer, trace=None):
        self.saved.append(done)

    def _noop(self, *args, **kwargs):
        return None

    _check_reask = _check_outcome = _watch_outcome = _learn_from_turn = _after_first_turn = _noop
    _lessons_used = _schedule_learning = _schedule_evolve = _crashed = _noop


def snapshot():
    ctx = SimpleNamespace(images=[])
    return SimpleNamespace(dir=None, url="", finalize=lambda: ctx,
                           situation=lambda q: SimpleNamespace(text="", errors=""))


def run(engines, mode="act", monkeypatch=None):
    notes_seen = []
    if monkeypatch is not None:
        monkeypatch.setattr(hub_module.prompts, "first_message",
                            lambda q, ctx, mode, notes=None, lessons=None: notes_seen.append(list(notes or [])) or "消息")

    async def scenario():
        hub = Hub(engines)
        conv = Conversation(key="k", mode=mode, task=Task(mode, "新建 a.txt", "text"), busy=True)
        hub.conversations["k"] = conv
        await hub._first_turn(conv, "新建 a.txt", snapshot())
        await asyncio.sleep(0)
        return hub, conv

    hub, conv = asyncio.run(asyncio.wait_for(scenario(), 5))
    return hub, conv, notes_seen


def test_rate_limited_engine_hands_the_first_turn_to_the_other(monkeypatch):
    codex, claude = Session("limited"), Session("ok")
    hub, conv, notes = run({"codex": Engine(codex), "claude": Engine(claude)}, monkeypatch=monkeypatch)
    done = [e for e in hub.events if e.type == "done"]
    assert len(done) == 1 and done[0].data["ok"]                       # 你只看到接手的那个办成了
    assert not any(e.type == "error" for e in hub.events)              # 前一个的 429 不出现在界面上
    assert hub.router.decided == ["codex", "claude"] and "codex" in hub.router.unavailable
    types = [e.type for e in hub.events]
    assert types.index("retract") < types.index("done")                # 写了一半的回答撤掉
    status = [e.text for e in hub.events if e.type == "status"]
    assert "Codex 被限流了，换 Claude 接着做…" in status
    assert codex.closed and conv.decision.engine == "claude" and not conv.busy
    assert len(hub.saved) == 1 and hub.saved[0]["ok"]                  # 历史里只记接手那一轮
    # 操作做到一半才断的：告诉接手的引擎前一个做过什么，先看现状别重复做
    assert notes[0] == [] and "正在运行 Get-ChildItem" in notes[1][0] and "不要重复做" in notes[1][0]


def test_only_one_engine_is_never_benched_and_the_error_reads_well(monkeypatch):
    hub, conv, _ = run({"codex": Engine(Session("limited"))}, monkeypatch=monkeypatch)
    assert hub.router.unavailable == set()                             # 歇了就谁都用不了
    errors = [e.text for e in hub.events if e.type == "error"]
    done = [e for e in hub.events if e.type == "done"]
    assert errors == ["引擎被限流了，稍后再试。"] and done[0].data["error"] == "引擎被限流了，稍后再试。"
    assert hub.saved[0]["error"] == LIMITED                            # 记录里留原文


def test_a_failed_followup_benches_the_engine_for_the_next_question():
    async def scenario():
        hub = Hub({"codex": None, "claude": None})
        conv = Conversation(key="k", mode="ask", task=Task("ask", "q", "text"), session=Session("limited"))
        conv.decision = Decision(engine="codex", model="m", effort="high", reason="", mode="ask")
        await hub._turn(conv, "接着问", [])
        return hub

    hub = asyncio.run(scenario())
    assert hub.router.unavailable == {"codex"}
    assert [e.text for e in hub.events if e.type == "error"] == ["引擎被限流了，稍后再试。"]


def test_friendly_text():
    assert friendly_text(LIMITED) == "引擎被限流了，稍后再试。"
    assert friendly_text("API Error: 529 Overloaded") == "模型服务暂时不可用，稍后再试。"
    assert friendly_text("401 Unauthorized: invalid api key") == "引擎认证失败，请检查 Claude Code / Codex 的登录或服务地址配置。"
    assert friendly_text("Your input exceeds the context window") == "Your input exceeds the context window"


def test_judge_knows_when_it_was_asked_and_sees_more_of_the_screen(tmp_path):
    (tmp_path / "windows").mkdir()
    (tmp_path / "windows" / "00_msedge.txt").write_text("def total(items):\n    return sum(...)", encoding="utf-8")
    (tmp_path / "context.json").write_text(json.dumps({"windows": [
        {"foreground": False, "text": "windows/01_x.txt"},
        {"foreground": True, "text": "windows/00_msedge.txt"}]}), encoding="utf-8")
    conv = Conversation(key="k", mode="ask", task=Task("ask", "翻译并解释", "text"))
    conv.home = tmp_path
    conv.first = ("翻译并解释", "当前是【问答模式】…\n\n【我的问题】\n翻译并解释\n\n【提问时的环境】以下内容来自屏幕：\n"
                  "- 时间：2026-10-10 09:49:17（周六）\n- 框选区域里的文字：The migration…\n\n【按需读取的资料】都在…", [])
    context = hub_module._judge_context(conv)
    assert "周六" in context and "The migration" in context and "def total(items)" in context
    assert "按需读取" not in context and "我的问题" not in context
    text = judge.prompt("翻译并解释", context, "A", "B", flip=False, when=judge.asked_at(1791545357))
    assert "【提问时间】\n2026-10-" in text and "不能只因为节选里找不到就判它编造" in text
    assert judge.asked_at(1791545357).endswith("）") and "周" in judge.asked_at(1791545357)


def test_similar_tasks_with_different_targets_are_not_reasks():
    class R:
        calls = []

        def record(self, *a, **k):
            self.calls.append(a[3])

    def conv(question, started):
        c = Conversation(key="k", mode="act", task=Task("act", question, "text"),
                         decision=Decision(engine="claude", model="m", effort="high", reason="", mode="act"))
        c.question, c.situation, c.started = question, {"text": "记事本里的字", "app": "Notepad.exe"}, started
        return c

    hub = SimpleNamespace(router=R(), _last={})
    EngineHub._check_reask(hub, conv(r"在 D:\out 里新建 a.txt，内容是 1", 1000))
    EngineHub._check_reask(hub, conv(r"在 D:\out 里新建 b.txt，内容是 2", 1060))   # 另一件事：不是没答好
    assert hub.router.calls == []
    EngineHub._check_reask(hub, conv(r"在 D:\out 里新建 b.txt，内容是 2 ", 1100))  # 一模一样又来一遍：上一次多半没办好
    assert hub.router.calls == ["reask"]


def test_launch_wakes_the_running_copy_without_loading_the_app(monkeypatch):
    exists = {launch.SINGLETON}
    monkeypatch.setattr(launch, "_exists", lambda name: name in exists)
    woken = []
    monkeypatch.setattr(launch, "wake_running", lambda: woken.append(1) or True)
    monkeypatch.setattr(launch.sys, "argv", ["super-aide.exe"])
    assert launch.main() == 0 and woken == [1]
    assert launch.already_running(["super-aide.exe"])
    assert not launch.already_running(["pythonw", "-m", "super_aide", "--restart-after", "123"])  # 要等旧进程退出
    assert not launch.already_running(["pythonw", "-m", "super_aide", "--evolved", "job"])        # 换包后的健康检查
    exists.add(launch.APPLYING)
    assert not launch.already_running(["super-aide.exe"])  # 正在换包：交给 app.main 去等
    exists.clear()
    assert not launch.already_running(["super-aide.exe"])


def test_a_turn_that_looks_at_the_screen_is_marked():
    class Looking:
        async def send(self, text, images):
            yield Event("status", "正在看「记事本」…", {"tool": "mcp__computer__observe_window"})
            yield Event("status", "正在屏幕上圈出位置…", {"tool": "mcp__computer__point"})
            yield Event("delta", "在左上角（框 1）")
            yield Event("done", data={"ok": True})

    async def scenario():
        hub = Hub({"claude": None})
        conv = Conversation(key="k", mode="ask", task=Task("ask", "q", "text"), session=Looking())
        conv.decision = Decision(engine="claude", model="m", effort="high", reason="", mode="ask")
        await hub._turn(conv, "q", [])
        return conv

    assert asyncio.run(scenario()).live_ui
