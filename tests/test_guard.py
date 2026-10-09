"""键鼠护栏和"把前台还给用户"的判断。钩子回调直接用构造的事件调用，不装真钩子、不动真键鼠。"""

from __future__ import annotations

import ctypes
import time

import pytest

from super_aide.cu import guard
from super_aide.snapshot.win32 import WindowInfo

PASS = 0  # 不在钩子链里调用 CallNextHookEx 时返回 0：表示放行


def _key(vk: int, injected: bool = False):
    ev = guard.KBDLLHOOKSTRUCT(vkCode=vk, flags=guard.LLKHF_INJECTED if injected else 0)
    return ev, ctypes.addressof(ev)


def _mouse(injected: bool = False):
    ev = guard.MSLLHOOKSTRUCT(flags=guard.LLMHF_INJECTED if injected else 0)
    return ev, ctypes.addressof(ev)


@pytest.fixture
def held():
    g = guard.Guard()
    noticed = []
    g.on_blocked = noticed.append
    g.held, g.until = True, time.monotonic() + 5
    g.noticed = noticed
    return g


def test_blocks_your_keys_and_mouse_while_held(held):
    _ev, a = _key(0x41)
    assert held._on_key(0, guard.WM_KEYDOWN, a) == 1
    _ev, m = _mouse()
    assert held._on_mouse(0, guard.WM_MOUSEMOVE, m) == 1
    assert held._on_mouse(0, 0x0201, m) == 1  # 左键按下
    assert held.user_moved and held.blocked == 3
    assert len(held.noticed) == 1  # 只提示一次


def test_lets_assistant_input_and_releases_through(held):
    _ev, a = _key(0x41, injected=True)
    assert held._on_key(0, guard.WM_KEYDOWN, a) == PASS
    _ev, up = _key(0x41)
    assert held._on_key(0, 0x0101, up) == PASS  # 按键抬起放行：你按着的键不会卡住
    _ev, m = _mouse(injected=True)
    assert held._on_mouse(0, guard.WM_MOUSEMOVE, m) == PASS
    _ev, m = _mouse()
    assert held._on_mouse(0, 0x0202, m) == PASS  # 左键抬起放行
    assert held.blocked == 0 and not held.noticed


def test_escape_always_passes_and_lets_go(held):
    _ev, esc = _key(guard.VK_ESCAPE)
    assert held._on_key(0, guard.WM_KEYDOWN, esc) == PASS
    _ev, a = _key(0x41)
    assert held._on_key(0, guard.WM_KEYDOWN, a) == PASS  # 按过 Esc 就不再挡


def test_never_blocks_longer_than_max_hold(held):
    held.until = time.monotonic() - 0.01
    _ev, a = _key(0x41)
    assert held._on_key(0, guard.WM_KEYDOWN, a) == PASS
    held.held, held.until = False, time.monotonic() + 5
    assert held._on_key(0, guard.WM_KEYDOWN, a) == PASS


def test_release_puts_your_cursor_back_only_when_you_were_elsewhere(monkeypatch):
    moved = []
    monkeypatch.setattr(guard.user32, "SetCursorPos", lambda x, y: moved.append((x, y)))
    monkeypatch.setattr(guard.user32, "PostThreadMessageW", lambda *a: None)
    g = guard.Guard()
    g._ack.set = lambda: None
    g.held, g.user_cursor = True, (10, 10)
    monkeypatch.setattr(guard, "_inside", lambda hwnd, pt: True)  # 你的鼠标本来就停在助手操作的窗口上
    g._ack.wait = lambda timeout: True
    g.release(target=123)
    assert moved == []
    g.held, g.user_moved = True, True  # 挡着的时候你动过鼠标：你在用，放回去
    g.release(target=123)
    assert moved == [(10, 10)]
    monkeypatch.setattr(guard, "_inside", lambda hwnd, pt: False)
    g.held, g.user_moved = True, False  # 你的鼠标在别的地方
    g.release(target=123)
    g.held = True
    g.release(target=123, keep_cursor=True)  # 悬停：鼠标得留在那里
    assert moved == [(10, 10), (10, 10)]


def test_settle_waits_for_you_to_let_go_then_releases_for_you(monkeypatch):
    """你按着鼠标左键（正在拖东西）：等一会儿你松开了就不用管；一直按着就替你松开，助手的点击才不会落进你拖的窗口。"""
    state = {0x01: True, 0x11: False}
    sent = []
    monkeypatch.setattr(guard.user32, "GetAsyncKeyState", lambda vk: 0x8000 if state.get(vk) else 0)
    monkeypatch.setattr(guard.user32, "mouse_event", lambda flags, *a: sent.append(("mouse", flags)))
    monkeypatch.setattr(guard.user32, "keybd_event", lambda vk, scan, flags, extra: sent.append(("key", vk, flags)))
    monkeypatch.setattr(guard, "SETTLE", 0.1)
    g = guard.Guard()
    g._settle()
    assert sent == [("mouse", 0x0004)]  # 一直按着：替你松开左键

    sent.clear()
    state[0x01], state[0x11] = False, True  # 你按着 Ctrl
    monkeypatch.setattr(guard.time, "sleep", lambda s: state.update({0x11: False}))  # 等的时候你松开了
    g._settle()
    assert sent == []


# ---- 用户在用别的窗口时，做完把前台还给他 ----


def _win(hwnd: int, pid: int = 50, title: str = "窗口") -> WindowInfo:
    return WindowInfo(hwnd=hwnd, title=title, process="app.exe", pid=pid, rect=(0, 0, 10, 10),
                      minimized=False, elevated=False)


@pytest.fixture
def server(monkeypatch):
    from super_aide.cu import server as srv

    monkeypatch.setattr(srv, "OWN_PID", 999)
    monkeypatch.setitem(srv.STATE, "fg_after", None)
    monkeypatch.setitem(srv.STATE, "given_back", None)
    return srv


def test_user_window_rules(server, monkeypatch):
    fg = {"w": _win(1)}
    monkeypatch.setattr(server.win32, "foreground", lambda: fg["w"])
    target = 1
    assert server._user_window(target) == 0  # 第一步：用户刚在这个窗口上召唤了助手
    server.STATE["fg_after"] = 1
    fg["w"] = _win(2, title="飞书")
    assert server._user_window(target) == 2  # 上一步之后用户切到了飞书
    server.STATE["fg_after"], server.STATE["given_back"] = 2, 2
    assert server._user_window(target) == 2  # 还在用上次还给他的窗口
    server.STATE["given_back"] = None
    assert server._user_window(target) == 0  # 前台是助手自己上一步留下的，不是用户切的
    fg["w"] = _win(3, pid=999)
    server.STATE["fg_after"] = 1
    assert server._user_window(target) == 0  # 超级助手自己的窗口不算
    fg["w"] = _win(1)
    assert server._user_window(target) == 0  # 用户切回了助手正在操作的窗口


def test_after_target_ignores_the_users_other_app(server, monkeypatch):
    windows = {1: _win(1, pid=50), 7: _win(7, pid=50, title="另存为"), 9: _win(9, pid=60, title="飞书")}
    monkeypatch.setattr(server.win32, "window_info", lambda h: windows.get(h))
    monkeypatch.setattr(server.win32, "foreground", lambda: windows[7])
    assert server._after_target(1) == (7, "")  # 目标程序弹出的对话框：看它
    monkeypatch.setattr(server.win32, "foreground", lambda: windows[9])
    target, note = server._after_target(1)
    assert target == 1 and "飞书" in note  # 别的程序：还看原来的，提一句
    assert server._after_target(1, user=9) == (1, "")  # 用户正在用的窗口：不用提
