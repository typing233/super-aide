"""键鼠护栏：助手要用真实键鼠的那一刻，暂时挡住你亲手的键鼠，免得两边的输入搅在一起。

- 只在真要动键鼠的时候挡（点网页、在网页里打字、按快捷键、拖动……），通常不到 1 秒；最长 MAX_HOLD 秒自动放开。
  用控件直接操作（不动鼠标）、跑命令、读界面、模型思考的时候都不挡，你可以照常用电脑。
- 只挡你亲手的输入：助手模拟的输入带"注入"标记，照常通过。按键抬起、鼠标按钮抬起也放行，免得你按着的键卡住。
- Esc 永远放行（交给主程序急停），而且一按就马上放开护栏。
- 挡住你的时候，鼠标旁边提示"助手正在用键鼠"。
- 开始挡的时候你正按着鼠标键或 Ctrl、Shift 这些键：先等你松开（最多 SETTLE 秒），还按着就替你松开。
  不然助手的点击会落进你正在拖的窗口（按着鼠标时它"捕获"了鼠标），打的字会变成快捷键（实测：用户正在用鼠标时第一下点击丢了）。
- 放开时，如果你刚才在别处用鼠标，把鼠标放回你原来的位置。

SetCursorPos 不经过低级鼠标钩子（实测），所以助手自己移动鼠标不会被当成你在动。
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

MAX_HOLD = 8.0  # 一次最多挡这么久，之后不管助手做没做完都放开
SETTLE = 1.2  # 最多等你松开按着的键多久
#: 按着会改掉助手输入的：鼠标左、右、中键，Shift、Ctrl、Alt、左右 Win
WATCHED = ((0x01, 0x0004), (0x02, 0x0010), (0x04, 0x0040), (0x10, 0), (0x11, 0), (0x12, 0), (0x5B, 0), (0x5C, 0))
KEYEVENTF_KEYUP = 0x0002
WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_APP_ON, WM_APP_OFF, WM_QUIT = 0x8001, 0x8002, 0x0012
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
WM_MOUSEMOVE = 0x0200
MOUSE_UPS = {0x0202, 0x0205, 0x0208, 0x020C}  # 左、右、中、侧键抬起
VK_ESCAPE = 0x1B
LLKHF_INJECTED, LLMHF_INJECTED = 0x10, 0x01

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


def cursor() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


class Guard:
    def __init__(self) -> None:
        self.enabled = True
        self.held = False
        self.until = 0.0
        self.user_cursor: tuple[int, int] | None = None  # 挡之前你的鼠标在哪
        self.user_moved = False  # 挡着的时候你动过鼠标
        self.blocked = 0  # 挡掉了你几次输入
        self.installed = 0  # 现在装着几个钩子（自检用）
        #: 第一次挡掉你的输入时调用（参数是鼠标位置），用来提示你
        self.on_blocked: Callable[[tuple[int, int]], None] | None = None
        self._noticed = False
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._ready = threading.Event()
        self._ack = threading.Event()
        self._kb = HOOKPROC(self._on_key)  # 必须保持引用，否则回调会被回收
        self._ms = HOOKPROC(self._on_mouse)

    # ---------- 动作线程调用 ----------

    def engage(self) -> None:
        """要动真实键鼠了：开始挡（已经在挡就什么也不做）。"""
        if self.held or not self.enabled:
            return
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="input-guard", daemon=True)
            self._thread.start()
            self._ready.wait(1.0)
        self.user_cursor = cursor()
        self.user_moved, self.blocked, self._noticed = False, 0, False
        self.until = time.monotonic() + MAX_HOLD
        self.held = True
        self._ack.clear()
        user32.PostThreadMessageW(self._tid, WM_APP_ON, 0, 0)
        self._ack.wait(0.3)
        self._settle()

    def _settle(self) -> None:
        """等你松开按着的鼠标键和 Ctrl、Shift 这些键（护栏放行抬起）；等不到就替你松开。"""
        end = time.monotonic() + SETTLE
        while time.monotonic() < end and any(_down(vk) for vk, _up in WATCHED):
            time.sleep(0.03)
        for vk, mouse_up in WATCHED:
            if _down(vk):
                if mouse_up:
                    user32.mouse_event(mouse_up, 0, 0, 0, 0)
                else:
                    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    def release(self, keep_cursor: bool = False, target: int = 0) -> None:
        """这一段真实键鼠做完了：放开。你刚才在别处用鼠标的话，把鼠标放回去。"""
        if not self.held:
            return
        self.held = False
        self._ack.clear()
        user32.PostThreadMessageW(self._tid, WM_APP_OFF, 0, 0)
        self._ack.wait(0.3)
        if self.user_cursor is not None and not keep_cursor and (self.user_moved or not _inside(target, self.user_cursor)):
            user32.SetCursorPos(*self.user_cursor)

    # ---------- 钩子线程 ----------

    def _run(self) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # 先建好消息队列，才收得到线程消息
        self._ready.set()
        hooks: list[int] = []
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_APP_ON:
                if not hooks:
                    module = kernel32.GetModuleHandleW(None)
                    hooks = [h for h in (user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb, module, 0),
                                         user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms, module, 0)) if h]
                self.installed = len(hooks)
                self._ack.set()
            elif msg.message == WM_APP_OFF:
                for h in hooks:  # 不挡的时候不留钩子：每个键鼠事件都要经过钩子，留着会拖慢整台电脑
                    user32.UnhookWindowsHookEx(h)
                hooks = []
                self.installed = 0
                self._ack.set()
        for h in hooks:
            user32.UnhookWindowsHookEx(h)

    def _active(self) -> bool:
        return self.held and time.monotonic() < self.until

    def _block(self, pos: tuple[int, int]) -> int:
        self.blocked += 1
        if not self._noticed and self.on_blocked is not None:
            self._noticed = True
            try:
                self.on_blocked(pos)
            except Exception:  # noqa: BLE001 - 提示失败不能影响挡输入
                pass
        return 1

    def _on_key(self, code: int, wparam: int, lparam: int) -> int:
        if code == 0 and self._active() and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = KBDLLHOOKSTRUCT.from_address(lparam)
            if not kb.flags & LLKHF_INJECTED:
                if kb.vkCode == VK_ESCAPE:
                    self.until = 0.0  # 你要接管：马上放开，Esc 照常交给主程序去停止助手
                else:
                    return self._block(cursor())
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _on_mouse(self, code: int, wparam: int, lparam: int) -> int:
        if code == 0 and self._active() and wparam not in MOUSE_UPS:
            ms = MSLLHOOKSTRUCT.from_address(lparam)
            if not ms.flags & LLMHF_INJECTED:
                if wparam == WM_MOUSEMOVE:
                    self.user_moved = True
                return self._block(cursor())
        return user32.CallNextHookEx(None, code, wparam, lparam)


def _down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _inside(hwnd: int, pt: tuple[int, int]) -> bool:
    if not hwnd:
        return False
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    return r.left <= pt[0] < r.right and r.top <= pt[1] < r.bottom


GUARD = Guard()
