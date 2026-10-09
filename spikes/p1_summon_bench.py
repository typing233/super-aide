"""召唤延迟实测：在真实屏幕上召唤 3 次（每次约 0.7 秒后自动关闭），打印每一步的耗时。

不接引擎（用一个空的中枢代替），不发送任何内容。
用法：uv run python spikes/p1_summon_bench.py
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from super_aide import config, paths
from super_aide.app import _displays
from super_aide.shell.controller import Controller
from super_aide.snapshot.collector import Collector
from super_aide.snapshot.uia import UiaWorker


class NoEngines(QObject):
    event = Signal(str, dict)

    def is_busy(self, _key: str) -> bool:
        return False

    def interrupt(self, _key: str) -> None:
        pass

    def feedback(self, *_args) -> None:
        pass


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    app = QApplication(sys.argv)
    paths.ensure()
    cfg = config.load()
    worker = UiaWorker()
    worker.wait_ready()
    ctrl = Controller(cfg, Collector(worker, cfg.blocked_apps, _displays(app)), NoEngines())

    rounds = iter(range(3))

    def next_round() -> None:
        if next(rounds, None) is None:
            app.quit()
            return
        ctrl.summon("ask")
        QTimer.singleShot(700, ctrl.dismiss)
        QTimer.singleShot(1800, next_round)

    def start_when_ready() -> None:
        if ctrl.ready:
            next_round()
        else:
            QTimer.singleShot(200, start_when_ready)

    QTimer.singleShot(500, start_when_ready)
    QTimer.singleShot(30_000, app.quit)
    app.exec()
    worker.stop()


if __name__ == "__main__":
    main()
