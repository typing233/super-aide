"""入口：单实例、前置检查（准备窗口）、托盘、全局快捷键、引擎预热、模型发现、自我改进，以及设置的实时生效。"""

from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import winreg
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import __version__, autostart, config, history, hotkeys, i18n, paths, relocate, update
from .launch import SINGLETON, WAKE_EVENT
from .engines import prompts
from .engines.hub import EngineHub
from .evolve.manager import EvolveManager, wait_for_apply, write_health
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
CREATE_NEW_PROCESS_GROUP, SYNCHRONIZE = 0x00000200, 0x00100000
PRUNE_EVERY_MS = 6 * 3600 * 1000  # 会话文件夹的清理：启动时一次，之后每 6 小时（开机自启后常常连着跑好多天）
#: 自己重启自己（换了数据位置）：新的进程带上旧进程的编号，先等它退出，单实例检查才过得去
RESTART_FLAG = "--restart-after"
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]


#: 系统通知认的应用标识。不设的话通知上写的是"来自 Python"、图标也是 Python 的
AUMID = "Typing233.SuperAide"
AUMID_KEY = rf"Software\Classes\AppUserModelId\{AUMID}"


def register_identity() -> None:
    """系统通知的来源写"超级助手"（按界面语言）：给进程设应用标识，并在用户注册表里登记它的名字和图标
    （没有开始菜单快捷方式也认）。换语言时再调一次。卸载时安装器删掉这一项。"""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUMID_KEY) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, app_name())
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(paths.ICON))
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(AUMID))
    except OSError as e:
        log.warning("登记通知用的应用标识失败：%s", e)


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


def _watch_child_exits() -> None:
    """asyncio 在 Windows 上靠系统线程池的等待回调（WT_EXECUTEINWAITTHREAD）得知子进程退出。
    实测（2026-10-09）进程里 UI Automation 的一个内部工作项卡在跨进程 COM 调用上以后，这类回调再也不来了
    （不带这个标志的照常）：子进程退出一个也收不到，Claude SDK 等 `claude -v` 退出时就一直等下去，
    任务停在"正在理解任务…"。改成每个子进程一个守护线程，直接等它的进程句柄。"""
    import _winapi
    from asyncio import windows_events, windows_utils

    def start(self, args, shell, stdin, stdout, stderr, bufsize, **kwargs):
        self._proc = proc = windows_utils.Popen(args, shell=shell, stdin=stdin, stdout=stdout, stderr=stderr,
                                                bufsize=bufsize, **kwargs)
        loop = self._loop

        def wait() -> None:
            _winapi.WaitForSingleObject(int(proc._handle), _winapi.INFINITE)
            try:
                loop.call_soon_threadsafe(lambda: self._process_exited(proc.poll()))
            except RuntimeError:  # 事件循环已经关了
                pass

        threading.Thread(target=wait, name="child-exit", daemon=True).start()

    windows_events._WindowsSubprocessTransport._start = start


def _wait_for_previous(timeout_ms: int = 30000) -> None:
    if RESTART_FLAG not in sys.argv:
        return
    try:
        pid = int(sys.argv[sys.argv.index(RESTART_FLAG) + 1])
    except (IndexError, ValueError):
        return
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if handle:
        kernel32.WaitForSingleObject(handle, timeout_ms)
        kernel32.CloseHandle(handle)


def relaunch() -> None:
    """起一个新的自己（不弹控制台窗口），它等这个进程退出后再起来。"""
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    subprocess.Popen([str(windowless if windowless.exists() else exe), "-m", "super_aide", RESTART_FLAG, str(os.getpid())],
                     creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, close_fds=True)


