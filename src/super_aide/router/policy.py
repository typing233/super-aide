"""智能路由：每次自动定"交给哪个引擎、用哪个模型、思考多深"。原则：先保证办成，再求快、求省。

一次决策（纯本地，几毫秒）：
1. 候选：可用引擎里打开的每个模型 × 它支持的每一档思考强度（不超过设置里的上限，见 catalog.py）。
2. 先验：模型档次（旗舰 / 主力 / 轻量）对任务难度。难度看问题，再加上屏幕上框选的内容和报错（只看问题的话，
   助手的问题大多很短，几乎全被当成简单题，实测 0.10～0.16）；屏幕上的内容只能让难度变高，不能变低。
   每个模型有一档"参照强度"：问答 medium / high / xhigh，操作 high / xhigh / max（按难度，两个引擎同一把尺子，
   不低于 Claude Code 5.5 系列的默认 medium）。低于参照的每一档先验扣一点，高于参照不加分（边际递减）。
3. 证据：学习记录里和这次任务相关的结果（evidence.py）加上先验，得到每个配置成功率的 Beta 后验。
4. 参照：默认是先验最强的那个（两边一样时选更快的）。只有证据表明别的配置大概率明显更好
   （七成把握好 3 个百分点以上）才换过去：同一类任务上失败一次就会升一档思考强度或换引擎，
   别的类型上偶尔一次失败不会（不来回摇摆）。失败只往下传（高档办不成，低档也算办不成）。
5. 降级要过关（非劣效检验）：更便宜的配置，只有"成功率比参照低不到 3 个百分点"的把握达到 90%、
   它自己有足够的真实结果（只靠先验不行）、而且能省下至少 15%，才会被选上。冷启动永远用最强的，便宜的一失败就退回。
问答模式不在你面前试便宜的配置：答完以后在后台用便宜的配置把同一个问题再答一遍，由强模型对比（judge.py）。
操作有副作用，不试。某一轮没办成时，同一个对话的下一轮自动换更强的配置（escalate）。
模型服务出了问题（这个模型用不了、限流、过载、断网）：出问题的模型或整个引擎先放一边，换能用的接着做（sideline）。
"""

from __future__ import annotations

import json
import logging
import math
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .. import paths
from ..config import EFFORTS, ENGINES, Config
from . import catalog
from .catalog import Profile
from .evidence import Evidence, Outcome
from .judge import Verdict

log = logging.getLogger(__name__)

MODES = ("ask", "act")

DEV_TOOLS = {
    "code.exe", "cursor.exe", "windowsterminal.exe", "powershell.exe", "pwsh.exe", "cmd.exe",
    "idea64.exe", "pycharm64.exe", "devenv.exe", "rider64.exe", "webstorm64.exe", "goland64.exe",
}
BROWSERS = {"chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe", "opera.exe", "arc.exe", "firefox.exe"}
# 只用来给问答细分学习的桶，不决定能力
WRITE_HINT = re.compile(r"帮我写|回复|润色|改写|起草|写一|拟")
TRANSLATE_HINT = re.compile(r"翻译|translate", re.IGNORECASE)
SYSADMIN_HINT = re.compile(r"卸载|安装|装不上|环境|驱动|注册表|服务|进程|端口|代理|网络|磁盘|清理|权限|启动项"
                           r"|pip|conda|winget|path", re.IGNORECASE)
#: 你明说要多想想：难度至少升一档
THINK_HINT = re.compile(r"仔细|认真想|深入|好好想|慢慢想|想清楚|深度思考|think (hard|carefully)", re.IGNORECASE)
LABELS = {
    ("translation", "screen_text"): "翻译", ("creative", "writing"): "写作", ("code_fix", "explain_error"): "报错分析",
    ("code_fix", "explain_code"): "代码解释", ("qa_factual", "ui_help"): "界面问答", ("qa_factual", "system_help"): "系统问题",
    ("qa_factual", "general"): "一般问答", ("code_fix", "dev"): "开发任务", ("agentic", "browser"): "浏览器操作",
    ("agentic", "desktop"): "桌面操作",
}

