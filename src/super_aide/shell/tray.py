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


class Tray(QSystemTrayIcon):
    def __init__(self, ctrl, app: QApplication, cfg: Config, open_settings, open_history) -> None:
        super().__init__(orb_icon(), app)
        menu = QMenu()
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        menu.setStyleSheet(MENU_QSS)

        def add(label: str, handler) -> QAction:
            action = QAction(label, menu)
            action.triggered.connect(handler)
            menu.addAction(action)
            return action

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

    def refresh(self, cfg: Config) -> None:
        """快捷键或语言改了以后更新提示和菜单。制表符后面的部分 Qt 会右对齐显示。"""
        self.setToolTip(tr("{app} · {ask} 问答 / {act} 操作", app=app_name(), ask=cfg.hotkey_ask, act=cfg.hotkey_act))
        self.ask_action.setText(f"{tr('问答')}\t{cfg.hotkey_ask}")
        self.act_action.setText(f"{tr('操作')}\t{cfg.hotkey_act}")
        self.history_action.setText(tr("历史记录"))
        self.settings_action.setText(tr("设置"))
        self.quit_action.setText(tr("退出"))
