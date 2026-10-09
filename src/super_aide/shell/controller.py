"""控制器：召唤 → 定格画面 + 自动选区 + 输入框 → 提问 → 回答卡片 / 操作胶囊 → 消失。

坐标：快照和 Win32 用物理像素，Qt 用逻辑像素。每次召唤只定格你正在用的那块屏幕，
按它自己的缩放比换算（多显示器、混合缩放见 screens.py）。
"""

from __future__ import annotations

import logging
import re
import time
import winreg

import win32api
import win32gui
from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap, QRegion

from .. import i18n
from ..config import Config
from ..engines.hub import EngineHub
from ..i18n import tr
from ..router import Task
from ..snapshot import content, uia
from ..snapshot.collector import Collector
from ..snapshot.collector import Session as Snapshot
from ..snapshot.win32 import Rect
from ..cu.signals import Signals
from .killswitch import EscWatcher
from . import screens
from .overlay import Overlay
from .panel import INPUT_SIZE, MARGIN, Bridge, Panel, disable_transitions, exclude_from_capture

log = logging.getLogger(__name__)

GAP = 20              # 输入框与选区的距离
EDGE = 20             # 胶囊、结果提示与屏幕边缘的距离
#: 空闲时窗口停在屏幕外而不是隐藏：重新显示一个窗口要多等一两百毫秒（实测），挪回来几乎不花时间
PARK = QPoint(-30000, -30000)
PARKED_FRAME_MS = 100  # 网页把收起后的空白画到窗口上，留足这么久
RECENT_S = 600        # 10 分钟内可以 Ctrl+Enter 接着上次问
CLIPBOARD_LIMIT = 2000
NEGATIVE_FOLLOWUP = re.compile(r"不对|错了|没用|不行|没解决|还是不|不是这样|没有用|不管用|失败了"
                               r"|\b(wrong|incorrect|not working|doesn'?t work|didn'?t work|still (not|broken|fail)|no luck)\b",
                               re.IGNORECASE)
#: Markdown 的编号列表项。回答规范里编号列表只用来写"照着做"的步骤
STEP_ITEM = re.compile(r"^ {0,3}\d{1,2}[.)] +\S", re.M)


def windows_theme() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
    except OSError:
        return "dark"