#: 参照强度：按模式和难度（0 一般 / 1 较难 / 2 很难）
REFERENCE = {"ask": ("medium", "high", "xhigh"), "act": ("high", "xhigh", "max")}
#: 先验里的任务难度（和模型的起步能力比）
DIFFICULTY = {"ask": (0.30, 0.50, 0.65), "act": (0.50, 0.62, 0.75)}
BAND_LIMITS = (0.45, 0.70)
SLOPE = 6.0
EFFORT_STEP = 0.06     # 低于参照强度每一档，起步能力扣这么多
PRIOR_N = 3.0          # 先验抵几次真实结果
MARGIN = 0.03          # 非劣效界值：成功率最多低这么多
CONFIDENCE = 0.90      # 降级需要的把握
MIN_EVIDENCE = 4.0     # 降级的配置自己至少要有这么多（加权后的）真实结果
MIN_SAVING = 0.15      # 省得太少不值得换（换总有一点风险）
#: 往上换（更高的思考强度、别的模型或引擎）：有七成把握它比现在的参照至少好 3 个百分点就换。
#: 比降级的门槛低：先保证办成。同一类任务上一次失败就够，别的类型上偶尔一次失败不够（不来回摇摆）。
UP_MARGIN = 0.03
UP_CONFIDENCE = 0.70
TIE = 0.002
LATENCY_USD_PER_S = 0.02  # 耗时折算成花费：每秒 0.02 美元（先办成，再求快）
KIND_BIAS = 0.05       # Codex 用官方界面操作时，操作模式下前台是浏览器或桌面软件：Codex 起步高一点
UNAVAILABLE_S = 300    # 限流、过载、断网：先歇这么久
MODEL_DOWN_S = 1800    # 这个模型用不了（服务没提供、没开通）：歇得久一点，配置改了（重新准备）就作废

#: 各类结果信号的可信度（学习权重）。"正常结束"几乎说明不了答得对不对，权重很低；失败信号（报错、汇报没完成、👎、
#: 追问说不对、很快又问同一个问题）说明力强得多。后台对比是带参照的评审，比较可信。
SIGNALS: dict[str, float | dict[str, float]] = {
    "status_ok": {"ask": 0.1, "act": 0.3}, "status_fail": 0.7, "feedback": 1.0, "negative_followup": 0.8,
    "reask": 0.5, "acted_on": 0.4, "delegated": 0.3, "delegate_result": 0.6, "duel": 0.8, "duel_ref": 0.8,
}
DUEL_MIN_P = 0.15      # 后台对比只试"有可能过关"的配置
DUEL_RIVAL = 0.2       # 偶尔对比另一个引擎：学两边谁更擅长这类问题


@dataclass
class Task:
    mode: str           # ask | act
    question: str
    content_kind: str   # error | code | foreign | dialog | text
    foreground: str = ""  # 前台进程 exe 名
    url: str = ""
    context: str = ""   # 框选区域的原文、选中的文字（判断难度用）
    errors: str = ""    # 前台窗口里的报错行
    vec: Any = None     # 问题的向量（找相似的旧任务；向量模型没好时为空）
    id: str = ""        # 第一次决策时分配：这个任务的决策和之后的结果信号都记在它名下（"路由表现"按它对上）


@dataclass
class Decision:
    engine: str
    model: str
    effort: str
    reason: str
    capabilities: tuple[str, ...] = ()
    via: str = "router"  # router | rules | pinned | escalated | duel
    explore: bool = False
    mode: str = ""
    kind: str = ""
    domain: str = ""
    band: int = 0
    vec: Any = None
    candidates: list[dict] = field(default_factory=list)
    task: str = ""          # 任务的 id（Task.id）
    cost: float = 0.0       # 选中的配置的估算花费（美元 + 耗时折算）
    ref: str = ""           # 最可靠的那个配置（参照）
    ref_cost: float = 0.0   # 参照的估算花费：两者一比，就是这次比"一直用最可靠的"省了多少


@dataclass
class View:
    """路由眼里的这次任务。"""
    mode: str
    kind: str
    domain: str
    band: int
    vec: Any = None

    @property
    def agentic(self) -> bool:
        return self.mode == "act" and self.kind == "agentic"

    @property
    def label(self) -> str:
        return LABELS.get((self.kind, self.domain), "这类任务")


@dataclass
class Scored:
    profile: Profile
    effort: str
    alpha: float
    beta: float
    real: float   # 加权后的真实结果数（不含先验）
    cost: float   # 有效花费：美元 + 耗时折算
    prior: float

    @property
    def engine(self) -> str:
        return self.profile.engine

    @property
    def model(self) -> str:
        return self.profile.id

    @property
    def eidx(self) -> int:
        return EFFORTS.index(self.effort)

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def var(self) -> float:
        n = self.alpha + self.beta
        return self.mean * (1 - self.mean) / (n + 1)

    @property
    def name(self) -> str:
        return f"{self.model} · {self.effort}"


