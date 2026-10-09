"""助手动真实鼠标时，Super Aide 自己的窗口暂时不接点击。

这些窗口（操作中的胶囊、点开后的进度小窗）不出现在截图里（WDA_EXCLUDEFROMCAPTURE），引擎看不见它们，
会照着下面的内容去点；胶囊能点开以后，它占着的那一块就会把助手的点击接走。
护栏开始挡你的输入时（engage）把它们设成鼠标穿透，放开时（release）复原。
只动主程序（环境变量 SUPER_AIDE_PID）里截图看不见的分层窗口，别的程序的窗口不碰。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT, WS_EX_LAYERED = 0x20, 0x80000
WDA_EXCLUDEFROMCAPTURE = 0x11

user32 = ctypes.WinDLL("user32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.GetWindowDisplayAffinity.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.GetWindowLongW.restype = wintypes.LONG
user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.LONG)

_lifted: list[int] = []


def ours(pid: int) -> list[int]:
    """主程序里正显示着、截图看不见的顶层窗口。"""
    found: list[int] = []

    @WNDENUMPROC
    def visit(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            affinity = wintypes.DWORD()
            if user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity)) and affinity.value == WDA_EXCLUDEFROMCAPTURE:
                found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found


def lift() -> None:
    """让它们穿透（已经穿透的不动，免得放开时把主程序自己设的穿透也撤了）。"""
    if _lifted:
        return
    pid = int(os.environ.get("SUPER_AIDE_PID") or 0)
    if not pid:
        return
    for hwnd in ours(pid):
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if style & WS_EX_LAYERED and not style & WS_EX_TRANSPARENT:  # 不是分层窗口的话，穿透标志不管用
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT)
            _lifted.append(hwnd)


def restore() -> None:
    while _lifted:
        hwnd = _lifted.pop()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if style & WS_EX_TRANSPARENT:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT)