class Controller(QObject):
    kind_found = Signal(str, str)  # (快照标识, 内容类型)，来自 UIA 线程

    def __init__(self, cfg: Config, collector: Collector, hub: EngineHub) -> None:
        super().__init__()
        self.cfg, self.collector, self.hub = cfg, collector, hub
        self.bridge = Bridge()
        self.panel = Panel(self.bridge)
        self.overlay = Overlay()
        self.esc = EscWatcher()
        self.signals = Signals()  # 和界面操作的工具服务器之间：Esc 停止、收起屏幕指引
        self.screen = screens.primary()  # 这次召唤所在的屏幕
        self.view: str | None = None  # 为空：面板收在屏幕外
        self.content = INPUT_SIZE
        self.pill_area = QRect()  # 胶囊（展开时是小窗）在窗口里占的那一块，别处的点击穿过去
        self.anchor = QPoint()
        self.snap: Snapshot | None = None
        self.kind = "text"
        self.conv_key = ""
        self.conv_mode = "ask"
        self.conv_time = 0.0
        self.last_question = ""
        self.answer = ""
        self.last_answer = ""
        self.prev_fg = 0
        self.t_hotkey: float | None = None
        self.ready = False
        self._clip = ("", 0.0)
        self.on_use = lambda: None  # 你在用助手（召唤、提问）：自我改进挑你空下来的时候做事

        b = self.bridge
        b.readied.connect(self._warm_panel)
        b.sized.connect(self._on_sized)
        b.view_changed.connect(self._on_view)
        b.cancelled.connect(self.dismiss)
        b.submitted.connect(self._on_submit)
        b.followed_up.connect(self._on_followup)
        b.continued.connect(self._on_continue)
        b.rated.connect(lambda value: self.hub.feedback(self.conv_key, value > 0))
        b.reasoned.connect(lambda kind, choice, text: self.hub.reason(self.conv_key, kind, choice, text))
        b.shown_on_screen.connect(self._on_shown)
        b.dock_expanded.connect(self._expand_dock)
        b.pill_area.connect(self._on_pill_area)
        self.overlay.reselected.connect(self._on_reselected)
        self.panel.deactivated.connect(self._on_deactivated)
        self.kind_found.connect(self._on_kind)
        self.hub.event.connect(self._on_engine_event)
        self.esc.triggered.connect(self._on_esc)
        QGuiApplication.clipboard().dataChanged.connect(self._on_clipboard)

        for w in (self.panel, self.overlay):
            w.winId()  # 预先创建原生窗口
            exclude_from_capture(w)
            disable_transitions(w)

    # ---------- 几何 ----------

    def _screen(self) -> tuple[QRect, QRect, float]:
        return self.screen.geometry, self.screen.available, self.screen.dpr

    def _to_logical(self, r: Rect) -> QRect:
        return self.screen.to_logical(r)

    def _to_physical(self, q: QRect) -> Rect:
        return self.screen.to_physical(q)

    @staticmethod
    def _active_point(cap) -> tuple[int, int]:
        """你正在用的那块屏幕上的一点：选中的文字或前台窗口的中心，都没有时看鼠标在哪。"""
        if cap.selection_source in ("text", "window"):
            r = cap.default_selection
            return (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
        return win32api.GetCursorPos()

    def _place(self) -> None:
        w, h = self.content.width(), self.content.height()
        geo, avail, _ = self._screen()
        if self.view in ("input", "card"):
            sel = self.overlay.sel.translated(geo.topLeft())
            if self.view == "input":
                x = max(avail.left(), min(sel.center().x() - w // 2, avail.right() - w))
                below = sel.bottom() + GAP - MARGIN
                above = sel.top() - GAP - (h - MARGIN)
                if below + h <= avail.bottom():
                    y = below
                elif above >= avail.top():
                    y = above
                else:  # 选区几乎占满屏幕：放在选区内偏下的位置
                    y = sel.top() + int(sel.height() * 0.8) - h // 2
                self.anchor = QPoint(x, y)
            x = self.anchor.x()
            y = max(avail.top(), min(self.anchor.y(), avail.bottom() - h))
        elif self.view == "dock":  # 贴在离选区远的那一侧，不挡住你正在照着做的地方
            sel = self.overlay.sel.translated(geo.topLeft())
            right = sel.center().x() < avail.center().x()
            x = avail.right() - w + MARGIN - EDGE if right else avail.left() - MARGIN + EDGE
            y = avail.top() + max(0, (avail.height() - h) // 2)
        else:  # 胶囊和结果提示：右下角
            x = avail.right() - w + MARGIN - EDGE
            y = avail.bottom() - h + MARGIN - EDGE
        self.panel.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
        if self.view == "dock":
            # 四周给阴影留的透明边也会挡住下面窗口的点击（实测）。贴边时会长时间停在别的窗口上，只保留卡片本身
            self.panel.setMask(QRegion(MARGIN, MARGIN, w - 2 * MARGIN, h - 2 * MARGIN))
        elif self.view == "pill" and not self.pill_area.isEmpty():
            # 操作中窗口是展开后的大小，只保留胶囊（展开时是小窗）那一块，别处的透明地方让点击穿过去
            self.panel.setMask(QRegion(self.pill_area))
        elif not self.panel.mask().isEmpty():
            self.panel.clearMask()

    def theme(self) -> str:
        return self.cfg.theme if self.cfg.theme in ("light", "dark") else windows_theme()

    # ---------- 启动预热 ----------

    def _warm_panel(self) -> None:
        """两个窗口在屏幕外显示出来并一直停在那里：第一次召唤不用等网页首次渲染，之后每次召唤
        也只是把窗口挪回来，不用重新显示（实测重新显示要多等一两百毫秒）。"""
        geo, _, _ = self._screen()
        self.collector.warm()
        # 在屏幕外把输入框画一遍。网页画好后报上来的视图和尺寸不会把面板摆回屏幕上：面板收着（self.view 为空）
        # 时不理它们，开机时网页慢、预热结束后才报上来也一样（见 _on_view）
        self.panel.call("showInput", {"mode": "ask", "theme": self.theme(), "lang": i18n.lang()})
        self.panel.setAttribute(Qt.WA_ShowWithoutActivating, True)  # 预热不抢当前窗口的焦点
        self.panel.move(PARK)
        self.panel.show()
        self.overlay.setGeometry(QRect(PARK, geo.size()))
        self.overlay.show()

        def finish() -> None:
            self.panel.setAttribute(Qt.WA_ShowWithoutActivating, False)
            self._park()
            self.ready = True
            log.info("界面就绪")

        QTimer.singleShot(600, finish)

    def _park(self) -> None:
        # 网页先清空：下次召唤时窗口一挪回来，露出的是它最后画的那一帧，不能是上一次的输入框或卡片
        # （网页重画好之前，旧画面会先闪一下）
        self.panel.call("park")
        self.overlay.move(PARK)
        self.panel.move(PARK)

    # ---------- 召唤 ----------

    def on_hotkey(self, name: str, arrived: float) -> None:
        if self.conv_mode == "act" and self.hub.is_busy(self.conv_key):
            return  # 操作进行中不打断它（按 Esc 可以停止）
        self.summon(name, arrived)

    def summon(self, mode: str, arrived: float | None = None) -> None:
        if not self.ready:
            return
        self.on_use()
        self.signals.clear_guide()
        self.t_hotkey = arrived or time.perf_counter()
        marks: list[tuple[str, float]] = []

        def mark(label: str) -> None:
            marks.append((label, (time.perf_counter() - self.t_hotkey) * 1000))

        own = {self.panel.hwnd(), int(self.overlay.winId())}
        cap = self.collector.capture(mode, own, prefer_hwnd=self.prev_fg, clipboard=self._recent_clipboard())
        mark("采集")
        if cap.foreground is not None:
            self.prev_fg = cap.foreground.hwnd
        self.screen = screens.at(*self._active_point(cap))
        geo, _, dpr = self._screen()
        # 截图是整个虚拟桌面，只取这块屏幕
        image = QImage(cap.screen_bgra, cap.screen_size[0], cap.screen_size[1], QImage.Format_RGB32)
        frozen = QPixmap.fromImage(image.copy(*self.screen.crop_box(cap.screen_origin)))
        frozen.setDevicePixelRatio(dpr)
        mark("画面")
        self.kind = cap.content_kind
        sel = self._to_logical(self.screen.clamp(cap.default_selection) or self.screen.phys).translated(-geo.topLeft())
        rects = [self._to_logical(r) for w in cap.windows if not w.minimized and (r := self.screen.clamp(w.rect))]
        self.overlay.summon(frozen, sel, mode, geo, rects)
        self.overlay.repaint()  # 立刻画出定格画面，不等后面的步骤
        mark("定格画面")
        cap_id = str(id(cap))
        self.snap = self.collector.start(cap, on_kind=lambda kind: self.kind_found.emit(cap_id, kind))

        self.view = "input"
        self.content = INPUT_SIZE  # 上一次是回答卡片时，不先按卡片的高度摆、再跳到输入框该在的位置
        self.panel.set_click_through(False)
        self.panel.set_no_activate(False)
        recent = bool(self.conv_key) and time.time() - self.conv_time < RECENT_S
        self.panel.call("showInput", {"mode": mode, "theme": self.theme(), "lang": i18n.lang(),
                                      "placeholders": content.placeholders(self.kind),
                                      "answerMax": int(geo.height() * 0.6) - 120, "hasRecent": recent})
        self._place()
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()
        self.panel.view.setFocus()
        mark("输入框")
        log.info("召唤耗时：%s（其中采集：%s）", "，".join(f"{label} {ms:.0f}ms" for label, ms in marks),
                 "，".join(f"{k} {v:.0f}ms" for k, v in cap.timings.items()))

    def _on_shown(self) -> None:
        if self.t_hotkey is None:
            return
        now = time.perf_counter()
        overlay_ms = ((self.overlay.first_paint_at or now) - self.t_hotkey) * 1000
        log.info("召唤延迟：定格画面 %.0fms，输入框可输入 %.0fms", overlay_ms, (now - self.t_hotkey) * 1000)
        self.t_hotkey = None

    def _on_kind(self, cap_id: str, kind: str) -> None:
        if self.view == "input" and self.snap is not None and str(id(self.snap.cap)) == cap_id:
            self.kind = kind
            self.panel.call("setPlaceholders", content.placeholders(kind))

    def _on_reselected(self, local: QRect) -> None:
        if self.snap is None:
            return
        geo, _, _ = self._screen()
        rect = self._to_physical(local.translated(geo.topLeft()))
        self.snap.set_selection(rect, "manual")
        self._place()
        cap_id = str(id(self.snap.cap))
        fut = self.collector.uia_fast.submit(uia.text_at, (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        fut.add_done_callback(lambda f: self.kind_found.emit(
            cap_id, content.classify(f.result() if not f.exception() else "", source="selection")))

    # ---------- 提问 ----------

    def _task(self, mode: str, question: str, snap: Snapshot) -> Task:
        fg = snap.cap.foreground
        return Task(mode=mode, question=question, content_kind=self.kind, foreground=fg.process if fg else "")

    def _on_submit(self, text: str, mode: str) -> None:
        if self.snap is None:
            return
        snap = self.snap
        self.on_use()
        self.conv_key, self.conv_mode, self.conv_time = snap.id, mode, time.time()
        self.last_question, self.answer = text, ""
        self.hub.ask(snap.id, mode, text, snap, self._task(mode, text, snap))
        if mode == "act":
            self.signals.resume()
            self.esc.start()

    def _on_continue(self, text: str, mode: str) -> None:
        """输入框里 Ctrl+Enter：用这次召唤的画面和选区，接着上次的对话问。"""
        if self.snap is None or not self.conv_key or time.time() - self.conv_time > RECENT_S:
            self._on_submit(text, mode)
            return
        self._ask_more(text, mode, self.snap)

    def _on_followup(self, text: str, mode: str) -> None:
        if not self.conv_key:
            return
        own = {self.panel.hwnd(), int(self.overlay.winId())}
        cap = self.collector.capture(mode, own, prefer_hwnd=self.prev_fg, clipboard=self._recent_clipboard())
        self._ask_more(text, mode, self.collector.start(cap))

    def _ask_more(self, text: str, mode: str, snap: Snapshot) -> None:
        self.on_use()
        if mode == self.conv_mode and NEGATIVE_FOLLOWUP.search(text):
            self.hub.feedback(self.conv_key, False, "negative_followup")  # "不对""没用"：上一轮没答好
        if mode != self.conv_mode:
            # 问答 → 操作（Tab「照这个帮我做」）：新开一个操作对话，带上刚才的问答
            if self.conv_mode == "ask":
                self.hub.feedback(self.conv_key, True, "acted_on")  # 要照着这个回答去做：它答到点子上了
            question = (f"{text}\n\n（接着刚才的问答。上一轮的问题：{self.last_question}\n"
                        f"上一轮的回答：\n{self.last_answer or self.answer}）")
            self.conv_key, self.conv_mode = snap.id, mode
            self.hub.ask(snap.id, mode, question, snap, self._task(mode, text, snap))
            if mode == "act":
                self.signals.resume()
                self.esc.start()
        else:
            self.hub.followup(self.conv_key, text, snap)
        self.conv_time = time.time()
        self.last_question, self.answer = text, ""

    def _on_engine_event(self, key: str, ev: dict) -> None:
        if key != self.conv_key:
            return  # 已经被新的提问取代
        kind = ev.get("type")
        if kind in ("new_message", "retract"):
            self.answer = ""
        elif kind == "delta":
            self.answer += ev.get("text", "")
        elif kind == "done":
            self.last_answer = self.answer
            if self.conv_mode == "act":
                self.esc.stop()
        self.panel.call("onEvent", ev)

    def _on_esc(self) -> None:
        self.signals.stop()  # 工具服务器正在执行的那一步也立刻停下
        if self.hub.is_busy(self.conv_key):
            self.hub.interrupt(self.conv_key)
            self.panel.call("onEvent", {"type": "status", "text": tr("已按 Esc 停止")})
        self.esc.stop()

    # ---------- 状态 ----------

    def _on_sized(self, w: int, h: int) -> None:
        self.content = QSize(w, h)
        if self.view:
            self._place()

    def _on_view(self, view: str) -> None:
        if self.view is None:
            # 面板收着（启动预热、刚关掉）：网页换了视图也不把它摆回屏幕上，只有召唤和找回回答才会。
            # 开机时网页慢，预热那次"显示输入框"可能在预热结束后才报上来，输入框会自己停在屏幕左上角（实测）
            return
        self.view = view
        if view == "input":  # 输入框里按 Tab 切了模式：定格画面的描边颜色跟着变
            self.panel.view.page().runJavaScript("app.mode()", 0, lambda m: self.overlay.set_mode(m or "ask"))
        else:
            self.overlay.move(PARK)
        # 胶囊能点开：不再整个鼠标穿透，只是还不知道它在窗口里哪一块之前先穿透（见 _on_pill_area）。
        # 点它也不抢走焦点：助手正在操作的窗口不受影响。助手动真实鼠标时，工具服务器会让它暂时穿透（cu/passthrough.py）
        self.pill_area = QRect()
        self.panel.set_click_through(view == "pill")
        self.panel.set_no_activate(view in ("pill", "dock"))
        if view == "pill" and self.prev_fg:
            try:
                win32gui.SetForegroundWindow(self.prev_fg)  # 开始操作前把焦点还给原来的窗口
            except Exception:  # noqa: BLE001 - 原窗口可能已关闭
                pass
        self._place()

    def _on_pill_area(self, x: int, y: int, w: int, h: int) -> None:
        if self.view != "pill":
            return
        first = self.pill_area.isEmpty()
        self.pill_area = QRect(x, y, w, h)
        self.panel.setMask(QRegion(self.pill_area))
        if first:
            # 只在胶囊刚出来时撤掉穿透。之后的上报（步骤说明一变就会报）只改形状：这时工具服务器可能正让它穿透着
            self.panel.set_click_through(False)

    def _on_deactivated(self) -> None:
        # 点了别处：回答完的卡片淡出，分步骤的回答缩到屏幕边上；还在回答时不打断（可能只是在对照着看）
        if self.view != "card" or self.hub.is_busy(self.conv_key):
            return
        if len(STEP_ITEM.findall(self.last_answer)) >= 2:
            self.dock()
        else:
            self.dismiss()

    def dock(self) -> None:
        self.panel.set_no_activate(True)
        self.panel.call("dock")  # 网页切到贴边视图后会通知 setView('dock')，在那里摆位置

    def _expand_dock(self) -> None:
        if self.view != "dock":
            return
        self.panel.set_no_activate(False)
        self.view = None
        self.restore()

    def restore(self) -> None:
        """单击托盘图标：找回最近一次的回答（贴边的步骤展开回卡片）。"""
        if self.view == "dock":
            self._expand_dock()
            return
        if not self.conv_key or self.view is not None:
            return
        self.view = "card"
        self.panel.call("restore")
        self._place()
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def dismiss(self) -> None:
        self.signals.clear_guide()  # 收起回答，屏幕上的指引框也收起（贴边的步骤不走这里，指引会留着）
        if self.view in ("card", "input") and self.hub.is_busy(self.conv_key) and self.conv_mode == "ask":
            self.hub.interrupt(self.conv_key)
        self._park()
        self._return_focus()
        self.panel.set_no_activate(False)
        self.view = None

    def _return_focus(self) -> None:
        """面板停在屏幕外后仍是活动窗口，键盘输入会进到看不见的地方：把焦点还给原来的窗口。"""
        if not self.panel.isActiveWindow():
            return
        if self.prev_fg and win32gui.IsWindow(self.prev_fg):
            try:
                win32gui.SetForegroundWindow(self.prev_fg)
                return
            except Exception:  # noqa: BLE001 - 系统不允许时退回隐藏
                pass
        # 退回隐藏，下次召唤时会重新显示。重新显示时先露出的是隐藏前的最后一帧：等网页把空白画上去再隐藏
        QTimer.singleShot(PARKED_FRAME_MS, self._hide_parked)

    def _hide_parked(self) -> None:
        if self.view is None:  # 这期间又召唤了就不隐藏
            self.panel.hide()

    # ---------- 剪贴板 ----------

    def _on_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        self._clip = (text[:CLIPBOARD_LIMIT], time.time()) if text else ("", 0.0)

    def _recent_clipboard(self) -> str:
        text, t = self._clip
        return text if text and time.time() - t <= self.cfg.clipboard_max_age_s else ""
