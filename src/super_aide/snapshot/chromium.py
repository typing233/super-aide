"""Chromium / Electron 系窗口（Edge、Chrome、VS Code、各种 Electron 应用）的无障碍树是按需打开的：
没有读屏软件来问之前，网页内容根本不在 UI Automation 里。像读屏软件那样请求一次，它就会建起来。
"""

from __future__ import annotations

import ctypes

import win32gui

CHROMIUM_CHILD = "Chrome_RenderWidgetHostHWND"
WM_GETOBJECT, OBJID_CLIENT, SMTO_ABORTIFHUNG = 0x003D, -4, 0x0002


def children(hwnd: int) -> list[int]:
    """窗口里显示网页的子窗口（Edge 的侧边栏也算一个）。"""
    found: list[int] = []
    if not hwnd:
        return found  # 0 会被当成桌面：列出的是所有 Chromium 系程序的网页子窗口

    def visit(child: int, _) -> bool:
        if win32gui.GetClassName(child) == CHROMIUM_CHILD and win32gui.IsWindowVisible(child):
            found.append(child)
        return True

    try:
        win32gui.EnumChildWindows(hwnd, visit, None)
    except Exception:  # noqa: BLE001
        pass
    return found


def wake(hwnd: int) -> list[int]:
    """请求一次无障碍对象，返回网页子窗口（不是 Chromium 系窗口时返回空列表）。"""
    kids = children(hwnd)
    result = ctypes.c_size_t()
    for child in kids:
        ctypes.windll.user32.SendMessageTimeoutW(child, WM_GETOBJECT, 0, OBJID_CLIENT, SMTO_ABORTIFHUNG, 500,
                                                 ctypes.byref(result))
    return kids
