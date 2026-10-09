"""引擎中枢：在一个后台 asyncio 线程里管理引擎会话，把事件以 Qt 信号交给界面。

一次对话（conversation）= 一个引擎会话：首问时整理快照 → 路由 → 打开会话 → 流式转发；追问沿用同一个会话。
- 转交：操作模式下 Claude 发现需要动界面时调用 operate_ui，这里打开（或复用）一个 Codex 会话去做，
  进度显示在界面上，结果交回 Claude。
- 学习：每轮的结束状态、你的 👍/👎、追问里的"不对"、很快又问同一个问题、问答后"照这个帮我做"、发生转交，
  都回传给路由。和能力无关的失败（网络、认证、限流、你中途停止）不计入。
- 加强：某一轮没办成，同一个对话的下一轮换更强的配置（先保证办成）。
- 后台对比：问答答完、你这边空下来以后，用路由想试的更便宜/更快的配置在后台把同一个问题再答一遍（看不到实时界面），
  请强模型对比两份回答。路由只有在这样证明"一样好"之后才会换成它，你看到的永远是当前最可靠的那份。
- 经验：提问时按这次的情况想起以前踩过的相似的坑（对不上就一条也不带）；对话结束后，走了弯路的总结成经验。
- 自我改进：没办成（不算网络之类的故障）、我们自己的代码出错、你点了 👎、按 Esc 停下并说是助手的问题，
  等这次对话结束（10 分钟没再接着问）后交给自我改进（evolve），由它分析、改进超级助手自己。
某个引擎打不开时，暂时把它排除，换另一个引擎接着做。DeepSeek Harness 是可选的替代引擎（准备窗口里选了用它才参与）。
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
import traceback
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .. import history
from ..evolve import evidence, triggers
from ..experience import learn, recall
from ..i18n import tr
from ..experience.embed import Embedder
from ..experience.semantic import Semantic
from ..experience.store import Store
from ..router import Decision, EngineRouter, Task, judge
from ..router.judge import Verdict
from ..router.policy import fg_category
from ..snapshot.collector import Context
from ..snapshot.collector import Session as Snapshot
from . import browser_use, computer, prompts
from .base import Event, friendly_error, reported_failure
from .claude import ClaudeEngine, claude_env
from .claude import complete as claude_complete
from .claude import list_models as claude_models
from .codex import CodexEngine
from .dsh import DshEngine

log = logging.getLogger(__name__)

MAX_REACTIVE = 2  # 一轮里做到一半最多再想起几次（每次最多 3 条）
REASK_S = 600     # 这么久之内又问了几乎一样的问题（同一个程序、同样的内容）：上一次多半没答好
DUEL_DELAY = 15   # 答完过一会儿再在后台对比，不跟你接着问抢
EVOLVE_DELAY = 600  # 对话结束（这么久没再接着问；Ctrl+Enter 能在 10 分钟内接着问）后再交给自我改进，证据才完整
OPEN_TIMEOUT = 90   # 打开一个引擎会话最多等这么久（秒）：Claude 冷启动约 3 秒，它自己的初始化最多等 60 秒
STOP_GRACE = 10     # 按 Esc 后给引擎自己停下的时间（秒），过了还在跑就直接结束这一轮
STOPPED = {"ok": False, "stopped": True, "reason": "interrupted"}


SLOW_STEP = 20  # 一步用了这么久（秒）就在记录里写上，看得出卡在哪儿


def _note_slow_step(trace: list[str], seconds: float) -> None:
    if seconds >= SLOW_STEP and not trace[-1].endswith("秒）"):
        trace[-1] += f"（这一步用了 {seconds:.0f} 秒）"


def _counted(done: dict) -> bool:
    """这一轮的结果算不算数：你中途停止、网络或认证问题、接口故障、浏览器操作没接通，都和能力无关。"""
    return not triggers.is_infra(done)


def _crash(e: BaseException) -> dict:
    """引擎或我们自己的代码抛了异常：这一轮的结束事件带上异常的类型和内容（分得清是网络问题还是代码问题）。"""
    return {"ok": False, "error": friendly_error(e), "exception": f"{type(e).__name__}: {e}"[:500]}


@dataclass
class Conversation:
    key: str
    mode: str
    task: Task
    decision: Decision | None = None
    session: object | None = None   # ClaudeSession | CodexSession
    ctx: Context | None = None       # 最近一次的环境
    delegate: object | None = None  # 转交用的 Codex 会话
    delegated: bool = False          # 这一轮里发生过转交
    busy: bool = False      # 在处理一问：从提交起（整理快照、打开引擎也算），到这一轮结束
    sending: bool = False   # 引擎正在回答（这时按 Esc 先请它自己停下）
    job: asyncio.Task | None = None  # 处理这一问的任务：还在准备、或者引擎停不下来时，按 Esc 直接取消它
    turns: list[dict] = field(default_factory=list)
    home: Path | None = None  # 首问的会话文件夹，问答记录（历史）存在这里
    question: str = ""        # 正在回答的这一问
    record: list[dict] = field(default_factory=list)
    situation: dict = field(default_factory=dict)  # 这一问的情况（想经验、总结经验用）
    seen: set[str] = field(default_factory=set)    # 这次对话里已经想起过的经验，不重复给
    turn_lessons: list[str] = field(default_factory=list)  # 这一轮交给引擎的经验
    last_lessons: list[str] = field(default_factory=list)  # 上一轮交给引擎的经验（事后反馈用）
    negative: bool = False  # 你说过上一轮没答好
    reactive: int = 0       # 这一轮做到一半又想起了几次
    learned: int = 0        # 已经总结到第几轮
    learn_timer: object | None = None
    started: float = field(default_factory=time.time)
    first: tuple | None = None  # 首问原样的（问题, 消息, 图片）：后台对比用同一份再答一遍
    escalate: bool = False      # 上一轮没办成：下一轮换更强的配置
    stopped: bool = False       # 这一轮是你按 Esc 停下的
    trouble: list[dict] = field(default_factory=list)  # 这次对话里要交给自我改进的信号（没办成、👎、停下的原因）
    evolve_timer: object | None = None


class EngineHub(QObject):
    #: (对话 key, 事件字典)。从后台线程发出，Qt 自动排队到主线程。
    event = Signal(str, dict)
    #: 模型发现的结果：{"found": {引擎: [模型名]}, "errors": [说明]}
    models_found = Signal(dict)

    def __init__(self, router: EngineRouter, instructions: str, blocklist: bool) -> None:
        super().__init__()
        self.router = router
        self.lessons = Store()
        # 本地向量模型：意思相近、字面不同的经验也能想起来。模型在后台下载，好了之前只按字面
        self.semantic = Semantic(Embedder(), self.lessons.path.with_name("vectors.json"))
        # 操作界面用谁的：Codex 官方账号 → 官方的（Claude 转交给它）；否则两边都用自研的 computer 工具
        self.gui = "official" if computer.official_codex() else "ours"
        blocked = lambda: list(router.cfg.blocked_apps)  # noqa: E731 - 设置里改了隐私名单，新会话就用新的
        self.engines = {"claude": ClaudeEngine(instructions, blocklist, self.gui, blocked),
                        "codex": CodexEngine(instructions, blocklist, self.gui, blocked),
                        "dsh": DshEngine(instructions, blocked)}
        log.info("界面操作：%s", "Codex 官方的 Computer Use / Browser Use" if self.gui == "official"
                 else "自研的 Computer Use / Browser Use（两个引擎共用）")
        self.conversations: dict[str, Conversation] = {}
        self._last: dict[str, Conversation] = {}  # 每种模式最近一次提问（看是不是很快又问了一样的）
        self._duel_lock = asyncio.Lock()  # 后台对比一次只跑一个
        self.evolve = None  # 自我改进（EvolveManager），由外面接上
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="engines", daemon=True)
        self.thread.start()

    # ---- 主线程调用的接口 ----

    def warm_up(self) -> None:
        self._submit(self._warm_up())

    def refresh(self, names: set[str]) -> None:
        """准备窗口里改了这些引擎的登录或服务地址：丢掉按旧配置建好的连接，下次按新配置连。"""
        async def reload() -> None:
            for name in names:
                await self.engines[name].reload()

        self._submit(reload())

    def reconfigure(self, ready: list[str] | None = None) -> None:
        """可被路由的模型（或配好了模型的引擎）改了：在引擎线程里重建路由（路由的读写都在这个线程里，不会读到一半）。"""
        def apply() -> None:
            if ready is not None:
                self.router.set_ready(ready)
            self.router.rebuild()

        self.loop.call_soon_threadsafe(apply)

    def discover_models(self) -> None:
        self._submit(self._discover_models())

    def ask(self, key: str, mode: str, question: str, snap: Snapshot, task: Task) -> None:
        conv = Conversation(key=key, mode=mode, task=task, busy=True)
        self.conversations[key] = conv
        self._submit(self._first_turn(conv, question, snap))

    def followup(self, key: str, question: str, snap: Snapshot) -> None:
        conv = self.conversations.get(key)
        if conv is None or conv.session is None:
            self._emit(key, Event("error", tr("这个对话已经结束，请重新提问。")))
            return
        conv.busy, conv.stopped = True, False
        self._submit(self._followup(conv, question, snap))

    def feedback(self, key: str, good: bool, source: str = "feedback") -> None:
        conv = self.conversations.get(key)
        if conv is not None and conv.decision is not None:
            self.loop.call_soon_threadsafe(self.router.record, conv.decision, conv.task, good, source)
        if conv is not None and not good:
            self.loop.call_soon_threadsafe(self._bad_turn, conv)
            if source == "feedback":  # 你亲手点的 👎：这次任务没办好，交给自我改进（原因可以之后补上）
                self.loop.call_soon_threadsafe(self._note_trouble, conv, {"kind": "thumbs_down"})

    def reason(self, key: str, kind: str, choice: str, text: str) -> None:
        """你给的原因：按 Esc 停下以后（kind=stop），或者点了 👎 以后（kind=bad）。"""
        conv = self.conversations.get(key)
        if conv is not None:
            self.loop.call_soon_threadsafe(self._on_reason, conv, kind, choice, text.strip()[:1000])

    def interrupt(self, key: str) -> None:
        conv = self.conversations.get(key)
        if conv is None or not conv.busy:
            return
        conv.stopped = True  # 引擎被打断后可能仍报"正常结束"：这一轮按你停下的算，不当成没办成
        self._submit(self._stop(conv))

    def is_busy(self, key: str) -> bool:
        conv = self.conversations.get(key)
        return bool(conv and conv.busy)

    def shutdown(self) -> None:
        async def close_all() -> None:
            for engine in self.engines.values():
                await engine.close()

        try:
            self._submit(close_all()).result(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)

    # ---- 后台线程 ----

    def _submit(self, coro) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _emit(self, key: str, event: Event) -> None:
        self.event.emit(key, event.as_dict())

    async def _warm_up(self) -> None:
        self.semantic.embedder.ensure()  # 没下载就在后台下载（下好会顺手加载）；已经有了就提前加载，第一问不用等
        asyncio.get_running_loop().run_in_executor(None, self.semantic.ready)
        ready = self.router.available()
        claude, effort = self.router.warm_target("claude") if "claude" in ready else ("", "")  # 一般问题最可能用到的配置
        codex = self.router.best_model("codex") if "codex" in ready else ""
        await self.engines["claude"].prune({m.id for m in self.router.models["claude"]} if claude else set())
        jobs = []
        if claude:
            jobs.append(self.engines["claude"].warm("ask", claude, effort))
        if codex:
            jobs.append(self.engines["codex"].warm("ask"))
            if self.gui == "official":
                jobs.append(self.engines["codex"].prime(codex))
        if "dsh" in ready:
            jobs.append(self.engines["dsh"].warm("ask"))
        await asyncio.gather(*jobs)

    async def _discover_models(self) -> None:
        """两边各自能用的模型。新发现的由主线程加进配置（默认关闭）。"""
        found: dict[str, list[str]] = {}
        errors: list[str] = []
        cfg = self.router.cfg
        ready = self.router.ready
        if cfg.codex.enabled and (ready is None or "codex" in ready):
            try:
                client = await self.engines["codex"].client("ask")
                listed = (await client.models()).data
                found["codex"] = [m.id for m in listed]
                # 每个模型支持哪几档思考强度、一句说明（看得出是旗舰、主力还是轻量）：路由只在合法的档里选
                value = lambda x: str(getattr(x, "value", x))  # noqa: E731
                self.router.update_models("codex", {m.id: {
                    "efforts": [value(o.reasoning_effort) for o in m.supported_reasoning_efforts],
                    "default": value(m.default_reasoning_effort), "desc": m.description or "",
                    "upgrade": m.upgrade or ""} for m in listed})
            except Exception as e:  # noqa: BLE001
                log.warning("获取 Codex 模型列表失败：%s", e)
                errors.append(tr("{engine}：{error}", engine="Codex", error=friendly_error(e)))
        if cfg.claude.enabled and (ready is None or "claude" in ready):
            try:
                found["claude"] = await asyncio.get_running_loop().run_in_executor(None, claude_models)
            except Exception as e:  # noqa: BLE001
                log.warning("获取 Claude 模型列表失败：%s", e)
                errors.append(tr("{engine}：{error}", engine="Claude", error=friendly_error(e)))
        if cfg.dsh.enabled and (ready is None or "dsh" in ready):
            try:
                listed = await self.engines["dsh"].models()
                if listed:
                    found["dsh"] = [m["id"] for m in listed]
                    self.router.update_models("dsh", {m["id"]: {k: v for k, v in m.items() if k != "id"}
                                                      for m in listed})
            except Exception as e:  # noqa: BLE001
                log.warning("获取 DeepSeek Harness 模型列表失败：%s", e)
                errors.append(tr("{engine}：{error}", engine="DeepSeek Harness", error=friendly_error(e)))
        self.models_found.emit({"found": found, "errors": errors})

    async def _first_turn(self, conv: Conversation, question: str, snap: Snapshot) -> None:
        conv.job = asyncio.current_task()
        conv.home, conv.question = snap.dir, question
        loop = asyncio.get_running_loop()
        answering = False
        try:
            conv.ctx = await loop.run_in_executor(None, snap.finalize)
            conv.task.url = snap.url
            situation = snap.situation(question)
            # 路由判断难度看屏幕上框选的内容和报错；找相似的旧任务用问题的向量（向量模型没好就不用）
            conv.task.context, conv.task.errors = situation.text, situation.errors
            lessons = await loop.run_in_executor(None, self._recall, conv, situation)
            conv.task.vec = await loop.run_in_executor(None, self._vector, question, situation.text)
            self._check_reask(conv)
            await self._open(conv)
            message = prompts.first_message(question, conv.ctx, conv.mode, self._notes(conv), lessons)
            conv.first = (question, message, list(conv.ctx.images))
            answering = True
            await self._turn(conv, message, conv.ctx.images)
        except asyncio.CancelledError:
            if not answering:  # 还在准备（整理快照、打开引擎）时按了 Esc。回答中途停下的结束由 _turn 报
                self._drop_sessions(conv)  # 问题还没交给引擎：这个对话不再接着问
                self._emit(conv.key, Event("done", data=dict(STOPPED)))
        except Exception as e:  # noqa: BLE001
            log.exception("首问失败")
            self._emit(conv.key, Event("error", friendly_error(e)))
            self._emit(conv.key, Event("done", data=_crash(e)))
            self._crashed(conv, e)
        finally:
            conv.busy, conv.job = False, None

    async def _open(self, conv: Conversation) -> None:
        while True:
            decision = self.router.decide(conv.task)
            conv.decision = decision
            self._emit(conv.key, Event("route", data={
                "engine": decision.engine, "model": decision.model, "effort": decision.effort,
                "via": decision.via, "explore": decision.explore, "reason": decision.reason}))
            try:
                # 有时间上限：打开卡住时（2026-10-09 实测卡死过）换另一个引擎，不能让你一直等
                conv.session = await asyncio.wait_for(
                    self.engines[decision.engine].open(conv.mode, decision.model, decision.effort), OPEN_TIMEOUT)
                slot = getattr(conv.session, "slot", None)  # Claude 的会话：转交、想起经验的入口在这里接上这个对话
                if slot is not None:
                    slot.remember = lambda text, c=conv: self._recall_more(c, text)
                    slot.lookup = lambda query, c=conv: self._recall_query(c, query)
                    if conv.mode == "act" and self.gui == "official":
                        slot.fn = lambda task, c=conv: self._delegate(c, task)
                return
            except Exception as e:  # noqa: BLE001
                log.warning("%s 打不开：%s", decision.engine, str(e) or type(e).__name__)
                self.router.mark_unavailable(decision.engine)
                if not self.router.available():
                    raise
                self._emit(conv.key, Event("status", tr("{error} 换一个引擎接着做…", error=friendly_error(e))))

    async def _followup(self, conv: Conversation, question: str, snap: Snapshot) -> None:
        conv.job = asyncio.current_task()
        conv.question = question
        answering = False
        try:
            conv.ctx = await asyncio.get_running_loop().run_in_executor(None, snap.finalize)
            lessons = await asyncio.get_running_loop().run_in_executor(None, self._recall, conv,
                                                                       snap.situation(question))
            await self._escalate(conv)
            answering = True
            await self._turn(conv, prompts.followup_message(question, conv.ctx, conv.mode, self._notes(conv), lessons),
                             conv.ctx.images)
        except asyncio.CancelledError:
            if not answering:  # 还在准备时按了 Esc：会话没动过，还能接着问
                self._emit(conv.key, Event("done", data=dict(STOPPED)))
        except Exception as e:  # noqa: BLE001
            log.exception("追问失败")
            self._emit(conv.key, Event("error", friendly_error(e)))
            self._emit(conv.key, Event("done", data=_crash(e)))
            self._crashed(conv, e)
        finally:
            conv.busy, conv.job = False, None

    def _browser_status(self, conv: Conversation) -> browser_use.Status | None:
        """用 Codex 官方的浏览器操作、操作模式、前台是浏览器、而它没接通时，返回原因和修法。
        用自研的时候浏览器直接能操作，不需要接通什么。"""
        if self.gui != "official" or conv.mode != "act" or fg_category(conv.task.foreground) != "browser":
            return None
        status = browser_use.status(conv.task.foreground)
        return None if status.ready else status

    def _browser_problem(self, conv: Conversation) -> str:
        """浏览器操作没接通时给你看的原因和修法（按界面语言）；接通了或用不上是空。"""
        status = self._browser_status(conv)
        return status.problem if status else ""

    def _notes(self, conv: Conversation) -> list[str]:
        status = self._browser_status(conv)
        if status is None:
            return []
        return [f"{status.note}这次需要操作浏览器里的网页时，不要尝试 Browser Use；可以试 Computer Use，"
                "但它可能因为确定不了当前网址而停下。办不成就在汇报第一行写「没完成：浏览器操作还没接通」。"]

    async def _turn(self, conv: Conversation, text: str, images: list) -> None:
        conv.busy, conv.sending, conv.delegated = True, True, False
        if conv.learn_timer is not None:
            conv.learn_timer.cancel()  # 还在接着问：等这次对话结束了再总结
        conv.reactive = 0
        answer, trace, started = "", [], time.monotonic()
        step_started = started
        finished = False
        try:
            async for ev in conv.session.send(text, images):
                transient = ev.data.get("transient")  # "正在思考…"：只在界面上显示，不算一步
                if ev.type in ("status", "done") and trace and not transient:
                    _note_slow_step(trace, time.monotonic() - step_started)
                if ev.type in ("new_message", "retract"):
                    answer = ""
                elif ev.type == "delta":
                    answer += ev.text
                elif ev.type == "status" and ev.text and not transient and (not trace or trace[-1] != ev.text):
                    trace.append(ev.text)  # 助手做了哪些步骤：总结经验时用来看它绕没绕路
                    step_started = time.monotonic()
                elif ev.type == "done":
                    finished = True
                    ev.data.setdefault("model", conv.decision.model if conv.decision else "")
                    ev.data["delegated"] = conv.delegated
                    ev.data.update(seconds=round(time.monotonic() - started), tools=len(trace))
                    if conv.stopped:
                        ev.data.update(stopped=True, reason="interrupted")
                    else:
                        self._check_outcome(conv, ev.data, answer)
                    self._watch_outcome(conv, ev.data)
                    conv.turns.append(ev.data)
                    self._learn_from_turn(conv, ev.data)
                    if len(conv.turns) == 1:
                        self._after_first_turn(conv, ev.data, answer)
                    self._lessons_used(conv, ev.data)
                    self._save_history(conv, ev.data, answer, trace)
                self._emit(conv.key, ev)
            if not finished:  # 比如 CLI 中途退出、退出码却是 0：输出就这么断了。界面不能一直等着
                raise ConnectionError(tr("引擎没给出结果就断开了"))
        except asyncio.CancelledError:
            if not finished:  # 按了 Esc，引擎过了 STOP_GRACE 秒还在跑：直接结束这一轮
                done = dict(STOPPED, seconds=round(time.monotonic() - started), tools=len(trace))
                conv.turns.append(done)
                self._lessons_used(conv, done)
                self._save_history(conv, done, answer, trace)
                self._emit(conv.key, Event("done", data=done))
                self._drop_sessions(conv)  # 引擎可能还停在半路：不再用这个会话，接着问会说对话已经结束
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("引擎出错")
            self._emit(conv.key, Event("error", friendly_error(e)))
            self._emit(conv.key, Event("done", data=_crash(e) | ({"stopped": True} if conv.stopped else {})))
            if not conv.stopped:
                self._crashed(conv, e)
        finally:
            conv.busy = conv.sending = False
            self._schedule_learning(conv)
            self._schedule_evolve(conv)

    async def _stop(self, conv: Conversation) -> None:
        """按了 Esc。引擎正在回答：先请它自己停下（会话还能接着问），过了 STOP_GRACE 秒还在跑就直接结束这一轮；
        还在准备（整理快照、打开引擎）：直接结束。"""
        job = conv.job
        if job is None or job.done():
            return
        if conv.sending:
            for session in (conv.session, conv.delegate):
                if session is not None:
                    self.loop.create_task(self._ask_to_stop(session))
            await asyncio.wait({job}, timeout=STOP_GRACE)
            if job.done():
                return
            log.warning("按了 Esc，引擎 %d 秒还没停下：直接结束这一轮", STOP_GRACE)
        job.cancel()

    @staticmethod
    async def _ask_to_stop(session) -> None:
        try:
            await session.interrupt()
        except Exception as e:  # noqa: BLE001 - 它不回应的话，过一会儿直接结束这一轮
            log.warning("请引擎停下失败：%s", str(e) or type(e).__name__)

    def _drop_sessions(self, conv: Conversation) -> None:
        for session in (conv.session, conv.delegate):
            if session is not None:
                self.loop.create_task(session.close())
        conv.session = conv.delegate = None

    def _check_outcome(self, conv: Conversation, done: dict, answer: str) -> None:
        """操作模式下，回合正常结束不等于事情办成了：看汇报第一行。没办成是因为浏览器操作没接通时，附上修法。"""
        if conv.mode != "act" or not done.get("ok"):
            return
        failure = reported_failure(answer)
        if not failure:
            return
        done.update(ok=False, error=failure, reason="reported")
        problem = self._browser_problem(conv)
        if problem:
            done["hint"] = problem

    def _save_history(self, conv: Conversation, done: dict, answer: str, trace: list[str] | None = None) -> None:
        if conv.home is None:
            return
        d = conv.decision
        conv.record.append({
            "t": datetime.now().isoformat(timespec="seconds"), "question": conv.question,
            "answer": answer.strip(), "ok": bool(done.get("ok")),
            "error": done.get("hint") or done.get("error") or "", "reason": done.get("reason", ""),
            "engine": d.engine if d else "", "model": d.model if d else "", "effort": d.effort if d else "",
            "seconds": done.get("seconds", 0), "tools": done.get("tools", 0), "trace": (trace or [])[:60],
            "lessons": conv.last_lessons, "situation": conv.situation,
        })
        try:
            history.save(conv.home, {"mode": conv.mode, "started": conv.record[0]["t"],
                                     "foreground": conv.task.foreground, "turns": conv.record})
        except OSError as e:
            log.warning("保存历史记录失败：%s", e)

    # ---- 经验 ----

    def _recall(self, conv: Conversation, situation: recall.Situation) -> list:
        """想起和这次情况相似的经验（这次对话里给过的不再给）。对不上就是空列表，首条消息里什么也不加。"""
        conv.situation = {"text": situation.text[:3000], "errors": situation.errors[:2000], "app": situation.app,
                          "url": situation.url, "title": situation.title}
        try:
            found = recall.recall(self.lessons, situation, exclude=conv.seen, semantic=self.semantic)
        except Exception as e:  # noqa: BLE001 - 想不起来也不能耽误回答
            log.warning("想起经验失败：%s", e)
            return []
        conv.turn_lessons = [x.id for x in found]
        conv.seen.update(conv.turn_lessons)
        if found:
            log.info("想起经验：%s", "；".join(x.title for x in found))
            self._emit(conv.key, Event("status", tr("想起以前的经验：{title}", title=found[0].title)))
        return found

    def _recall_more(self, conv: Conversation, text: str) -> str:
        """做到一半，工具结果里出现了报错：再想一次。这一轮最多再想 MAX_REACTIVE 次，给过的不重复。"""
        if conv.reactive >= MAX_REACTIVE:
            return ""
        env = conv.situation
        situation = recall.Situation(question=conv.question, text=text[:6000], app=env.get("app", ""),
                                     url=env.get("url", ""), title=env.get("title", ""))
        found = recall.recall(self.lessons, situation, exclude=conv.seen, semantic=self.semantic)
        if not found:
            return ""
        conv.reactive += 1
        ids = [x.id for x in found]
        conv.seen.update(ids)
        conv.turn_lessons += ids
        log.info("做到一半想起经验：%s", "；".join(x.title for x in found))
        self._emit(conv.key, Event("status", tr("想起以前的经验：{title}", title=found[0].title)))
        return ("【以前踩过的坑】刚才的结果里有报错。以前遇到相似情况时总结的经验，只在和这次情况相符时参考：\n"
                + recall.render(found))

    def _recall_query(self, conv: Conversation, query: str) -> str:
        """模型主动问（recall 工具）。问到的就算用过，结果跟着这一轮记。"""
        env = conv.situation
        found = recall.recall(self.lessons, recall.Situation(question=query, app=env.get("app", ""),
                                                             url=env.get("url", "")), semantic=self.semantic)
        new = [x.id for x in found if x.id not in conv.turn_lessons]
        conv.seen.update(new)
        conv.turn_lessons += new
        return recall.render(found)

    def _lessons_used(self, conv: Conversation, done: dict) -> None:
        self.lessons.used(conv.turn_lessons, bool(done.get("ok")) if _counted(done) else None)
        conv.last_lessons, conv.turn_lessons = conv.turn_lessons, []

    def _bad_turn(self, conv: Conversation) -> None:
        """你说上一轮没答好：给它出主意的经验记一次失败，这次对话也值得总结。"""
        conv.negative = True
        conv.escalate = True  # 接着问的时候换更强的配置
        self.lessons.failed(conv.last_lessons)

    def _schedule_learning(self, conv: Conversation) -> None:
        if conv.learn_timer is not None:
            conv.learn_timer.cancel()
        conv.learn_timer = self.loop.call_later(learn.LEARN_DELAY, lambda: self.loop.create_task(self._learn(conv)))

    async def _learn(self, conv: Conversation) -> None:
        """对话结束后：走了弯路的总结成经验，顺利的不总结。"""
        conv.learn_timer = None
        if conv.busy or conv.learned >= len(conv.record):
            return
        reason = learn.worth_learning(conv.record, conv.negative)
        if not reason:
            return
        conv.learned = len(conv.record)
        try:
            result = await learn.learn(self.lessons, conv.record, reason, self._complete,
                                       "说了“不对”或者点了 👎" if conv.negative else "",
                                       source=conv.home.name if conv.home else "", semantic=self.semantic)
            log.info("经验：%s", result)
        except Exception as e:  # noqa: BLE001 - 总结不出来不影响使用
            log.warning("总结经验失败：%s", friendly_error(e))

    async def _complete(self, prompt: str, schema: dict | None = learn.SCHEMA) -> str:
        """后台小活的一次性模型调用：有 Claude 就直接调它的接口（快、不起进程），没有再用 Codex，最后是 DSH。"""
        ready = self.router.available()
        claude = self.router.best_model("claude") if "claude" in ready else ""
        if claude and claude_env():
            try:
                return await asyncio.get_running_loop().run_in_executor(None, claude_complete, prompt, claude)
            except Exception as e:  # noqa: BLE001
                log.warning("用 Claude 总结经验失败：%s", friendly_error(e))
        codex = self.router.best_model("codex") if "codex" in ready else ""
        if codex:
            return await self.engines["codex"].complete(prompt, codex, schema)
        dsh = self.router.best_model("dsh") if "dsh" in ready else ""
        if dsh:
            return await self.engines["dsh"].complete(prompt, dsh, schema)
        raise RuntimeError(tr("没有可用的模型"))

    def _learn_from_turn(self, conv: Conversation, done: dict) -> None:
        if conv.decision is None:
            return
        if not _counted(done):
            return  # 和能力无关：你中途停止、网络或认证问题、浏览器操作没接通
        ok = bool(done.get("ok"))
        self.router.record(conv.decision, conv.task, ok, "status_ok" if ok else "status_fail")
        if not ok:
            conv.escalate = True  # 接着问的时候换更强的配置
        if conv.delegated:
            # 这类任务它需要别人帮忙动界面：下次同类任务直接交给能动界面的引擎更快
            self.router.record(conv.decision, conv.task, False, "delegated")

    # ---- 自我改进：攒下这次对话里的信号，对话结束后交出去 ----

    def _watch_outcome(self, conv: Conversation, done: dict) -> None:
        """这一轮没办成（而且不是网络之类的故障）：记一个信号。前台被限流时告诉自我改进先让一让。"""
        if done.get("api_error_status") == 429 and self.evolve is not None:
            self.evolve.on_rate_limited()
        if not done.get("ok") and _counted(done):
            self._note_trouble(conv, {"kind": "failure", "error": str(done.get("error") or "")[:500],
                                      "reason": str(done.get("reason") or "")})

    def _crashed(self, conv: Conversation, e: BaseException) -> None:
        """我们自己的代码（或引擎）抛了异常：不是网络之类的故障就记一个信号，带上调用栈。"""
        if not triggers.exception_is_infra(e):
            self._note_trouble(conv, {"kind": "exception", "error": f"{type(e).__name__}: {e}"[:500],
                                      "traceback": traceback.format_exc()[-6000:]})

    def _on_reason(self, conv: Conversation, kind: str, choice: str, text: str) -> None:
        if kind == "stop":
            if triggers.stop_counts(choice, text):  # 不答、"不是助手的问题"、"改主意了"都不算
                self._note_trouble(conv, {"kind": "stopped", "choice": choice, "text": text})
            return
        for item in reversed(conv.trouble):  # 👎 的原因补到那个信号上（已经交出去的，补给那个任务）
            if item.get("kind") == "thumbs_down":
                item.update(choice=choice, text=text)
                return
        if self.evolve is not None:
            self.evolve.add_reason(conv.key, choice, text)

    def _note_trouble(self, conv: Conversation, item: dict) -> None:
        item.setdefault("t", time.time())
        conv.trouble.append(item)
        self._schedule_evolve(conv)

    def _schedule_evolve(self, conv: Conversation) -> None:
        if getattr(self, "evolve", None) is None or not conv.trouble:
            return
        if conv.evolve_timer is not None:
            conv.evolve_timer.cancel()
        conv.evolve_timer = self.loop.call_later(EVOLVE_DELAY, self._hand_to_evolve, conv)

    def _hand_to_evolve(self, conv: Conversation) -> None:
        conv.evolve_timer = None
        if conv.busy:
            self._schedule_evolve(conv)
            return
        trouble, conv.trouble = conv.trouble, []
        if not trouble or self.evolve is None:
            return
        try:
            self.evolve.submit(evidence.capture(conv, trouble))
        except Exception:  # noqa: BLE001 - 交不出去不影响使用
            log.exception("交给自我改进失败")

    # ---- 路由：看任务、加强、后台对比 ----

    def _vector(self, question: str, text: str):
        """问题（带一点屏幕内容）的向量。向量模型还没加载好就算了，不等它。"""
        embedder = self.semantic.embedder
        if not embedder.loaded():
            return None
        try:
            vecs = embedder.encode([f"{question}\n{text[:400]}"], "query")
        except Exception as e:  # noqa: BLE001
            log.warning("算问题的向量失败：%s", e)
            return None
        return None if vecs is None else vecs[0]

    def _check_reask(self, conv: Conversation) -> None:
        """很快又问了几乎一样的问题（同一个程序、同样的屏幕内容）：上一次多半没答好，记一次失败。"""
        prev, self._last[conv.mode] = self._last.get(conv.mode), conv
        if prev is None or prev.decision is None or conv.started - prev.started > REASK_S:
            return
        if prev.situation.get("app") != conv.situation.get("app"):
            return

        def same(a: str, b: str) -> bool:
            return SequenceMatcher(None, a, b).ratio() >= 0.8

        if same(prev.question, conv.question) and same(prev.situation.get("text", "")[:500],
                                                        conv.situation.get("text", "")[:500]):
            self.router.record(prev.decision, prev.task, False, "reask")
            log.info("很快又问了一样的问题：上一次（%s · %s）记一次没答好", prev.decision.model, prev.decision.effort)

    def _after_first_turn(self, conv: Conversation, done: dict, answer: str) -> None:
        """首问答完：用实际耗时校准路由的快慢估计；问答答得好好的，再看要不要在后台对比一次。"""
        if conv.decision is None or not _counted(done) or not done.get("ok"):
            return
        self.router.observe(conv.decision, float(done.get("seconds") or 0), done.get("cost"))
        if conv.mode != "ask" or conv.first is None or not answer.strip():
            return
        candidate = self.router.duel_candidate(conv.decision)
        if candidate is not None:
            self.router.count_duel()  # 先记上：失败了也算一次，免得一直重试
            self.loop.create_task(self._duel(conv, conv.decision, candidate, answer))

    async def _escalate(self, conv: Conversation) -> None:
        """上一轮没办成：这一轮换更强的配置（同一个引擎，对话接着来）。"""
        if not conv.escalate or conv.decision is None or conv.session is None:
            return
        conv.escalate = False
        stronger = self.router.escalate(conv.decision, conv.task)
        if stronger is None:
            return
        try:
            conv.session = await self.engines[stronger.engine].switch(conv.session, conv.mode, stronger.model,
                                                                        stronger.effort)
        except Exception as e:  # noqa: BLE001 - 换不了就接着用原来的
            log.warning("换更强的配置失败，接着用原来的：%s", e)
            return
        conv.decision = stronger
        log.info("上一轮没办成，换成 %s · %s", stronger.model, stronger.effort)
        self._emit(conv.key, Event("route", data={
            "engine": stronger.engine, "model": stronger.model, "effort": stronger.effort,
            "via": stronger.via, "explore": False, "reason": stronger.reason}))
        self._emit(conv.key, Event("status", tr("上一轮没办成，这次加强：{model} · {effort}", model=stronger.model,
                                                effort=stronger.effort)))

    async def _duel(self, conv: Conversation, served: Decision, candidate: Decision, answer: str) -> None:
        """后台对比：等你这边空下来，用候选配置把首问原样再答一遍（只读，看不到实时界面），再请强模型评两份回答。"""
        async with self._duel_lock:
            await asyncio.sleep(DUEL_DELAY)
            for _ in range(60):  # 你在用助手时不跟你抢，最多等 10 分钟
                if not any(c.busy for c in self.conversations.values()):
                    break
                await asyncio.sleep(10)
            else:
                return
            question, message, images = conv.first
            session, text, done = None, "", {}
            try:
                engine = self.engines[candidate.engine]
                if candidate.engine == "claude":
                    session = await engine.open("duel", candidate.model, candidate.effort, rewarm=False)
                else:
                    session = await engine.open("duel", candidate.model, candidate.effort)
                async for ev in session.send(message, images):
                    if ev.type in ("new_message", "retract"):
                        text = ""
                    elif ev.type == "delta":
                        text += ev.text
                    elif ev.type == "done":
                        done = ev.data
                if not _counted(done):
                    return  # 网络、限流之类：和能力无关
                if not done.get("ok") or not text.strip():
                    self.router.record(candidate, conv.task, False, "duel")
                    return
                verdict = await self._judge(question, conv, answer, text)
                if verdict is not None:
                    self.router.record_duel(served, candidate, conv.task, verdict)
                    log.info("后台对比 %s · %s vs %s · %s：%s / %s（%s）", served.model, served.effort, candidate.model,
                             candidate.effort, verdict.served, verdict.candidate, verdict.why)
            except Exception as e:  # noqa: BLE001 - 对比失败不影响使用
                log.warning("后台对比失败：%s", friendly_error(e))
                if not triggers.exception_is_infra(e):
                    self.router.record(candidate, conv.task, False, "duel")  # 比如这个模型根本用不了：别一直试它
            finally:
                if session is not None:
                    await session.close()

    async def _judge(self, question: str, conv: Conversation, served: str, candidate: str) -> Verdict | None:
        flip = random.random() < 0.5  # 两份随机排前后
        context = "\n".join(x for x in (conv.situation.get("text", ""), conv.situation.get("errors", "")) if x)
        try:
            text = await self._complete(judge.prompt(question, context, served, candidate, flip), judge.SCHEMA)
        except Exception as e:  # noqa: BLE001
            log.warning("后台对比的评审失败：%s", friendly_error(e))
            return None
        return judge.parse(text, flip)

    async def _delegate(self, conv: Conversation, task: str) -> str:
        """Claude 调用 operate_ui：交给 Codex 操作界面，返回 Codex 的说明。"""
        model = self.router.best_model("codex")
        if not model or "codex" not in self.router.available():
            return "现在没有可用的 Codex，没法操作界面。请把需要在界面上做的步骤告诉用户。"
        conv.delegated = True  # "交给 Codex 操作界面…"这行状态由 Claude 的工具调用事件显示
        try:
            first = conv.delegate is None
            if first:
                conv.delegate = await self.engines["codex"].open("act", model, "high")
            images = conv.ctx.images if first and conv.ctx else []
            text, ok, error = "", False, ""
            message = prompts.delegate_message(task, conv.ctx if first else None, self._notes(conv))
            async for ev in conv.delegate.send(message, images):
                if ev.type == "status":
                    self._emit(conv.key, ev)
                elif ev.type in ("new_message", "retract"):
                    text = ""
                elif ev.type == "delta":
                    text += ev.text
                elif ev.type == "error":
                    error = ev.text
                elif ev.type == "done":
                    ok = bool(ev.data.get("ok"))
                    error = error or ev.data.get("error", "")
            failure = reported_failure(text) if ok else ""
            if failure:
                ok, error = False, failure
            if not (failure and self._browser_problem(conv)):  # 浏览器操作没接通不算 Codex 不行
                self.router.record(conv.decision, conv.task, ok, "delegate_result", engine="codex")
            if ok:
                return text.strip() or "（已完成，没有额外说明）"
            return f"没能完成：{error or text.strip() or '原因不明'}。请改用别的办法，或把步骤告诉用户。"
        except Exception as e:  # noqa: BLE001
            log.exception("转交失败")
            return f"转交失败：{friendly_error(e)}。请把需要在界面上做的步骤告诉用户。"
