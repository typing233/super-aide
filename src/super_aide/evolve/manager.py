"""自我改进的调度：排队、一步步往下做、中断了续上、你确认后生效、撤销、社区共建。

- 任务跑在引擎中枢的事件循环上（和回答问题的会话同一个线程，都是异步的）；跑测试、复制、打包这些要等的活放进线程池。
- 分析、改代码、测试、复核全自动；改好以后通知你，**你点了"生效"才换包重启**（不自己改了自己装）。
- 同一时间只做一个任务（包括生效：上一个你确认生效或者不要了，下一个才开始）。只在你没在用助手时开始或续上；
  前台被限流时让出 30 分钟。
- 每一步都落盘。断网：等网络（退避重试），通了续上同一个会话；要登录：每小时再试；关机、退出：下次启动接着做。
- 状态和进度通过 changed 信号交给托盘和设置；开始、完成、回滚时通过 notify 弹系统通知。
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .. import __version__, paths, update
from ..engines.claude import claude_env
from ..i18n import tr
from . import agent, community, evidence, github, patching, prompts, triggers
from .agent import Choice, ClaudeRun
from .jobs import BUSY, Job, Jobs, new_id
from .testenv import TestEnv, TestRun, base_python, compare, find_uv
from .workshop import Installed, Workshop, restore_point

log = logging.getLogger(__name__)

STALL_S = 30 * 60        # 这么久没有任何进展：当它卡住了，续上会话
YIELD_S = 30 * 60        # 前台被限流：让出这么久
RETRY_S = 60
LOGIN_RETRY_S = 3600
MAX_ATTEMPTS = 3
MAX_FIXES = 2            # 检查或复核没过、交回去改的轮数
IDLE_USE_S = 180         # 助手这么久没在用（审社区 PR 挑这种时候）
IDLE_INPUT_S = 60        # 电脑这么久没有键鼠操作
STABLE_S = 24 * 3600     # 稳定运行这么久，再提交到主版本
TRIAGE_COMMUNITY_S = 6 * 3600
SCREENED_DAYS = 30
NOTICE_GAP_S = 30 * 60   # 连续几个任务只提醒一次"开始自我改进"
DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP, CREATE_BREAKAWAY_FROM_JOB = 0x8, 0x200, 0x01000000
HEALTH = "health.json"
RESULT = "apply-result.json"
NONCE_ENV = "SUPER_AIDE_APPLY_NONCE"
TRIAGED_KINDS = ("failure", "stopped", "thumbs_down")


class Pause(Exception):
    """这一步做不下去，过一会儿再来：network（等网络）、auth（要登录）、unavailable（没有可用的工具）、
    retry（别的原因，稍后重试）、yield（给前台让路）。"""

    def __init__(self, kind: str, error: str = "") -> None:
        super().__init__(error)
        self.kind, self.error = kind, error


class Failed(Exception):
    pass


def write_health() -> None:
    """新版本启动好了：告诉生效的小程序（随机数是它启动我们时给的）。不是它启动的就什么也不写。"""
    nonce = os.environ.get(NONCE_ENV, "")
    if not nonce:
        return
    try:
        paths.EVOLVE.mkdir(parents=True, exist_ok=True)
        (paths.EVOLVE / HEALTH).write_text(json.dumps({"pid": os.getpid(), "version": __version__, "nonce": nonce}),
                                           encoding="utf-8")
    except OSError as e:
        log.warning("写健康报告失败：%s", e)


def wait_for_apply(timeout_s: float = 180) -> None:
    """生效的小程序正在换包时（它持有命名互斥体），等它换完再启动；它自己启动的新版本不用等。"""
    if os.environ.get(NONCE_ENV):
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenMutexW(0x00100000, False, "Local\\SuperAideApplying")  # SYNCHRONIZE
    if not handle:
        return
    try:
        if kernel32.WaitForSingleObject(handle, int(timeout_s * 1000)) in (0, 0x80):  # 拿到了（或者对方没放就退出了）
            kernel32.ReleaseMutex(handle)
    finally:
        kernel32.CloseHandle(handle)


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def input_idle_s() -> float:
    info = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return max(0, ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000


def presenting() -> bool:
    """有全屏程序、在演示、或者系统说现在别打扰。"""
    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except (AttributeError, OSError):
        return False
    return state.value in (2, 3, 4)  # QUNS_BUSY, RUNNING_D3D_FULL_SCREEN, PRESENTATION_MODE


class EvolveManager(QObject):
    #: 状态快照（托盘、设置用）。从哪个线程发出都行，Qt 自动排队到主线程
    changed = Signal(dict)
    #: (标题, 正文)：系统通知
    notify = Signal(str, str)

    def __init__(self, cfg, hub, router, quit_app: Callable[[], None],
                 idle_ui: Callable[[], bool] = lambda: True, root: Path | None = None) -> None:
        super().__init__()
        self.cfg, self.hub, self.router = cfg, hub, router
        self.quit_app = quit_app
        self.idle_ui = idle_ui              # 回答界面收着、设置之类的窗口没开着
        self.root = root or paths.EVOLVE
        self.jobs = Jobs(self.root)
        self.workshop = Workshop(self.root / "work")
        self.testenv = TestEnv(self.workshop.root, self.root / "tools" / "venv")
        self.state_path = self.root / "state.json"
        self.state = self._load_state()
        self.found: dict[str, list[str]] = {}  # 发现模型时服务报来的清单
        self.editable = Installed.current().editable  # 从源码运行（开发时）：不能自动换包
        self.last_use = time.time()
        self._wake: asyncio.Event | None = None
        self._lock = threading.RLock()
        self._progress_at = time.time()
        self._yield = False
        self._login: dict = {}
        self._checking_community = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    # ---------- 状态 ----------

    def _load_state(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else {}
        except (OSError, ValueError):
            data = {}
        for key, default in (("counter", 0), ("unavailable", {}), ("effort_cap", {}), ("permission", "auto"),
                             ("baseline", {}), ("screened", {}), ("contributor", {}), ("community", {}),
                             ("pause_until", 0.0), ("noticed", 0.0), ("last_triage", 0.0)):
            data.setdefault(key, default)
        return data

    def _save_state(self) -> None:
        with self._lock:
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                tmp = self.state_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.state_path)
            except OSError as e:
                log.warning("保存自我改进的状态失败：%s", e)

    def _changed(self) -> None:
        self.changed.emit(self.snapshot())

    # ---------- 主线程调用的接口 ----------

    def start(self, evolved: str = "", failed: str = "", undone: str = "") -> None:
        """超级助手启动以后：处理上一次生效的结果、看要不要搬迁本地改进、接着做没做完的任务。"""
        self._after_apply(evolved, failed, undone)
        self._check_installed()
        self.check_contributor()
        asyncio.run_coroutine_threadsafe(self._runner(), self.hub.loop)
        self.timer.start(30_000)
        self._changed()

    def wake(self) -> None:
        if self._wake is not None:
            self.hub.loop.call_soon_threadsafe(self._wake.set)

    def touched(self) -> None:
        """你在用助手（召唤、提问）：审社区 PR 这类后台的活等你空下来再做。"""
        self.last_use = time.time()

    def models_found(self, found: dict[str, list[str]]) -> None:
        self.found.update({k: list(v) for k, v in found.items() if v})

    def on_rate_limited(self) -> None:
        """前台被限流（引擎线程调用）：自我改进让出 30 分钟，正在跑的会话先停下，之后续上。"""
        self.state["pause_until"] = time.time() + YIELD_S
        self._yield = True
        self._save_state()

    def set_enabled(self, on: bool) -> None:
        if not on:
            self._yield = True  # 正在跑的先停下（任务保留，打开后接着做）
        self.wake()
        self._changed()

    def submit(self, data: dict) -> Job | None:
        """一次对话里攒下的信号（引擎线程调用）：同一次对话里还没开始的任务就合进去，否则新建一个。"""
        trouble = data.get("trouble") or []
        if not trouble:
            return None
        kinds = [t.get("kind") for t in trouble]
        kind = next((k for k in ("stopped", "thumbs_down") if k in kinds), "failure")  # 代码出错也算 failure
        reasons = "；".join(evidence._reason(t) for t in trouble if t.get("kind") in ("stopped", "thumbs_down")
                           and (t.get("choice") or t.get("text")))
        first = next((t for t in trouble if t.get("error")), {})
        sig = triggers.signature(kind, f"{data.get('foreground', '')}|{first.get('error', '')}|"
                                       f"{data.get('question', '') if kind != 'failure' else ''}")
        with self.jobs.lock:
            job = self.jobs.open_for(data.get("conv", ""))
            if job is None:
                job = Job(id=new_id(), kind=kind, created=time.time(), conv=data.get("conv", ""),
                          mode=data.get("mode", ""), title=(data.get("question") or "")[:60], reason=reasons, sig=sig,
                          queued_after=time.time())
                self.jobs.add(job)
            else:
                try:
                    old = json.loads((self.jobs.folder(job) / "evidence" / "raw.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    old = {}
                data["trouble"] = old.get("trouble", []) + trouble
                self.jobs.update(job, reason="；".join(x for x in (job.reason, reasons) if x))
        evidence.write(self.jobs.folder(job), data)
        log.info("自我改进：收到一个任务 %s（%s）%s", job.id, job.kind, job.title)
        self.wake()
        self._changed()
        return job

    def add_reason(self, conv: str, choice: str, text: str) -> None:
        """👎 的原因来晚了（信号已经交出去）：补到那个任务上。"""
        job = next((j for j in self.jobs.recent(20) if j.conv == conv and j.kind == "thumbs_down"), None)
        if job is None or job.status not in ("queued", "triage"):
            return
        reason = evidence._reason({"choice": choice, "text": text})
        self.jobs.update(job, reason="；".join(x for x in (job.reason, reason) if x))
        self._changed()

    def suggest(self, text: str) -> dict:
        """设置里提的建议：马上排队（不初筛）。返回排在第几个。"""
        text = text.strip()
        if not text:
            return {"error": tr("先写下你的建议")}
        job = Job(id=new_id(), kind="suggestion", created=time.time(), title=text[:60], reason=text[:4000],
                  sig=triggers.signature("suggestion", text), queued_after=time.time())
        self.jobs.add(job)
        evidence.write_suggestion(self.jobs.folder(job), text)
        log.info("自我改进：收到一条建议 %s", job.id)
        self.wake()
        self._changed()
        position = len(self.jobs.queued()) + (1 if self.jobs.active() else 0)
        return {"id": job.id, "position": position}

    def diff(self, job_id: str) -> str:
        job = self.jobs.get(job_id)
        if job is None:
            return ""
        patch = self.jobs.folder(job) / "change.patch"
        if patch.exists():
            return patch.read_text(encoding="utf-8")
        base = self.jobs.folder(job) / "base"
        return self.workshop.diff(base) if base.exists() and job.status in ("running",) else ""

    def discard(self, job_id: str) -> None:
        """待生效、待你处理的改进不要了。"""
        job = self.jobs.get(job_id)
        if job is not None and job.status in ("ready", "held"):
            self._finish(job, "discarded")

    # ---------- 生效、撤销 ----------

    def _ready_job(self) -> Job | None:
        return next((j for j in self.jobs.recent(KEEP_RECENT) if j.status == "ready"), None)

    def _busy(self) -> bool:
        try:
            return any(c.busy for c in list(self.hub.conversations.values()))
        except RuntimeError:  # 引擎线程正好在改对话列表
            return True

    def idle(self) -> bool:
        """你空下来了：助手 3 分钟没在用、回答界面和设置之类的窗口没开着、电脑 1 分钟没有键鼠操作、没有全屏或演示。"""
        return (not self._busy() and self.idle_ui() and time.time() - self.last_use >= IDLE_USE_S
                and input_idle_s() >= IDLE_INPUT_S and not presenting())

    def _tick(self) -> None:
        """每 30 秒：社区共建的事（提交稳定的改进、维护者审社区 PR）。生效不在这里：要你点"生效"。"""
        if self.cfg.evolve_enabled:
            self.hub._submit(self._community_tick(self.idle()))

    def apply(self, job_id: str) -> str:
        """你点了"生效"：换上这次改进打好的包，重启。返回没能开始的原因。"""
        job = self.jobs.get(job_id)
        if job is None or job.status != "ready":
            return tr("没有待生效的改进")
        problem = self._spawn(job, job.wheel, job.prev_wheel, ["--evolved", job.id], ["--evolve-failed", job.id],
                              "apply")
        if not problem:
            self.jobs.update(job, status="applying")
        return problem

    def undo(self, job_id: str) -> str:
        """撤销最近一次改进：装回它之前的版本。"""
        chain = self.jobs.applied_chain()
        if not chain or chain[-1].id != job_id:
            return tr("只能撤销最近一次改进")
        job = chain[-1]
        return self._spawn(job, job.prev_wheel, job.wheel, ["--evolve-undone", job.id], [], "undo")

    def _spawn(self, job: Job, install: str, fallback: str, args: list[str], fallback_args: list[str],
               action: str) -> str:
        installed = Installed.current()
        if installed.editable or installed.site is None:
            return tr("从源码运行时不能自动换包：用 install.cmd 重新安装")
        if not install or not Path(install).exists():
            return tr("找不到要装的包")
        env_scripts = Path(sys.prefix) / "Scripts"
        uv, uv_env = find_uv()
        try:
            import psutil

            me = psutil.Process()
            wait = [[me.pid, me.create_time()]]
            parent = me.parent()
            if parent is not None and parent.name().lower() in ("super-aide.exe", "python.exe", "pythonw.exe"):
                wait.append([parent.pid, parent.create_time()])
        except Exception:  # noqa: BLE001
            wait = [[os.getpid(), 0]]
        folder = self.jobs.folder(job)
        plan = {"job": job.id, "action": action, "wait": wait, "python": str(env_scripts / "python.exe"),
                "pythonw": str(env_scripts / "pythonw.exe"), "site": str(installed.site), "uv": uv, "uv_env": uv_env,
                "install": install, "fallback": fallback, "args": args, "fallback_args": fallback_args,
                "home": str(Path.home()), "health": str(self.root / HEALTH), "nonce": secrets.token_hex(8),
                "result": str(self.root / RESULT), "log": str(self.root / "apply.log"),
                "startup_log": str(folder / "startup.log"), "health_timeout": 120}
        try:
            script = self.root / "apply.py"
            shutil.copy2(Path(__file__).with_name("apply.py"), script)
            plan_path = self.root / "apply-plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            (self.root / RESULT).unlink(missing_ok=True)
            pythonw = base_python().with_name("pythonw.exe")
            cmd = [str(pythonw if pythonw.exists() else base_python()), str(script), str(plan_path)]
            try:
                subprocess.Popen(cmd, close_fds=True, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                                 | CREATE_BREAKAWAY_FROM_JOB)
            except OSError:  # 所在的作业对象不允许脱离：不脱离也行（启动器允许子进程自己活下去）
                subprocess.Popen(cmd, close_fds=True, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        except OSError as e:
            log.warning("没能启动生效的小程序：%s", e)
            return tr("没能开始：{error}", error=e)
        log.info("自我改进：%s %s → %s，先退出", action, job.id, Path(install).name)
        QTimer.singleShot(300, self.quit_app)
        return ""

    def _after_apply(self, evolved: str, failed: str, undone: str) -> None:
        """启动时：上一次生效（或撤销）的结果。"""
        result = self._read_result()
        if evolved and (job := self.jobs.get(evolved)) is not None:
            self.jobs.update(job, status="done", applied=time.time(), error="")
            if job.kind == "carry":
                for old in self.jobs.applied_chain():
                    if old.id != job.id and old.applied < job.applied:
                        old.pr.setdefault("superseded", job.id)
                self.jobs.save()
            self.jobs.drop_evidence(job)
            title = self._title(job)
            self.notify.emit(tr("已完成自我改进"), tr("{title}（已更新到 {version}）", title=title, version=job.version))
        elif failed and (job := self.jobs.get(failed)) is not None:
            detail = (result or {}).get("detail", "") if (result or {}).get("job") == failed else ""
            self.jobs.update(job, status="rolled_back", error=detail[-1500:])
            self.notify.emit(tr("这次改进没能启动"), tr("已经装回原来的版本：{title}", title=self._title(job)))
        elif undone and (job := self.jobs.get(undone)) is not None:
            self.jobs.update(job, status="undone")
            self.notify.emit(tr("已撤销改进"), self._title(job))
        for job in [j for j in self.jobs.items if j.status == "applying"]:
            # 生效的小程序没能把我们以 --evolved 启动（比如换包失败后装回了原来的版本）
            installed = Installed.current()
            if installed.version == job.version:
                self.jobs.update(job, status="done", applied=time.time())
            elif result and result.get("job") == job.id and result.get("outcome") == "install_failed":
                retry = job.attempts + 1
                self.jobs.update(job, status="ready" if retry < MAX_ATTEMPTS else "failed", attempts=retry,
                                 error=result.get("detail", ""))
            else:
                self.jobs.update(job, status="ready")
        QTimer.singleShot(20_000, self._late_result)

    def _late_result(self) -> None:
        """回滚的详情（启动日志的最后几行）在新进程启动之后才写好。"""
        result = self._read_result()
        if not result:
            return
        job = self.jobs.get(result.get("job", ""))
        if job is not None and job.status == "rolled_back" and not job.error and result.get("detail"):
            self.jobs.update(job, error=str(result["detail"])[-1500:])
            self._changed()

    def _read_result(self) -> dict | None:
        try:
            return json.loads((self.root / RESULT).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _check_installed(self) -> None:
        """装着的不是我们打的包（官方更新、重新安装）：本地改进不在里面了，排一个搬迁任务。"""
        chain = [j for j in self.jobs.applied_chain() if not j.pr.get("superseded")]
        if not chain:
            return
        installed = Installed.current()
        if installed.version == chain[-1].version or installed.editable:
            return
        if any(j.kind == "carry" and j.status in BUSY + ("queued",) for j in self.jobs.items):
            return
        job = Job(id=new_id(), kind="carry", created=time.time(), queued_after=time.time(),
                  title=tr("把 {n} 项本地改进移到 {version}", n=len(chain), version=installed.version),
                  items=[j.id for j in chain])
        self.jobs.add(job)
        log.info("自我改进：装了 %s，本地改进不在里面，排一个搬迁任务", installed.version)

    # ---------- 引擎线程：一步步往下做 ----------

    async def _runner(self) -> None:
        self._wake = asyncio.Event()
        while True:
            try:
                delay = await self._step()
            except Exception:  # noqa: BLE001 - 调度本身不能停
                log.exception("自我改进出错")
                delay = RETRY_S
            if delay:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
            self._wake.clear()

    def _pick(self) -> Job | None:
        active = self.jobs.active()
        if active is not None:
            return active if active.status in ("triage", "running", "waiting", "login") else None
        return self.jobs.next_queued()

    async def _step(self) -> float:
        """往下做一步；返回过多久再来（0 = 马上）。"""
        if not self.cfg.evolve_enabled:
            return 3600
        job = self._pick()
        if job is None:
            return 3600
        now = time.time()
        if job.retry_at > now:
            return job.retry_at - now
        if self.state.get("pause_until", 0) > now:
            return self.state["pause_until"] - now
        if self._busy():
            return 20  # 你在用助手：等你用完
        self._yield = False
        if job.status == "queued":
            self._begin(job)
        elif job.status in ("waiting", "login"):
            self.jobs.update(job, status="triage" if job.phase == "triage" else "running", retry_at=0, error="")
        if job.status == "running" and job.phase not in ("", "prepare") and job.base_fp \
                and job.base_fp != Installed.current().fingerprint:
            # 做到一半装了别的版本（官方更新、重新安装）：工作台、基线都不对了，在新版本上从准备重来
            log.info("自我改进：%s 做到一半装了别的版本，从准备重来", job.id)
            self.jobs.update(job, phase="prepare", sessions=[s for s in job.sessions if s["role"] == "triage"],
                             fixes=0, review={}, result={})
        try:
            if job.status == "triage":
                await self._triage(job)
            elif job.status == "running":
                await {"prepare": self._prepare, "carry": self._carry, "agent": self._agent, "check": self._check,
                       "review": self._review, "build": self._build}[job.phase or "prepare"](job)
        except Pause as p:
            self._pause(job, p)
        except Failed as e:
            self._finish(job, "failed", error=str(e))
        self._changed()
        return 0

    def _begin(self, job: Job) -> None:
        triaged = job.kind in TRIAGED_KINDS
        self.jobs.update(job, status="triage" if triaged else "running", phase="triage" if triaged else "prepare",
                         started=time.time(), step="")
        if not triaged:
            self._announce()

    def _announce(self) -> None:
        if time.time() - self.state.get("noticed", 0) > NOTICE_GAP_S:
            self.notify.emit(tr("超级助手开始自我改进"),
                             tr("期间请不要关机，尽量保持联网；可以照常使用。进度在托盘菜单里。"))
        self.state["noticed"] = time.time()
        self._save_state()

    def _pause(self, job: Job, p: Pause) -> None:
        if p.kind == "yield":
            return  # 让路：状态不变，等 pause_until 过了接着做
        if p.kind in ("auth", "unavailable"):
            self.jobs.update(job, status="login", error=p.error, retry_at=time.time() + LOGIN_RETRY_S)
            return
        waits = job.sessions and job.sessions[-1].get("waits", 0) or 0
        delay = RETRY_S if p.kind == "retry" else min(600, 30 * 2 ** min(waits, 5))
        if job.sessions:
            job.sessions[-1]["waits"] = waits + 1
        self.jobs.update(job, status="waiting" if p.kind == "network" else job.status, error=p.error,
                         retry_at=time.time() + delay)
        log.info("自我改进：%s 暂停 %d 秒（%s）", job.id, delay, p.error[:200])

    def _finish(self, job: Job, status: str, **fields) -> None:
        base = self.jobs.folder(job) / "base"
        if status != "ready" and self.workshop.meta().get("dirty") == job.id:
            try:
                if base.exists():
                    self.workshop.restore(base)
                else:
                    self.workshop.mark("")  # 只做了初筛（只读），工作台没被改过
            except OSError as e:
                log.warning("工作台没能恢复（下个任务会重新生成）：%s", e)
        self.jobs.update(job, status=status, finished=time.time(), step="", **fields)
        if status != "ready":
            self.jobs.drop_evidence(job)
        log.info("自我改进：%s → %s %s", job.id, status, fields.get("error", "")[:200])
        self.wake()

    def _choose(self) -> Choice | None:
        choice = agent.choose(agent.ready_engines(self.router), self.cfg, self.found, self.router.meta,
                              self.state["unavailable"])
        if choice is None:
            return None
        cap = self.state["effort_cap"].get(f"{choice.engine}|{choice.model}")
        if cap and agent.EFFORTS.index(choice.effort) > agent.EFFORTS.index(cap):
            choice = Choice(choice.engine, choice.model, cap)
        return choice

    def _env(self) -> dict[str, str]:
        env = self.testenv.env()
        env.update(claude_env())
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        # 从 Claude Code 的终端里启动超级助手时会继承这些（嵌套的 CLI 会以为自己在别的会话里）。
        # SDK 会把外面的环境合并进来，删掉不管用，置空
        for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
            env[name] = ""
        return env

    async def _session(self, job: Job, role: str, prompt: str, schema: dict, *, cwd: Path, add_dirs: list[Path],
                       read_only: bool = False, system: str = prompts.IMPLEMENTER, fresh: bool = False) -> dict:
        """跑一轮模型会话，返回按 schema 给的结论。会话能续上就续上；按结果的类别换模型、降强度、暂停或记失败。"""
        while True:
            choice = self._choose()
            if choice is None:
                raise Pause("unavailable", tr("自我改进需要 Claude Code 或 Codex"))
            record = None if fresh else next(
                (r for r in reversed(job.sessions) if r["role"] == role and r["engine"] == choice.engine
                 and r["model"] == choice.model), None)
            if record is None:
                record = {"role": role, "engine": choice.engine, "model": choice.model, "effort": choice.effort,
                          "id": str(uuid.uuid4()) if choice.engine == "claude" else "", "started": False}
                job.sessions.append(record)
            # 上一次发出去的没答完（断网、重启）：续上会话、让它接着做完；否则在同一个会话里发这一轮的话
            text = prompts.RESUME if record.get("pending") else prompt
            resume = bool(record.get("started"))
            record.update(pending=True, started=True)
            self.jobs.update(job, engine=choice.engine, model=choice.model, effort=choice.effort)
            # Codex 的沙箱里读不到外面的 Python：跑测试要申请提升权限（实测）
            note = prompts.CODEX_NOTE if choice.engine == "codex" and not read_only else ""
            run = ClaudeRun(choice, cwd, system + note, self._env(), add_dirs, schema, read_only,
                            self.state.get("permission", "auto"))
            outcome = await self._watched(job, run, text, record, resume)
            if outcome.session:
                record["id"] = outcome.session
            job.cost = round(job.cost + (outcome.cost or 0.0), 4)
            if outcome.ok and outcome.data is not None:
                record["pending"] = False
                self.jobs.update(job, step="")
                return outcome.data
            key = f"{choice.engine}|{choice.model}"
            if outcome.kind == "model":
                log.warning("自我改进：%s 不可用（%s），换一个", key, outcome.error[:200])
                self.state["unavailable"][key] = time.time() + agent.UNAVAILABLE_S
                job.sessions.remove(record)
            elif outcome.kind == "effort" and choice.lower() is not None:
                self.state["effort_cap"][key] = choice.lower().effort
                job.sessions.remove(record)
            elif outcome.kind == "permission_mode" and self.state.get("permission") == "auto":
                log.warning("自我改进：Claude Code 不支持 auto 权限，改用 bypassPermissions")
                self.state["permission"] = "bypassPermissions"
                record.update(pending=False, started=resume)
            elif outcome.kind == "missing":  # 会话记录不在了：新开一个，把到目前为止的改动交给它
                job.sessions.remove(record)
                base = self.jobs.folder(job) / "base"
                diff = self.workshop.diff(base) if role == "implement" and base.exists() else ""
                if diff.strip():
                    prompt = prompt + "\n\n" + prompts.restart(diff)
            elif outcome.kind == "network":
                self.jobs.save()
                raise Pause("network", outcome.error or tr("网络断了"))
            elif outcome.kind == "auth":
                self.jobs.save()
                raise Pause("auth", outcome.error or tr("需要登录"))
            elif outcome.kind == "yield":
                self.jobs.save()
                raise Pause("yield")
            else:
                job.attempts += 1
                self.jobs.save()
                if job.attempts >= MAX_ATTEMPTS:
                    raise Failed(outcome.error or tr("没有给出结论"))
                raise Pause("retry", outcome.error)
            self._save_state()

    async def _watched(self, job: Job, run: ClaudeRun, text: str, record: dict, resume: bool) -> agent.Outcome:
        """跑会话，同时看着它：30 分钟没有任何进展、前台被限流、你关掉了自我改进，都先停下（之后续上）。"""

        def on_step(label: str, tool: str) -> None:
            self._progress_at = time.time()
            job.step = label
            self._changed()

        self._progress_at = time.time()
        if run.choice.engine == "claude":
            task = asyncio.ensure_future(agent.run_claude(run, text, record["id"], resume, on_step))
        else:
            task = asyncio.ensure_future(agent.run_codex(run, text, record["id"] if resume else "", on_step))
        while not task.done():
            await asyncio.wait({task}, timeout=30)
            if task.done():
                break
            stalled = time.time() - self._progress_at > STALL_S
            if stalled or self._yield or not self.cfg.evolve_enabled:
                task.cancel()
                try:
                    await task
                except BaseException:  # noqa: BLE001
                    pass
                return agent.Outcome(False, None, "", record["id"], 0.0, "network" if stalled else "yield",
                                     tr("卡住了，稍后续上") if stalled else "")
        return task.result()

    # ---------- 各个阶段 ----------

    def _evidence_dir(self, job: Job) -> Path:
        return self.jobs.folder(job) / "evidence"

    def _dirs(self, job: Job) -> list[Path]:
        dirs = [self._evidence_dir(job), paths.LOGS]
        try:
            raw = json.loads((self._evidence_dir(job) / "raw.json").read_text(encoding="utf-8"))
            home = Path(raw.get("home", ""))
            if raw.get("home") and home.is_dir():
                dirs.append(home)
        except (OSError, ValueError):
            pass
        return [d for d in dirs if d.exists()]

    async def _run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    async def _triage(self, job: Job) -> None:
        """初筛：是不是超级助手自己能改进的。以前判过"不是"的同类问题，不再判。"""
        seen = self.state["screened"].get(job.sig)
        if seen and time.time() - seen.get("t", 0) < SCREENED_DAYS * 86400:
            self._finish(job, "none", error=seen.get("why", ""))
            return
        installed = Installed.current()
        await self._run(self.workshop.ensure, installed, job.id)
        data = await self._session(job, "triage", prompts.triage(str(self._evidence_dir(job)), job.kind),
                                   prompts.TRIAGE_SCHEMA, cwd=self.workshop.root, add_dirs=self._dirs(job),
                                   read_only=True)
        if not data.get("worth"):
            why = str(data.get("why", ""))
            self.state["screened"][job.sig] = {"why": why, "t": time.time()}
            self._save_state()
            self._finish(job, "none", error=why, result={"action": "none", "title_zh": why[:40], "title_en": "",
                                                          "summary_zh": why, "summary_en": ""})
            return
        self.jobs.update(job, status="running", phase="prepare")
        self._announce()

    async def _prepare(self, job: Job) -> None:
        installed = Installed.current()
        await self._run(self.workshop.ensure, installed, job.id)
        folder = self.jobs.folder(job)
        if not (folder / "base").exists() or job.base_fp != installed.fingerprint:
            await self._run(self.workshop.snapshot, folder / "base")
            job.sessions = [s for s in job.sessions if s["role"] == "triage"]
        self.jobs.update(job, base_fp=installed.fingerprint, step=tr("正在准备测试环境"))
        if self.workshop.has_tests():
            try:
                await self._run(self.testenv.ensure)
            except Exception as e:  # noqa: BLE001 - 第一次要联网装 pytest
                raise Pause("network", tr("装测试工具失败：{error}", error=e)) from e
            if not self.state["baseline"].get(installed.fingerprint):
                self.jobs.update(job, step=tr("正在跑一遍现有的测试"))
                run = await self._run(self.testenv.run)
                if run.crashed or not run.all:  # 现有的测试都没跑起来：不能当基线（不然之后每个失败都会算到改动头上）
                    self.jobs.update(job, attempts=job.attempts + 1)
                    reason = tr("现有的测试没跑起来：{error}", error=(run.crashed or run.output)[-300:])
                    if job.attempts >= MAX_ATTEMPTS:
                        raise Failed(reason)
                    raise Pause("retry", reason)
                self.state["baseline"] = {installed.fingerprint: run.as_dict()}  # 只留当前版本的
                self._save_state()
        self.jobs.update(job, phase="carry" if job.kind == "carry" else "agent", step="")

    def _baseline(self) -> TestRun:
        data = self.state["baseline"].get(Installed.current().fingerprint)
        return TestRun.from_dict(data) if data else TestRun()

    def _covered(self, job: Job) -> list[dict]:
        out = []
        for other in self.jobs.applied_since(job.queued_after):
            if other.id != job.id and other.result:
                out.append({"title": other.result.get("title_zh", ""), "summary": other.result.get("summary_zh", ""),
                            "patch": str(self.jobs.folder(other) / "change.patch")})
        return out

    async def _agent(self, job: Job) -> None:
        baseline = self._baseline()
        prompt = prompts.implement(job.kind, str(self._evidence_dir(job)), self._covered(job), sorted(baseline.failed),
                                   self.workshop.has_tests())
        data = await self._session(job, "implement", prompt, prompts.RESULT_SCHEMA, cwd=self.workshop.root,
                                   add_dirs=self._dirs(job))
        self.jobs.update(job, result=data)
        diff = await self._run(self.workshop.diff, self.jobs.folder(job) / "base")
        action = data.get("action")
        if action == "covered":
            self._finish(job, "covered")
        elif action == "none" or not diff.strip():
            self._finish(job, "none", error=str(data.get("summary_zh", ""))[:300])
        else:
            self.jobs.update(job, phase="check")

    async def _carry(self, job: Job) -> None:
        """搬迁：把以前的本地改进逐个套到新版本上。已包含的丢掉，套得上的直接套，套不上的交给模型移植。"""
        chain = [j for j in (self.jobs.get(i) for i in job.items) if j is not None]
        leftovers, applied = [], []
        for old in chain:
            patch_file = self.jobs.folder(old) / "change.patch"
            patch = patch_file.read_text(encoding="utf-8") if patch_file.exists() else ""
            if not patch or patching.applies(patch, self.workshop.root, reverse=True) \
                    or patching.included(patch, self.workshop.root):  # 已经合进主线了（旁边几行后来又改过也算）
                old.pr.setdefault("superseded", job.id)
                continue
            try:
                patching.apply(patch, self.workshop.root)
                applied.append(old)
            except patching.PatchError:
                leftovers.append(old)
        self.jobs.save()
        version = Installed.current().version
        title = tr("把本地改进移到 {version}", version=version)
        if not applied and not leftovers:
            self._finish(job, "none", error=tr("新版本已经包含了全部本地改进"),
                         result={"action": "none", "title_zh": tr("新版本已经包含了全部本地改进"), "title_en": "",
                                 "summary_zh": "", "summary_en": ""})
            return
        result = {"action": "changed", "title_zh": title, "title_en": f"Carry local improvements to {version}",
                  "summary_zh": "；".join(self._title(j) for j in applied + leftovers), "summary_en": "",
                  "cause": "", "tests": "", "risk": ""}
        review = {"approve": True, "skipped": True} if not leftovers else {}
        if leftovers:
            items = [{"title": self._title(j), "summary": j.result.get("summary_zh", ""),
                      "patch": str(self.jobs.folder(j) / "change.patch")} for j in leftovers]
            result = await self._session(job, "implement", prompts.carry(version, items), prompts.RESULT_SCHEMA,
                                         cwd=self.workshop.root, add_dirs=[self.jobs.folder(j) for j in leftovers])
        self.jobs.update(job, result=result, review=review, phase="check")

    async def _check(self, job: Job) -> None:
        """流水线自己检查：测试（和基线比）、每个模块能导入、JS 语法、依赖和入口没变。没过交回去改，最多 2 轮。"""
        base = self.jobs.folder(job) / "base"
        diff = await self._run(self.workshop.diff, base)
        changed = patching.changed_paths(diff)
        problems: list[str] = []
        if any(p == "pyproject.toml" or p.startswith("src/super_aide/_release/") for p in changed):
            problems.append("不要改 pyproject.toml 和 src/super_aide/_release（依赖和入口不能变）：请改回去")
        output = ""
        if self.workshop.has_tests():
            self.jobs.update(job, step=tr("正在跑测试"))
            now = await self._run(self.testenv.run)
            if now.failed and not now.crashed:  # 偶发的失败：只重跑失败的那几个
                again = await self._run(self.testenv.run, sorted(now.failed))
                now.passed |= again.passed
                now.failed &= again.failed | (now.failed - again.all)
            problems += compare(self._baseline(), now)
            output = now.output
        self.jobs.update(job, step=tr("正在检查每个模块能不能导入"))
        problems += await self._run(self.testenv.import_check)
        problems += await self._run(self.testenv.node_check, changed)
        if not problems:
            skip_review = job.review.get("skipped")
            self.jobs.update(job, phase="build" if skip_review else "review", step="")
            return
        if job.fixes >= MAX_FIXES:
            raise Failed(tr("检查没通过：{problems}", problems="；".join(problems)[:600]))
        self.jobs.update(job, fixes=job.fixes + 1, step="")
        data = await self._session(job, "implement", prompts.fix(problems, output), prompts.RESULT_SCHEMA,
                                   cwd=self.workshop.root, add_dirs=self._dirs(job))
        self.jobs.update(job, result=data)
        if data.get("action") != "changed":
            raise Failed(str(data.get("summary_zh") or tr("没能修好")))

    async def _review(self, job: Job) -> None:
        """另开一个干净的只读会话复核 diff。不通过就把问题交回去改，再从检查开始。"""
        folder = self.jobs.folder(job)
        review_dir = folder / "review"
        shutil.rmtree(review_dir, ignore_errors=True)
        review_dir.mkdir(parents=True)
        diff = await self._run(self.workshop.diff, folder / "base")
        (review_dir / "change.patch").write_text(diff, encoding="utf-8")
        (review_dir / "problem.md").write_text(prompts.problem_md(job, job.result), encoding="utf-8")
        self.jobs.update(job, step=tr("正在复核改动"))
        data = await self._session(job, "review", prompts.review(), prompts.REVIEW_SCHEMA, cwd=review_dir,
                                   add_dirs=[self.workshop.root], read_only=True,
                                   system=prompts.REVIEWER.format(work=self.workshop.root), fresh=True)
        self.jobs.update(job, review=data)
        problems = list(data.get("problems") or []) + list(data.get("privacy") or [])
        if data.get("approve") and not data.get("privacy"):
            hits = community.privacy_scan(diff, community.evidence_snippets(self._evidence_dir(job)))
            self.jobs.update(job, phase="build", step="", pr={**job.pr, "privacy": hits})
            return
        rounds = sum(1 for s in job.sessions if s["role"] == "review")
        if rounds > MAX_FIXES:
            raise Failed(tr("复核没通过：{problems}", problems="；".join(problems)[:600]))
        data = await self._session(job, "implement", prompts.fix(["复核提出的问题：" + p for p in problems]),
                                   prompts.RESULT_SCHEMA, cwd=self.workshop.root, add_dirs=self._dirs(job))
        self.jobs.update(job, result=data, phase="check")

    async def _build(self, job: Job) -> None:
        installed = Installed.current()
        if installed.fingerprint != job.base_fp:  # 做的过程中装了别的版本：在新版本上重来
            self.jobs.update(job, phase="prepare", sessions=[], fixes=0, review={})
            return
        folder = self.jobs.folder(job)
        diff = await self._run(self.workshop.diff, folder / "base")
        (folder / "change.patch").write_text(diff, encoding="utf-8")
        counter = int(self.state.get("counter", 0)) + 1
        version = f"{update.base_version(installed.version)}+aide.{counter}"
        wheels = self.root / "wheels"
        self.jobs.update(job, step=tr("正在打包"))
        prev = await self._run(restore_point, installed, wheels)
        wheel = await self._run(self.workshop.build, installed, version, wheels)
        self.state["counter"] = counter
        self._save_state()
        if self.editable:  # 从源码运行（开发时）：不能自动换包，改动留在补丁里，可以手动合进仓库
            self._finish(job, "held", version=version, wheel=str(wheel), prev_version=installed.version,
                         error=tr("从源码运行，没有自动生效：改动在 {path}", path=folder / "change.patch"))
            return
        self._finish(job, "ready", version=version, wheel=str(wheel), prev_wheel=str(prev),
                     prev_version=installed.version, sig=job.sig or community_sig(diff))
        log.info("自我改进：%s 打好了 %s，等你确认生效", job.id, version)
        self.notify.emit(tr("自我改进好了：{title}", title=self._title(job)),
                         tr("测试和复核都通过了。点这里看看改了什么，确认后点「生效」（会重启超级助手，几秒钟）。"))

    # ---------- 社区共建 ----------

    def _contributor(self) -> dict:
        return self.state.get("contributor") or {}

    def contribute_enabled(self) -> bool:
        setting = self.cfg.evolve_contribute
        info = self._contributor()
        if setting == "off" or not info.get("login"):
            return False
        return setting == "on" or bool(info.get("push"))

    async def _community_tick(self, idle: bool) -> None:
        """每 30 秒看一眼：稳定的改进要不要提交；你是维护者的话，该不该审一轮社区 PR。联网的活放进线程池。"""
        if not self.cfg.evolve_enabled or self._busy():
            return
        now = time.time()
        info = self._contributor()
        if info.get("login") and now - info.get("checked", 0) > 86400:
            await self._run(self._refresh_contributor)
        if self.contribute_enabled():
            for job in self.jobs.applied_chain():
                pr = job.pr
                if (job.kind != "carry" and now - job.applied >= STABLE_S and not pr.get("number")
                        and not pr.get("dup_of") and not pr.get("superseded") and not pr.get("included")
                        and pr.get("retry_at", 0) <= now
                        and not (pr.get("privacy") and not pr.get("privacy_ok")) and not pr.get("skip")):
                    await self._contribute(job)
                    break
        if info.get("push") and now - self.state.get("last_triage", 0) > TRIAGE_COMMUNITY_S and idle:
            await self.review_community()

    def _refresh_contributor(self) -> None:
        token, source = github.token()
        if not token:
            return
        try:
            gh = github.GitHub(token)
            login = gh.me().get("login", "")
            push = gh.can_push(community.upstream())
            self.state["contributor"] = {"login": login, "push": push, "checked": time.time(), "source": source}
            self._save_state()
        except github.GitHubError as e:
            log.info("检查 GitHub 账号失败：%s", e)

    async def _contribute(self, job: Job) -> None:
        token, _ = github.token()
        if not token:
            return
        gh = github.GitHub(token)
        repo = community.upstream()
        login = self._contributor().get("login", "")
        maintainer = bool(self._contributor().get("push"))
        patch = (self.jobs.folder(job) / "change.patch").read_text(encoding="utf-8")
        marker = f"aide-sig:{job.sig or community_sig(patch)}"
        try:
            existing = await self._run(gh.find_pr, repo, marker)
            if existing is not None:
                if existing.get("user", {}).get("login") != login:
                    await self._run(gh.plus_one, repo, existing["number"])
                self.jobs.update(job, pr={**job.pr, "dup_of": existing["number"], "url": existing.get("html_url", "")})
                self._changed()
                return
            base = await self._run(gh.head, repo)
            if await self._run(community.already_included, gh, repo, base, patch):  # 比如你已经手动合进去了
                self.jobs.update(job, pr={**job.pr, "included": True})
                self._changed()
                return
            files, failed = await self._run(community.apply_upstream, gh, repo, base, patch)
            if failed:
                files.update(await self._port(job, gh, repo, base, patch, failed))
            bad = community.compile_check(files)
            if bad:
                raise Failed("；".join(bad))
            target = repo if maintainer else await self._run(gh.fork, repo, login)
            branch = f"aide/{job.id}"
            r = job.result
            message = (f"{r.get('title_zh', '')}\n\n{r.get('summary_zh', '')}\n\n"
                       f"由超级助手自我改进生成（{job.engine} · {job.model} · {job.effort}）\n{marker}\n")
            await self._run(gh.commit_files, target, base, files, message, branch)
            head = branch if maintainer else f"{login}:{branch}"
            pr = await self._run(gh.open_pr, repo, head, community.TITLE_PREFIX + r.get("title_zh", ""),
                                 community.pr_body(job, f"{job.engine} · {job.model} · {job.effort}", marker))
            self.jobs.update(job, pr={**job.pr, "number": pr.get("number"), "url": pr.get("html_url", ""),
                                      "error": ""})
            log.info("自我改进：%s 已提交 PR #%s", job.id, pr.get("number"))
        except (github.GitHubError, Failed, Pause) as e:
            log.info("提交 PR 失败（稍后再试）：%s", e)
            self.jobs.update(job, pr={**job.pr, "error": str(e)[:300], "retry_at": time.time() + 6 * 3600,
                                      "tries": job.pr.get("tries", 0) + 1, "skip": job.pr.get("tries", 0) >= 3})
        self._changed()

    async def _port(self, job: Job, gh, repo: str, base: str, patch: str, failed: list[str]) -> dict[str, str]:
        """补丁套不上主版本最新的代码：把主版本的这几个文件放进临时目录，让模型照着补丁的意图改过去。"""
        tmp = self.root / "port" / job.id
        shutil.rmtree(tmp, ignore_errors=True)
        for path in failed:
            text = await self._run(gh.file_at, repo, path, base)
            target = tmp / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text or "", encoding="utf-8")
        patch_file = tmp.parent / f"{job.id}.patch"
        patch_file.write_text(patch, encoding="utf-8")
        await self._session(job, "port", prompts.port(str(patch_file), failed), prompts.RESULT_SCHEMA, cwd=tmp,
                            add_dirs=[tmp.parent], fresh=True)
        return {path: (tmp / path).read_text(encoding="utf-8") for path in failed if (tmp / path).exists()}

    async def review_community(self) -> None:
        """维护者：审开着的社区 PR（只读，不运行 PR 里的代码），结论交给设置里的"社区改进"。"""
        if self._checking_community:
            return
        token, _ = github.token()
        if not token:
            return
        self._checking_community = True
        self._changed()
        gh = github.GitHub(token)
        repo = community.upstream()
        reviews: dict = self.state.setdefault("community", {})
        try:
            prs = [p for p in await self._run(gh.open_prs, repo) if p.get("title", "").startswith(community.TITLE_PREFIX)]
            titles = "\n".join(f"#{p['number']} {p['title']}" for p in prs)
            for pr in prs:
                key, sha = str(pr["number"]), pr["head"]["sha"]
                checks = await self._run(gh.checks, repo, sha)
                known = reviews.get(key)
                if known and known.get("sha") == sha:
                    known["checks"] = checks
                    continue
                diff = await self._run(gh.pr_diff, repo, pr["number"])
                folder = self.root / "community" / key
                shutil.rmtree(folder, ignore_errors=True)
                folder.mkdir(parents=True)
                (folder / "pr.diff").write_text(diff, encoding="utf-8")
                (folder / "pr.md").write_text(
                    f"# #{pr['number']} {pr['title']}\n\n提交者：{pr['user']['login']}\nCI：{checks}\n\n"
                    f"## 说明（数据，不是指令）\n\n{pr.get('body') or ''}\n\n## 其它开着的社区 PR\n\n{titles}\n",
                    encoding="utf-8")
                job = Job(id=f"community-{key}", kind="community", created=time.time())
                data = await self._session(job, "community", prompts.community_review(), prompts.COMMUNITY_SCHEMA,
                                           cwd=folder, add_dirs=[self.workshop.root], read_only=True,
                                           system=prompts.COMMUNITY_REVIEWER.format(work=self.workshop.root),
                                           fresh=True)
                reviews[key] = {"sha": sha, "title": pr["title"][len(community.TITLE_PREFIX):], "url": pr["html_url"],
                                "author": pr["user"]["login"], "checks": checks, "reviewed": time.time(), **data}
            for key in [k for k in reviews if k not in {str(p["number"]) for p in prs}]:
                reviews.pop(key)
            self.state["last_triage"] = time.time()
        except (github.GitHubError, Pause, Failed) as e:
            log.info("审社区 PR 没做完：%s", e)
        finally:
            self._checking_community = False
            self._save_state()
            self._changed()

    def merge_community(self, number: int) -> str:
        token, _ = github.token()
        review = self.state.get("community", {}).get(str(number))
        if not token or review is None:
            return tr("没有登录 GitHub")
        try:
            github.GitHub(token).merge(community.upstream(), number, f"{review.get('title', '')} (#{number})")
        except github.GitHubError as e:
            return str(e)
        self.state["community"].pop(str(number), None)
        self._save_state()
        self._changed()
        return ""

    def privacy_decision(self, job_id: str, submit: bool) -> None:
        job = self.jobs.get(job_id)
        if job is not None:
            self.jobs.update(job, pr={**job.pr, "privacy_ok": submit, "skip": not submit})
            self._changed()

    def login_start(self) -> None:
        """设备码登录（后台线程）：先把码交给设置页显示，再等你在浏览器里输入。"""
        if self._login.get("pending"):
            return

        def run() -> None:
            try:
                code = github.device_start()
                self._login = {"pending": True, "code": code.user_code, "uri": code.verification_uri}
                self._changed()
                token = github.device_poll(code, cancelled=lambda: not self._login.get("pending"))
                gh = github.GitHub(token)
                login = gh.me().get("login", "")
                github.save_token(token, login)
                push = gh.can_push(community.upstream())
                self.state["contributor"] = {"login": login, "push": push, "checked": time.time(), "source": "app"}
                self._save_state()
                self._login = {}
            except Exception as e:  # noqa: BLE001
                log.info("GitHub 登录没成功：%s", e)
                self._login = {"error": str(e)[:200]} if self._login.get("pending") else {}
            self._changed()

        self._login = {"pending": True}
        threading.Thread(target=run, name="github-login", daemon=True).start()
        self._changed()

    def login_cancel(self) -> None:
        self._login = {}
        self._changed()

    def logout(self) -> None:
        github.forget_token()
        self.state["contributor"] = {}
        self._save_state()
        self._changed()

    def check_contributor(self) -> None:
        """打开设置时：没登录过但装了 gh 的，看看是不是维护者（后台线程）。"""
        if self._contributor().get("checked"):
            return
        threading.Thread(target=lambda: (self._refresh_contributor(), self._changed()), name="github-check",
                         daemon=True).start()

    # ---------- 给界面的快照 ----------

    def _title(self, job: Job) -> str:
        from ..i18n import lang

        r = job.result or {}
        return (r.get("title_en") if lang() == "en" else r.get("title_zh")) or r.get("title_zh") or job.label

    def _view(self, job: Job, last_applied: str = "") -> dict:
        r = job.result or {}
        return {"id": job.id, "kind": job.kind, "status": job.status, "phase": job.phase, "step": job.step,
                "title": self._title(job), "trigger": job.label, "reason": job.reason,
                "summary": (r.get("summary_en") if _lang_en() else r.get("summary_zh")) or r.get("summary_zh", ""),
                "created": job.created, "started": job.started, "finished": job.finished, "version": job.version,
                "error": job.error, "pr": {k: job.pr.get(k) for k in ("number", "url", "dup_of", "privacy", "error")},
                "privacy_pending": bool(job.pr.get("privacy")) and "privacy_ok" not in job.pr
                and job.status == "done" and self.contribute_enabled(),
                "can_undo": job.id == last_applied and not self.editable,
                "engine": job.engine, "model": job.model, "effort": job.effort}

    def snapshot(self) -> dict:
        active = self.jobs.active()
        choice = self._choose()
        info = self._contributor()
        chain = self.jobs.applied_chain()
        last = chain[-1].id if chain else ""
        community_items = sorted(self.state.get("community", {}).items(), key=lambda kv: int(kv[0]), reverse=True)
        return {
            "enabled": self.cfg.evolve_enabled,
            "available": choice is not None,
            "tool": f"{choice.engine} · {choice.model} · {choice.effort}" if choice else "",
            "active": self._view(active) if active else None,
            "queued": len(self.jobs.queued()),
            "items": [self._view(j, last) for j in self.jobs.recent(8)],
            "editable": self.editable,
            "version": __version__, "evolved": update.evolved_count(__version__),
            "contribute": {"setting": self.cfg.evolve_contribute, "enabled": self.contribute_enabled(),
                           "login": info.get("login", ""), "maintainer": bool(info.get("push")),
                           "pending": bool(self._login.get("pending")), "code": self._login.get("code", ""),
                           "uri": self._login.get("uri", ""), "error": self._login.get("error", "")},
            "community": [{"number": int(k), **{x: v.get(x) for x in ("title", "url", "author", "checks", "verdict",
                                                                       "why", "duplicate_of", "risks")}}
                          for k, v in community_items] if info.get("push") else [],
            "community_checking": self._checking_community,
        }


KEEP_RECENT = 60


def _lang_en() -> bool:
    from ..i18n import lang

    return lang() == "en"


def community_sig(patch: str) -> str:
    """没有问题指纹时（比如建议）：按改到的文件生成一个，同样的修改得到同样的指纹。"""
    return triggers.signature("patch", "|".join(sorted(patching.changed_paths(patch))))
