"""装网页界面的透明窗口：输入框、回答卡片、胶囊、结果提示都在同一个页面里切换。"""

from __future__ import annotations

import ctypes
import json

from PySide6.QtCore import QEvent, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .. import paths

MARGIN = 40  # 与 CSS 中 #root 的 padding 一致：给阴影留的透明边
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_NOACTIVATE = 0x08000000
WDA_EXCLUDEFROMCAPTURE = 0x11
DWMWA_TRANSITIONS_FORCEDISABLED = 3
user32 = ctypes.windll.user32


class Bridge(QObject):
    """网页通过 QWebChannel 调用这些槽。"""

    readied = Signal()
    submitted = Signal(str, str)
    followed_up = Signal(str, str)
    continued = Signal(str, str)  # 输入框里 Ctrl+Enter：带着这次的画面接着上次的对话问
    rated = Signal(int)  # 卡片上的 👍（1）/ 👎（-1）
    cancelled = Signal()
    sized = Signal(int, int)
    view_changed = Signal(str)
    shown_on_screen = Signal()
    dock_expanded = Signal()

    @Slot()
    def ready(self) -> None:
        self.readied.emit()

    @Slot(str, str)
    def submit(self, text: str, mode: str) -> None:
        self.submitted.emit(text, mode)

    @Slot(str, str)
    def followup(self, text: str, mode: str) -> None:
        self.followed_up.emit(text, mode)

    @Slot(str, str)
    def continueLast(self, text: str, mode: str) -> None:  # noqa: N802
        self.continued.emit(text, mode)

    @Slot(int)
    def feedback(self, value: int) -> None:
        self.rated.emit(value)

    @Slot()
    def cancel(self) -> None:
        self.cancelled.emit()

    @Slot(int, int)
    def contentSize(self, w: int, h: int) -> None:  # noqa: N802 - JS 侧的命名
        self.sized.emit(w, h)

    @Slot(str)
    def setView(self, view: str) -> None:  # noqa: N802
        self.view_changed.emit(view)

    @Slot()
    def shown(self) -> None:
        self.shown_on_screen.emit()

    @Slot()
    def expandDock(self) -> None:  # noqa: N802
        self.dock_expanded.emit()

    @Slot(str)
    def copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    @Slot(str)
    def openUrl(self, url: str) -> None:  # noqa: N802
        if url.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(url))


class Panel(QWidget):
    deactivated = Signal()

    def __init__(self, bridge: Bridge) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.view = QWebEngineView(self)
        self.view.page().setBackgroundColor(Qt.transparent)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", bridge)
        self.view.page().setWebChannel(self.channel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.view.load(QUrl.fromLocalFile(str(paths.UI_INDEX)))
        self.resize(600 + 2 * MARGIN, 56 + 2 * MARGIN)

    def call(self, fn: str, arg: object = None) -> None:
        payload = "" if arg is None else json.dumps(arg, ensure_ascii=False)
        self.view.page().runJavaScript(f"window.app && app.{fn}({payload})")

    def hwnd(self) -> int:
        return int(self.winId())

    def _set_exstyle(self, flag: int, on: bool) -> None:
        style = user32.GetWindowLongW(self.hwnd(), GWL_EXSTYLE)
        style = style | flag if on else style & ~flag
        user32.SetWindowLongW(self.hwnd(), GWL_EXSTYLE, style)

    def set_click_through(self, on: bool) -> None:
        self._set_exstyle(WS_EX_TRANSPARENT, on)

    def set_no_activate(self, on: bool) -> None:
        """点它不会抢走焦点（贴边步骤：你在别的窗口里照着做，点一下勾掉一步不打断你）。"""
        self._set_exstyle(WS_EX_NOACTIVATE, on)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            self.deactivated.emit()
        super().changeEvent(event)


def exclude_from_capture(widget: QWidget) -> None:
    """我们的界面不出现在任何截图里，引擎看到的永远是干净的画面。"""
    user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE)


def disable_transitions(widget: QWidget) -> None:
    """关掉 Windows 给窗口出现/消失加的淡入淡出动画，召唤时画面立刻出现。"""
    value = ctypes.c_int(1)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(int(widget.winId()), DWMWA_TRANSITIONS_FORCEDISABLED,
                                               ctypes.byref(value), ctypes.sizeof(value))
