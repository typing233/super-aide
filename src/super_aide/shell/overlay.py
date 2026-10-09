"""定格浮层：按键那一刻的画面，选区以外压暗；拖拽重新框选，单击选中光标下的窗口。"""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

ACCENT = {"ask": QColor("#7B7CFF"), "act": QColor("#FF9A46")}
DIM = QColor(0, 0, 0, 115)


class Overlay(QWidget):
    #: 用户改了选区（逻辑坐标，相对浮层左上角）
    reselected = Signal(QRect)

    def __init__(self) -> None:
        # 不抢焦点：拖拽框选时输入框保持可输入
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.CrossCursor)
        self.frozen = QPixmap()
        self.sel = QRect()
        self.mode = "ask"
        self.window_rects: list[QRect] = []
        self.first_paint_at: float | None = None
        self._drag_from: QPoint | None = None

    def summon(self, frozen: QPixmap, sel: QRect, mode: str, geometry: QRect,
               window_rects: list[QRect]) -> None:
        self.frozen, self.sel, self.mode, self.window_rects = frozen, sel, mode, window_rects
        self.first_paint_at = None
        self.setGeometry(geometry)
        self.show()
        self.raise_()
        self.update()

    def set_mode(self, mode: str) -> None:
        if mode != self.mode:
            self.mode = mode
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt 的方法名
        p = QPainter(self)
        p.drawPixmap(0, 0, self.frozen)
        full, r = self.rect(), self.sel
        p.fillRect(QRect(0, 0, full.width(), r.top()), DIM)
        p.fillRect(QRect(0, r.bottom() + 1, full.width(), full.height() - r.bottom() - 1), DIM)
        p.fillRect(QRect(0, r.top(), r.left(), r.height()), DIM)
        p.fillRect(QRect(r.right() + 1, r.top(), full.width() - r.right() - 1, r.height()), DIM)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(ACCENT.get(self.mode, ACCENT["ask"]), 1.5))
        p.drawRoundedRect(r.adjusted(0, 0, -1, -1), 8, 8)
        p.end()
        if self.first_paint_at is None:
            self.first_paint_at = time.perf_counter()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self._drag_from = e.position().toPoint()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag_from is not None:
            self.sel = QRect(self._drag_from, e.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._drag_from is None:
            return
        if self.sel.width() < 8 or self.sel.height() < 8:  # 单击：选中光标下的窗口
            point = e.position().toPoint() + self.geometry().topLeft()
            hit = next((r for r in self.window_rects if r.contains(point)), None)
            self.sel = hit.translated(-self.geometry().topLeft()) if hit else self.rect()
            self.update()
        self._drag_from = None
        self.reselected.emit(QRect(self.sel))
