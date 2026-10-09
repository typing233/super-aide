"""卡住时也停得下来：还在打开引擎时按 Esc、引擎不理 Esc、打开超时换一个引擎、输出没给结果就断了、
系统线程池的等待回调卡死时照样知道子进程退出了（2026-10-09：Alt+W 停在"正在理解任务…"15 分钟，Esc 没反应）。"""

import asyncio
import sys
from types import SimpleNamespace

from super_aide import app
from super_aide.engines import hub as hub_module
from super_aide.engines.base import Event
from super_aide.engines.hub import Conversation, EngineHub
from super_aide.router import Decision, Task


class Router:
    def __init__(self, engines):
        self.order, self.unavailable = list(engines), set()

    def decide(self, task):
        engine = next(e for e in self.order if e not in self.unavailable)
        return Decision(engine=engine, model="m", effort="medium", reason="", mode=task.mode)

    def mark_unavailable(self, engine):
        self.unavailable.add(engine)

    def available(self):
        return [e for e in self.order if e not in self.unavailable]


class Session:
    """先报一步，然后：done 正常结束；hang 等到被打断才结束（stop_ok=False 时打断了也不理）；end 不给结果就断开。"""

    def __init__(self, script="done", stop_ok=True):
        self.script, self.stop_ok, self.closed = script, stop_ok, False
        self.interrupted = asyncio.Event()

    async def send(self, text, images):
        yield Event("status", "正在操作界面…")
        if self.script == "end":
            return
        if self.script == "hang":
            await self.interrupted.wait()
            if not self.stop_ok:
                await asyncio.Event().wait()
            yield Event("done", data={"ok": False, "reason": "interrupted"})
            return
        yield Event("done", data={"ok": True})

    async def interrupt(self):
        self.interrupted.set()

    async def close(self):
        self.closed = True


class Engine:
    def __init__(self, session=None):
        self.session = session  # 没有会话：打开一直卡着

    async def open(self, mode, model, effort):
        if self.session is None:
            await asyncio.Event().wait()
        return self.session


class Hub:
    """EngineHub 里和停下、打开有关的方法；经验、路由学习、历史这些换成空的。"""

    interrupt, is_busy = EngineHub.interrupt, EngineHub.is_busy
    _first_turn, _open, _turn = EngineHub._first_turn, EngineHub._open, EngineHub._turn
    _stop, _drop_sessions = EngineHub._stop, EngineHub._drop_sessions
    _ask_to_stop = EngineHub.__dict__["_ask_to_stop"]

    def __init__(self, engines):
        self.engines, self.router, self.conversations, self.gui = engines, Router(engines), {}, "ours"
        self.loop, self.events = asyncio.get_running_loop(), []

    def _emit(self, key, ev):
        self.events.append(ev)

    def _submit(self, coro):
        return asyncio.ensure_future(coro)

    def _recall(self, conv, situation):
        return []

    def _vector(self, question, text):
        return None

    def _notes(self, conv):
        return []

    def _noop(self, *args, **kwargs):
        return None

    _check_reask = _check_outcome = _watch_outcome = _learn_from_turn = _after_first_turn = _noop
    _lessons_used = _save_history = _schedule_learning = _schedule_evolve = _crashed = _noop

    def done(self):
        return [e for e in self.events if e.type == "done"]


def snapshot():
    ctx = SimpleNamespace(images=[])
    return SimpleNamespace(dir=None, url="", finalize=lambda: ctx,
                           situation=lambda q: SimpleNamespace(text="", errors=""))


def ask(engines, until=None, press_esc=False):
    """首问跑起来；until 出现（有的话）后按 Esc；等这一轮结束。返回 (hub, 对话)。"""
    async def scenario():
        hub = Hub(engines)
        conv = Conversation(key="k", mode="act", task=Task("act", "看看有哪些模型", "text"), busy=True)
        hub.conversations["k"] = conv
        job = asyncio.ensure_future(hub._first_turn(conv, "看看有哪些模型", snapshot()))
        if press_esc:
            while until is not None and not any(e.type == until for e in hub.events):
                await asyncio.sleep(0.005)
            await asyncio.sleep(0.01)
            assert hub.is_busy("k")
            hub.interrupt("k")
        await job
        await asyncio.sleep(0)  # 让后台关会话的任务跑完
        return hub, conv

    return asyncio.run(asyncio.wait_for(scenario(), 5))


