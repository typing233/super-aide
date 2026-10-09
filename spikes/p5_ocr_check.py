"""OCR 当作控件的自检（不调用模型）：一个只有画布的窗口（UI Automation 里没有按钮），检查
- 观察时控件太少，自动把截图上的字认出来编上号；
- 按编号点"Settings"，点中的就是它；
- find 找不到控件时认图找到"导出为 PDF"并点中；
- 点"保存"后 wait_for 认图等到"已保存"。

会弹出一个小窗口并点击它，大约 10 秒。

    uv run --no-sync python -X utf8 spikes/p5_ocr_check.py
"""

from __future__ import annotations

import sys

sys.coinit_flags = 0

import ctypes  # noqa: E402

ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import win32gui  # noqa: E402

from super_aide.cu import server  # noqa: E402
from super_aide.cu.actions import Action  # noqa: E402
from super_aide.snapshot import win32  # noqa: E402

TARGET = Path(__file__).parent / "p5_ocr_target.py"
results: list[tuple[str, bool, str, float]] = []


def check(name, ok, detail="", ms=0.0):
    results.append((name, ok, detail, ms))


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t) * 1000


def ocr_id(text: str) -> int:
    for e in server.STATE["obs"].elements.values():
        if e.role == "OCR" and text in e.name.replace(" ", ""):
            return e.id
    raise LookupError(text)


def main() -> int:
    out = Path(tempfile.mkdtemp(prefix="aide-ocr-")) / "clicks.txt"
    proc = subprocess.Popen([sys.executable, str(TARGET), str(out)])
    hwnd = 0
    for _ in range(40):
        hwnd = next((w.hwnd for w in win32.visible_windows() if w.title == "OCR 靶子"), 0)
        if hwnd:
            break
        time.sleep(0.25)
    if not hwnd:
        print("靶子窗口没出现")
        proc.kill()
        return 1
    time.sleep(0.8)
    try:
        res, ms = timed(lambda: server.observe_window(str(hwnd)))
        text = res[0]
        names = [e.name for e in server.STATE["obs"].elements.values() if e.role == "OCR"]
        check("控件太少：自动认图编号", all(any(k in n.replace(" ", "") for n in names) for k in ("保存", "取消", "Settings")),
              f"{names}", ms)
        check("说明里提示了认图编号", "截图上认出来的字" in text)
        check("同一行隔得远的按钮分开编号", not any("保存" in n and "取消" in n for n in names), f"{names}")

        res, ms = timed(lambda: server.act([Action(do="click", id=ocr_id("Settings"))], observe_after=False))
        time.sleep(0.3)
        clicked = out.read_text(encoding="utf-8").split() if out.exists() else []
        check("按认图编号点中 Settings", clicked[-1:] == ["Settings"], f"{res[0]} → {clicked}", ms)

        res, ms = timed(lambda: server.find("导出"))
        check("find 认图找到控件没有的字", "导出" in res and "认出来" in res, res[:160], ms)
        new_id = max(server.STATE["obs"].elements)
        server.act([Action(do="click", id=new_id)], observe_after=False)
        time.sleep(0.3)
        clicked = out.read_text(encoding="utf-8").splitlines()
        check("点中 find 认图找到的「导出为 PDF」", clicked[-1:] == ["导出为 PDF"], f"{clicked}")

        res, ms = timed(lambda: server.act([Action(do="click", id=ocr_id("保存")),
                                            Action(do="wait_for", text="已保存", seconds=8)], observe_after=False))
        check("wait_for 认图等到「已保存」", "出现了" in res[0], res[0], ms)
    finally:
        win32gui.PostMessage(hwnd, 0x0010, 0, 0)
        time.sleep(0.3)
        proc.kill()

    width = max(len(r[0]) for r in results)
    for name, ok, detail, ms in results:
        timing = f"{ms:7.0f}ms" if ms else " " * 9
        print(f"{'✓' if ok else '✗'} {name.ljust(width)} {timing}  {detail[:150]!r}")
    passed = sum(r[1] for r in results)
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
