"""历史记录窗口：按时间列出以前的问答，可以搜索、看完整回答、复制、打开会话文件夹。"""

from __future__ import annotations

import json

from PySide6.QtCore import QUrl, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication

from .. import history, i18n, paths
from ..i18n import app_name, tr
from .webwindow import WebWindow, WindowBridge

HISTORY_PAGE = paths.UI_INDEX.with_name("history.html")


class HistoryBridge(WindowBridge):
    def __init__(self, window: HistoryWindow, theme) -> None:
        super().__init__(window)
        self.theme = theme

    @Slot(str, result=str)
    def list(self, query: str) -> str:
        return json.dumps({"theme": self.theme(), "lang": i18n.lang(), "items": history.summaries(query)},
                          ensure_ascii=False)

    @Slot(str, result=str)
    def load(self, session_id: str) -> str:
        return json.dumps(history.load(session_id), ensure_ascii=False)

    @Slot(str, result=str)
    def remove(self, ids: str) -> str:
        """删掉选中的会话（可以撤销），返回真删掉了哪些。"""
        return json.dumps(history.delete(json.loads(ids or "[]")))

    @Slot(str, result=str)
    def restore(self, ids: str) -> str:
        return json.dumps(history.restore(json.loads(ids or "[]")))

    @Slot(int)
    def purge(self, seconds: int) -> None:
        """撤销的提示消失了：删了超过这么多秒的真删掉。"""
        history.empty_trash(seconds)

    @Slot(str)
    def copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    @Slot(str)
    def openFolder(self, session_id: str) -> None:  # noqa: N802 - JS 侧的命名
        folder = history.folder(session_id)
        if folder is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    @Slot(str)
    def openUrl(self, url: str) -> None:  # noqa: N802
        if url.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(url))


class HistoryWindow(WebWindow):
    def __init__(self, theme) -> None:
        super().__init__(tr("{app}历史记录", app=app_name()), (980, 720))
        self.load_page(HISTORY_PAGE, HistoryBridge(self, theme))

    def retitle(self) -> None:
        self.setWindowTitle(tr("{app}历史记录", app=app_name()))

    def reopened(self) -> None:
        self.js("window.historyView && historyView.reload()")