def test_esc_while_the_engine_is_still_opening(monkeypatch):
    """原来 Esc 只在引擎开始回答以后才有用，打开卡住时按了没反应。现在直接结束这一轮。"""
    monkeypatch.setattr(hub_module.prompts, "first_message", lambda *a: "消息")
    hub, conv = ask({"claude": Engine()}, press_esc=True)
    assert len(hub.done()) == 1 and hub.done()[0].data["stopped"]
    assert not conv.busy and conv.session is None


def test_engine_that_does_not_open_in_time_is_swapped(monkeypatch):
    monkeypatch.setattr(hub_module, "OPEN_TIMEOUT", 0.05)
    monkeypatch.setattr(hub_module.prompts, "first_message", lambda *a: "消息")
    hub, _conv = ask({"claude": Engine(), "codex": Engine(Session())})
    assert hub.router.unavailable == {"claude"}
    assert "换一个引擎接着做" in next(e.text for e in hub.events if e.type == "status")
    assert len(hub.done()) == 1 and hub.done()[0].data["ok"]


def test_esc_asks_the_engine_to_stop_first(monkeypatch):
    monkeypatch.setattr(hub_module.prompts, "first_message", lambda *a: "消息")
    session = Session("hang")
    hub, conv = ask({"claude": Engine(session)}, until="status", press_esc=True)
    assert session.interrupted.is_set()
    assert len(hub.done()) == 1 and hub.done()[0].data["stopped"]
    assert conv.session is session and not session.closed  # 它自己停下了：会话还能接着问


def test_engine_that_ignores_esc_is_cut_off(monkeypatch):
    monkeypatch.setattr(hub_module, "STOP_GRACE", 0.05)
    monkeypatch.setattr(hub_module.prompts, "first_message", lambda *a: "消息")
    session = Session("hang", stop_ok=False)
    hub, conv = ask({"claude": Engine(session)}, until="status", press_esc=True)
    assert len(hub.done()) == 1 and hub.done()[0].data["stopped"]
    assert conv.session is None and session.closed and not conv.busy  # 它可能还停在半路：不再用这个会话


def test_output_that_ends_without_a_result_is_reported(monkeypatch):
    monkeypatch.setattr(hub_module.prompts, "first_message", lambda *a: "消息")
    hub, conv = ask({"claude": Engine(Session("end"))})
    assert [e.type for e in hub.events][-2:] == ["error", "done"]
    assert not hub.done()[0].data["ok"] and "ConnectionError" in hub.done()[0].data["exception"]
    assert not conv.busy


def test_child_exit_is_seen_when_thread_pool_waits_never_fire(monkeypatch):
    from asyncio import windows_events

    transport = windows_events._WindowsSubprocessTransport
    monkeypatch.setattr(transport, "_start", transport._start)  # 测完换回原样
    monkeypatch.setattr(windows_events.IocpProactor, "wait_for_handle",
                        lambda self, handle, timeout=None: self._loop.create_future())  # 等待回调永远不来

    async def exit_code(wait_s):
        proc = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
        popen = proc._transport.get_extra_info("subprocess")
        while popen.poll() is None:  # 等进程真的退出
            await asyncio.sleep(0.02)
        try:
            return await asyncio.wait_for(proc.wait(), wait_s)
        except TimeoutError:
            proc._transport.close()
            return None

    assert asyncio.run(exit_code(0.3)) is None  # 原来的做法：进程退出了也一直等不到
    app._watch_child_exits()
    assert asyncio.run(exit_code(10)) == 0
