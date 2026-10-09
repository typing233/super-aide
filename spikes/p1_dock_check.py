"""贴边步骤自检：真实的控制器 + 假的引擎中枢（不发送任何内容）。

召唤 → 提问 → 回答里有编号步骤 → 点别处 → 缩到屏幕边上（不抢焦点）→ 勾掉一步 → 展开回卡片。
再验证没有步骤的回答点别处直接消失。会在真实屏幕上出现约 10 秒。

    uv run --no-sync python -X utf8 spikes/p1_dock_check.py
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

import win32gui
from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from super_aide import config, paths
from super_aide.app import _displays
from super_aide.shell.controller import Controller
from super_aide.shell.panel import MARGIN, WS_EX_NOACTIVATE
from super_aide.snapshot.collector import Collector
from super_aide.snapshot.uia import UiaWorker

OUT = Path(__file__).parent / "out" / "dock"
OUT.mkdir(parents=True, exist_ok=True)
STEPS = ("把默认浏览器改成 Edge：\n\n1. 打开**设置** → **应用** → **默认应用**。\n"
         "2. 在列表里点 **Microsoft Edge**。\n3. 点顶部的**设为默认值**。\n\n改完后点开的链接都会用 Edge 打开。")
PLAIN = "这是 Windows 的默认应用设置页，决定了各类文件和链接用哪个程序打开。"


class FakeHub(QObject):
    event = Signal(str, dict)

    def __init__(self) -> None:
        super().__init__()
        self.answer = STEPS

    def ask(self, key, mode, question, snap, task) -> None:
        def emit() -> None:
            self.event.emit(key, {"type": "route", "engine": "claude", "model": "fake", "effort": "low"})
            self.event.emit(key, {"type": "delta", "text": self.answer})
            self.event.emit(key, {"type": "done", "ok": True})
        QTimer.singleShot(200, emit)

    def is_busy(self, _key: str) -> bool:
        return False

    def interrupt(self, _key: str) -> None:
        pass

    def feedback(self, *_args) -> None:
        pass


def main() -> int:
    app = QApplication(sys.argv)
    paths.ensure()
    cfg = config.load()
    worker = UiaWorker()
    worker.wait_ready()
    hub = FakeHub()
    ctrl = Controller(cfg, Collector(worker, cfg.blocked_apps, _displays(app)), hub)
    other = QWidget()  # 用来模拟"点了别处"：激活另一个窗口
    other.setWindowTitle("别处")
    other.resize(200, 120)
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    def js(code: str) -> None:
        ctrl.panel.view.page().runJavaScript(code)

    def probe(code: str, name: str, expect) -> None:
        ctrl.panel.view.page().runJavaScript(code, 0, lambda v: check(name, expect(v), repr(v)))

    def physical(p: QPoint) -> tuple[int, int]:
        dpr = ctrl.panel.devicePixelRatioF()
        return round(p.x() * dpr), round(p.y() * dpr)

    def click_away() -> None:
        other.move(ctrl.panel.geometry().center() - QPoint(600, 0))
        other.show()
        other.raise_()
        other.activateWindow()

    def dock_checks() -> None:
        geo = ctrl.panel.geometry()
        avail = ctrl.panel.screen().availableGeometry()
        check("缩到屏幕边上", ctrl.view == "dock", str(ctrl.view))
        check("贴在离选区远的右侧", abs((geo.right() - MARGIN) - (avail.right() - 20)) <= 2, str(geo))
        style = ctypes.windll.user32.GetWindowLongW(ctrl.panel.hwnd(), -20)
        check("贴边时点它不抢焦点", bool(style & WS_EX_NOACTIVATE))
        card = win32gui.WindowFromPoint(physical(geo.center()))
        margin = win32gui.WindowFromPoint(physical(geo.topLeft() + QPoint(6, 6)))
        check("卡片区域能点到", card == ctrl.panel.hwnd())
        # 阴影留的透明边如果挡住下面窗口的点击，就要给贴边视图加窗口裁剪
        check("透明边不挡住下面的窗口", margin != ctrl.panel.hwnd(), f"margin hwnd={margin} panel={ctrl.panel.hwnd()}")
        canvas = QPixmap(ctrl.panel.size() * ctrl.panel.devicePixelRatioF())
        canvas.setDevicePixelRatio(ctrl.panel.devicePixelRatioF())
        canvas.fill(QColor("#4a5570"))
        p = QPainter(canvas)
        p.drawPixmap(0, 0, ctrl.panel.grab())
        p.end()
        canvas.save(str(OUT / f"dock-{ctrl.theme()}.png"))

    def step_done() -> None:
        js("document.querySelector('#dock-steps li').click()")

    steps = [
        (0, lambda: ctrl.summon("ask")),
        (600, lambda: setattr(ctrl.overlay, "sel", QRect(80, 120, 500, 300))),  # 选区在左半边
        (0, lambda: js("app.submit('怎么把默认浏览器改成 Edge？')")),
        (900, lambda: check("回答卡片", ctrl.view == "card", str(ctrl.view))),
        (0, click_away),
        (900, dock_checks),
        (0, lambda: probe("[...document.querySelectorAll('#dock-steps li')].length", "只留下 3 个步骤",
                          lambda v: v == 3)),
        (0, step_done),
        (300, lambda: probe("document.querySelector('#dock-steps li').classList.contains('done')",
                            "点一下勾掉第一步", lambda v: v is True)),
        (0, lambda: check("勾步骤没抢焦点", win32gui.GetForegroundWindow() != ctrl.panel.hwnd())),
        (0, lambda: js("document.querySelector('#dock-expand').click()")),
        (700, lambda: check("展开回卡片", ctrl.view == "card", str(ctrl.view))),
        (0, lambda: check("展开后能输入（窗口被激活）", ctrl.panel.isActiveWindow())),
        (0, ctrl.dismiss),
        # 没有步骤的回答：点别处直接消失
        (500, lambda: setattr(hub, "answer", PLAIN)),
        (0, lambda: ctrl.summon("ask")),
        (600, lambda: js("app.submit('这是什么页面？')")),
        (900, click_away),
        (900, lambda: check("没有步骤的回答点别处就消失", ctrl.view is None, str(ctrl.view))),
    ]

    def run(i: int = 0) -> None:
        if i >= len(steps):
            finish()
            return
        delay, fn = steps[i]

        def go() -> None:
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                check(f"第 {i} 步出错", False, repr(e))
            run(i + 1)

        QTimer.singleShot(delay, go)

    def finish() -> None:
        other.close()
        bad = [r for r in results if not r[1]]
        for name, ok, detail in results:
            print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
        print(f"\n{len(results) - len(bad)}/{len(results)} 通过，截图在 {OUT}")
        app.exit(1 if bad else 0)

    def start_when_ready() -> None:
        if ctrl.ready:
            run()
        else:
            QTimer.singleShot(200, start_when_ready)

    QTimer.singleShot(500, start_when_ready)
    code = app.exec()
    worker.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
