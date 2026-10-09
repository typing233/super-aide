"""大网页上 UIA 读取会不会卡住浏览器：在 Edge 里打开一个约 4 万个元素的靶子页，比较几种读法的耗时，
以及读的时候浏览器界面线程最长有多久没响应（另一个线程每 50ms 给浏览器窗口发一条空消息计时）。

    uv run --no-sync python -X utf8 spikes/p7_heavy_page.py
"""

from __future__ import annotations

import sys

sys.coinit_flags = 0

import ctypes  # noqa: E402

ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

import subprocess  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import win32gui  # noqa: E402
from uiautomation.uiautomation import _AutomationClient  # noqa: E402

from super_aide.cu import elements  # noqa: E402
from super_aide.snapshot import chromium, uiawalk, win32  # noqa: E402

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
TITLE = "UIA 压力靶子"


def page() -> Path:
    rows = "\n".join(
        f"<tr><td>{i}</td><td><a href='#r{i}'>链接 {i}</a></td><td><button>按钮 {i}</button></td>"
        f"<td><input value='值 {i}'></td><td><div><span>第 {i} 行</span><span>说明文字 {i}</span></div></td></tr>"
        for i in range(4000))
    html = (f"<!doctype html><html><head><meta charset='utf-8'><title>{TITLE}</title></head><body>"
            f"<h1>压力测试</h1><table>{rows}</table><p>END-7731</p></body></html>")
    path = Path(tempfile.mkdtemp(prefix="aide-heavy-")) / "heavy.html"
    path.write_text(html, encoding="utf-8")
    return path


class Pinger:
    """不停地问浏览器窗口"还在吗"，记下最长的一次等待。"""

    def __init__(self, hwnd: int) -> None:
        self.hwnd, self.worst, self.running = hwnd, 0.0, True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        result = ctypes.c_size_t()
        while self.running:
            t = time.perf_counter()
            ctypes.windll.user32.SendMessageTimeoutW(self.hwnd, 0, 0, 0, 0, 30000, ctypes.byref(result))
            self.worst = max(self.worst, time.perf_counter() - t)
            time.sleep(0.05)

    def reset(self) -> None:
        self.worst = 0.0


def main() -> int:
    for w in win32.visible_windows():
        if w.title.startswith(TITLE):
            win32gui.PostMessage(w.hwnd, 0x0010, 0, 0)
    time.sleep(0.5)
    before = {w.hwnd for w in win32.visible_windows()}
    subprocess.Popen([str(EDGE), "--new-window", page().as_uri()])
    hwnd = 0
    for _ in range(80):
        hwnd = next((w.hwnd for w in win32.visible_windows() if w.title.startswith(TITLE) and w.hwnd not in before), 0)
        if hwnd and chromium.children(hwnd):
            break
        time.sleep(0.25)
    if not hwnd:
        print("Edge 窗口没出现")
        return 1
    time.sleep(3)
    uia = _AutomationClient.instance().IUIAutomation
    chromium.wake(hwnd)
    root = uia.ElementFromHandle(hwnd)
    t = time.perf_counter()
    for _ in range(240):  # 网页内容交出来要一会儿（元素越多越久）：等到看得见页尾的标记
        found = root.FindFirst(4, uia.CreatePropertyCondition(elements.P_NAME, "END-7731"))
        if found:
            break
        chromium.wake(hwnd)
        time.sleep(0.5)
    print(f"网页内容交出来用了 {time.perf_counter() - t:.1f}s（{'好了' if found else '超时'}）")
    bounds = win32.dwm_rect(hwnd) or win32gui.GetWindowRect(hwnd)
    ping = Pinger(hwnd)
    rows = []

    def measure(name, fn):
        ping.reset()
        t = time.perf_counter()
        try:
            n = fn()
        except Exception as e:  # noqa: BLE001
            n = f"出错：{e}"
        rows.append((name, time.perf_counter() - t, ping.worst, n))

    full_props = elements._cache_request()
    visible = uia.CreateAndCondition(uia.ControlViewCondition, uia.CreatePropertyCondition(elements.P_OFFSCREEN, False))

    def old_query() -> int:  # 改之前的读法：一次取整棵树里看得见的
        found = root.FindAllBuildCache(4, visible, full_props)
        return sum(1 for i in range(found.Length)
                   if elements._is_interactive(found.GetElement(i), elements.ROLES.get(
                       elements._get(found.GetElement(i), elements.P_TYPE), "Custom"),
                       elements._patterns(found.GetElement(i))))

    def document_text() -> int:
        from comtypes.gen.UIAutomationClient import IUIAutomationTextPattern

        host = uia.ElementFromHandle(chromium.children(hwnd)[0])
        doc = host.FindFirst(2, uia.CreatePropertyCondition(elements.P_TYPE, 50030))
        pattern = doc.GetCurrentPattern(10014).QueryInterface(IUIAutomationTextPattern)
        return len(pattern.DocumentRange.GetText(400000))

    from super_aide.snapshot import uia as snapshot_uia

    class Direct:  # 让快照里的函数在当前线程直接用这个 UIA 客户端
        _uia = uia

    try:
        measure("旧：观察窗口（一次取整棵树）", old_query)
        measure("新：观察窗口（分小步，只取屏幕上的）", lambda: len(elements.query(hwnd, bounds)))
        measure("新：按名字找「按钮 12」（在屏幕上）", lambda: [e.name for e in elements.search(hwnd, "按钮 12")][:2])
        measure("新：按名字找「按钮 3999」（在最底下）", lambda: [e.name for e in elements.search(hwnd, "按钮 3999")])
        measure("新：快照读完整内容", lambda: (lambda r: f"{len(r[0]):,} 字，{r[1]}")(
            snapshot_uia.window_content(Direct, hwnd, budget_s=3.0)))
        measure("新：框选区域的原文", lambda: len(snapshot_uia.text_in_rect(
            Direct, hwnd, (bounds[0], bounds[1] + 200, bounds[2], bounds[1] + 500))))
    finally:
        ping.running = False
        win32gui.PostMessage(hwnd, 0x0010, 0, 0)
    print(f"{'读法':<28} {'耗时':>7} {'浏览器最长没响应':>12}  结果")
    for name, seconds, worst, n in rows:
        print(f"{name:<28} {seconds:6.2f}s {worst:10.2f}s    {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
