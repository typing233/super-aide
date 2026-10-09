"""急停：操作进行中监听物理 Esc 键（低级键盘钩子）。

助手自己模拟的按键带有"注入"标记，这里会忽略，只响应你亲手按下的 Esc。
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_SYSKEYDOWN, WM_QUIT = 0x0100, 0x0104, 0x0012
VK_ESCAPE = 0x1B
LLKHF_INJECTED = 0x10

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class EscWatcher(QObject):
    triggered = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._proc = HOOKPROC(self._hook)  # 必须保持引用，否则回调会被回收

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="esc-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is not None and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self._thread = None
        self._tid = 0

    def _run(self) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        if hook:
            user32.UnhookWindowsHookEx(hook)

    def _hook(self, code: int, wparam: int, lparam: int) -> int:
        if code == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = KBDLLHOOKSTRUCT.from_address(lparam)
            if kb.vkCode == VK_ESCAPE and not kb.flags & LLKHF_INJECTED:
                self.triggered.emit()
                return 1  # 吞掉这次 Esc：它是给助手的"停止"，不该再传给当前应用
        return user32.CallNextHookEx(None, code, wparam, lparam)
