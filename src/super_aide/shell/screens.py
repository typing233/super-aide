"""多显示器：召唤时只定格你正在用的那块屏幕，按它自己的缩放比换算坐标（混合缩放也对得上）。

快照和 Win32 用物理像素（整个虚拟桌面的坐标），Qt 用逻辑像素。在同一块屏幕里：
    逻辑坐标 = 这块屏幕的逻辑左上角 + (物理坐标 - 这块屏幕的物理左上角) / 缩放比
Qt 的屏幕名就是 Win32 的显示器设备名（\\\\.\\DISPLAY1），靠它把两边的同一块屏幕对上。
"""

from __future__ import annotations

from dataclasses import dataclass

import win32api
from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QScreen

from ..snapshot.win32 import Rect

MONITOR_DEFAULTTONEAREST = 2


@dataclass(frozen=True)
class ScreenMap:
    phys: Rect          # 这块屏幕的物理矩形
    geometry: QRect     # Qt 里的几何（逻辑像素）
    available: QRect    # 去掉任务栏后的部分
    dpr: float

    def to_logical(self, r: Rect) -> QRect:
        g, (ox, oy) = self.geometry, self.phys[:2]
        return QRect(g.x() + round((r[0] - ox) / self.dpr), g.y() + round((r[1] - oy) / self.dpr),
                     round((r[2] - r[0]) / self.dpr), round((r[3] - r[1]) / self.dpr))

    def to_physical(self, q: QRect) -> Rect:
        g, (ox, oy) = self.geometry, self.phys[:2]
        left, top = ox + round((q.x() - g.x()) * self.dpr), oy + round((q.y() - g.y()) * self.dpr)
        return left, top, left + round(q.width() * self.dpr), top + round(q.height() * self.dpr)

    def clamp(self, r: Rect) -> Rect | None:
        """裁到这块屏幕里；完全在屏幕外时返回 None。"""
        left, top = max(r[0], self.phys[0]), max(r[1], self.phys[1])
        right, bottom = min(r[2], self.phys[2]), min(r[3], self.phys[3])
        return (left, top, right, bottom) if right > left and bottom > top else None

    def crop_box(self, origin: tuple[int, int]) -> tuple[int, int, int, int]:
        """这块屏幕在整张虚拟桌面截图里的位置 (x, y, 宽, 高)。origin 是截图左上角的物理坐标。"""
        x, y = self.phys[0] - origin[0], self.phys[1] - origin[1]
        return x, y, self.phys[2] - self.phys[0], self.phys[3] - self.phys[1]


def of(screen: QScreen, phys: Rect | None = None) -> ScreenMap:
    g, dpr = screen.geometry(), screen.devicePixelRatio()
    if phys is None:  # 对不上 Win32 显示器时，假定物理左上角和逻辑左上角相同（单屏时就是这样）
        phys = (g.x(), g.y(), g.x() + round(g.width() * dpr), g.y() + round(g.height() * dpr))
    return ScreenMap(phys, g, screen.availableGeometry(), dpr)


def primary() -> ScreenMap:
    screen = QGuiApplication.primaryScreen()
    return _match(screen) or of(screen)


def _match(screen: QScreen) -> ScreenMap | None:
    for handle, _dc, _rect in win32api.EnumDisplayMonitors():
        info = win32api.GetMonitorInfo(handle)
        if info["Device"] == screen.name():
            return of(screen, tuple(info["Monitor"]))
    return None


def at(x: int, y: int) -> ScreenMap:
    """物理坐标 (x, y) 所在（不在任何屏幕上时取最近）的屏幕。"""
    info = win32api.GetMonitorInfo(win32api.MonitorFromPoint((x, y), MONITOR_DEFAULTTONEAREST))
    for screen in QGuiApplication.screens():
        if screen.name() == info["Device"]:
            return of(screen, tuple(info["Monitor"]))
    return primary()
