"""启动时：预热的输入框留在屏幕外（只有快捷键召唤才出现）；开机自启安静启动，自己打开时提示一下。"""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QRegion

from super_aide import autostart
from super_aide.shell import controller as ctl


class FakePanel:
    def __init__(self) -> None:
        self.geometry = QRect()
        self.view = SimpleNamespace(page=lambda: SimpleNamespace(runJavaScript=lambda *a: None))

    def call(self, *args) -> None: ...
    def setAttribute(self, *args) -> None: ...  # noqa: N802
    def show(self) -> None: ...
    def set_click_through(self, on: bool) -> None: ...
    def mask(self) -> QRegion: return QRegion()
    def clearMask(self) -> None: ...  # noqa: N802

    def move(self, point: QPoint) -> None:
        self.geometry.moveTopLeft(point)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        self.geometry = QRect(rect)


class FakeOverlay(FakePanel):
    sel = QRect()

    def set_mode(self, mode: str) -> None: ...


def fake_controller(monkeypatch):
    timers = []
    monkeypatch.setattr(ctl.QTimer, "singleShot", lambda ms, fn: timers.append(fn))
    screen = QRect(0, 0, 1920, 1080)
    c = SimpleNamespace(panel=FakePanel(), overlay=FakeOverlay(), collector=SimpleNamespace(warm=lambda: None),
                        content=QSize(680, 136), view=None, ready=False, prev_fg=0,
                        _screen=lambda: (screen, screen, None), theme=lambda: "dark")
    for name in ("_place", "_park", "_on_view", "_on_sized"):
        setattr(c, name, getattr(ctl.Controller, name).__get__(c))
    return c, timers, screen


def test_warm_up_keeps_the_input_off_screen(monkeypatch):
    c, timers, screen = fake_controller(monkeypatch)
    ctl.Controller._warm_panel(c)
    c._on_view("input")      # 网页显示了输入框，报告给宿主
    c._on_sized(680, 140)
    assert not c.panel.geometry.intersects(screen)
    timers[0]()              # 预热结束
    assert c.ready and c.view is None
    assert c.panel.geometry.topLeft() == ctl.PARK
    c.view = "input"         # 之后的召唤照常摆在屏幕上
    c._place()
    assert c.panel.geometry.intersects(screen)


def test_slow_page_at_boot_does_not_bring_the_input_on_screen(monkeypatch):
    """开机时网页慢：预热那次"显示输入框"在预热结束以后才报上来，输入框也不能自己出现在屏幕上。"""
    c, timers, screen = fake_controller(monkeypatch)
    ctl.Controller._warm_panel(c)
    timers[0]()              # 预热结束，网页还没报告
    c._on_view("input")
    c._on_sized(680, 136)
    assert c.view is None
    assert not c.panel.geometry.intersects(screen)


def test_autostart_command_is_quiet_and_upgrade_only_touches_its_own_entry(monkeypatch):
    assert autostart.command().endswith(f" -m super_aide {autostart.FLAG}")
    written = []
    monkeypatch.setattr(autostart, "set_enabled", lambda on: written.append(on))
    monkeypatch.setattr(autostart, "_stored", lambda: autostart.command().removesuffix(f" {autostart.FLAG}"))
    autostart.upgrade()
    assert written == [True]
    written.clear()
    monkeypatch.setattr(autostart, "_stored", lambda: r'"D:\other\pythonw.exe" -m super_aide')
    autostart.upgrade()      # 别的副本（比如开发版）写的：不动
    monkeypatch.setattr(autostart, "_stored", lambda: autostart.command())
    autostart.upgrade()      # 已经是新的：不动
    assert written == []
