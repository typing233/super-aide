"""键鼠护栏自检（不调用模型）：钩子真的装上又卸掉、鼠标放回原处、挡住时的提示出现又消失。

亲手的键鼠没法用程序模拟（SendInput 发出的都带"注入"标记），挡不挡由 tests/test_guard.py 用构造的事件验证；
助手自己的输入在护栏开着时照常通过，由 p4_cu_check.py、p4_cu_browser_check.py 验证（真实点击、打字都在护栏下进行）。

    uv run --no-sync python -X utf8 spikes/p5_guard_check.py
"""

from __future__ import annotations

import sys

sys.coinit_flags = 0

import ctypes  # noqa: E402

ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

import time  # noqa: E402

import win32gui  # noqa: E402

from super_aide.cu import guard, inputs, server  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def main() -> int:
    g = guard.GUARD
    start = guard.cursor()
    try:
        t = time.perf_counter()
        g.engage()
        ms = (time.perf_counter() - t) * 1000
        check("开始挡：两个钩子都装上", g.installed == 2, f"{g.installed} 个，{ms:.0f}ms（第一次含建线程）")
        inputs.move(start[0] + 120, start[1] + 80)  # 助手挪鼠标（SetCursorPos 不经过钩子）
        check("助手挪鼠标不算你动", not g.user_moved and g.blocked == 0)
        t = time.perf_counter()
        g.release(target=0)  # 你的鼠标不在助手操作的窗口上：放回去
        ms = (time.perf_counter() - t) * 1000
        check("放开：钩子都卸掉", g.installed == 0, f"{ms:.0f}ms")
        check("放开：鼠标回到你原来的位置", guard.cursor() == start, f"{guard.cursor()} vs {start}")

        t = time.perf_counter()
        g.engage()
        g.release(target=0)
        check("再挡一次又放开很快", g.installed == 0, f"{(time.perf_counter() - t) * 1000:.0f}ms")

        g.until = 0
        g.held = True  # 模拟：超过最长时间还没放开
        check("超过最长时间自动放行", not g._active())
        g.held = False

        server._guide()
        time.sleep(0.3)
        server._on_blocked(start)
        time.sleep(0.4)
        hl = server._highlighter
        check("挡住你时：鼠标旁边出现提示", win32gui.IsWindowVisible(hl.hwnd))
        time.sleep(1.8)
        check("提示过一会儿自己消失", not win32gui.IsWindowVisible(hl.hwnd))
    finally:
        g.release(target=0)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    passed = sum(r[1] for r in results)
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
