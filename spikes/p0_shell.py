"""P0-①⑤ 外壳原型：快捷键 → 定格浮层 + 自动选区 + 输入框 → 回答卡片 / 操作胶囊（回答是模拟的）。

  uv run python spikes/p0_shell.py              交互试用：Alt+Q 问答、Alt+W 操作；托盘图标里退出
  uv run python spikes/p0_shell.py --selftest   自测：不注册快捷键、不截真实屏幕，窗口放在屏幕外，
                                                用合成桌面把深色/浅色下的每个状态各存一张图到
                                                spikes/out/ui/，并打印召唤延迟

已知简化（P1 再做）：只按主显示器处理坐标；自动选区只框前台窗口（还没框选中的文字）；
点别处时卡片直接关闭（还没做"分步骤回答缩到屏幕边上"）。
"""

from __future__ import annotations

import ctypes
import json
import statistics
import sys
import time
import winreg
from ctypes import wintypes
from pathlib import Path

import mss
import win32gui
from PySide6.QtCore import (QAbstractNativeEventFilter, QEvent, QObject, QPoint, QRect, QSize, Qt,
                            QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import (QAction, QColor, QFont, QGuiApplication, QIcon, QImage, QLinearGradient,
                           QPainter, QPen, QPixmap)
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QVBoxLayout, QWidget

ROOT = Path(__file__).resolve().parents[1]
UI_INDEX = ROOT / "src" / "super_aide" / "ui" / "web" / "index.html"
OUT = Path(__file__).parent / "out" / "ui"

MARGIN = 40  # 与 CSS 中 #root 的 padding 一致：给阴影留的透明边
GAP = 12     # 输入框与选区之间的距离
EDGE = 20    # 胶囊、结果提示与屏幕边缘的距离
WM_HOTKEY = 0x0312
MOD_ALT, MOD_NOREPEAT = 0x0001, 0x4000
HOTKEYS = {1: ("ask", ord("Q")), 2: ("act", ord("W"))}
WDA_EXCLUDEFROMCAPTURE = 0x11
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
DWMWA_EXTENDED_FRAME_BOUNDS = 9
ACCENT = {"ask": QColor("#7B7CFF"), "act": QColor("#FF9A46")}

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi


def windows_theme() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
    except OSError:
        return "dark"


def dwm_rect(hwnd: int) -> QRect | None:
    """窗口的可见边界（物理像素，不含 Win11 四周看不见的缩放边框）。"""
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                    ctypes.byref(r), ctypes.sizeof(r)) != 0:
        return None
    return QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)


def to_logical(r: QRect, dpr: float) -> QRect:
    return QRect(round(r.x() / dpr), round(r.y() / dpr), round(r.width() / dpr), round(r.height() / dpr))


def visible_window_rects(dpr: float, exclude: set[int]) -> list[QRect]:
    """按 Z 序（从上到下）返回可见应用窗口的逻辑坐标矩形，供单击选窗口用。"""
    rects: list[QRect] = []

    def cb(hwnd: int, _: object) -> bool:
        if hwnd in exclude or not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return True
        if not win32gui.GetWindowText(hwnd) or win32gui.GetWindow(hwnd, 4):  # GW_OWNER
            return True
        r = dwm_rect(hwnd)
        if r and r.width() > 40 and r.height() > 40:
            rects.append(to_logical(r, dpr))
        return True

    win32gui.EnumWindows(cb, None)
    return rects


# ---------------------------------------------------------------------------
# 与网页通信的对象：JS 通过 QWebChannel 调用这些槽
# ---------------------------------------------------------------------------

class Bridge(QObject):
    readied = Signal()
    submitted = Signal(str, str)
    cancelled = Signal()
    sized = Signal(int, int)
    view_changed = Signal(str)
    shown_on_screen = Signal()

    @Slot()
    def ready(self) -> None:
        self.readied.emit()

    @Slot(str, str)
    def submit(self, text: str, mode: str) -> None:
        self.submitted.emit(text, mode)

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

    @Slot(str)
    def copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)


