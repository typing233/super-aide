"""盯着有没有新的控制台窗口冒出来（开机自启用 pythonw 运行时，子进程不应弹黑窗口）。

    python spikes/p1_console_watch.py 90
"""

from __future__ import annotations

import sys
import time

import psutil
import win32gui
import win32process

CONSOLE_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"}


def consoles() -> dict[int, tuple[str, str]]:
    found: dict[int, tuple[str, str]] = {}

    def visit(hwnd: int, _) -> bool:
        cls = win32gui.GetClassName(hwnd)
        if cls in CONSOLE_CLASSES and win32gui.IsWindowVisible(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                name = psutil.Process(pid).name()
            except psutil.Error:
                name = "?"
            found[hwnd] = (cls, f"{name}({pid}) {win32gui.GetWindowText(hwnd)[:60]}")
        return True

    win32gui.EnumWindows(visit, None)
    return found


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    before = set(consoles())
    seen: dict[int, tuple[str, str]] = {}
    end = time.time() + seconds
    while time.time() < end:
        for hwnd, info in consoles().items():
            if hwnd not in before and hwnd not in seen:
                seen[hwnd] = info
                print(f"{time.strftime('%H:%M:%S')} 新控制台窗口：{info[0]} {info[1]}", flush=True)
        time.sleep(0.05)
    print(f"共 {len(seen)} 个新控制台窗口")
    return 1 if seen else 0


if __name__ == "__main__":
    sys.exit(main())
