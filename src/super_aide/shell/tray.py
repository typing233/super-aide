"""托盘图标和菜单。菜单自己绘制样式，与界面规范一致。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..config import Config
from ..i18n import app_name, tr

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
    gradient = QLinearGradient(8, 8, 56, 56)
    gradient.setColorAt(0, QColor("#5B8CFF"))
    gradient.setColorAt(1, QColor("#9B6BFF"))
    p.setBrush(gradient)
    p.setPen(Qt.NoPen)
    p.drawEllipse(10, 10, 44, 44)
    p.end()
    return QIcon(pm)


#: 自我改进进行到哪（菜单顶上那一行、悬停提示）：(状态, 阶段) → 中文原文（用的时候 tr）
EVOLVE_LABELS = {
    ("triage", ""): "正在自我改进 · 先看看是不是助手的问题",
    ("running", "prepare"): "正在自我改进 · 正在准备",
    ("running", "agent"): "正在自我改进 · 正在分析和修改",
    ("running", "carry"): "正在把本地改进移到新版本",
    ("running", "check"): "正在自我改进 · 正在跑测试",
    ("running", "review"): "正在自我改进 · 正在复核",
    ("running", "build"): "正在自我改进 · 正在打包",
    ("waiting", ""): "自我改进 · 等网络恢复",
    ("login", ""): "自我改进 · 需要登录或配置",
    ("ready", ""): "自我改进好了 · 点这里确认生效",
    ("applying", ""): "自我改进 · 正在生效",
}


def evolve_label(state: dict | None) -> str:
    """托盘里显示的一行：只在改进进行中（含等你确认生效）才有；做完了就不再占地方（生效时已经弹过通知）。"""
    active = (state or {}).get("active")
    if not active:
        return ""
    key = (active["status"], active.get("phase", "") if active["status"] == "running" else "")
    text = EVOLVE_LABELS.get(key) or EVOLVE_LABELS.get((active["status"], ""), "")
    return tr(text) if text else ""


class Tray(QSystemTrayIcon):
    def __init__(self, ctrl, app: QApplication, cfg: Config, open_settings, open_history, open_evolve=None) -> None:
        super().__init__(orb_icon(), app)
        self.cfg = cfg
        self.evolve_text = ""
        menu = QMenu()
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        menu.setStyleSheet(MENU_QSS)

        def add(label: str, handler) -> QAction:
            action = QAction(label, menu)
            action.triggered.connect(handler)
            menu.addAction(action)
            return action

        # 自我改进进行中才出现在最上面：点它打开设置里的"自我改进"
        self.evolve_action = add("", open_evolve or open_settings)
        self.evolve_sep = menu.addSeparator()
        self.evolve_action.setVisible(False)
        self.evolve_sep.setVisible(False)
        # 菜单关闭后稍等再召唤，避免菜单本身被截进定格画面
        self.ask_action = add("", lambda: QTimer.singleShot(200, lambda: ctrl.summon("ask")))
        self.act_action = add("", lambda: QTimer.singleShot(200, lambda: ctrl.summon("act")))
        menu.addSeparator()
        self.history_action = add("", open_history)
        self.settings_action = add("", open_settings)
        menu.addSeparator()
        self.quit_action = add("", app.quit)
        self.setContextMenu(menu)
        self.menu = menu  # 防止被回收
        self.activated.connect(lambda reason: ctrl.restore() if reason == QSystemTrayIcon.Trigger else None)
        self.refresh(cfg)
        self.show()

    def set_evolve(self, state: dict | None) -> None:
        """自我改进的进度：菜单顶上一行 + 悬停提示。没有在做的就收起来。"""
        self.evolve_text = evolve_label(state)
        self.evolve_action.setText(f"●  {self.evolve_text}" if self.evolve_text else "")
        self.evolve_action.setVisible(bool(self.evolve_text))
        self.evolve_sep.setVisible(bool(self.evolve_text))
        self.refresh(self.cfg)

    def refresh(self, cfg: Config) -> None:
        """快捷键或语言改了以后更新提示和菜单。制表符后面的部分 Qt 会右对齐显示。"""
        tip = tr("{app} · {ask} 问答 / {act} 操作", app=app_name(), ask=cfg.hotkey_ask, act=cfg.hotkey_act)
        self.setToolTip(f"{tip}\n{self.evolve_text}" if self.evolve_text else tip)
        self.ask_action.setText(f"{tr('问答')}\t{cfg.hotkey_ask}")
        self.act_action.setText(f"{tr('操作')}\t{cfg.hotkey_act}")
        self.history_action.setText(tr("历史记录"))
        self.settings_action.setText(tr("设置"))
        self.quit_action.setText(tr("退出"))