# ---------------------------------------------------------------------------
# 窗口
# ---------------------------------------------------------------------------

class Overlay(QWidget):
    """定格画面：压暗 + 选区保持原亮度；拖拽重新框选，单击选中光标下的窗口。"""

    reselected = Signal()

    def __init__(self) -> None:
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

    def summon(self, frozen: QPixmap, sel: QRect, mode: str, geometry: QRect) -> None:
        self.frozen, self.sel, self.mode = frozen, sel, mode
        self.first_paint_at = None
        self.setGeometry(geometry)
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.drawPixmap(0, 0, self.frozen)
        full, r = self.rect(), self.sel
        dim = QColor(0, 0, 0, 115)
        p.fillRect(QRect(0, 0, full.width(), r.top()), dim)
        p.fillRect(QRect(0, r.bottom() + 1, full.width(), full.height() - r.bottom() - 1), dim)
        p.fillRect(QRect(0, r.top(), r.left(), r.height()), dim)
        p.fillRect(QRect(r.right() + 1, r.top(), full.width() - r.right() - 1, r.height()), dim)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(ACCENT[self.mode], 1.5))
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
            self.sel = (hit.translated(-self.geometry().topLeft()) if hit else self.rect())
            self.update()
        self._drag_from = None
        self.reselected.emit()


class Panel(QWidget):
    """装网页界面的透明窗口：输入框、回答卡片、胶囊、结果提示都在这一个页面里切换。"""

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
        self.view.load(QUrl.fromLocalFile(str(UI_INDEX)))
        self.resize(600 + 2 * MARGIN, 56 + 2 * MARGIN)

    def call(self, fn: str, arg: object = None) -> None:
        payload = "" if arg is None else json.dumps(arg, ensure_ascii=False)
        self.view.page().runJavaScript(f"app.{fn}({payload})")

    def set_click_through(self, on: bool) -> None:
        hwnd = int(self.winId())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = style | WS_EX_TRANSPARENT if on else style & ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            self.deactivated.emit()
        super().changeEvent(event)


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, on_hotkey) -> None:
        super().__init__()
        self.on_hotkey = on_hotkey

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        name = event_type.data() if hasattr(event_type, "data") else bytes(event_type)
        if name == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam in HOTKEYS:
                arrived = time.perf_counter()
                mode = HOTKEYS[msg.wParam][0]
                QTimer.singleShot(0, lambda: self.on_hotkey(mode, arrived))
                return True, 0
        return False, 0


# ---------------------------------------------------------------------------
# 控制器：召唤、摆放、状态切换
# ---------------------------------------------------------------------------

