"""无边框的网页窗口（设置、历史记录）：和其它界面同一套视觉规范，在任务栏里有图标，关闭只是隐藏。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget


class WindowBridge(QObject):
    """各窗口共用的槽；具体窗口的桥在子类里加自己的槽。"""

    page_rendered = Signal()

    def __init__(self, window: WebWindow) -> None:
        super().__init__()
        self.window = window

    @Slot()
    def rendered(self) -> None:
        self.page_rendered.emit()

    @Slot()
    def startDrag(self) -> None:  # noqa: N802 - JS 侧的命名
        handle = self.window.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    @Slot()
    def close(self) -> None:
        self.window.hide()


class WebWindow(QWidget):
    def __init__(self, title: str, size: tuple[int, int]) -> None:
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self.preferred = size  # 含四周给阴影留的透明边
        self.loaded = False
        self.view = QWebEngineView(self)
        self.view.page().setBackgroundColor(Qt.transparent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        QShortcut(QKeySequence("Ctrl+W"), self, self.hide)

    def load_page(self, page: Path, bridge: WindowBridge) -> None:
        self.bridge = bridge
        bridge.page_rendered.connect(self._on_rendered)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", bridge)
        self.view.page().setWebChannel(self.channel)
        self.view.load(QUrl.fromLocalFile(str(page)))

    def js(self, code: str) -> None:
        self.view.page().runJavaScript(code)

    def open(self) -> None:
        """第一次打开时网页还没画好：等它画好（_on_rendered）再显示，不闪空白或错误的主题。"""
        if not self.loaded:
            return
        if not self.isVisible():
            self.reopened()
        self._show()

    def reopened(self) -> None:
        """隐藏后再次打开时调用：子类在这里让网页刷新内容。"""

    def retitle(self) -> None:
        """语言换了：子类在这里换窗口标题（任务栏上显示的）。"""

    def _on_rendered(self) -> None:
        if not self.loaded:
            self.loaded = True
            self._show()

    def _show(self) -> None:
        avail = self.screen().availableGeometry()
        self.resize(min(self.preferred[0], avail.width()), min(self.preferred[1], avail.height()))
        if not self.isVisible():
            self.move(avail.center() - self.rect().center())
        self.show()
        self.raise_()
        self.activateWindow()
