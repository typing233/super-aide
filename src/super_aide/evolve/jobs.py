"""自我改进的任务：排队、状态，落盘在 ~/.super_aide/evolve/jobs.json（每换一个阶段都存，中断了下次接着做）。

一个任务从触发到结束：
  queued（排队；对话里的信号一来就排上，等这次对话结束才开始）→ triage（初筛：是不是助手自己能改进的）
  → running（准备、分析和修改、检查、复核、打包）
  → ready（待生效：等你空闲时重启生效）→ applying → done
中途可能：waiting（等网络）、login（需要登录）；结论可能是 none（无需改进）、covered（已被前面的改进覆盖）、
held（待你处理，比如从源码运行时）、failed（没改成）、discarded（改好了但你没要）；
生效后可能 rolled_back（新版本没能启动，已装回）、undone（你撤销了）。生效要你点"生效"，不会自己装。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

KINDS = ("failure", "stopped", "thumbs_down", "suggestion", "carry")
#: 还没结束的状态（会被调度、续上）
OPEN = ("queued", "triage", "running", "waiting", "login", "ready", "applying")
#: 占着"同一时间只做一个"的名额：上一个装好或放弃了，下一个才开始
BUSY = ("triage", "running", "waiting", "login", "ready", "applying")
FINISHED = ("done", "none", "covered", "held", "failed", "discarded", "rolled_back", "undone")
KEEP = 60  # 最多留多少条历史（结论和补丁很小；证据在任务结束时就删了）


@dataclass
class Job:
    id: str
    kind: str
    created: float
    status: str = "queued"
    phase: str = ""            # running 时在哪一步：prepare / agent / check / review / build
    step: str = ""             # 最近一行进度（给界面看），比如"正在读 hub.py"
    title: str = ""            # 触发摘要：问题或建议的开头
    conv: str = ""             # 对话 key：同一次对话里的多个信号合成一个任务
    mode: str = ""             # 触发时的模式（ask / act）
    reason: str = ""           # 你说的原因 / 建议原文
    started: float = 0.0
    finished: float = 0.0
    attempts: int = 0          # 非网络原因失败的次数（3 次算没改成）
    fixes: int = 0             # 检查或复核没过、交回去改的轮数
    sessions: list[dict] = field(default_factory=list)  # [{role, engine, model, effort, id}]，续上用
    engine: str = ""
    model: str = ""
    effort: str = ""
    base_fp: str = ""          # 做这个任务时正在运行的版本的指纹
    result: dict = field(default_factory=dict)   # 模型的结论（RESULT_SCHEMA）
    review: dict = field(default_factory=dict)   # 复核的结论
    version: str = ""          # 打出来的版本号（0.2.0+aide.3）
    wheel: str = ""
    prev_wheel: str = ""
    prev_version: str = ""
    applied: float = 0.0       # 生效的时间（稳定 24 小时后提交到主版本）
    error: str = ""            # 没改成、等网络、需要登录的原因
    retry_at: float = 0.0      # 等网络、需要登录时，下次再试的时间
    sig: str = ""              # 问题指纹（去重、社区共建用）
    pr: dict = field(default_factory=dict)       # {number, url, dup_of, state, held}
    cost: float = 0.0          # 累计花费（美元，只记录不设上限）
    queued_after: float = 0.0  # 入队时间：轮到它时，看这之后做过的改进有没有覆盖它
    hold_until: float = 0.0    # 排着时：这之前不开始（这次对话还没结束，见 hub._schedule_evolve）
    items: list[str] = field(default_factory=list)  # 搬迁任务：要搬的那些本地改进（任务编号，按生效先后）

    @property
    def label(self) -> str:
        return self.title or self.reason[:40]

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Job:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)


class Jobs:
    """任务列表。主线程（界面、触发）和引擎线程（跑任务）都会读写：一把锁，每次改完整个写回文件。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "jobs.json"
        self.lock = threading.RLock()
        self.items: list[Job] = []
        self.load()

    def load(self) -> None:
        with self.lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
            except (OSError, ValueError) as e:
                log.warning("读取自我改进的任务失败：%s", e)
                data = []
            self.items = [Job.from_dict(d) for d in data if isinstance(d, dict) and d.get("id")]

    def save(self) -> None:
        with self.lock:
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps([j.as_dict() for j in self.items], ensure_ascii=False, indent=1),
                               encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError as e:
                log.warning("保存自我改进的任务失败：%s", e)

    def folder(self, job: Job | str) -> Path:
        return self.root / "jobs" / (job if isinstance(job, str) else job.id)

    def add(self, job: Job) -> Job:
        with self.lock:
            self.items.append(job)
            self._trim()
            self.save()
        return job

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return next((j for j in self.items if j.id == job_id), None)

    def update(self, job: Job, **changes) -> Job:
        with self.lock:
            for key, value in changes.items():
                setattr(job, key, value)
            self.save()
        return job

    def open_for(self, conv: str) -> Job | None:
        """同一次对话还没开始做的任务（新信号合进去）。"""
        with self.lock:
            return next((j for j in self.items if conv and j.conv == conv and j.status == "queued"), None)

    def active(self) -> Job | None:
        """占着名额的那一个（正在做、等网络、待生效……）。"""
        with self.lock:
            return next((j for j in self.items if j.status in BUSY), None)

    def next_queued(self) -> Job | None:
        """下一个能开始的。还在等对话结束的跳过，不挡着后面的。"""
        now = time.time()
        with self.lock:
            return next((j for j in self.items if j.status == "queued" and j.hold_until <= now), None)

    def held_until(self) -> float:
        """排着、还在等对话结束的任务里，最早的那个什么时候能开始（没有就是 0）。"""
        now = time.time()
        with self.lock:
            return min((j.hold_until for j in self.items if j.status == "queued" and j.hold_until > now), default=0.0)

    def queued(self) -> list[Job]:
        with self.lock:
            return [j for j in self.items if j.status == "queued"]

    def applied_since(self, t: float) -> list[Job]:
        """t 之后生效（或待生效）的改进：轮到排着的任务时，看它们有没有覆盖它。"""
        with self.lock:
            return [j for j in self.items if j.status in ("ready", "applying", "done") and j.finished >= t]

    def applied_chain(self) -> list[Job]:
        """现在装着的本地改进，按生效先后（撤销、回滚了的不算）。"""
        with self.lock:
            return sorted((j for j in self.items if j.status == "done" and j.applied), key=lambda j: j.applied)

    def recent(self, n: int = 8) -> list[Job]:
        with self.lock:
            return sorted(self.items, key=lambda j: j.created, reverse=True)[:n]

    def _trim(self) -> None:
        """太旧的已结束任务删掉（连同文件夹）；没结束的、装着的不删。"""
        finished = sorted((j for j in self.items if j.status in FINISHED and j.status != "done"),
                          key=lambda j: j.created)
        while len(self.items) > KEEP and finished:
            old = finished.pop(0)
            self.items.remove(old)
            shutil.rmtree(self.folder(old), ignore_errors=True)

    def drop_evidence(self, job: Job) -> None:
        """任务结束：证据（对话、屏幕上的文字、日志）删掉，只留结论和补丁。"""
        shutil.rmtree(self.folder(job) / "evidence", ignore_errors=True)
        shutil.rmtree(self.folder(job) / "base", ignore_errors=True)


def now() -> float:
    return time.time()
