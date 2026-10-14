"""回答卡片拖开以后，收起再展开、关了再从托盘找回，都停在你放的地方；我们自己挪窗口不算拖动。"""

from types import SimpleNamespace

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QRegion

from super_aide.shell import controller as ctl
from super_aide.shell.controller import PARK, Controller
from super_aide.shell.panel import MARGIN


class Panel:
    def __init__(self):
        self.geo = QRect(PARK, QSize(10, 10))
        self.moved = []

    def pos(self):
        return self.geo.topLeft()

    def geometry(self):
        return QRect(self.geo)

    def setGeometry(self, rect):  # noqa: N802
        self.geo = QRect(rect)
        self.on_move()

    def move(self, point):
        self.geo.moveTopLeft(point)
        self.on_move()

    def setMask(self, region):  # noqa: N802
        pass

    def mask(self):
        return QRegion()

    def clearMask(self):  # noqa: N802
        pass


def fake_controller(monkeypatch):
    monkeypatch.setattr(ctl.QGuiApplication, "screenAt", staticmethod(lambda point: None))
    screen = SimpleNamespace(geometry=QRect(0, 0, 1920, 1080), available=QRect(0, 0, 1920, 1040), dpr=1.0)
    c = SimpleNamespace(panel=Panel(), screen=screen, overlay=SimpleNamespace(sel=QRect(600, 300, 400, 200)),
                        content=QSize(680, 300), view=None, anchor=QPoint(), placed_at=PARK, dragging=False,
                        dragged=False, pill_area=QRect(), placed=SimpleNamespace(emit=lambda rect: None))
    for name in ("_place", "_screen", "_shown_rect", "_on_moved"):
        setattr(c, name, getattr(Controller, name).__get__(c))
    c.panel.on_move = c._on_moved
    return c


def test_a_dragged_card_stays_where_you_put_it(monkeypatch):
    c = fake_controller(monkeypatch)
    c.view = "input"
    c._place()
    c.view = "card"
    c._place()
    start = c.panel.pos()
    c.panel.move(QPoint(1100, 500))   # 系统挪了一下（比如换了缩放）：不是你拖的，不记
    assert not c.dragged
    c._place()
    assert c.panel.pos() == start
    c.dragging = True                 # 你按住卡片拖到右边
    c.panel.move(QPoint(1200, 120))
    assert c.dragged and c.anchor == QPoint(1200, 120)
    c.content = QSize(680, 420)       # 还在长高：不跳回去
    c._place()
    assert c.panel.pos() == QPoint(1200, 120)
    c.view, c.content = "mini", QSize(380, 120)  # 点了别处：收成右下角的一小条
    c._place()
    assert c.panel.pos() != QPoint(1200, 120)
    c.view, c.content = "card", QSize(680, 420)  # 点一下展开：回到你放的地方
    c._place()
    assert c.panel.pos() == QPoint(1200, 120)
    c.placed_at = PARK                # 关掉：和 _park 一样，先记下再收到屏幕外；之后从托盘找回
    c.panel.move(PARK)
    c._place()
    assert c.panel.pos() == QPoint(1200, 120)
    c.view, c.content = "input", QSize(680, 136)  # 下一次召唤：重新贴着选区摆
    c._place()
    assert not c.dragged and not c.dragging and c.panel.pos().y() > 300 - MARGIN