class Controller(QObject):
    def __init__(self, selftest: bool) -> None:
        super().__init__()
        self.selftest = selftest
        self.theme = windows_theme()
        self.bridge = Bridge()
        self.panel = Panel(self.bridge)
        self.overlay = Overlay()
        self.view: str | None = None
        self.content = QSize(600 + 2 * MARGIN, 56 + 2 * MARGIN)
        self.anchor = QPoint()
        self.offset = QPoint()  # 自测时把所有窗口挪到屏幕外
        self.prev_foreground = 0
        self.t_hotkey: float | None = None
        self.latencies: list[tuple[float, float]] = []
        self.is_ready = False

        b = self.bridge
        b.readied.connect(self.on_ready)
        b.sized.connect(self.on_sized)
        b.view_changed.connect(self.on_view)
        b.cancelled.connect(self.dismiss)
        b.shown_on_screen.connect(self.on_shown)
        self.overlay.reselected.connect(self.place)
        self.panel.deactivated.connect(self.on_deactivated)

        # 预先创建好原生窗口：召唤时只需要显示，不用再创建
        self.panel.winId()
        self.overlay.winId()
        if not selftest:
            for w in (self.panel, self.overlay):
                user32.SetWindowDisplayAffinity(int(w.winId()), WDA_EXCLUDEFROMCAPTURE)

    # ---- 几何 ----

    def screen(self) -> tuple[QRect, QRect, float]:
        s = QGuiApplication.primaryScreen()
        return s.geometry(), s.availableGeometry(), s.devicePixelRatio()

    def place(self) -> None:
        w, h = self.content.width(), self.content.height()
        geo, avail, _ = self.screen()
        if self.view in ("input", "card"):
            sel = self.overlay.sel
            if self.view == "input":
                x = max(avail.left(), min(sel.center().x() - w // 2, avail.right() - w))
                below = sel.bottom() + GAP - MARGIN
                above = sel.top() - GAP - (h - MARGIN)
                if below + h <= avail.bottom():
                    y = below
                elif above >= avail.top():
                    y = above
                else:  # 选区几乎占满屏幕：放在选区内偏下的位置
                    y = sel.top() + int(sel.height() * 0.72) - h // 2
                self.anchor = QPoint(x, y)
            x = self.anchor.x()
            y = max(avail.top(), min(self.anchor.y(), avail.bottom() - h))
        else:  # 胶囊和结果提示：右下角
            x = avail.right() - w + MARGIN - EDGE
            y = avail.bottom() - h + MARGIN - EDGE
        self.panel.setGeometry(QRect(QPoint(x, y) + self.offset, QSize(w, h)))

    # ---- 召唤 ----

    def capture_real(self, dpr: float) -> tuple[QPixmap, QRect]:
        fg = win32gui.GetForegroundWindow()
        own = {int(self.panel.winId()), int(self.overlay.winId())}
        if fg not in own:
            self.prev_foreground = fg
        with mss.MSS() as sct:
            shot = sct.grab(sct.monitors[0])
        image = QImage(shot.bgra, shot.width, shot.height, QImage.Format_RGB32).copy()
        frozen = QPixmap.fromImage(image)
        frozen.setDevicePixelRatio(dpr)
        geo, _, _ = self.screen()
        rect = dwm_rect(self.prev_foreground) if self.prev_foreground else None
        sel = to_logical(rect, dpr).intersected(geo) if rect else geo.adjusted(80, 80, -80, -80)
        self.overlay.window_rects = visible_window_rects(dpr, own)
        return frozen, sel

    def summon(self, mode: str, arrived: float | None = None,
               frozen: QPixmap | None = None, sel: QRect | None = None) -> None:
        if not self.is_ready:
            return
        self.t_hotkey = arrived or time.perf_counter()
        geo, _, dpr = self.screen()
        if frozen is None:
            frozen, sel = self.capture_real(dpr)
        self.overlay.summon(frozen, sel, mode, geo.translated(self.offset))
        self.view = "input"
        self.panel.set_click_through(False)
        self.panel.call("showInput", {"mode": mode, "theme": self.theme,
                                      "answerMax": int(geo.height() * 0.6) - 120})
        self.place()
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()
        self.panel.view.setFocus()

    def on_shown(self) -> None:
        if self.t_hotkey is None:
            return
        now = time.perf_counter()
        overlay_ms = ((self.overlay.first_paint_at or now) - self.t_hotkey) * 1000
        input_ms = (now - self.t_hotkey) * 1000
        self.latencies.append((overlay_ms, input_ms))
        print(f"召唤延迟：定格画面 {overlay_ms:.0f}ms，输入框可输入 {input_ms:.0f}ms", flush=True)
        self.t_hotkey = None

    # ---- 状态 ----

    def on_ready(self) -> None:
        if self.selftest:
            self.is_ready = True
            print("界面已就绪", flush=True)
            return
        # 预热：在屏幕外把输入框显示一次再藏起来，第一次真正召唤时就不用再等网页首次渲染
        geo, _, _ = self.screen()
        self.offset = QPoint(geo.width() + 400, 0)
        self.panel.call("showInput", {"mode": "ask", "theme": self.theme})
        self.panel.move(self.offset)
        self.panel.setAttribute(Qt.WA_ShowWithoutActivating, True)  # 预热不抢你当前窗口的焦点
        self.panel.show()

        def finish() -> None:
            self.panel.hide()
            self.panel.setAttribute(Qt.WA_ShowWithoutActivating, False)
            self.offset = QPoint()
            self.is_ready = True
            print("界面已就绪（已预热）", flush=True)

        QTimer.singleShot(600, finish)

    def on_sized(self, w: int, h: int) -> None:
        self.content = QSize(w, h)
        if self.view:
            self.place()

    def on_view(self, view: str) -> None:
        self.view = view
        if view != "input":
            self.overlay.hide()
        self.panel.set_click_through(view == "pill")
        if view == "pill" and self.prev_foreground and not self.selftest:
            win32gui.SetForegroundWindow(self.prev_foreground)  # 开始操作前把焦点还给原窗口
        self.place()

    def on_deactivated(self) -> None:
        # 点了别处：回答卡片淡出（输入阶段点浮层不会触发，因为浮层不抢焦点）
        if self.view == "card" and not self.selftest:
            self.dismiss()

    def dismiss(self) -> None:
        self.panel.call("park")
        self.overlay.hide()
        self.panel.hide()
        self.view = None


# ---------------------------------------------------------------------------
# 托盘
# ---------------------------------------------------------------------------

MENU_QSS = """
QMenu { background: #1E1E20; color: #ECECEC; border: 1px solid rgba(255,255,255,0.09);
        border-radius: 10px; padding: 6px; font-family: "Segoe UI Variable Text", "Microsoft YaHei UI";
        font-size: 13px; }
QMenu::item { padding: 7px 36px 7px 12px; border-radius: 6px; }
QMenu::item:selected { background: rgba(255,255,255,0.08); }
QMenu::separator { height: 1px; background: rgba(255,255,255,0.08); margin: 5px 8px; }
"""


def orb_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(8, 8, 56, 56)
    g.setColorAt(0, QColor("#5B8CFF"))
    g.setColorAt(1, QColor("#9B6BFF"))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawEllipse(10, 10, 44, 44)
    p.end()
    return QIcon(pm)


def build_tray(ctrl: Controller, app: QApplication) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(orb_icon(), app)
    tray.setToolTip("Super Aide 原型 · Alt+Q 问答 / Alt+W 操作")
    menu = QMenu()
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_TranslucentBackground)
    menu.setStyleSheet(MENU_QSS)
    for label, mode in (("问答        Alt+Q", "ask"), ("操作        Alt+W", "act")):
        action = QAction(label, menu)
        action.triggered.connect(lambda _=False, m=mode: QTimer.singleShot(150, lambda: ctrl.summon(m)))
        menu.addAction(action)
    menu.addSeparator()
    quit_action = QAction("退出", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.show()
    tray._menu = menu  # 防止被回收
    return tray


# ---------------------------------------------------------------------------
# 自测：合成桌面 + 屏幕外窗口，逐个状态存图
# ---------------------------------------------------------------------------

def synthetic_desktop(geo: QRect, dpr: float) -> tuple[QPixmap, QRect]:
    pm = QPixmap(round(geo.width() * dpr), round(geo.height() * dpr))
    pm.setDevicePixelRatio(dpr)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    bg = QLinearGradient(0, 0, geo.width(), geo.height())
    bg.setColorAt(0, QColor("#2B3A55"))
    bg.setColorAt(1, QColor("#56435E"))
    p.fillRect(QRect(0, 0, geo.width(), geo.height()), bg)
    win = QRect(int(geo.width() * 0.16), int(geo.height() * 0.14), int(geo.width() * 0.62), 300)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1B1D22"))
    p.drawRoundedRect(win, 10, 10)
    p.setBrush(QColor("#2A2D34"))
    p.drawRoundedRect(QRect(win.x(), win.y(), win.width(), 34), 10, 10)
    p.fillRect(QRect(win.x(), win.y() + 24, win.width(), 10), QColor("#2A2D34"))
    p.setPen(QColor("#9AA0A6"))
    p.setFont(QFont("Segoe UI", 10))
    p.drawText(win.adjusted(14, 8, 0, 0), "analysis.ipynb - JupyterLab")
    p.setFont(QFont("Consolas", 12))
    p.setPen(QColor("#E06C75"))
    p.drawText(win.adjusted(24, 60, -24, -20), Qt.TextWordWrap,
               "Traceback (most recent call last):\n"
               '  File "C:\\work\\analysis.py", line 3, in <module>\n'
               "    import pandas as pd\n"
               "ModuleNotFoundError: No module named 'pandas'")
    p.end()
    return pm, win


class SelfTest:
    def __init__(self, ctrl: Controller, app: QApplication) -> None:
        self.ctrl, self.app = ctrl, app
        geo, _, dpr = ctrl.screen()
        ctrl.offset = QPoint(geo.width() + 400, 0)
        self.desktop, self.sel = synthetic_desktop(geo, dpr)
        OUT.mkdir(parents=True, exist_ok=True)
        steps = []
        for theme in ("dark", "light"):
            steps += [
                (300, lambda t=theme: self.summon("ask", t)), (900, lambda t=theme: self.save(f"{t}-1-ask-input")),
                (0, lambda: ctrl.panel.call("submit", "")), (1000, lambda t=theme: self.save(f"{t}-2-ask-thinking")),
                (4200, lambda t=theme: self.save(f"{t}-3-ask-answer")),
                (0, lambda t=theme: self.summon("act", t)), (900, lambda t=theme: self.save(f"{t}-4-act-input")),
                (0, lambda: ctrl.panel.call("submit", "")), (2600, lambda t=theme: self.save(f"{t}-5-act-pill")),
                (4200, lambda t=theme: self.save(f"{t}-6-act-toast")),
            ]
        steps.append((300, self.finish))
        self.steps = steps

    def start(self) -> None:
        self.next()

    def next(self) -> None:
        if not self.steps:
            return
        delay, fn = self.steps.pop(0)

        def run() -> None:
            fn()
            self.next()

        QTimer.singleShot(delay, run)

    def summon(self, mode: str, theme: str) -> None:
        self.ctrl.theme = theme
        self.ctrl.summon(mode, frozen=self.desktop, sel=self.sel)

    def save(self, name: str) -> None:
        base = self.ctrl.overlay.grab() if self.ctrl.overlay.isVisible() else self.desktop.copy()
        p = QPainter(base)
        if self.ctrl.panel.isVisible():
            p.drawPixmap(self.ctrl.panel.pos() - self.ctrl.offset, self.ctrl.panel.grab())
        p.end()
        base.save(str(OUT / f"{name}.png"))
        print(f"已保存 {name}.png", flush=True)

    def finish(self) -> None:
        if self.ctrl.latencies:
            overlay = statistics.median(v[0] for v in self.ctrl.latencies)
            ready = statistics.median(v[1] for v in self.ctrl.latencies)
            print(f"召唤延迟中位数：定格画面 {overlay:.0f}ms，输入框可输入 {ready:.0f}ms", flush=True)
        self.app.quit()


def main() -> None:
    selftest = "--selftest" in sys.argv
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    ctrl = Controller(selftest)

    if selftest:
        test = SelfTest(ctrl, app)
        ctrl.bridge.readied.connect(test.start)
    else:
        hotkeys = HotkeyFilter(ctrl.summon)
        app.installNativeEventFilter(hotkeys)
        for hid, (mode, vk) in HOTKEYS.items():
            ok = user32.RegisterHotKey(None, hid, MOD_ALT | MOD_NOREPEAT, vk)
            print(f"注册 Alt+{chr(vk)}（{mode}）：{'成功' if ok else '失败，可能被其它程序占用'}", flush=True)
        tray = build_tray(ctrl, app)  # noqa: F841
        app.aboutToQuit.connect(lambda: [user32.UnregisterHotKey(None, hid) for hid in HOTKEYS])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
