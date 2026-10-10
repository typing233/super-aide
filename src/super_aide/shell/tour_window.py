"""新手指引的窗口（步骤在 tour.py，网页在 ui/web/tour.*）。

- 欢迎：屏幕正中一张小卡片，能拿到焦点（回车开始，Esc 跳过）。
- 开始以后是一个小气泡：贴在要你看的东西旁边（输入框、回答、胶囊、托盘图标；要你按快捷键时在屏幕下方正中），
  尾巴指着它。点它不抢焦点、不出现在截图里，快照也不读它。你真的做了那件事，外壳报上来（controller.happened），
  就换下一个气泡。
- 目标外面一圈慢慢扩散的光环（Spotlight，自己画的）；托盘那一步再把屏幕别处压暗。
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
from typing import Protocol

import win32gui
from PySide6.QtCore import (QEasingCurve, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, QVariantAnimation,
                            Signal, Slot)
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QSystemTrayIcon, QVBoxLayout, QWidget

from .. import i18n, paths
from ..config import Config
from ..i18n import tr
from ..snapshot import uia, win32
from ..tour import Tour
from . import screens
from .controller import Controller
from .panel import GWL_EXSTYLE, WS_EX_NOACTIVATE, disable_transitions, exclude_from_capture

log = logging.getLogger(__name__)

TOUR_PAGE = paths.UI_INDEX.with_name("tour.html")
PAD = 18          # 网页里气泡四周给阴影、尾巴留的边（tour.css 里气泡布局的 #root padding）
TIP = 11          # 气泡边到目标的距离（尾巴尖离目标约 4px）
EDGE = 8          # 气泡离屏幕边至少这么远
CENTER_LIFT = 64  # 要你按快捷键时，气泡在屏幕下方正中，离底边这么高
DONE_MS = 3000    # "都会了"停这么久
#: 任务栏、托盘、桌面：从托盘菜单打开时前台是它们，"开始"以后焦点不还给它们
SHELL_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "TopLevelWindowForOverflowXamlIsland",
                 "NotifyIconOverflowWindow", "Progman", "WorkerW"}
#: 每种目标：气泡先试放在哪边；光环的圆角（和真实界面一致）
SIDES = {"input": ("below", "above"), "card": ("below", "above", "right", "left"),
         "pill": ("above", "left"), "tray": ("above", "left")}
RADIUS = {"input": 14, "card": 16, "pill": 20, "tray": 8}
COLORS = {"ask": ("#5B8CFF", "#9B6BFF"), "act": ("#FFB547", "#FF7A45")}
APP_NAMES = ("超级助手", "Super Aide")  # 托盘图标的提示以它开头（两种语言都认：换了语言提示可能还没跟上）
user32 = ctypes.windll.user32


class TourHost(Protocol):
    cfg: Config
    ctrl: Controller
    tray: QSystemTrayIcon

    def tour_closed(self, how: str) -> None: ...


# ---------- 气泡摆在哪 ----------

def place_bubble(target: QRect, size: QSize, avail: QRect, sides: tuple[str, ...]) -> tuple[QPoint, str, int]:
    """气泡窗口（大小 size，四周 PAD 是透明边）摆在目标旁边，按 sides 的顺序找第一个放得下的一边。
    返回 (窗口左上角, 尾巴朝哪 up / down / left / right, 尾巴尖在窗口里的位置)。"""
    w, h = size.width(), size.height()
    cx, cy = target.center().x(), target.center().y()

    def clamp(value: int, low: int, high: int) -> int:
        return max(low, min(value, high))

    for side in sides:
        if side in ("below", "above"):
            x = clamp(cx - w // 2, avail.left() + EDGE - PAD, avail.right() + 1 - EDGE + PAD - w)
            y = target.bottom() + 1 + TIP - PAD if side == "below" else target.top() - TIP + PAD - h
            fits = y + h - PAD <= avail.bottom() + 1 - EDGE if side == "below" else y + PAD >= avail.top() + EDGE
            at = clamp(cx - x, PAD + 18, w - PAD - 18)
        else:
            y = clamp(cy - h // 2, avail.top() + EDGE - PAD, avail.bottom() + 1 - EDGE + PAD - h)
            x = target.right() + 1 + TIP - PAD if side == "right" else target.left() - TIP + PAD - w
            fits = x + w - PAD <= avail.right() + 1 - EDGE if side == "right" else x + PAD >= avail.left() + EDGE
            at = clamp(cy - y, PAD + 14, h - PAD - 14)
        if fits:
            return QPoint(x, y), {"below": "up", "above": "down", "right": "left", "left": "right"}[side], at
    # 哪边都放不下（目标几乎占满屏幕）：放在它里面靠下的地方，不要尾巴
    return QPoint(clamp(cx - w // 2, avail.left(), avail.right() - w), target.bottom() - h - 24), "none", 0


def screen_of(rect: QRect) -> tuple[QRect, QRect]:
    """rect 所在那块屏幕的 (整块, 去掉任务栏的部分)，逻辑像素。"""
    screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
    return screen.geometry(), screen.availableGeometry()


def center_bubble(size: QSize, avail: QRect) -> QPoint:
    """要你按快捷键：屏幕下方正中（像游戏里"按 X"的提示）。"""
    return QPoint(avail.center().x() - size.width() // 2, avail.bottom() + 1 - CENTER_LIFT + PAD - size.height())


# ---------- 目标外面那一圈 ----------

class Spotlight(QWidget):
    """目标外面一圈模式色的光环，慢慢往外扩散；托盘那一步再把屏幕别处压暗（像游戏的新手指引）。
    点击穿透（托盘图标照样能右键）、不抢焦点、不进截图。"""

    RING = 34  # 光环四周留的地方（扩散的那一圈也画在里面）

    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.hole = QRectF()      # 目标（窗口里的坐标），已经放宽了一点
        self.radius = 12.0
        self.colors = COLORS["ask"]
        self.dim = False
        self.phase = 0.0
        self.pulse = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1700, loopCount=-1)
        self.pulse.setEasingCurve(QEasingCurve.OutCubic)
        self.pulse.valueChanged.connect(self._tick)

    def light(self, target: QRect, radius: int, mode: str, dim: QRect | None = None) -> None:
        """dim：要压暗的那块屏幕（托盘那一步）；None = 只画光环。"""
        area = dim or target.adjusted(-self.RING, -self.RING, self.RING, self.RING)
        self.dim, self.colors, self.radius = dim is not None, COLORS.get(mode, COLORS["ask"]), radius + 5
        self.hole = QRectF(target.translated(-area.topLeft())).adjusted(-5, -5, 5, 5)
        self.setGeometry(area)
        exclude_from_capture(self)
        if not self.isVisible():
            self.show()
            self.pulse.start()
        self.raise_()
        self.update()

    def off(self) -> None:
        self.pulse.stop()
        self.hide()

    def _tick(self, value: float) -> None:
        self.phase = value
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt 的方法名
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.dim:
            shade = QPainterPath()
            shade.addRect(QRectF(self.rect()))
            hole = QPainterPath()
            hole.addRoundedRect(self.hole, self.radius, self.radius)
            p.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 115))
        a, b = (QColor(c) for c in self.colors)
        grad = QLinearGradient(self.hole.topLeft(), self.hole.bottomRight())
        grad.setColorAt(0, a)
        grad.setColorAt(1, b)
        grow = 3 + 12 * self.phase
        wave = QColor(b)
        wave.setAlphaF(0.6 * (1 - self.phase))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(wave, 2))
        p.drawRoundedRect(self.hole.adjusted(-grow, -grow, grow, grow), self.radius + grow, self.radius + grow)
        p.setPen(QPen(grad, 2.5))
        p.drawRoundedRect(self.hole, self.radius, self.radius)
        p.end()


# ---------- 窗口 ----------

class TourBridge(QObject):
    """网页通过 QWebChannel 调用这些槽。"""

    def __init__(self, window: TourWindow) -> None:
        super().__init__()
        self.w = window

    @Slot()
    def ready(self) -> None:
        self.w.page_ready()

    @Slot(int, int)
    def contentSize(self, w: int, h: int) -> None:  # noqa: N802 - JS 侧的命名
        self.w.sized(QSize(w, h))

    @Slot()
    def start(self) -> None:
        self.w.begin()

    @Slot()
    def done(self) -> None:
        self.w.done()

    @Slot(str)
    def close(self, how: str) -> None:
        self.w.finish(how or "closed")


class TourWindow(QWidget):
    tray_found = Signal(object)  # 托盘图标在哪（UIA 线程查完 → 主线程）

    def __init__(self, host: TourHost) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.host, self.ctrl = host, host.ctrl
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(tr("新手指引"))
        self.view = QWebEngineView(self)
        self.view.page().setBackgroundColor(Qt.transparent)
        self.bridge = TourBridge(self)  # 要留着引用：QWebChannel 不管它的死活，被回收了网页那边就卡住
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.tour = Tour()
        self.layout_ = ""        # welcome | bubble；空 = 没开着
        self.loaded = False
        self.size_ = QSize()     # 网页报上来的大小（连着透明边）
        self.panel = QRect()     # 回答界面现在占着的那一块（controller.placed）
        self.panel_view = ""     # 回答界面现在是什么样子（空 = 收着）
        self.prev_fg = 0         # 打开欢迎页之前在用的窗口：开始以后把焦点还给它
        #: 托盘图标在哪：(位置, 收在 ^ 里) ；None = 还没查；位置是空的 = 没找到
        self.tray: tuple[QRect, bool] | None = None
        self.finding = False     # 正在查托盘图标
        self.spot = Spotlight()
        self.closing = QTimer(self, singleShot=True, interval=DONE_MS, timeout=lambda: self.finish("finished"))
        self.view.load(QUrl.fromLocalFile(str(TOUR_PAGE)))
        exclude_from_capture(self)
        disable_transitions(self)
        self.ctrl.happened.connect(self._on_happened)
        self.ctrl.placed.connect(self._on_placed)
        host.tray.contextMenu().aboutToShow.connect(lambda: self._on_happened("tray_menu"))
        self.tray_found.connect(self._on_tray_found)

    # ---------- 打开、关上 ----------

    def open(self) -> None:
        """打开欢迎页（第一次用时自动打开；托盘菜单、设置里再打开）。正在引导就不从头来。"""
        if self.layout_ == "bubble":
            return
        self.tour = Tour()
        self.tray = None  # 每次重新查：你可能把图标拖到任务栏上了
        self.prev_fg = win32gui.GetForegroundWindow()
        self.layout_ = "welcome"
        self._set_no_activate(False)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self.ctrl.coach_windows.add(int(self.winId()))  # 开着就和我们自己的界面一样：快照不读它
        self.push()  # 网页画好后报上来大小（sized），那时再显示，不先闪一下别的大小

    def page_ready(self) -> None:
        self.loaded = True
        self.push()

    def is_open(self) -> bool:
        return bool(self.layout_)

    def begin(self) -> None:
        """欢迎页上点了"开始"：变成气泡，焦点还给原来的窗口（召唤时框的是它）。"""
        self.tour.start()
        self.layout_ = "bubble"
        self.hide()
        self._set_no_activate(True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        target = self._work_window()
        if target:
            try:
                win32gui.SetForegroundWindow(target)
            except Exception:  # noqa: BLE001 - 系统不让切就算了
                pass
        self._refresh()

    def done(self) -> None:
        """托盘那一步点了"完成"，或者真的右键打开了托盘菜单：显示"都会了"，过一会儿自己关掉。"""
        self.tour.finish()
        self._refresh()

    def finish(self, how: str) -> None:
        """skipped：欢迎页上跳过；closed：中途跳过；finished：看完了。都不再自动打开。"""
        if not self.layout_:
            return
        log.info("新手指引：%s（到第 %d 步）", how, self.tour.index + 1)
        self.layout_ = ""
        self.closing.stop()
        self.spot.off()
        self.ctrl.suggest = {}
        self.ctrl.coach_windows.discard(int(self.winId()))
        self.hide()
        self.host.tour_closed(how)

    def retitle(self) -> None:
        """语言换了。"""
        self.setWindowTitle(tr("新手指引"))
        self.refresh()

    def refresh(self) -> None:
        """快捷键、主题、语言换了：气泡上写的跟着换。"""
        if self.layout_:
            self.push()

    # ---------- 发生了什么 ----------

    def _on_happened(self, event: str) -> None:
        if event.startswith("view:"):
            self.panel_view = event.removeprefix("view:")
        elif event == "dismiss":
            self.panel_view = ""
        if self.layout_ != "bubble" or self.tour.stage != "step":
            return
        changed = self.tour.handle(event)
        if event.startswith("summon:"):
            # 定格画面刚盖上来：光环和气泡排到它上面，回答界面再排到最上面
            self.spot.raise_()
            self.raise_()
            self.ctrl.panel.raise_()
        if changed or event.startswith(("view:", "summon:")) or event == "dismiss":
            self._refresh()

    def _on_placed(self, rect: QRect) -> None:
        self.panel = rect
        if self.layout_ == "bubble":
            self._refresh(moved=True)

    # ---------- 摆气泡 ----------

    def _target(self) -> tuple[str, QRect]:
        """气泡现在该指着谁、在屏幕哪儿；现在不该出现就是空的。"""
        if self.tour.stage == "done":
            return "center", QRect()
        step = self.tour.step
        if step is None or not step.target:
            return "", QRect()
        if step.target in ("center", "tray"):
            # 这两种只在回答界面收着时出现，不挡着你正在看的；贴在屏幕边上的分步骤小卡不算（它会留好几分钟）
            if self.panel_view and self.panel_view != "dock":
                return "", QRect()
            if step.target == "tray":
                if self.tray is None:
                    self._find_tray()  # 查到了再出现（约 0.1 秒）
                    return "", QRect()
                return "tray", self.tray[0]
            return "center", QRect()
        if self.panel_view == step.target and not self.panel.isEmpty():
            return step.target, self.panel
        return "", QRect()

    def _refresh(self, moved: bool = False) -> None:
        """按现在这一步重画气泡（换了步）或者只是挪一下（目标挪了）。"""
        if self.layout_ != "bubble":
            return
        self.ctrl.suggest = self.tour.suggest()
        kind, _rect = self._target()
        if not kind:
            self.hide()
            self.spot.off()
            return
        if moved and self.isVisible():
            self._place()
        else:
            self.push()  # 网页画好新内容、报上来大小以后（sized）再摆

    def sized(self, size: QSize) -> None:
        self.size_ = size
        if self.layout_ == "welcome":
            avail = self._screen()
            rect = QRect(QPoint(0, 0), size.boundedTo(avail.size()))
            rect.moveCenter(avail.center())
            self.setGeometry(rect)
            if not self.isVisible():
                self.show()
                self.raise_()
                self.activateWindow()
        elif self.layout_ == "bubble":
            self._place(pop=True)

    def _place(self, pop: bool = False) -> None:
        kind, target = self._target()
        if not kind or self.size_.isEmpty():
            return
        avail = self._screen(target)
        mode = self.tour.step.mode if self.tour.step is not None else "ask"
        if kind == "center":
            pos, tail, at = center_bubble(self.size_, avail), "none", 0
            self.spot.off()
        else:
            ring = not target.isEmpty()
            if not ring:  # 托盘图标没找到：指着任务栏右边，不画光环
                target = QRect(avail.right() - 60, avail.bottom() + 1, 40, 40)
            pos, tail, at = place_bubble(target, self.size_, avail, SIDES[kind])
            if ring:
                self.spot.light(target, RADIUS[kind], mode, screen_of(target)[0] if kind == "tray" else None)
            else:
                self.spot.off()
        self.setGeometry(QRect(pos, self.size_))
        if not self.isVisible():
            self.show()
        self.raise_()
        if self.tour.stage == "done" and not self.closing.isActive():
            self.closing.start()
        self.js(f"tour.place({json.dumps({'tail': tail, 'at': at, 'pop': pop})})")

    def _find_tray(self) -> None:
        """托盘图标在哪：在 UIA 线程里查，查完回到主线程（tray_found）。"""
        if self.finding:
            return
        self.finding = True
        fut = self.ctrl.collector.uia_fast.submit(uia.tray_icon, APP_NAMES)
        fut.add_done_callback(lambda f: self.tray_found.emit(None if f.exception() else f.result()))

    def _on_tray_found(self, found) -> None:
        self.finding = False
        if found is None:
            self.tray = (QRect(), False)
        else:
            (left, top, right, bottom), hidden = found
            self.tray = (screens.at((left + right) // 2, (top + bottom) // 2).to_logical(found[0]), hidden)
        self._refresh()

    # ---------- 小工具 ----------

    def _screen(self, near: QRect | None = None) -> QRect:
        """目标所在的那块屏幕（没有目标时跟着最近一次召唤的那块，开始时是主屏幕）。"""
        if near is not None and not near.isEmpty():
            return screen_of(near)[1]
        return self.ctrl.screen.available

    def _work_window(self) -> int:
        """焦点还给谁：打开欢迎页之前在用的那个应用窗口；那时前台是任务栏、托盘（从托盘菜单打开的），
        或者是已经关掉的准备窗口，就交给最上面的那个应用窗口（和 Alt+Tab 一样）。"""
        own = self.ctrl.own_windows() | {int(self.winId())}
        fg = self.prev_fg
        if (fg and fg not in own and win32gui.IsWindow(fg) and win32gui.IsWindowVisible(fg)
                and win32gui.GetClassName(fg) not in SHELL_CLASSES):
            return fg
        return next((w.hwnd for w in win32.visible_windows(exclude=own)
                     if not w.minimized and w.pid != os.getpid() and w.class_name not in SHELL_CLASSES), 0)

    def _set_no_activate(self, on: bool) -> None:
        """气泡点了不抢焦点。"""
        hwnd = int(self.winId())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE if on else style & ~WS_EX_NOACTIVATE)

    def push(self) -> None:
        if not self.loaded or not self.layout_:
            return
        cfg = self.host.cfg
        data = self.tour.state(cfg.hotkey_ask, cfg.hotkey_act, hidden=self.tray is not None and self.tray[1])
        data.update(layout=self.layout_, theme=self.ctrl.theme(), lang=i18n.lang(), target=self._target()[0])
        self.js(f"tour.update({json.dumps(data, ensure_ascii=False)})")

    def js(self, code: str) -> None:
        self.view.page().runJavaScript(f"window.tour && {code}")