def fg_category(foreground: str) -> str:
    fg = foreground.lower()
    return "dev" if fg in DEV_TOOLS else "browser" if fg in BROWSERS else "desktop"


def required_capabilities(task: Task) -> tuple[str, ...]:
    """硬约束只看模式。要不要动界面不在这里猜：路由到的引擎发现需要时会转交 Codex。"""
    return ("text", "vision") if task.mode != "act" else ("text", "vision", "tools", "shell")


def task_kind(task: Task) -> tuple[str, str]:
    """→ (任务类型, 子类)。只用来分开学习不同场景。"""
    if task.mode == "act":
        category = fg_category(task.foreground)
        return ("code_fix", "dev") if category == "dev" else ("agentic", category)
    q = task.question
    if TRANSLATE_HINT.search(q) or task.content_kind == "foreign":
        return "translation", "screen_text"
    if WRITE_HINT.search(q):
        return "creative", "writing"
    if task.content_kind == "error":
        return "code_fix", "explain_error"
    if task.content_kind == "code":
        return "code_fix", "explain_code"
    if task.content_kind == "dialog":
        return "qa_factual", "ui_help"
    if SYSADMIN_HINT.search(q):
        return "qa_factual", "system_help"
    return "qa_factual", "general"


def noninferior(c: Scored, r: Scored, margin: float = MARGIN) -> float:
    """P(c 的成功率 ≥ r 的成功率 − margin)，用两个 Beta 后验的均值和方差（正态近似）。"""
    var = c.var + r.var
    if var <= 0:
        return 1.0 if c.mean >= r.mean - margin else 0.0
    z = (c.mean - r.mean + margin) / math.sqrt(var)
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def superior(c: Scored, r: Scored, margin: float = UP_MARGIN) -> float:
    """P(c 的成功率 ≥ r 的成功率 + margin)。"""
    return noninferior(c, r, -margin)


def _difficulty_fn(path: str) -> Callable[[str], float] | None:
    """llmrouter 的难度估计（纯标准库）。没有它就用一个简单的估计。"""
    if path and Path(path).exists() and path not in sys.path:
        sys.path.insert(0, path)
    try:
        from llmrouter.features import FeatureExtractor
        from llmrouter.providers.base import CallRequest
    except Exception as e:  # noqa: BLE001 - 难度估计不可用时用简单估计，不能让助手起不来
        log.warning("llmrouter 不可用，难度改用简单估计：%s", e)
        return None
    extractor = FeatureExtractor()
    return lambda text: extractor.extract(CallRequest(messages=[{"role": "user", "content": text}])).difficulty


def _simple_difficulty(text: str) -> float:
    code = sum(text.count(k) for k in ("Traceback", "Error", "error:", "def ", "class ", "{", "};", "=>"))
    return min(0.9, 0.2 + 0.1 * min(3, code) + min(0.3, len(text) / 20000))


def _ema(old: float | None, new: float, rate: float = 0.2) -> float:
    new = max(0.2, min(20.0, new))
    return new if old is None else old + rate * (new - old)


