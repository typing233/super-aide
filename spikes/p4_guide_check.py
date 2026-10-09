"""屏幕指引自检：在靶子窗口上圈出两处，核对指引窗口出现、到时间消失、收到"收起"信号消失；
指引窗口不进截图，所以另外把画出来的图叠在靶子窗口的截图上保存，看样子。

    uv run --no-sync python -X utf8 spikes/p4_guide_check.py
"""

from __future__ import annotations

import sys

sys.coinit_flags = 0

import ctypes  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import win32gui  # noqa: E402
from PIL import Image  # noqa: E402

from super_aide.cu import guide, server  # noqa: E402
from super_aide.snapshot import win32  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "out" / "guide"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    state = Path(tempfile.mkdtemp()) / "s.json"
    target = subprocess.Popen([sys.executable, str(HERE / "p4_cu_target.py"), str(state)])
    results = []
    try:
        time.sleep(2.5)
        server.observe_window("CU 靶子", screenshot=False)
        ids = {e.name: e.id for e in server.STATE["obs"].elements.values()}
        out = server.point([server.Target(id=ids["城市"], label="先选城市"),
                            server.Target(id=ids["提交"], label="再点提交")], seconds=4)
        time.sleep(0.6)
        hwnd = server._highlighter.hwnd
        results.append(("指引窗口出现", win32gui.IsWindowVisible(hwnd), out))
        ex = win32gui.GetWindowLong(hwnd, -20)
        results.append(("鼠标穿透、不抢焦点", bool(ex & 0x20) and bool(ex & 0x08000000), hex(ex)))
        time.sleep(4.2)
        results.append(("到时间自动消失", not win32gui.IsWindowVisible(hwnd), ""))

        server.point([server.Target(id=ids["姓名"], label="填姓名")], seconds=60)
        time.sleep(0.5)
        event = ctypes.windll.kernel32.OpenEventW(0x0002, False, guide.CLEAR_EVENT)  # EVENT_MODIFY_STATE
        ctypes.windll.kernel32.SetEvent(event)
        time.sleep(0.4)
        results.append(("收起回答时（命名事件）消失", not win32gui.IsWindowVisible(hwnd), ""))

        # 看样子：把指引画在靶子截图上
        obs = server.STATE["obs"]
        shot = obs.full.convert("RGBA")
        boxes = [(obs.elements[ids["城市"]].rect, "先选城市"), (obs.elements[ids["提交"]].rect, "再点提交")]
        dpi = ctypes.windll.user32.GetDpiForWindow(obs.hwnd) or 96
        overlay = guide.render(boxes, obs.origin, shot.size, dpi / 96)
        Image.alpha_composite(shot, overlay).save(OUT / "guide.png")
    finally:
        target.terminate()
    for name, ok, detail in results:
        print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if not ok else ""))
    print(f"截图：{OUT / 'guide.png'}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