SYNCED = ".synced.json"
#: 你点了"生效"或"撤销"后，生效的小程序重启我们时带的参数：--evolved <编号> 等
EVOLVE_FLAGS = ("--evolved", "--evolve-failed", "--evolve-undone")


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sync_workspace() -> None:
    """把包里的扩展包模板（共享指令、技能）同步到 ~/.super_aide/workspace。

    记下每个文件上次同步过去的内容：你没改过的文件跟着模板走（升级、自我改进、撤销回旧版本都一样；
    只看时间先后的话，撤销后新内容会一直留着）；你自己改过的不覆盖。还没有记录的文件照旧：模板更新了就覆盖。
    """
    src = paths.WORKSPACE_TEMPLATE
    if not src.exists():
        return
    record = paths.WORKSPACE / SYNCED
    try:
        synced = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        synced = {}
    changed = False
    for path in src.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(src).as_posix()
        target = paths.WORKSPACE / rel
        new = _digest(path)
        if target.exists():
            current = _digest(target)
            if current == new:
                changed |= synced.get(rel) != new
                synced[rel] = new
                continue
            known = synced.get(rel)
            if known is None and path.stat().st_mtime <= target.stat().st_mtime:
                continue
            if known is not None and current != known:
                continue  # 你改过
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        synced[rel], changed = new, True
    if changed:
        try:
            record.write_text(json.dumps(synced, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as e:
            log.warning("记录扩展包的同步状态失败：%s", e)


def _flag(name: str) -> str:
    """命令行里 --evolved <编号> 这样的参数。"""
    args = sys.argv
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else ""


def _single_instance() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, SINGLETON)
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
        self.tray = Tray(self.ctrl, app, cfg, self.open_settings, self.open_history,
                         lambda: self.open_settings("evolve"))
        self.settings: SettingsWindow | None = None  # 第一次打开时再创建
        self.history: HistoryWindow | None = None
        self.setup: SetupWindow | None = None
        #: 刚在准备窗口里配好的引擎 → 你填的模型（空 = 等发现模型时挑一个它的服务确实提供的）
        self.fresh: dict[str, str] = {}
        self.warm_pending = False  # 设置里改了模型：关窗口时再预热，免得每拨一下开关都预热一次
        self.hub.models_found.connect(self._on_models_found)
        # 自我改进：没办好的时候分析、改进自己的代码；改好后通知你，你点"生效"才换包重启
        self.evolve = EvolveManager(cfg, self.hub, self.router, quit_app=app.quit, idle_ui=self._idle_ui)
        self.hub.evolve = self.evolve
        self.ctrl.on_use = self._on_use
        # 本地向量模型闲着时卸掉（召唤时再在后台加载）：常驻内存少约 160MB
        self.embed_timer = QTimer(app)
        self.embed_timer.timeout.connect(self.hub.unload_idle)
        self.embed_timer.start(60_000)
        self.evolve.changed.connect(self._evolve_changed)
        self.evolve.notify.connect(self._evolve_notice)
        self.tray.messageClicked.connect(self._notice_clicked)
        self._notice_target = ""  # 最近一条系统通知是谁发的：自我改进的通知点开就到设置里那一条

    def start(self, announce: bool = False, updated: bool = False, moved: bool = False) -> None:
        failed = self._register_hotkeys(self.cfg)
        if failed:
            self.tray.showMessage(app_name(), tr("快捷键 {keys} 注册失败（可能被其它程序占用），可以在设置里换一个。",
                                                 keys=tr("、").join(failed)), QSystemTrayIcon.Warning, 8000)
        elif moved:
            self.tray.showMessage(tr("数据已经移到新位置"), str(paths.DATA), QSystemTrayIcon.Information, 6000)
        elif announce or updated:
            self.announce(updated=updated)
        threading.Thread(target=relocate.cleanup, name="relocate-cleanup", daemon=True).start()
        try:
            autostart.upgrade()
        except OSError as e:
            log.warning("更新开机自启的命令失败：%s", e)
        self.hub.warm_up()
        self.hub.discover_models()
        self.evolve.start(*(_flag(name) for name in EVOLVE_FLAGS))
        self._prune_later()
        self.prune_timer = QTimer(self.app)
        self.prune_timer.timeout.connect(self._prune_later)
        self.prune_timer.start(PRUNE_EVERY_MS)
        log.info("Super Aide 已启动：%s 问答 / %s 操作", self.cfg.hotkey_ask, self.cfg.hotkey_act)

    def announce(self, again: bool = False, updated: bool = False) -> None:
        """你自己打开 Super Aide 时（开机自启不提示）：它只在托盘里，没有窗口，告诉你它在哪、怎么用。"""
        if updated:
            title = tr("{app}已更新到 {version}", app=app_name(), version=__version__)
        else:
            title = tr("{app}已经在运行", app=app_name()) if again else tr("{app}已在后台运行", app=app_name())
        self._notice_target = ""
        self.tray.showMessage(title, tr("按 {ask} 问答，{act} 操作。右键托盘图标可以打开设置。",
                                        ask=self.cfg.hotkey_ask, act=self.cfg.hotkey_act),
                              QSystemTrayIcon.Information, 6000)

    def restart(self) -> None:
        """换了数据位置：起一个新的自己（它会等这个退出），自己退出。"""
        try:
            relaunch()
        except OSError as e:
            log.warning("没能重启：%s", e)
            return
        log.info("数据位置换好了，重启")
        QTimer.singleShot(300, self.app.quit)

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

    def _prune_later(self) -> None:
        threading.Thread(target=self._prune_sessions, name="prune", daemon=True).start()

    @staticmethod
    def _prune_sessions() -> None:
        cleaned = history.prune()
        if cleaned:
            log.info("清理了 %d 个会话文件夹（%d 天前的只留下问答记录，召唤了没提问的整个删掉）", cleaned, history.KEEP_DAYS)

    def open_history(self) -> None:
        if self.history is None:
            self.history = HistoryWindow(self.ctrl.theme)
        self.history.open()

    def _on_use(self) -> None:
        """你在用助手（召唤、提问）：自我改进挑你空下来的时候做事；本地向量模型不在内存里就先加载。"""
        self.evolve.touched()
        self.hub.prewarm()

    # ---------- 自我改进 ----------

    def _idle_ui(self) -> bool:
        """回答界面收着，设置、历史、准备窗口都没开着。"""
        windows = (self.settings, self.history, self.setup)
        return self.ctrl.view is None and not any(w is not None and w.isVisible() for w in windows)

    def _evolve_changed(self, state: dict) -> None:
        self.tray.set_evolve(state)
        if self.settings is not None:
            self.settings.evolve_changed(state)

    def _evolve_notice(self, title: str, body: str) -> None:
        self._notice_target = "evolve"
        self.tray.showMessage(title, body, QSystemTrayIcon.Information, 10000)

    def _notice_clicked(self) -> None:
        if self._notice_target == "evolve":
            self.open_settings("evolve")

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

    def open_settings(self, section: str = "") -> None:
        if self.settings is None:
            self.settings = SettingsWindow(self)
        self.settings.open(section)

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
        evolve_changed = (new.evolve_enabled, new.evolve_contribute) != (old.evolve_enabled, old.evolve_contribute)
        old.update_from(new)
        self.collector.blocked = {a.lower() for a in old.blocked_apps}
        if routing_changed:
            self.hub.reconfigure()
            self.warm_pending = True
        config.save(old)
        if evolve_changed:
            self.evolve.set_enabled(old.evolve_enabled)
        if language_changed:
            self.apply_language()
        self.tray.refresh(old)
        self.ctrl.panel.call("setTheme", self.ctrl.theme())
        return errors

    def apply_language(self) -> None:
        """设置里换了语言：托盘、回答界面、各个窗口立刻换（设置窗口自己按保存结果重画）。"""
        i18n.set_language(i18n.resolve(self.cfg.language))
        register_identity()  # 系统通知上的名字也跟着换
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
        self.evolve.models_found(result["found"])  # 自我改进看服务到底提供哪些模型（有没有 Opus 5.5）
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
            write_health()  # 你点了"生效"、超级助手重启时：告诉生效的小程序新版本起来了
            return
        if not self.cfg.setup_done:
            self.cfg.setup_done = True  # 本来就都装好、配好了
            config.save(self.cfg)
        self._launch(report)
        write_health()

    def _done(self, result: SetupResult) -> None:
        apply_choices(self.cfg, result)
        self._launch(result.report, result)

    def _launch(self, report: detect.Report, result: SetupResult | None = None) -> None:
        self.aide = SuperAide(self.app, self.cfg, report)
        if result is not None:
            self.aide.adopt_setup(self.window, result)
        self.app.aboutToQuit.connect(self.aide.shutdown)
        # 刚准备完也提示：告诉你怎么用。安装器更新完重新打开时带 --updated；自我改进生效后重启时由它自己提示
        evolving = any(flag in sys.argv for flag in EVOLVE_FLAGS)
        moved = RESTART_FLAG in sys.argv
        self.aide.start(announce=(result is not None or not self.quiet) and not evolving and not moved,
                        updated="--updated" in sys.argv, moved=moved)


def main() -> int:
    paths.ensure()
    _setup_logging()
    _hide_child_consoles()
    _watch_child_exits()
    _wait_for_previous()
    # 引擎再启动的工具服务器靠它认出我们自己的窗口（截图里看不见的胶囊、小窗），动真实鼠标时让点击穿过去
    os.environ["SUPER_AIDE_PID"] = str(os.getpid())
    wait_for_apply()  # 你点了"生效"、正在换包：等它换完再启动（它自己重启我们时不用等）
    if not _single_instance():
        log.info("已经在运行了")
        _wake_running()
        return 0
    _sync_workspace()  # 放在单实例检查之后：已经有一个在运行时，不动它正在用的扩展包
    cfg = config.load()
    i18n.set_language(i18n.resolve(cfg.language))
    register_identity()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Super Aide")
    app.setWindowIcon(orb_icon())

    startup = Startup(app, cfg, quiet=autostart.FLAG in sys.argv)
    startup.run()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
