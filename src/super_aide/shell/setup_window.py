"""准备窗口：开始用之前的前置检查（流程见 setup/flow.py）。第一次启动、或者一个能用的引擎都没有时自动打开；
设置里也能随时再打开（"环境检查"）。

和设置窗口同一套视觉规范。状态都在这里（检查结果、安装进度、等待登录的工具），网页只负责显示。
慢的事（检查、安装、测试连接）放在后台线程里做，做完经信号回到主线程再刷新网页。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QTimer, Signal, Slot
from PySide6.QtGui import QShortcut

from .. import config, i18n, paths
from ..i18n import app_name, tr
from ..setup import configure, detect, flow
from ..setup import install as installer
from .controller import windows_theme
from .webwindow import WebWindow, WindowBridge

log = logging.getLogger(__name__)

SETUP_PAGE = paths.UI_INDEX.with_name("setup.html")
MANUAL = {"claude": "npm i -g @anthropic-ai/claude-code", "codex": "npm i -g @openai/codex"}
POLL_MS = 2500
LOGIN_WAIT_S = 15 * 60  # 打开登录窗口后最多等这么久（一直检查有没有登录好）


@dataclass
class SetupResult:
    report: detect.Report
    use_dsh: bool
    fresh: set[str] = field(default_factory=set)        # 这次新配好模型的引擎
    models: dict[str, str] = field(default_factory=dict)  # 你在自定义服务地址里填的模型


class SetupBridge(WindowBridge):
    """网页通过 QWebChannel 调用这些槽。"""

    def __init__(self, window: SetupWindow) -> None:
        super().__init__(window)
        self.w = window

    @Slot(result=str)
    def load(self) -> str:
        return json.dumps(self.w.state(), ensure_ascii=False)

    @Slot(str)
    def install(self, tools: str) -> None:
        self.w.install(json.loads(tools))

    @Slot()
    def chooseDsh(self) -> None:  # noqa: N802 - JS 侧的命名
        self.w.choose_dsh()

    @Slot(str)
    def login(self, tool: str) -> None:
        self.w.login(tool)

    @Slot(str, str, str, str)
    def saveCustom(self, tool: str, base: str, key: str, model: str) -> None:  # noqa: N802
        self.w.save_custom(tool, base, key, model)

    @Slot()
    def recheck(self) -> None:
        self.w.rescan()

    @Slot()
    def finish(self) -> None:
        self.w.finish()

    @Slot()
    def close(self) -> None:
        self.w.dismiss()


class SetupWindow(WebWindow):
    scanned = Signal(object)       # detect.Report，后台线程 → 主线程
    progressed = Signal(str, str)  # (工具, 一行状态)
    installed = Signal(dict)       # {工具: 没装上的原因}
    checked = Signal(str, dict)    # (工具, {ok, message, model})

    def __init__(self, cfg: config.Config, report: detect.Report, first_run: bool,
                 on_done: Callable[[SetupResult], None], on_quit: Callable[[], None] | None = None) -> None:
        super().__init__(tr("准备{app}", app=app_name()), (720, 680))
        self.cfg, self.report, self.first_run = cfg, report, first_run
        self.on_done, self.on_quit = on_done, on_quit
        self.busy: dict[str, str] = {}      # 正在安装：工具 → 一行进度
        self.errors: dict[str, str] = {}    # 没装上：工具 → 原因
        self.waiting: dict[str, float] = {}  # 打开了登录窗口、还没登录好：工具 → 等到什么时候
        self.chose_dsh = False   # 你选了"先只用 DSH"
        self.decided = False     # 已经回答过"要不要装"
        self.fresh: set[str] = set()
        self.models: dict[str, str] = {}
        self.note = ""
        self.done = False
        self._scanning = False
        self._auto_started = False
        self.poll = QTimer(self, interval=POLL_MS, timeout=self.rescan)
        self.scanned.connect(self._on_scanned)
        self.progressed.connect(self._on_progress)
        self.installed.connect(self._on_installed)
        self.checked.connect(self._on_checked)
        for shortcut in self.findChildren(QShortcut):  # Ctrl+W 也按"关闭"处理（第一次准备时关掉就是退出）
            shortcut.activated.disconnect()
            shortcut.activated.connect(self.dismiss)
        bridge = SetupBridge(self)
        self.load_page(SETUP_PAGE, bridge)
        bridge.page_rendered.connect(self._auto_install)  # 接在显示窗口之后：那时网页已经能接收刷新

    # ---------- 状态 ----------

    def _use_dsh(self) -> bool:
        return flow.use_dsh(self.report, self.chose_dsh, self.cfg.dsh.enabled)

    def can_start(self) -> bool:
        return flow.can_start(self.report, self.chose_dsh, self.cfg.dsh.enabled)

    def state(self) -> dict:
        return {
            "first_run": self.first_run,
            "lang": i18n.lang(),
            "resolved_theme": self.cfg.theme if self.cfg.theme in ("light", "dark") else windows_theme(),
            "tools": self.report.as_dict(),
            "busy": self.busy,
            "errors": self.errors,
            "waiting": [t for t in self.waiting if not self.report.tool(t).configured],
            "manual": MANUAL,
            "ask": flow.should_ask(self.report, self.decided) and not self.busy,
            "use_dsh": self._use_dsh(),
            "can_start": self.can_start(),
            "note": self.note,
        }

    def push(self) -> None:
        if self.loaded:
            self.js(f"window.setup && setup.update({json.dumps(self.state(), ensure_ascii=False)})")

    def retitle(self) -> None:
        self.setWindowTitle(tr("准备{app}", app=app_name()))

    def reopened(self) -> None:
        self.note = ""
        if self.waiting:
            self.poll.start()
        self.rescan()

    # ---------- 检查 ----------

    def rescan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        threading.Thread(target=lambda: self.scanned.emit(detect.scan()), name="setup-scan", daemon=True).start()

    def _on_scanned(self, report: detect.Report) -> None:  # noqa: C901
        self._scanning = False
        self.report = report
        now = time.monotonic()
        for tool, deadline in list(self.waiting.items()):
            if report.tool(tool).configured:
                self.waiting.pop(tool)
                self.fresh.add(tool)
                log.info("%s 登录好了", detect.NAMES[tool])
            elif now > deadline:
                self.waiting.pop(tool)
        if not self.waiting:
            self.poll.stop()
        self.push()

    def changeEvent(self, event) -> None:  # noqa: N802
        """从浏览器或命令行窗口切回来时再查一次：可能刚登录好。"""
        if event.type() == QEvent.ActivationChange and self.isActiveWindow() and self.loaded:
            self.rescan()
        super().changeEvent(event)

    # ---------- 安装 ----------

    def _auto_install(self) -> None:
        """第一次画好以后：没有 DSH 时，缺的 Claude Code / Codex 直接开始装。"""
        if not self._auto_started:
            self._auto_started = True
            self.install(flow.auto_install(self.report))

    def install(self, tools: list[str]) -> None:
        tools = [t for t in tools if t in installer.PACKAGES and t not in self.busy]
        if not tools:
            return
        self.decided = True
        for tool in tools:
            self.busy[tool] = tr("准备安装…")
            self.errors.pop(tool, None)
        self.push()
        threading.Thread(target=self._install_worker, args=(tools,), name="setup-install", daemon=True).start()

    def _install_worker(self, tools: list[str]) -> None:
        try:
            result = installer.install(tools, self.progressed.emit)
        except Exception as e:  # noqa: BLE001 - 安装出了意外也要让界面知道
            log.exception("安装失败")
            result = {tool: tr("没装上：{error}", error=e) for tool in tools}
        self.installed.emit(result)

    def _on_progress(self, tool: str, text: str) -> None:
        if tool in self.busy:
            self.busy[tool] = text
            self.push()

    def _on_installed(self, result: dict) -> None:
        for tool, error in result.items():
            self.busy.pop(tool, None)
            if error:
                self.errors[tool] = error
                log.warning("%s %s", detect.NAMES[tool], error)
            else:
                log.info("%s 装好了", detect.NAMES[tool])
        self.rescan()

    def choose_dsh(self) -> None:
        self.chose_dsh = self.decided = True
        self.push()

    # ---------- 配置模型 ----------

    def login(self, tool: str) -> None:
        try:
            if tool == "dsh":
                configure.open_dsh_login(self.report)
            else:
                configure.open_login(tool, self.report)
        except (OSError, ValueError, configure.ConfigError) as e:
            self.note = tr("没能打开登录窗口：{error}", error=e)
            self.push()
            return
        self.note = ""
        self.waiting[tool] = time.monotonic() + LOGIN_WAIT_S
        self.poll.start()
        self.push()

    def save_custom(self, tool: str, base: str, key: str, model: str) -> None:
        threading.Thread(target=self._save_worker, args=(tool, base, key, model),
                         name="setup-save", daemon=True).start()

    def _save_worker(self, tool: str, base: str, key: str, model: str) -> None:
        result = configure.check(tool, base, key, model)
        used = model.strip()
        message = result.message
        if result.ok:
            try:
                used, replaced = configure.save(tool, base, key, model, offered=result.models if result.verified else [])
                # 写明"已保存"：原来成功了也只显示一句"连上了，但没法提前确认密钥"，读起来像没生效
                message = tr("已保存 · {detail}", detail=result.message)
                if replaced:
                    message += tr("；默认模型换成了 {model}（这个服务没有原来的 {old}）", model=used, old=replaced)
                elif not result.verified and tool != "dsh":
                    message += tr("；用的时候出错，再回来检查密钥")
            except (configure.ConfigError, OSError) as e:
                result, message = configure.Check(False, str(e)), str(e)
        self.checked.emit(tool, {"ok": result.ok, "message": message, "model": used})

    def _on_checked(self, tool: str, result: dict) -> None:
        if result["ok"]:
            self.fresh.add(tool)
            self.waiting.pop(tool, None)
            if result["model"]:
                self.models[tool] = result["model"]
            log.info("%s 改用自定义服务地址", detect.NAMES[tool])
        self.js(f"window.setup && setup.saved({json.dumps(tool)}, {json.dumps(result, ensure_ascii=False)})")
        self.rescan()

    # ---------- 结束 ----------

    def finish(self) -> None:
        if not self.can_start():
            return
        self.done = True
        self.poll.stop()
        result = SetupResult(self.report, self._use_dsh(), set(self.fresh), dict(self.models))
        self.fresh.clear()
        self.models.clear()
        self.hide()
        self.on_done(result)

    def dismiss(self) -> None:
        """关窗口：能用了就当"开始使用"；第一次准备、一个能用的引擎都没有时，关掉就是退出。"""
        if self.can_start():
            self.finish()
            return
        self.poll.stop()
        self.hide()
        if self.first_run and not self.done and self.on_quit is not None:
            self.on_quit()

    def closeEvent(self, event) -> None:  # noqa: N802
        """你按 Alt+F4：当"关闭"处理。程序退出时发来的关闭照常放行（Qt 6 里窗口拒绝关闭会拦住退出）。"""
        if event.spontaneous() and self.isVisible():
            event.ignore()
            self.dismiss()
        else:
            super().closeEvent(event)

    def show_again(self) -> None:
        """设置里再次打开：不再是第一次准备。"""
        self.first_run = False
        self.done = False
        self.open()
