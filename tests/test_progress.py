"""看得见助手在干什么：想得久时显示"正在思考…"（不算一步）、托盘只在改进进行中才显示那一行、
胶囊能点开以后助手动真实鼠标时让我们自己的窗口暂时穿透。"""

import asyncio
import time
from types import SimpleNamespace

from claude_agent_sdk import ResultMessage, StreamEvent

from super_aide.cu import passthrough
from super_aide.engines.base import Event
from super_aide.engines.claude import ClaudeSession
from super_aide.engines.hub import Conversation, EngineHub
from super_aide.router import Task
from super_aide.shell.tray import evolve_label


def stream(*events):
    return [StreamEvent(uuid=str(i), session_id="s", event=e) for i, e in enumerate(events)]


class Client:
    def __init__(self, messages):
        self.messages = messages

    async def query(self, prompt):
        async for _ in prompt:
            pass

    async def receive_response(self):
        for m in self.messages:
            yield m


def test_thinking_is_shown_as_a_passing_status():
    result = ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                           session_id="s", total_cost_usd=0.01)
    client = Client(stream({"type": "message_start"},
                           {"type": "content_block_start", "content_block": {"type": "thinking"}},
                           {"type": "content_block_start", "content_block": {"type": "text"}},
                           {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "好的"}}) + [result])

    async def collect():
        return [ev async for ev in ClaudeSession(client, SimpleNamespace()).send("问题", [])]

    events = asyncio.run(collect())
    thinking = [e for e in events if e.type == "status"]
    assert [e.text for e in thinking] == ["正在思考…"] and thinking[0].data == {"transient": True}
    assert [e.type for e in events][-2:] == ["delta", "done"]


def test_thinking_is_not_a_step():
    """"正在思考…"只是让你知道它在想：不进步骤列表，也不算进"这一步用了多久"。"""
    saved = {}

    class Session:
        async def send(self, text, images):
            yield Event("status", "正在思考…", {"transient": True})
            yield Event("status", "正在读 a.py")
            yield Event("status", "正在思考…", {"transient": True})
            yield Event("done", data={"ok": True})

    noop = lambda *a, **k: None  # noqa: E731
    hub = SimpleNamespace(_emit=noop, _check_outcome=noop, _watch_outcome=noop, _learn_from_turn=noop,
                          _after_first_turn=noop, _lessons_used=noop, _schedule_learning=noop, _schedule_evolve=noop,
                          _crashed=noop, _drop_sessions=noop, _avoid_after=noop,
                          _save_history=lambda conv, done, answer, trace=None: saved.update(trace=trace))
    conv = Conversation(key="k", mode="ask", task=Task("ask", "q", "text"), session=Session())
    asyncio.run(EngineHub._turn(hub, conv, "q", []))
    assert saved["trace"] == ["正在读 a.py"]


def test_tray_shows_improvement_only_while_it_runs():
    done = {"active": None, "items": [{"status": "done", "title": "设置里不再显示那一行", "finished": time.time()}]}
    assert evolve_label(done) == ""  # 做完了（生效时已经弹过通知）：菜单顶上不再占一行
    running = {"active": {"status": "running", "phase": "agent"}, "items": []}
    assert evolve_label(running) == "正在自我改进 · 正在分析和修改"
    assert evolve_label({"active": {"status": "ready"}, "items": []}).startswith("自我改进好了")  # 等你确认生效
    assert evolve_label(None) == ""


def test_our_invisible_windows_let_the_assistant_click_through(monkeypatch):
    styles = {1: passthrough.WS_EX_LAYERED, 2: passthrough.WS_EX_LAYERED | passthrough.WS_EX_TRANSPARENT, 3: 0}
    fake = SimpleNamespace(GetWindowLongW=lambda h, _i: styles[h],
                           SetWindowLongW=lambda h, _i, v: styles.__setitem__(h, v))
    monkeypatch.setattr(passthrough, "user32", fake)
    monkeypatch.setattr(passthrough, "ours", lambda pid: [1, 2, 3] if pid == 4242 else [])
    monkeypatch.setenv("SUPER_AIDE_PID", "4242")
    passthrough.lift()
    assert styles[1] & passthrough.WS_EX_TRANSPARENT  # 胶囊：助手的点击穿过去
    assert styles[3] == 0  # 不是分层窗口：穿透标志不管用，不动它
    passthrough.restore()
    assert styles[1] == passthrough.WS_EX_LAYERED  # 放开时复原
    assert styles[2] & passthrough.WS_EX_TRANSPARENT  # 本来就穿透的（主程序自己设的）不撤

    monkeypatch.delenv("SUPER_AIDE_PID")
    passthrough.lift()  # 不是从 Super Aide 启动的（比如单独跑工具服务器）：什么也不动
    assert styles[1] == passthrough.WS_EX_LAYERED
