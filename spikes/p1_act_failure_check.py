"""操作没办成时的结果提示：真实的控制器 + 假的引擎中枢（不发送任何内容）。

模拟这次的真实情况：Codex 汇报"没完成"，原因是浏览器操作没接通。结果提示应该是红色的、直接写修法。

    uv run --no-sync python -X utf8 spikes/p1_act_failure_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from super_aide import config, paths
from super_aide.app import _displays
from super_aide.engines import browser_use
from super_aide.shell.controller import Controller
from super_aide.snapshot.collector import Collector
from super_aide.snapshot.uia import UiaWorker

OUT = Path(__file__).parent / "out" / "act"
OUT.mkdir(parents=True, exist_ok=True)
HINT = browser_use.status("msedge.exe").problem or "浏览器操作还没接通：（本机已接通，这里用示例文字）"
REPORT = "没完成：浏览器操作还没接通，Computer Use 因为确定不了当前网址停下了。\n本次没有改动任何东西，不用撤销。"


class FakeHub(QObject):
    event = Signal(str, dict)

    def ask(self, key, mode, question, snap, task) -> None:
        def emit() -> None:
            self.event.emit(key, {"type": "route", "engine": "codex", "model": "fake", "effort": "medium"})
            self.event.emit(key, {"type": "status", "text": "正在操作界面…"})
            self.event.emit(key, {"type": "delta", "text": REPORT})
            self.event.emit(key, {"type": "done", "ok": False, "error": REPORT.splitlines()[0],
                                  "reason": "reported", "hint": HINT})
        QTimer.singleShot(600, emit)

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
    ctrl = Controller(cfg, Collector(worker, cfg.blocked_apps, _displays(app)), FakeHub())
    results: list[tuple[str, bool, str]] = []

    def probe(code: str, name: str, expect) -> None:
        ctrl.panel.view.page().runJavaScript(code, 0, lambda v: results.append((name, expect(v), repr(v))))

    def shot() -> None:
        canvas = QPixmap(ctrl.panel.size() * ctrl.panel.devicePixelRatioF())
        canvas.setDevicePixelRatio(ctrl.panel.devicePixelRatioF())
        canvas.fill(QColor("#4a5570"))
        p = QPainter(canvas)
        p.drawPixmap(0, 0, ctrl.panel.grab())
        p.end()
        canvas.save(str(OUT / f"toast-failed-{ctrl.theme()}.png"))

    steps = [
        (0, lambda: ctrl.summon("act")),
        (700, lambda: ctrl.panel.view.page().runJavaScript("app.submit('帮我修好它')")),
        (1500, lambda: probe("document.querySelector('#toast-view').hidden", "出现结果提示", lambda v: v is False)),
        (0, lambda: probe("document.querySelector('#toast-view').classList.contains('failed')", "红色（没完成）",
                          lambda v: v is True)),
        (0, lambda: probe("document.querySelector('#toast-title').textContent", "直接写修法",
                          lambda v: (v or "").startswith("浏览器操作还没接通"))),
        (0, shot),
        (300, ctrl.dismiss),
    ]

    def run(i: int = 0) -> None:
        if i >= len(steps):
            bad = [r for r in results if not r[1]]
            for name, ok, detail in results:
                print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if not ok else ""))
            print(f"\n{len(results) - len(bad)}/{len(results)} 通过，截图在 {OUT}")
            app.exit(1 if bad else 0)
            return
        delay, fn = steps[i]
        QTimer.singleShot(delay, lambda: (fn(), run(i + 1)))

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
