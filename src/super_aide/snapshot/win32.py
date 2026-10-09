"""Win32 层：前台窗口、可见窗口列表、窗口截图（被挡住也能截到）。

坐标一律是物理像素：进程启动时由 Qt 声明了 Per-Monitor V2 DPI 感知。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import win32con
import win32gui
import win32process
import win32ui
from PIL import Image

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi
advapi32 = ctypes.windll.advapi32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
PW_RENDERFULLCONTENT = 0x2

Rect = tuple[int, int, int, int]  # left, top, right, bottom


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process: str          # exe 文件名
    pid: int
    rect: Rect            # DWM 可见边界（不含 Win11 四周看不见的缩放边框）
    minimized: bool
    elevated: bool | None  # None = 无法判断
    class_name: str = ""


def _open_process(pid: int) -> int:
    return kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)


def process_name(pid: int) -> str:
    h = _open_process(pid)
    if not h:
        return f"pid{pid}"
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name
        return f"pid{pid}"
    finally:
        kernel32.CloseHandle(h)


def is_elevated(pid: int) -> bool | None:
    h = _open_process(pid)
    if not h:
        return None
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(token)):
            return None
        elevation = wintypes.DWORD()
        size = wintypes.DWORD()
        ok = advapi32.GetTokenInformation(token, TOKEN_ELEVATION, ctypes.byref(elevation),
                                          ctypes.sizeof(elevation), ctypes.byref(size))
        return bool(elevation.value) if ok else None
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(h)


def dwm_rect(hwnd: int) -> Rect | None:
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                    ctypes.byref(r), ctypes.sizeof(r)) != 0:
        return None
    return r.left, r.top, r.right, r.bottom


def _is_cloaked(hwnd: int) -> bool:
    cloaked = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return cloaked.value != 0


def window_info(hwnd: int) -> WindowInfo | None:
    if not hwnd or not win32gui.IsWindow(hwnd):
        return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    rect = dwm_rect(hwnd) or win32gui.GetWindowRect(hwnd)
    return WindowInfo(hwnd=hwnd, title=win32gui.GetWindowText(hwnd), process=process_name(pid),
                      pid=pid, rect=rect, minimized=bool(win32gui.IsIconic(hwnd)),
                      elevated=is_elevated(pid), class_name=win32gui.GetClassName(hwnd))


def foreground() -> WindowInfo | None:
    return window_info(user32.GetForegroundWindow())


def visible_windows(exclude: set[int] = frozenset()) -> list[WindowInfo]:
    """按 Z 序（从上到下）列出用户能看到的应用窗口，含最小化的。"""
    hwnds: list[int] = []

    def cb(hwnd: int, _: object) -> bool:
        if hwnd in exclude or not win32gui.IsWindowVisible(hwnd) or _is_cloaked(hwnd):
            return True
        if not win32gui.GetWindowText(hwnd) or win32gui.GetWindow(hwnd, win32con.GW_OWNER):
            return True
        if win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
            return True
        hwnds.append(hwnd)
        return True

    win32gui.EnumWindows(cb, None)
    return [w for w in (window_info(h) for h in hwnds) if w is not None]


def capture_window(hwnd: int) -> Image.Image | None:
    """PrintWindow + PW_RENDERFULLCONTENT：窗口被挡住也能截到；最小化的窗口没有画面，返回 None。"""
    if win32gui.IsIconic(hwnd):
        return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return None
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    mem_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    try:
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        mem_dc.SelectObject(bmp)
        if not user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), PW_RENDERFULLCONTENT):
            return None
        info = bmp.GetInfo()
        img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                               bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    finally:
        win32gui.DeleteObject(bmp.GetHandle())
        mem_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
    vis = dwm_rect(hwnd)
    if vis:
        vl, vt, vr, vb = vis
        img = img.crop((vl - left, vt - top, vr - left, vb - top))
    return None if is_blank(img) else img


def is_blank(img: Image.Image) -> bool:
    lo, hi = img.convert("L").getextrema()
    return hi - lo < 8