class EngineRouter:
    def __init__(self, cfg: Config, gui_official: bool | None = None) -> None:
        self.cfg = cfg
        if gui_official is None:
            from ..engines.computer import official_codex

            gui_official = official_codex()
        self.gui_official = gui_official  # Codex 有没有官方的界面操作（决定操作类任务的起步偏好）
        self.unavailable: dict[str, float] = {}  # 运行中报错、限流的引擎 → 时刻；5 分钟内不再选它
        self.models_down: dict[tuple[str, str], tuple[float, float]] = {}  # (引擎, 模型) → (时刻, 歇多久)
        #: 配好了模型的引擎（准备窗口的检查结果）。None = 不限制。没配好的不参与，免得每次都去试一个打不开的引擎
        self.ready: set[str] | None = None
        self.meta_path = paths.ROUTER / "models.json"
        self.state_path = paths.ROUTER / "state.json"
        self.meta = catalog.load_meta(self.meta_path)
        self.state: dict = self._load_json(self.state_path)
        self.evidence = Evidence(paths.ROUTER / "outcomes.jsonl")
        if not self.evidence.items:
            self._migrate()
        self.difficulty = _difficulty_fn(cfg.llmrouter_path) or _simple_difficulty
        self._rng = random.Random()
        self.rebuild()

    # ---------- 构建 ----------

    def rebuild(self) -> None:
        """模型开关变了：重建档案。学到的记录按"引擎|模型"存在 outcomes.jsonl 里，停用的模型重新打开后接着用。"""
        self.models = {name: self.cfg.engine(name).enabled_models() for name in ENGINES}
        self.profiles: dict[str, list[Profile]] = catalog.build(self.cfg, self.meta)

    def update_models(self, engine: str, info: dict[str, dict]) -> None:
        """发现模型时拿到的元数据（支持哪些思考强度、默认哪一档、一句说明），存下来并重建。"""
        self.meta[engine] = {**self.meta.get(engine, {}), **info}
        catalog.save_meta(self.meta_path, self.meta)
        self.rebuild()

    def mark_unavailable(self, engine: str, model: str = "", seconds: float = UNAVAILABLE_S) -> None:
        """引擎（或它的一个模型）先歇一会儿，这期间路由不选它。"""
        if model:
            self.models_down[engine, model] = (time.time(), seconds)
        else:
            self.unavailable[engine] = time.time()

    def sideline(self, engine: str, model: str, kind: str) -> bool:
        """这个配置因为模型服务没办成，先放一边，接下来换别的（设计 7.6 节）：
        - model：这个模型用不了（服务没提供、没开通、中转没有它的渠道）→ 只歇这个模型，MODEL_DOWN_S 秒；
        - auth：认证失败 → 整个引擎都用不了；
        - service：限流、过载、断网 → 有别的引擎就整个引擎歇（多半是整个服务的问题），只有它一个就只歇这个模型
          （中转服务常常只是某个模型的渠道挂了）。
        歇了以后什么都用不了时不歇（歇了就谁都用不了），返回 False；返回 True = 还有别的能接着做。"""
        saved = dict(self.unavailable), dict(self.models_down)
        if kind == "model":
            self.mark_unavailable(engine, model, MODEL_DOWN_S)
        elif kind == "auth" or [e for e in self.available() if e != engine]:
            self.mark_unavailable(engine)
        else:
            self.mark_unavailable(engine, model)
        if self.available():
            log.info("路由：%s · %s 先放一边（%s），换别的接着做", engine, model, kind)
            return True
        self.unavailable, self.models_down = saved
        return False

    def set_ready(self, engines) -> None:
        self.ready = set(engines)
        for engine in self.ready:
            self.unavailable.pop(engine, None)  # 刚配好：之前因为没配好打不开的记录作废
        # 刚配好的服务可能就有这些模型了
        self.models_down = {k: v for k, v in self.models_down.items() if k[0] not in self.ready}
        log.info("路由：可用的引擎 %s", "、".join(sorted(self.ready)) or "（没有）")

    def _down(self, engine: str, model: str) -> bool:
        since, seconds = self.models_down.get((engine, model), (0.0, 0.0))
        return time.time() - since < seconds

    def usable(self, engine: str) -> list[Profile]:
        """这个引擎现在能选的模型（打开了，而且没在歇）。"""
        return [p for p in self.profiles.get(engine, []) if not self._down(engine, p.id)]

    def available(self) -> list[str]:
        now = time.time()
        return [e for e in ENGINES if self.usable(e) and now - self.unavailable.get(e, 0) > UNAVAILABLE_S
                and (self.ready is None or e in self.ready)]

    def best_model(self, engine: str) -> str:
        """这个引擎能选的模型里最强的一个（转交、后台小活用）。"""
        found = self.usable(engine)
        return min(found, key=lambda p: (p.tier, -p.skill, p.order)).id if found else ""

    def _profile(self, engine: str, model: str) -> Profile | None:
        return next((p for p in self.profiles.get(engine, []) if p.id == model), None)

    def _tier(self, engine: str, model: str) -> int:
        p = self._profile(engine, model)
        if p is not None:
            return p.tier
        return catalog.tier_of(model, str(self.meta.get(engine, {}).get(model, {}).get("desc", "")))

    # ---------- 看任务 ----------

    def describe(self, task: Task) -> View:
        kind, domain = task_kind(task)
        d = self.difficulty(task.question)
        extra = "\n\n".join(x for x in (task.context[:4000], task.errors[:2000]) if x)
        if extra:
            d = max(d, self.difficulty(f"{task.question}\n\n{extra}"))  # 屏幕上的内容只能让难度变高
        band = sum(d >= limit for limit in BAND_LIMITS)
        if task.mode == "act" and kind == "code_fix":
            band = max(band, 1)  # 开发任务至少算"较难"
        if THINK_HINT.search(task.question):
            band = min(2, band + 1)
        return View(task.mode, kind, domain, band, task.vec)

    @staticmethod
    def _view(decision: Decision) -> View:
        return View(decision.mode, decision.kind, decision.domain, decision.band, decision.vec)

    @staticmethod
    def reference_effort(p: Profile, view: View) -> str:
        """这个模型在这次任务上的参照强度：两个引擎同一把尺子（各自的强度刻度谁更"值钱"不靠猜，靠后台对比学）。"""
        level = EFFORTS.index(REFERENCE[view.mode][view.band])
        return next((e for e in p.efforts if EFFORTS.index(e) >= level), p.efforts[-1])

    def _prior(self, p: Profile, effort: str, view: View) -> float:
        skill = p.skill - EFFORT_STEP * max(0, EFFORTS.index(self.reference_effort(p, view)) - EFFORTS.index(effort))
        if self.gui_official and view.agentic:
            skill += KIND_BIAS if p.engine == "codex" else -KIND_BIAS
        z = SLOPE * (skill - DIFFICULTY[view.mode][view.band])
        return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, z))))

    def _factor(self, table: str, engine: str, mode: str) -> float:
        """实测校准的倍数。这个引擎还没测过时，用测过的引擎的平均（保持两边先验的相对快慢）。"""
        known = self.state.get(table, {})
        if f"{engine}|{mode}" in known:
            return known[f"{engine}|{mode}"]
        others = [v for k, v in known.items() if k.endswith(f"|{mode}")]
        return sum(others) / len(others) if others else 1.0

    def _cost(self, p: Profile, effort: str, mode: str) -> float:
        usd = catalog.cost_usd(p, effort, mode) * self._factor("price", p.engine, mode)
        seconds = catalog.latency_s(p, effort, mode) * self._factor("speed", p.engine, mode)
        return usd + LATENCY_USD_PER_S * seconds

    def _score(self, view: View, engines: list[str]) -> list[Scored]:
        buckets = self.evidence.gather(view.mode, view.kind, view.domain, view.vec)
        tiers: dict[tuple[str, str], int] = {}

        def tier_of(engine: str, model: str) -> int:
            if (engine, model) not in tiers:
                tiers[engine, model] = self._tier(engine, model)
            return tiers[engine, model]

        out = []
        for engine in engines:
            for p in self.usable(engine):
                for effort in p.efforts:
                    prior = self._prior(p, effort, view)
                    s, f = Evidence.counts(buckets, p.engine, p.id, p.tier, EFFORTS.index(effort), tier_of)
                    out.append(Scored(p, effort, PRIOR_N * prior + s, PRIOR_N * (1 - prior) + f, s + f,
                                      self._cost(p, effort, view.mode), prior))
        return out

    @staticmethod
    def _best(scored: list[Scored], key: Callable[[Scored], float] = lambda s: s.mean) -> Scored:
        """预测成功率最高的；差不多一样高时选最省、最快的。"""
        top = max(key(s) for s in scored)
        return min((s for s in scored if key(s) >= top - TIE), key=lambda s: (s.cost, s.profile.tier, s.profile.order))

    def _reference(self, scored: list[Scored]) -> tuple[Scored, Scored]:
        """→ (参照, 冷启动的默认)。默认是只看先验最强的那个（两边一样时选更快的）；
        只有证据表明别的配置大概率明显更好（superior）时才换过去，偶尔一次旁证不会让它来回摇摆。"""
        default = self._best(scored, key=lambda s: s.prior)
        better = [s for s in scored if s is not default and superior(s, default) >= UP_CONFIDENCE]
        return (self._best(better) if better else default), default

    # ---------- 决策 ----------

    def decide(self, task: Task) -> Decision:
        caps = required_capabilities(task)
        engines = self.available()
        pinned = self.cfg.pin_engine if self.cfg.pin_engine in engines else ""
        if pinned:
            engines = [pinned]
        if not engines:
            raise RuntimeError("没有可用的引擎：请在设置里至少启用一个模型")
        task.id = task.id or uuid.uuid4().hex[:12]
        view = self.describe(task)
        try:
            decision = self._route(view, engines)
            if pinned:
                decision.via = "pinned"
        except Exception as e:  # noqa: BLE001 - 学习记录坏了也不能让助手答不了
            log.warning("路由出错，改用规则：%s", e)
            decision = self._rules(view, engines)
        decision.capabilities, decision.task = caps, task.id
        self._log("decision", task, decision)
        return decision

    def _pick(self, view: View, engines: list[str]) -> tuple[Scored, Scored, Scored, float, list[Scored]]:
        """→ (选中的, 参照, 冷启动的默认, 降级的把握, 全部候选)。"""
        scored = self._score(view, engines)
        ref, default = self._reference(scored)
        chosen, confidence = ref, 0.0
        for s in sorted(scored, key=lambda s: s.cost):
            if s.cost > ref.cost * (1 - MIN_SAVING):
                break
            if s.real < MIN_EVIDENCE:
                continue
            p = noninferior(s, ref)
            if p >= CONFIDENCE:
                chosen, confidence = s, p
                break
        return chosen, ref, default, confidence, scored

    def _route(self, view: View, engines: list[str]) -> Decision:
        chosen, ref, default, confidence, scored = self._pick(view, engines)
        top = sorted(scored, key=lambda s: (-s.mean, s.cost))[:6]
        return Decision(engine=chosen.engine, model=chosen.model, effort=chosen.effort,
                        reason=self._reason(view, chosen, ref, default, confidence, scored), mode=view.mode,
                        kind=view.kind, domain=view.domain, band=view.band, vec=view.vec,
                        candidates=[{"arm": s.name, "engine": s.engine, "quality": round(s.mean, 3),
                                     "n": round(s.real, 1), "cost": round(s.cost, 3)} for s in top],
                        cost=round(chosen.cost, 4), ref=ref.name, ref_cost=round(ref.cost, 4))

    def learned(self, kinds: list[tuple[str, str, str, int]]) -> list[dict]:
        """这几类任务（模式, 类型, 子类, 难度档）现在实际会用的配置，和最可靠的那个不一样的（设置里"路由表现"列出来）：
        cheaper = 证明了一样能办成、更省；stronger = 原来的配置在这类任务上没办成过，换成了更强的。"""
        engines, out = self.available(), []
        for mode, kind, domain, band in kinds if engines else []:
            view = View(mode, kind, domain, band)
            try:
                chosen, ref, default, confidence, _ = self._pick(view, engines)
            except Exception:  # noqa: BLE001 - 这类任务算不出来就不列
                continue
            if chosen is not ref:
                out.append({"mode": mode, "label": view.label, "change": "cheaper", "use": chosen.name,
                            "instead": ref.name, "confidence": round(confidence, 3),
                            "saving": round(1 - chosen.cost / ref.cost, 3) if ref.cost else 0.0})
            elif ref is not default:
                out.append({"mode": mode, "label": view.label, "change": "stronger", "use": ref.name,
                            "instead": default.name})
        return out

    @staticmethod
    def _reason(view: View, chosen: Scored, ref: Scored, default: Scored, confidence: float,
                scored: list[Scored]) -> str:
        if chosen is not ref:
            return (f"{chosen.name} 在{view.label}上已证明和最可靠的配置（{ref.name}）几乎一样能办成"
                    f"（把握 {confidence:.0%}），更快、更省")
        if ref is not default:
            if ref.model == default.model and ref.eidx > default.eidx:
                return f"{view.label}用 {default.effort} 没办成过，思考强度提高到 {ref.effort}"
            return f"{ref.name} 在{view.label}上比 {default.name} 更可靠"
        cheaper = any(s.cost < chosen.cost * (1 - MIN_SAVING) for s in scored)
        return f"先保证办成：{chosen.name}" + ("（更便宜、更快的配置在这类任务上还没证明一样能办成）" if cheaper else "")

    def _rules(self, view: View, engines: list[str]) -> Decision:
        if self.gui_official and view.agentic:
            order = ["codex", "claude"]
        elif self.gui_official:
            order = ["claude", "codex"]  # 动界面会转交 Codex，其余的 Claude 首字更快
        else:
            order = self._rng.sample(["claude", "codex"], 2)  # 用自研的界面操作时两边工具一样：不偏向哪一边
        order.append("dsh")  # DeepSeek Harness 是替代：另外两个都用不了时才轮到它
        engine = next((e for e in order if e in engines), engines[0])
        p = self._profile(engine, self.best_model(engine))
        return Decision(engine=engine, model=p.id, effort=self.reference_effort(p, view), reason="规则路由",
                        via="rules", mode=view.mode, kind=view.kind, domain=view.domain, band=view.band, vec=view.vec)

    # ---------- 没办成：同一个对话里加强 ----------

    def escalate(self, decision: Decision, task: Task | None = None) -> Decision | None:
        """这一轮没办成（失败已经记下）：同一个引擎里换一个更强的配置——更高的思考强度，或者更强的模型。
        选预测成功率最高的；一样高时选最省的（通常是同一个模型高一档）。没有更强的返回 None。"""
        if decision.engine not in self.available():
            return None
        view = self._view(decision)
        current = self._profile(decision.engine, decision.model)
        level = EFFORTS.index(decision.effort) if decision.effort in EFFORTS else 0
        stronger = [s for s in self._score(view, [decision.engine])
                    if (s.model == decision.model and s.eidx > level)
                    or (current is not None and s.profile.tier < current.tier
                        and s.eidx >= max(level, EFFORTS.index(self.reference_effort(s.profile, view))))]
        if not stronger:
            return None
        chosen = self._best(stronger)
        return Decision(engine=chosen.engine, model=chosen.model, effort=chosen.effort,
                        reason=f"上一轮没办成，换更强的配置：{chosen.name}", capabilities=decision.capabilities,
                        via="escalated", mode=view.mode, kind=view.kind, domain=view.domain, band=view.band,
                        vec=view.vec, task=decision.task)

    # ---------- 后台对比（只在问答模式） ----------

    def duels_left(self) -> int:
        today = date.today().isoformat()
        used = self.state.get("duels", {})
        return max(0, self.cfg.shadow_daily - (used.get("n", 0) if used.get("date") == today else 0))

    def count_duel(self) -> None:
        today = date.today().isoformat()
        used = self.state.get("duels", {})
        self.state["duels"] = {"date": today, "n": (used.get("n", 0) if used.get("date") == today else 0) + 1}
        self._save_state()

    def duel_candidate(self, decision: Decision) -> Decision | None:
        """问答答完以后，值得在后台试一试的另一个配置：更便宜、有可能过关、还没过关的，按"可能省下的"排；
        偶尔是另一个引擎的配置（学两边谁更擅长这类问题）。界面问答要看实时界面、在屏幕上圈位置，后台比不公平，不比。"""
        if decision.mode != "ask" or not self.cfg.shadow_eval or self.duels_left() <= 0:
            return None
        if (decision.kind, decision.domain) == ("qa_factual", "ui_help") or decision.via in ("pinned", "rules"):
            return None
        view = self._view(decision)
        scored = self._score(view, self.available())
        served = next((s for s in scored if s.engine == decision.engine and s.model == decision.model
                       and s.effort == decision.effort), None)
        if served is None:
            return None
        cheaper = []
        for s in scored:
            if s is served or s.cost > served.cost * (1 - MIN_SAVING):
                continue
            p = noninferior(s, served)
            if p >= DUEL_MIN_P and not (p >= CONFIDENCE and s.real >= MIN_EVIDENCE):
                cheaper.append((p * (served.cost - s.cost), s))
        rivals = [s for s in scored if s.engine != served.engine and s.real < MIN_EVIDENCE * 2]
        pick = None
        if rivals and (not cheaper or self._rng.random() < DUEL_RIVAL):
            pick = self._best(rivals)
        elif cheaper:
            pick = max(cheaper, key=lambda t: t[0])[1]
        if pick is None:
            return None
        return Decision(engine=pick.engine, model=pick.model, effort=pick.effort,
                        reason=f"后台对比：{pick.name} 在{view.label}上能不能和 {served.name} 一样好",
                        capabilities=decision.capabilities, via="duel", mode=view.mode, kind=view.kind,
                        domain=view.domain, band=view.band, vec=view.vec, task=decision.task)

    def record_duel(self, served: Decision, candidate: Decision, task: Task | None, verdict: Verdict) -> None:
        """两份回答都按评审结果记：只记候选的话，被对比的那份永远只有很弱的"正常结束"，比较就偏了。"""
        self.record(candidate, task, verdict.candidate, "duel")
        self.record(served, task, verdict.served, "duel_ref")

    # ---------- 学习 ----------

    def record(self, decision: Decision | None, task: Task | None, success: bool | float, source: str,
               engine: str | None = None) -> bool:
        """把一次结果记下来。engine 不同于 decision.engine 时（转交），记到那个引擎最强的模型上。"""
        if decision is None:
            return False
        mode = decision.mode or (task.mode if task is not None else "act")
        name, model, effort = decision.engine, decision.model, decision.effort
        if engine and engine != decision.engine:
            name, model, effort = engine, self.best_model(engine), "high"  # 转交的会话用 high
            if not model:
                return False
        weight = SIGNALS.get(source, 0.3)
        if isinstance(weight, dict):
            weight = weight.get(mode, 0.3)
        y = float(success)
        self.evidence.add(Outcome(t=time.time(), mode=mode, kind=decision.kind, domain=decision.domain, engine=name,
                                  model=model, effort=effort, y=y, w=weight, source=source, vec=decision.vec))
        if task is not None:
            self._log("outcome", task, decision, {"arm": f"{name}|{model}|{effort}", "success": y, "source": source})
        return True

    def observe(self, decision: Decision, seconds: float, cost: float | None = None) -> None:
        """第一轮实际用了多久、花了多少：校准这个引擎在这个模式下的耗时（和花费）估计。"""
        p = self._profile(decision.engine, decision.model)
        if p is None or seconds <= 0 or decision.mode not in MODES:
            return
        key = f"{decision.engine}|{decision.mode}"
        speed = self.state.setdefault("speed", {})
        speed[key] = round(_ema(speed.get(key), seconds / catalog.latency_s(p, decision.effort, decision.mode)), 4)
        if cost:
            price = self.state.setdefault("price", {})
            price[key] = round(_ema(price.get(key), cost / catalog.cost_usd(p, decision.effort, decision.mode)), 4)
        self._save_state()

    def warm_target(self, engine: str, mode: str = "ask") -> tuple[str, str]:
        """启动时预热哪个配置：一般问题最可能用到的那个（模型, 思考强度）。"""
        if not self.usable(engine):
            return "", ""
        try:
            d = self._route(View(mode, "qa_factual", "general", 0), [engine])
            return d.model, d.effort
        except Exception:  # noqa: BLE001
            p = self._profile(engine, self.best_model(engine))
            return p.id, p.efforts[0]

    def _migrate(self) -> None:
        """升级前的学习结果（decisions.jsonl 里的 outcome）转成新的记录，学到的不丢。"""
        path = paths.ROUTER / "decisions.jsonl"
        if not path.exists():
            return
        moved = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("type") != "outcome" or r.get("success") is None or not r.get("kind"):
                continue
            engine, model, effort = r.get("engine", ""), r.get("model", ""), r.get("effort") or "high"
            arm = str(r.get("arm", ""))
            if arm and not arm.startswith(f"{engine}|"):  # 转交：记在另一个引擎的模型上
                engine, model, effort = arm.split("|")[0], arm.split("|")[1], "high"
            mode, source = r.get("mode", "act"), r.get("source", "")
            weight = SIGNALS.get(source, 0.3)
            weight = weight.get(mode, 0.3) if isinstance(weight, dict) else weight
            self.evidence.add(Outcome(t=r.get("t", time.time()), mode=mode, kind=r["kind"], domain=r.get("domain", ""),
                                      engine=engine, model=model, effort=effort, y=float(bool(r["success"])),
                                      w=weight, source=source))
            moved += 1
        if moved:
            log.info("路由：从旧记录迁移了 %d 条结果", moved)

    # ---------- 存取 ----------

    @staticmethod
    def _load_json(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.state_path)
        except OSError as e:
            log.warning("保存路由状态失败：%s", e)

    def _log(self, kind: str, task: Task, decision: Decision, extra: dict | None = None) -> None:
        record = {"t": time.time(), "type": kind, "mode": task.mode, "content": task.content_kind,
                  "fg": task.foreground, "kind": decision.kind, "domain": decision.domain, "band": decision.band,
                  "engine": decision.engine, "model": decision.model, "effort": decision.effort,
                  "via": decision.via, "explore": decision.explore, "reason": decision.reason,
                  "task": decision.task or task.id, **(extra or {})}
        if kind == "decision":
            record.update(candidates=decision.candidates, cost=decision.cost, ref=decision.ref, ref_cost=decision.ref_cost)
        try:
            paths.ROUTER.mkdir(parents=True, exist_ok=True)
            with (paths.ROUTER / "decisions.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass
