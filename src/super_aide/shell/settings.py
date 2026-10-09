"""设置窗口：和其它界面同一套视觉规范的网页窗口。改动即时生效，不用点保存。"""

from __future__ import annotations

import json
import logging
import threading
from typing import Protocol

from PySide6.QtCore import QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication

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

    evolve: object  # EvolveManager


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
        data["evolve_state"] = self.host.evolve.snapshot()  # 进度和记录（data["evolve"] 是配置：开关、社区共建）
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

    # ---- 自我改进 ----

    @Slot(str, result=str)
    def suggest(self, text: str) -> str:
        return json.dumps(self.host.evolve.suggest(text), ensure_ascii=False)

    @Slot(str, result=str)
    def evolveDiff(self, job_id: str) -> str:  # noqa: N802
        return self.host.evolve.diff(job_id)

    @Slot(str, result=str)
    def evolveApply(self, job_id: str) -> str:  # noqa: N802
        """你点了"生效"：换包、重启（超级助手会先退出）。返回没能开始的原因。"""
        return self.host.evolve.apply(job_id)

    @Slot(str, result=str)
    def evolveUndo(self, job_id: str) -> str:  # noqa: N802
        return self.host.evolve.undo(job_id)

    @Slot(str)
    def evolveDiscard(self, job_id: str) -> None:  # noqa: N802
        self.host.evolve.discard(job_id)

    @Slot(str, bool)
    def privacyDecision(self, job_id: str, submit: bool) -> None:  # noqa: N802
        self.host.evolve.privacy_decision(job_id, submit)

    @Slot()
    def githubLogin(self) -> None:  # noqa: N802
        self.host.evolve.login_start()

    @Slot()
    def githubCancel(self) -> None:  # noqa: N802
        self.host.evolve.login_cancel()

    @Slot()
    def githubLogout(self) -> None:  # noqa: N802
        self.host.evolve.logout()

    @Slot()
    def communityCheck(self) -> None:  # noqa: N802
        self.host.hub._submit(self.host.evolve.review_community())

    @Slot(int, result=str)
    def communityMerge(self, number: int) -> str:  # noqa: N802
        return self.host.evolve.merge_community(number)

    @Slot(str)
    def openUrl(self, url: str) -> None:  # noqa: N802
        if url.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(url))

    @Slot(str)
    def copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)


class SettingsWindow(WebWindow):
    def __init__(self, host: SettingsHost) -> None:
        super().__init__(tr("{app}设置", app=app_name()), (720, 820))
        self.host = host
        bridge = SettingsBridge(host, self)
        bridge.update_checked.connect(self._update_checked)
        self.load_page(SETTINGS_PAGE, bridge)

    def _js(self, code: str) -> None:
        self.js(f"window.settings && {code}")

    def open(self, section: str = "") -> None:
        """section：打开后滚到哪一节（托盘里点"正在自我改进"时是 evolve）。"""
        if section:
            self._js(f"settings.focusSection({json.dumps(section)})")
            self.pending_section = section
        self.host.evolve.check_contributor()  # 装了 gh 并登录过：顺手看看是不是维护者
        super().open()

    def _on_rendered(self) -> None:
        super()._on_rendered()
        section = getattr(self, "pending_section", "")
        if section:
            self._js(f"settings.focusSection({json.dumps(section)})")
            self.pending_section = ""

    def evolve_changed(self, state: dict) -> None:
        if self.isVisible():
            self._js(f"settings.evolveChanged({json.dumps(state, ensure_ascii=False)})")

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
