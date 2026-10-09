"""入口：单实例、前置检查（准备窗口）、托盘、全局快捷键、引擎预热、模型发现，以及设置的实时生效。"""

from __future__ import annotations

import ctypes
import logging
import shutil
import subprocess
import sys
import threading
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import __version__, autostart, config, history, hotkeys, i18n, paths, update
from .engines import prompts
from .engines.hub import EngineHub
from .i18n import app_name, tr
from .router import EngineRouter
from .setup import detect, flow
from .shell.controller import Controller
from .shell.history_window import HistoryWindow
from .shell.settings import SettingsWindow
from .shell.setup_window import SetupResult, SetupWindow
from .shell.tray import Tray, orb_icon
from .snapshot.collector import Collector
from .snapshot.uia import UiaWorker

log = logging.getLogger("super_aide")
ERROR_ALREADY_EXISTS = 183
WAKE_EVENT = "Local\\SuperAideWake"  # 再打开一次时，叫醒正在运行的那个
EVENT_MODIFY_STATE, INFINITE, WAIT_OBJECT_0 = 0x0002, 0xFFFFFFFF, 0
kernel32 = ctypes.windll.kernel32
kernel32.CreateEventW.restype = ctypes.c_void_p
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
kernel32.OpenEventW.restype = ctypes.c_void_p
kernel32.OpenEventW.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_wchar_p]
kernel32.SetEvent.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
kernel32.WaitForSingleObject.restype = ctypes.c_uint
CREATE_NO_WINDOW, CREATE_NEW_CONSOLE, DETACHED_PROCESS = 0x08000000, 0x00000010, 0x00000008


def _has_console() -> bool:
    return bool(ctypes.windll.kernel32.GetConsoleWindow())


def _setup_logging() -> None:
    handler = RotatingFileHandler(paths.LOGS / "super_aide.log", maxBytes=2 * 1024 * 1024,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:  # pythonw（开机自启）下没有 stderr
        root.addHandler(logging.StreamHandler())


def _hide_child_consoles() -> None:
    """没有控制台时（开机自启用 pythonw），两边 SDK 启动的 CLI 和它们再启动的命令行程序
    会各弹出一个黑窗口：统一加上 CREATE_NO_WINDOW。"""
    if _has_console():
        return
    original = subprocess.Popen.__init__

    def init(self, *args, creationflags=0, **kwargs):
        if not creationflags & (CREATE_NEW_CONSOLE | DETACHED_PROCESS):
            creationflags |= CREATE_NO_WINDOW
        original(self, *args, creationflags=creationflags, **kwargs)

    subprocess.Popen.__init__ = init


def _sync_workspace() -> None:
    """把仓库里的扩展包模板（共享指令、技能）同步到 ~/.super_aide/workspace。"""
    src = paths.WORKSPACE_TEMPLATE
    if not src.exists():
        return
    for path in src.rglob("*"):
        if path.is_file():
            target = paths.WORKSPACE / path.relative_to(src)
            if not target.exists() or path.stat().st_mtime > target.stat().st_mtime:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)


def _single_instance() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\SuperAideSingleton")
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def _wake_running() -> None:
    """已经在运行了（比如你又从开始菜单点了一次）：叫醒它，让它提示一下自己在哪。"""
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, WAKE_EVENT)
    if handle:
        kernel32.SetEvent(handle)
        kernel32.CloseHandle(handle)


class Wakeup(QObject):
    """等别的副本来叫醒（Windows 命名事件）。从后台线程发出的信号，Qt 自动排队到主线程。"""

    woken = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.handle = kernel32.CreateEventW(None, False, False, WAKE_EVENT)  # 自动复位：叫一次响一次
        if self.handle:
            threading.Thread(target=self._wait, name="wakeup", daemon=True).start()

    def _wait(self) -> None:
        while kernel32.WaitForSingleObject(self.handle, INFINITE) == WAIT_OBJECT_0:
            self.woken.emit()


def _displays(app: QApplication) -> list[dict]:
    return [{"name": s.name(), "size": [round(s.size().width() * s.devicePixelRatio()),
                                        round(s.size().height() * s.devicePixelRatio())],
             "scale": s.devicePixelRatio(), "primary": s == app.primaryScreen()} for s in app.screens()]


