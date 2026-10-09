"""拆开计时：按键瞬间采集和后台采集各步骤的耗时（只打印耗时，不打印内容）。"""

from __future__ import annotations

import ctypes
import time

ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

import mss  # noqa: E402

from super_aide.snapshot import system, uia, win32  # noqa: E402
from super_aide.snapshot.uia import UiaWorker  # noqa: E402


def timed(label: str, fn, repeat: int = 3):
    result = None
    times = []
    for _ in range(repeat):
        t = time.perf_counter()
        result = fn()
        times.append((time.perf_counter() - t) * 1000)
    print(f"{label:<28} 首次 {times[0]:7.0f}ms   之后 {min(times[1:] or times):7.0f}ms")
    return result


worker = UiaWorker()
worker.wait_ready()
timed("前台窗口信息", win32.foreground)
with mss.MSS() as sct:
    timed("全屏截图（原始像素）", lambda: sct.grab(sct.monitors[0]))
timed("焦点和选中文字", lambda: worker.call(uia.focus_and_selection, timeout=2))
windows = timed("枚举可见窗口", lambda: win32.visible_windows())
timed("  其中：判断是否管理员", lambda: [win32.is_elevated(w.pid) for w in windows])
timed("  其中：进程名", lambda: [win32.process_name(w.pid) for w in windows])

print("\n后台（每个窗口一次）：")
for i, w in enumerate(windows):
    t = time.perf_counter()
    img = win32.capture_window(w.hwnd)
    cap_ms = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    text, method = worker.call(uia.window_text, w.hwnd, timeout=10, default=("", "超时"))
    text_ms = (time.perf_counter() - t) * 1000
    print(f"  窗口 {i}（{w.process}）截图 {cap_ms:5.0f}ms  文字 {text_ms:6.0f}ms {len(text):>7} 字 {method}")
if windows:
    t = time.perf_counter()
    worker.call(uia.ui_tree, windows[0].hwnd, timeout=10)
    print(f"  控件树（前台）{(time.perf_counter() - t) * 1000:.0f}ms")
t = time.perf_counter()
system.dynamic_state()
print(f"  系统状态 {(time.perf_counter() - t) * 1000:.0f}ms")
worker.stop()
