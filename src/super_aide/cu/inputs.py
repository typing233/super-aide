"""真实的键鼠输入（SendInput）和把窗口切到前台。坐标是物理像素。

中文等任意文字用 Unicode 输入（KEYEVENTF_UNICODE），不经过输入法；长文字走剪贴板粘贴，快而且不会被自动补全打乱。
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Callable
from ctypes import wintypes

import win32clipboard
import win32con

from .guard import GUARD
from .keys import EXTENDED, parse_combo

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
for _name in ("IsIconic", "BringWindowToTop", "SetForegroundWindow"):
    getattr(user32, _name).argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
MOUSE_DOWN = {"left": 0x2, "right": 0x8, "middle": 0x20}
MOUSE_UP = {"left": 0x4, "right": 0x10, "middle": 0x40}
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x800, 0x1000
WHEEL_DELTA = 120
PASTE_OVER = 120  # 超过这么多字改用粘贴


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _KeybdInput(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput), ("ki", _KeybdInput), ("hi", _HardwareInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _InputUnion)]


def _send(*inputs: _Input) -> None:
    GUARD.engage()  # 要动真实键鼠了：先挡住你亲手的输入，免得两边搅在一起
    array = (_Input * len(inputs))(*inputs)
    if user32.SendInput(len(inputs), array, ctypes.sizeof(_Input)) != len(inputs):
        raise OSError(f"SendInput 失败（{ctypes.get_last_error()}），可能被更高权限的窗口挡住了")


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> _Input:
    if vk in EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    return _Input(type=INPUT_KEYBOARD, u=_InputUnion(ki=_KeybdInput(wVk=vk, wScan=scan, dwFlags=flags)))


def _mouse(flags: int, data: int = 0) -> _Input:
    return _Input(type=INPUT_MOUSE, u=_InputUnion(mi=_MouseInput(mouseData=data & 0xFFFFFFFF, dwFlags=flags)))


# ---------- 鼠标 ----------

def move(x: int, y: int) -> None:
    GUARD.engage()
    user32.SetCursorPos(int(x), int(y))


def click(x: int, y: int, button: str = "left", count: int = 1) -> None:
    move(x, y)
    time.sleep(0.03)
    for i in range(max(1, count)):
        _send(_mouse(MOUSE_DOWN[button]), _mouse(MOUSE_UP[button]))
        if i + 1 < count:
            time.sleep(0.05)


def scroll(x: int, y: int, dy: int = 0, dx: int = 0) -> None:
    """dy 正数向下、负数向上，单位是滚轮的一格。"""
    move(x, y)
    time.sleep(0.02)
    if dy:
        _send(_mouse(MOUSEEVENTF_WHEEL, -dy * WHEEL_DELTA))
    if dx:
        _send(_mouse(MOUSEEVENTF_HWHEEL, dx * WHEEL_DELTA))


def drag(x0: int, y0: int, x1: int, y1: int, button: str = "left", steps: int = 12) -> None:
    move(x0, y0)
    time.sleep(0.05)
    _send(_mouse(MOUSE_DOWN[button]))
    for i in range(1, steps + 1):
        move(x0 + (x1 - x0) * i // steps, y0 + (y1 - y0) * i // steps)
        time.sleep(0.015)
    time.sleep(0.05)
    _send(_mouse(MOUSE_UP[button]))


# ---------- 键盘 ----------

def press(combo: str) -> None:
    vks = parse_combo(combo)
    _send(*[_key(vk) for vk in vks], *[_key(vk, flags=KEYEVENTF_KEYUP) for vk in reversed(vks)])


class Interrupted(Exception):
    pass


def type_text(text: str, should_stop: Callable[[], bool] | None = None) -> None:
    """逐字输入。换行和制表符按真的回车、Tab 键发，别的字符用 Unicode 输入。每 20 个字检查一次要不要停。"""
    for i, ch in enumerate(text):
        if should_stop is not None and i % 20 == 0 and should_stop():
            raise Interrupted(f"已停止（输入了 {i} 个字）")
        if ch == "\n":
            press("enter")
        elif ch == "\t":
            press("tab")
        elif ch != "\r":
            units = ch.encode("utf-16-le")
            events = []
            for i in range(0, len(units), 2):  # 超出基本平面的字符是两个 UTF-16 单元
                code = int.from_bytes(units[i:i + 2], "little")
                events += [_key(scan=code, flags=KEYEVENTF_UNICODE),
                           _key(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
            _send(*events)
        time.sleep(0.004)


def paste_text(text: str) -> None:
    """借剪贴板粘贴，之后把你原来剪贴板里的文字放回去。"""
    previous = _clipboard_text()
    _set_clipboard(text)
    time.sleep(0.05)
    press("ctrl+v")
    time.sleep(0.35)  # 程序是在处理到这个按键时才读剪贴板的，太早放回去会粘贴成你原来的内容
    if previous is not None:
        _set_clipboard(previous)


def enter_text(text: str, should_stop: Callable[[], bool] | None = None) -> str:
    """纯英文、数字的短文字逐字输入；有中文、表情、换行或者很长的，走剪贴板粘贴。
    中文输入法开着的时候逐字发 Unicode 会丢字、重字（自检实测："：中文😀" 变成 "：：文"），粘贴不经过输入法。"""
    if len(text) > PASTE_OVER or not text.isascii() or "\n" in text:
        paste_text(text)
        return "粘贴"
    type_text(text, should_stop)
    return "键入"


def _clipboard_text() -> str | None:
    try:
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            return None
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001 - 剪贴板被别的程序占着
        return None


def _set_clipboard(text: str) -> None:
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                return
            finally:
                win32clipboard.CloseClipboard()
        except Exception:  # noqa: BLE001
            time.sleep(0.05)
    raise OSError("剪贴板被别的程序占着，没法粘贴")


# ---------- 窗口 ----------

def focus_window(hwnd: int, timeout: float = 1.0) -> bool:
    """把窗口切到前台。系统限制后台进程抢前台，先把输入队列挂到当前前台窗口上再切。
    切前台之后紧接着就是真实键鼠，所以从这里就开始挡你的输入（不然你一点，前台又被切走了）。"""
    GUARD.engage()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    if user32.GetForegroundWindow() == hwnd:
        return True
    fg = user32.GetForegroundWindow()
    ours = kernel32.GetCurrentThreadId()
    theirs = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(theirs) and theirs != ours and user32.AttachThreadInput(ours, theirs, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(ours, theirs, False)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.03)
    # 最后一招：模拟按一下 Alt，系统就允许本进程设置前台
    _send(_key(0x12), _key(0x12, flags=KEYEVENTF_KEYUP))
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.1)
    return user32.GetForegroundWindow() == hwnd
