"""设置窗口：和其它界面同一套视觉规范的网页窗口。改动即时生效，不用点保存。"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QFileDialog

from .. import __version__, autostart, config, i18n, paths, relocate, update
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
    def restart(self) -> None: ...

    evolve: object  # EvolveManager


class SettingsBridge(WindowBridge):
    """网页通过 QWebChannel 调用这些槽。"""

    update_checked = Signal(dict)  # 后台线程查完更新 → 主线程交给网页
    data_moved = Signal(dict)  # 换数据位置：后台线程的进度（done/total）、出错（error）、搬完（finished）

    def __init__(self, host: SettingsHost, window: WebWindow | None) -> None:
        super().__init__(window)
        self.host = host
        self._tools: dict = {}  # 打开窗口时查一次装没装、配没配（每拨一下开关都查就太慢了）
        self._release: update.Release | None = None  # 最近一次查到的新版本
        self._checking = False
        self._moving = False

    def _state(self) -> dict:
        data = config.to_dict(self.host.cfg)
        data["autostart"] = autostart.is_enabled()
        data["resolved_theme"] = self.host.resolved_theme()
        # 浏览器操作：只有用 Codex 官方账号时要接通它的 Chrome 插件（自研的直接能操作）。没接通时设置里才显示修法
        status = browser_use.status() if computer.official_codex() else browser_use.Status(True)
        data["browser"] = {"ready": status.ready, "problem": status.problem}
        data["tools"] = self._tools
        data["version"] = __version__
        data["lang"] = i18n.lang()
        data["data_dir"] = str(paths.DATA)
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

    # ---- 数据位置 ----

    @Slot(result=str)
    def chooseDataDir(self) -> str:  # noqa: N802
        """选文件夹（系统的选择框）。返回要搬去的地方、现在有多少数据、不能搬的原因；没选就是 {}。"""
        chosen = QFileDialog.getExistingDirectory(self.window, tr("选择数据位置"), str(paths.DATA.parent))
        if not chosen:
            return "{}"
        target = relocate.target_for(Path(chosen))
        total = relocate.size()
        return json.dumps({"target": str(target), "size": relocate.human(total), "problem": relocate.problem(target, total)},
                          ensure_ascii=False)

    @Slot(str, result=str)
    def moveData(self, target: str) -> str:  # noqa: N802
        """复制过去（后台，进度由 data_moved 交给网页），记下新位置，重启。返回没能开始的原因。"""
        if self._moving:
            return ""
        path = Path(target)
        problem = relocate.problem(path, relocate.size())
        if problem:
            return problem
        self._moving = True
        last = [-1]

        def progress(done: int, total: int) -> None:
            percent = done * 100 // max(total, 1)
            if percent != last[0]:  # 一个百分点报一次，不是每个文件都报
                last[0] = percent
                self.data_moved.emit({"percent": percent})

        def run() -> None:
            try:
                relocate.copy(path, progress)
                relocate.commit(path)
            except OSError as e:
                log.warning("换数据位置失败：%s", e)
                self._moving = False
                self.data_moved.emit({"error": tr("没能搬过去：{error}", error=e)})
                return
            log.info("数据复制到了 %s", path)
            self.data_moved.emit({"finished": True})

        threading.Thread(target=run, name="relocate", daemon=True).start()
        return ""

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

    @Slot(str)
    def evolveCancel(self, job_id: str) -> None:  # noqa: N802
        """正在做或排着的改进不要了。"""
        self.host.evolve.cancel(job_id)

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
        bridge.data_moved.connect(self._data_moved)
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

    def _data_moved(self, result: dict) -> None:
        self._js(f"settings.dataMoved({json.dumps(result, ensure_ascii=False)})")
        if result.get("finished"):
            self.host.restart()  # 新位置下次启动起生效：重启，新的进程起来后删掉旧的那份

    def models_refreshed(self, result: dict) -> None:
        if self.isVisible():
            self._js(f"settings.modelsRefreshed({json.dumps(result, ensure_ascii=False)})")

    def hideEvent(self, event) -> None:  # noqa: N802
        self._js("settings.stopRecording()")
        self.host.settings_closed()
        super().hideEvent(event)
