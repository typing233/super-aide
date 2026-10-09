"""P0-⑤ 补充：预热后的真实耗时，以及浏览器正文的直接定位。

1. 全屏截图拆开计时：原始像素抓取 / 转成图片 / 编码成 PNG、JPEG
2. UIA 预热后再取焦点和选中文字
3. 浏览器：用 UIA 原生 FindFirst 直接找文档节点（在 UIA 内部搜索，不在 Python 里逐个遍历）

用法：uv run python spikes/p0_snapshot_bench.py
"""

from __future__ import annotations

import ctypes
import io
import time

ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

import mss  # noqa: E402
import uiautomation as auto  # noqa: E402
import win32gui  # noqa: E402
from PIL import Image  # noqa: E402

from p0_snapshot import process_name, top_level_windows  # noqa: E402


def ms(t: float) -> str:
    return f"{(time.perf_counter() - t) * 1000:.0f}ms"


def bench_screen() -> None:
    with mss.MSS() as sct:
        t = time.perf_counter()
        sct.grab(sct.monitors[0])
        print(f"截图 首次抓取 {ms(t)}")
        for _ in range(3):
            t = time.perf_counter()
            shot = sct.grab(sct.monitors[0])
            grab = ms(t)
        t = time.perf_counter()
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        conv = ms(t)
        for fmt, kw in (("PNG", {}), ("PNG", {"compress_level": 1}), ("JPEG", {"quality": 85})):
            t = time.perf_counter()
            img.save(io.BytesIO(), fmt, **kw)
            print(f"  编码 {fmt} {kw or ''} {ms(t)}")
        print(f"截图 预热后抓取 {grab}，转图片 {conv}")


def bench_focus() -> None:
    t = time.perf_counter()
    auto.GetRootControl()
    print(f"UIA 初始化 {ms(t)}")
    for i in range(3):
        t = time.perf_counter()
        focused = auto.GetFocusedControl()
        kind = focused.ControlTypeName if focused else None
        pattern = focused.GetPattern(auto.PatternId.TextPattern) if focused else None
        n = 0
        if pattern:
            sel = pattern.GetSelection()
            n = sum(len(r.GetText(-1)) for r in sel) if sel else 0
        print(f"  焦点+选中文字 第{i + 1}次 {ms(t)}（焦点类型 {kind}，选中 {n} 字）")


def bench_browser_document() -> None:
    from uiautomation.uiautomation import _AutomationClient
    uia = _AutomationClient.instance().IUIAutomation
    cond = uia.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty,
                                       auto.ControlType.DocumentControl)
    for hwnd in top_level_windows():
        proc = process_name(hwnd)
        if proc.lower() not in ("msedge.exe", "chrome.exe"):
            continue
        t = time.perf_counter()
        root = auto.ControlFromHandle(hwnd)
        elem = root.Element.FindFirst(4, cond)  # TreeScope_Descendants（uiautomation 库未导出该枚举）
        find = ms(t)
        if not elem:
            print(f"{proc}：FindFirst 没找到文档节点（{find}）")
            continue
        doc = auto.Control.CreateControlFromElement(elem)
        t = time.perf_counter()
        pattern = doc.GetPattern(auto.PatternId.TextPattern)
        text = pattern.DocumentRange.GetText(200_000) if pattern else ""
        print(f"{proc}：FindFirst {find}，读正文 {ms(t)}，{len(text)} 字"
              f"（窗口{'最小化' if win32gui.IsIconic(hwnd) else '正常'}）")


if __name__ == "__main__":
    bench_screen()
    bench_focus()
    bench_browser_document()