def _routing(cfg: config.Config) -> tuple:
    return config.to_dict(cfg)["engines"], cfg.pin_engine


def apply_choices(cfg: config.Config, result: SetupResult) -> None:
    """准备窗口里的选择落到配置上：要用 DSH 就打开它（只开不关：关掉在设置里），
    你填的模型（填了就只用它，其它的在设置里还能再打开）。"""
    cfg.setup_done = True
    if result.use_dsh:
        cfg.dsh.enabled = True
    for name, model in result.models.items():
        flow.only_model(cfg.engine(name), model)
    config.save(cfg)


class SuperAide:
    """把各部分连起来。设置窗口里的改动经这里落到各部分上，立即生效。"""

    def __init__(self, app: QApplication, cfg: config.Config, report: detect.Report) -> None:
        self.app, self.cfg = app, cfg
        self.collector = Collector(UiaWorker(), cfg.blocked_apps, _displays(app))
        self.router = EngineRouter(cfg)
        self.router.set_ready(report.usable(cfg.dsh.enabled))  # 没配好模型的引擎不参与
        self.hub = EngineHub(self.router, prompts.shared_instructions(), cfg.blocklist_enabled)
        self.ctrl = Controller(cfg, self.collector, self.hub)
        self.hotkeys = hotkeys.HotkeyManager(self.ctrl.on_hotkey)
        app.installNativeEventFilter(self.hotkeys)
        self.tray = Tray(self.ctrl, app, cfg, self.open_settings, self.open_history)
        self.settings: SettingsWindow | None = None  # 第一次打开时再创建
        self.history: HistoryWindow | None = None
        self.setup: SetupWindow | None = None
        #: 刚在准备窗口里配好的引擎 → 你填的模型（空 = 等发现模型时挑一个它的服务确实提供的）
        self.fresh: dict[str, str] = {}
        self.warm_pending = False  # 设置里改了模型：关窗口时再预热，免得每拨一下开关都预热一次
        self.hub.models_found.connect(self._on_models_found)

    def start(self, announce: bool = False, updated: bool = False) -> None:
        failed = self._register_hotkeys(self.cfg)
        if failed:
            self.tray.showMessage(app_name(), tr("快捷键 {keys} 注册失败（可能被其它程序占用），可以在设置里换一个。",
                                                 keys=tr("、").join(failed)), QSystemTrayIcon.Warning, 8000)
        elif announce or updated:
            self.announce(updated=updated)
        try:
            autostart.upgrade()
        except OSError as e:
            log.warning("更新开机自启的命令失败：%s", e)
        self.hub.warm_up()
        self.hub.discover_models()
        threading.Thread(target=self._prune_sessions, name="prune", daemon=True).start()
        log.info("Super Aide 已启动：%s 问答 / %s 操作", self.cfg.hotkey_ask, self.cfg.hotkey_act)

    def announce(self, again: bool = False, updated: bool = False) -> None:
        """你自己打开 Super Aide 时（开机自启不提示）：它只在托盘里，没有窗口，告诉你它在哪、怎么用。"""
        if updated:
            title = tr("{app}已更新到 {version}", app=app_name(), version=__version__)
        else:
            title = tr("{app}已经在运行", app=app_name()) if again else tr("{app}已在后台运行", app=app_name())
        self.tray.showMessage(title, tr("按 {ask} 问答，{act} 操作。右键托盘图标可以打开设置。",
                                        ask=self.cfg.hotkey_ask, act=self.cfg.hotkey_act),
                              QSystemTrayIcon.Information, 6000)

    def apply_update(self, release: update.Release | None) -> str:
        """设置里点了更新：交给安装器（它等 Super Aide 退出后再装），自己退出。返回没能开始的原因。"""
        try:
            update.start_update(release)
        except (update.UpdateError, OSError) as e:
            log.warning("没能开始更新：%s", e)
            return str(e)
        log.info("开始更新到 %s，先退出", release.version if release else "最新版本")
        QTimer.singleShot(300, self.app.quit)
        return ""

    def shutdown(self) -> None:
        self.hotkeys.unregister_all()
        self.ctrl.esc.stop()
        self.hub.shutdown()
        self.collector.close()

    @staticmethod
    def _prune_sessions() -> None:
        cleaned = history.prune()
        if cleaned:
            log.info("清理了 %d 个 %d 天前的会话（只留下问答记录）", cleaned, history.KEEP_DAYS)

    def open_history(self) -> None:
        if self.history is None:
            self.history = HistoryWindow(self.ctrl.theme)
        self.history.open()

    # ---------- 快捷键 ----------

    def _register_hotkeys(self, cfg: config.Config) -> list[str]:
        """按 cfg 重新注册，返回没注册上的。"""
        self.hotkeys.unregister_all()
        failed = []
        for name, spec in (("ask", cfg.hotkey_ask), ("act", cfg.hotkey_act)):
            try:
                if not self.hotkeys.register(name, spec):
                    failed.append(spec)
            except ValueError as e:
                failed.append(tr("{spec}（{reason}）", spec=spec, reason=e))
        return failed

    def check_hotkey(self, spec: str) -> str:
        try:
            return "" if self.hotkeys.available(spec) else tr("已被其它程序占用")
        except ValueError as e:
            return str(e)

    def pause_hotkeys(self) -> None:
        """设置里录新快捷键时先放开，不然按下现在的快捷键会直接召唤出界面。"""
        self.hotkeys.unregister_all()

    def resume_hotkeys(self) -> None:
        if not self.hotkeys.active:
            self._register_hotkeys(self.cfg)

    # ---------- 设置 ----------

    def open_settings(self) -> None:
        if self.settings is None:
            self.settings = SettingsWindow(self)
        self.settings.open()

    def resolved_theme(self) -> str:
        return self.ctrl.theme()

    def apply_settings(self, new: config.Config) -> list[str]:
        """返回没能生效的项。快捷键注册不上时保留原来的。"""
        errors = []
        old = self.cfg
        if (new.hotkey_ask, new.hotkey_act) != (old.hotkey_ask, old.hotkey_act) or not self.hotkeys.active:
            failed = self._register_hotkeys(new)
            if failed:
                errors.append(tr("快捷键 {keys} 注册不上（可能被其它程序占用），还用原来的", keys=tr("、").join(failed)))
                new.hotkey_ask, new.hotkey_act = old.hotkey_ask, old.hotkey_act
                self._register_hotkeys(old)
        routing_changed = _routing(new) != _routing(old)
        language_changed = new.language != old.language
        old.update_from(new)
        self.collector.blocked = {a.lower() for a in old.blocked_apps}
        if routing_changed:
            self.hub.reconfigure()
            self.warm_pending = True
        config.save(old)
        if language_changed:
            self.apply_language()
        self.tray.refresh(old)
        self.ctrl.panel.call("setTheme", self.ctrl.theme())
        return errors

    def apply_language(self) -> None:
        """设置里换了语言：托盘、回答界面、各个窗口立刻换（设置窗口自己按保存结果重画）。"""
        i18n.set_language(i18n.resolve(self.cfg.language))
        self.ctrl.panel.call("setLang", i18n.lang())
        for window in (self.settings, self.history, self.setup):
            if window is not None:
                window.retitle()
        if self.history is not None and self.history.isVisible():
            self.history.reopened()
        if self.setup is not None:
            self.setup.rescan()  # 检查结果里的说明是按当时的语言写的：重新查一遍

    def settings_closed(self) -> None:
        self.resume_hotkeys()  # 正在录快捷键时关掉窗口，也要把快捷键恢复
        if self.warm_pending:
            self.warm_pending = False
            self.hub.warm_up()

    def refresh_models(self) -> None:
        self.hub.discover_models()

    def _on_models_found(self, result: dict) -> None:
        added, fitted = 0, False
        for name, ids in result["found"].items():
            engine = self.cfg.engine(name)
            added += engine.merge_discovered(ids)
            if name in self.fresh:
                fitted |= flow.fit_models(engine, name, ids, self.fresh.pop(name))
        if added or fitted:
            config.save(self.cfg)
            log.info("发现 %d 个新模型，已加入配置（默认关闭）", added)
        if fitted:
            self.hub.reconfigure()
            self.hub.warm_up()
            if self.settings is not None and self.settings.isVisible():
                self.settings.reopened()
        if self.settings is not None:
            self.settings.models_refreshed({"added": added, "errors": result["errors"]})

    # ---------- 准备窗口（环境检查） ----------

    def adopt_setup(self, window: SetupWindow, result: SetupResult) -> None:
        """第一次启动时的准备窗口：以后在设置里再打开的就是它。"""
        self.setup = window
        window.on_done, window.on_quit = self.apply_setup, None
        self.fresh.update({name: result.models.get(name, "") for name in result.fresh})

    def open_setup(self) -> None:
        if self.setup is None:
            self.setup = SetupWindow(self.cfg, detect.scan(), first_run=False, on_done=self.apply_setup)
        else:
            self.setup.show_again()

    def apply_setup(self, result: SetupResult) -> None:
        """准备窗口点了完成（或关掉）：路由只用配好的引擎；改过登录或服务地址的引擎按新配置重连、重新发现模型。
        什么都没变就到此为止。"""
        before = (self.cfg.dsh.enabled, set(self.router.ready or ()))
        apply_choices(self.cfg, result)
        ready = result.report.usable(self.cfg.dsh.enabled)
        if not result.fresh and before == (self.cfg.dsh.enabled, set(ready)):
            return
        self.fresh.update({name: result.models.get(name, "") for name in result.fresh})
        self.hub.reconfigure(ready=ready)
        if result.fresh:
            self.hub.refresh(result.fresh)
        self.hub.warm_up()
        self.hub.discover_models()
        if self.settings is not None and self.settings.isVisible():
            self.settings.reopened()


