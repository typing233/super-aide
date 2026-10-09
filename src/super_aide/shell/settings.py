"""设置窗口：和其它界面同一套视觉规范的网页窗口。改动即时生效，不用点保存。"""

from __future__ import annotations

import json
import logging
import threading
from typing import Protocol

from PySide6.QtCore import QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from .. import __version__, autostart, config, i18n, paths, update
from ..i18n import app_name, tr
from ..engines import browser_use, computer
from ..setup import detect
from .webwindow import WebWindow, WindowBridge

log = logging.getLogger(__name__)

SETTINGS_PAGE = paths.UI_INDEX.with_name("settings.html")


class SettingsHost(Protocol):
    cfg: config.Config

    def apply_settings(self, new: config.Config) -> list[str]: ...
    def check_hotkey(self, spec: str) -> str: ...
    def pause_hotkeys(self) -> None: ...
    def resume_hotkeys(self) -> None: ...
    def refresh_models(self) -> None: ...
    def resolved_theme(self) -> str: ...
    def settings_closed(self) -> None: ...
    def open_setup(self) -> None: ...
    def apply_update(self, release: update.Release | None) -> str: ...


class SettingsBridge(WindowBridge):
    """网页通过 QWebChannel 调用这些槽。"""

    update_checked = Signal(dict)  # 后台线程查完更新 → 主线程交给网页

    def __init__(self, host: SettingsHost, window: WebWindow | None) -> None:
        super().__init__(window)
        self.host = host
        self._tools: dict = {}  # 打开窗口时查一次装没装、配没配（每拨一下开关都查就太慢了）
        self._release: update.Release | None = None  # 最近一次查到的新版本
        self._checking = False

    def _state(self) -> dict:
        data = config.to_dict(self.host.cfg)
        data["autostart"] = autostart.is_enabled()
        data["resolved_theme"] = self.host.resolved_theme()
        official = computer.official_codex()
        status = browser_use.status() if official else browser_use.Status(True)
        data["browser"] = {"ready": status.ready, "problem": status.problem, "official": official}
        data["tools"] = self._tools
        data["version"] = __version__
        data["lang"] = i18n.lang()
        return data

    @Slot(result=str)
    def load(self) -> str:
        report = detect.scan()
        self._tools = {name: {"installed": t.installed, "configured": t.configured, "detail": t.detail}
                       for name, t in ((n, report.tool(n)) for n in detect.TOOLS)}
        return json.dumps(self._state(), ensure_ascii=False)

    @Slot(str, result=str)
    def save(self, payload: str) -> str:
        try:
            new = config.from_dict(json.loads(payload))
        except (KeyError, TypeError, ValueError) as e:
            return json.dumps({"errors": [tr("设置有误：{error}", error=e)], "data": self._state()}, ensure_ascii=False)
        errors = self.host.apply_settings(new)
        return json.dumps({"errors": errors, "data": self._state()}, ensure_ascii=False)

    @Slot(str, result=str)
    def checkHotkey(self, spec: str) -> str:  # noqa: N802 - JS 侧的命名
        return self.host.check_hotkey(spec)

    @Slot()
    def pauseHotkeys(self) -> None:  # noqa: N802
        self.host.pause_hotkeys()

    @Slot()
    def resumeHotkeys(self) -> None:  # noqa: N802
        self.host.resume_hotkeys()

    @Slot(bool, result=str)
    def setAutostart(self, on: bool) -> str:  # noqa: N802
        try:
            autostart.set_enabled(on)
            return ""
        except OSError as e:
            log.warning("开机自启设置失败：%s", e)
            return tr("没能设置开机自启：{error}", error=e)

    @Slot()
    def refreshModels(self) -> None:  # noqa: N802
        self.host.refresh_models()

    @Slot()
    def openConfig(self) -> None:  # noqa: N802
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.CONFIG)))

    @Slot()
    def openSetup(self) -> None:  # noqa: N802
        self.host.open_setup()

    @Slot()
    def checkUpdate(self) -> None:  # noqa: N802
        """查更新要联网（几秒）：放在后台，查完由 update_checked 交回网页。"""
        if self._checking:
            return
        self._checking = True

        def run() -> None:
            result = update.check()
            self._release = result.release if result.newer else None
            self._checking = False
            self.update_checked.emit(result.as_dict())

        threading.Thread(target=run, name="update-check", daemon=True).start()

    @Slot(result=str)
    def applyUpdate(self) -> str:  # noqa: N802
        return self.host.apply_update(self._release)


class SettingsWindow(WebWindow):
    def __init__(self, host: SettingsHost) -> None:
        super().__init__(tr("{app}设置", app=app_name()), (720, 820))
        self.host = host
        bridge = SettingsBridge(host, self)
        bridge.update_checked.connect(self._update_checked)
        self.load_page(SETTINGS_PAGE, bridge)

    def _js(self, code: str) -> None:
        self.js(f"window.settings && {code}")

    def reopened(self) -> None:
        self._js("settings.reload()")

    def retitle(self) -> None:
        self.setWindowTitle(tr("{app}设置", app=app_name()))

    def _update_checked(self, result: dict) -> None:
        self._js(f"settings.updateChecked({json.dumps(result, ensure_ascii=False)})")

    def models_refreshed(self, result: dict) -> None:
        if self.isVisible():
            self._js(f"settings.modelsRefreshed({json.dumps(result, ensure_ascii=False)})")

    def hideEvent(self, event) -> None:  # noqa: N802
        self._js("settings.stopRecording()")
        self.host.settings_closed()
        super().hideEvent(event)