class Startup:
    """先过准备窗口（需要时：第一次启动，或者一个能用的引擎都没有），再启动 Super Aide。"""

    def __init__(self, app: QApplication, cfg: config.Config, quiet: bool = False) -> None:
        self.app, self.cfg = app, cfg
        self.quiet = quiet  # 开机自启：不提示
        self.aide: SuperAide | None = None
        self.window: SetupWindow | None = None
        self.wakeup = Wakeup()
        self.wakeup.woken.connect(self._woken)

    def _woken(self) -> None:
        """又打开了一次：准备窗口开着就把它叫到前面，否则提示一下在后台运行。"""
        if self.window is not None and (self.aide is None or self.window.isVisible()):
            self.window.open()
        elif self.aide is not None:
            self.aide.announce(again=True)

    def run(self) -> None:
        report = detect.scan()
        if flow.needs_setup(report, self.cfg.dsh.enabled, self.cfg.setup_done):
            log.info("先做准备：%s", "；".join(f"{t.title}{'' if t.installed else '没装'}"
                                             f"{'' if t.configured or not t.installed else '没配模型'}"
                                             for t in (report.claude, report.codex, report.dsh)))
            self.window = SetupWindow(self.cfg, report, first_run=True, on_done=self._done, on_quit=self.app.quit)
            return
        if not self.cfg.setup_done:
            self.cfg.setup_done = True  # 本来就都装好、配好了
            config.save(self.cfg)
        self._launch(report)

    def _done(self, result: SetupResult) -> None:
        apply_choices(self.cfg, result)
        self._launch(result.report, result)

    def _launch(self, report: detect.Report, result: SetupResult | None = None) -> None:
        self.aide = SuperAide(self.app, self.cfg, report)
        if result is not None:
            self.aide.adopt_setup(self.window, result)
        self.app.aboutToQuit.connect(self.aide.shutdown)
        # 刚准备完也提示：告诉你怎么用。安装器更新完重新打开时带 --updated
        self.aide.start(announce=result is not None or not self.quiet, updated="--updated" in sys.argv)


def main() -> int:
    paths.ensure()
    _setup_logging()
    _hide_child_consoles()
    _sync_workspace()
    if not _single_instance():
        log.info("已经在运行了")
        _wake_running()
        return 0
    cfg = config.load()
    i18n.set_language(i18n.resolve(cfg.language))

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Super Aide")
    app.setWindowIcon(orb_icon())

    startup = Startup(app, cfg, quiet=autostart.FLAG in sys.argv)
    startup.run()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
