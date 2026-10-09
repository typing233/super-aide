"""模型档案：每个可路由的模型是哪一档、支持哪些思考强度、厂商默认哪一档、大概多贵多快。

路由的先验（冷启动先用最强的）和花费、耗时的估计都从这里来：
- 档次：旗舰 / 主力 / 轻量。先看名字（opus、fable、astra → 旗舰；sonnet、sol、terra → 主力；
  haiku、luna、mini… → 轻量），名字看不出再看 Codex 给的那句说明（"Frontier…"、"workhorse"、"Fast and affordable…"）。
  都看不出的按主力算：不认识的模型不能一上来就和旗舰平起平坐。
- 新旧：同一档里旧一代的起步低一点（Codex 说明里的 Older / Previous / Legacy；Claude 按型号里的版本号）。
- 思考强度：Codex 的 models() 给了每个模型支持哪几档（实测 gpt-5.5 只到 xhigh，luna 没有 ultra），
  发现模型时存进 ~/.super_aide/router/models.json；Claude 的按官方资料。
  都不超过设置里每个模型的上限，路由只在合法的档里选（不会把 max 发给不支持的模型）。
- 价格：Claude 已知型号用官方价；其它按档次估。只用来比较哪个更便宜，不用来记账。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import EFFORTS, ENGINES, Config

log = logging.getLogger(__name__)

TIER_NAMES = ("旗舰", "主力", "轻量")
#: 各档的起步能力（和任务难度比，见 policy.prior）
TIER_SKILL = (0.90, 0.80, 0.66)
TIER_PRICE = ((4.0, 20.0), (2.0, 10.0), (1.0, 5.0))  # 输入、输出（美元 / 百万 token），不认识的型号按档次估
TIER_SPEED = (55.0, 85.0, 140.0)  # 输出 token / 秒
#: 首字前的固定开销（秒，P0 实测：Claude 带图提问首字 2.6s，Codex 7.9s；DSH 每轮起一个进程，按 6s 估，之后按实测校准）
OVERHEAD_S = {"claude": 2.6, "codex": 7.9, "dsh": 6.0}
#: 思考强度 → 输出量的倍数（llmrouter 目录的先验，以 high 为 1）
EFFORT_TOKENS = {"low": 0.35, "medium": 0.6, "high": 1.0, "xhigh": 1.7, "max": 3.0}
OUTPUT_TOKENS = {"ask": 600, "act": 1500}
INPUT_TOKENS = 8000

_NAME_TIERS = (
    re.compile(r"opus|fable|mythos|(^|[-_.])astra($|[-_.])", re.IGNORECASE),
    re.compile(r"sonnet|(^|[-_.])(sol|terra)($|[-_.])", re.IGNORECASE),
    re.compile(r"haiku|(^|[-_.])luna($|[-_.])|mini|nano|lite|flash|small", re.IGNORECASE),
)
_DESC_TIERS = (
    re.compile(r"frontier|most (capable|demanding)|flagship", re.IGNORECASE),
    re.compile(r"workhorse|balanced|everyday", re.IGNORECASE),
    re.compile(r"fast and|affordable|efficient|easier tasks|lightweight", re.IGNORECASE),
)
_OLD = (("legacy", 0.08), ("older", 0.05), ("previous", 0.04))
_CLAUDE = re.compile(r"claude-(opus|sonnet|haiku|fable|mythos)-(\d+)(?:-(\d))?(?:-\d{8})?$")

#: Claude 官方价（2026-09，美元 / 百万 token），按型号前缀匹配，取最长的那个
CLAUDE_PRICES = {
    "claude-fable-5": (10.0, 50.0), "claude-mythos": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0), "claude-opus-4": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0), "claude-sonnet-4": (3.0, 15.0), "claude-haiku-4-5": (1.0, 5.0),
}


@dataclass(frozen=True)
class Profile:
    engine: str
    id: str
    tier: int                  # 0 旗舰 / 1 主力 / 2 轻量
    efforts: tuple[str, ...]   # 可以用的思考强度（由低到高，已按设置里的上限截断）
    skill: float               # 起步能力（档次减去"旧一代"的折扣）
    price: tuple[float, float]
    order: int = 0             # 在设置里的位置

    @property
    def label(self) -> str:
        return f"{self.id}（{TIER_NAMES[self.tier]}）"


def tier_of(model_id: str, desc: str = "") -> int:
    for tier, pattern in enumerate(_NAME_TIERS):
        if pattern.search(model_id):
            return tier
    for tier, pattern in enumerate(_DESC_TIERS):
        if pattern.search(desc):
            return tier
    return 1


def claude_version(model_id: str) -> tuple[str, float] | None:
    """claude-opus-4-8 → ("opus", 4.8)；claude-opus-4-20250514 → ("opus", 4.0)；认不出返回 None。"""
    m = _CLAUDE.match(model_id)
    if not m:
        return None
    return m.group(1), int(m.group(2)) + (int(m.group(3)) / 10 if m.group(3) else 0.0)


def claude_efforts(model_id: str) -> tuple[str, ...]:
    """官方资料：4.7 起五档都有，4.6 没有 xhigh，4.5 只有前三档，更早的（和 Haiku 4.5）不支持 effort。
    不支持的模型只给一个名义上的 high（Claude Code 默认档），路由就不会在它身上调强度。"""
    v = claude_version(model_id)
    if v is None:
        return EFFORTS
    line, version = v
    if version >= 4.7 and not (line == "haiku" and version < 5):
        return EFFORTS
    if version >= 4.6 and line != "haiku":
        return ("low", "medium", "high", "max")
    if version >= 4.5 and line == "opus":
        return ("low", "medium", "high")
    return ("high",)


def _longest_prefix(table: dict, model_id: str):
    keys = [k for k in table if model_id.startswith(k)]
    return table[max(keys, key=len)] if keys else None


def _capped(efforts: tuple[str, ...], cap: str) -> tuple[str, ...]:
    top = EFFORTS.index(cap) if cap in EFFORTS else len(EFFORTS) - 1
    kept = tuple(e for e in efforts if e in EFFORTS and EFFORTS.index(e) <= top)
    return kept or (min(efforts, key=EFFORTS.index) if efforts else "high",)


def build(cfg: Config, meta: dict[str, dict[str, dict]]) -> dict[str, list[Profile]]:
    """设置里打开的模型 → 档案。meta 是发现模型时存下的元数据：{引擎: {模型: {efforts, default, desc}}}。"""
    profiles: dict[str, list[Profile]] = {}
    for engine in ENGINES:
        entries = cfg.engine(engine).enabled_models()
        known = meta.get(engine, {})
        newest: dict[str, float] = {}  # Claude 每条产品线里最新的版本（含没打开的），用来给旧一代打折
        for m in cfg.engine(engine).models:
            v = claude_version(m.id) if engine == "claude" else None
            if v:
                newest[v[0]] = max(newest.get(v[0], 0.0), v[1])
        out = []
        for order, entry in enumerate(entries):
            info = known.get(entry.id, {})
            desc = str(info.get("desc", ""))
            tier = tier_of(entry.id, desc)
            if engine == "claude":
                efforts = claude_efforts(entry.id)
                price = _longest_prefix(CLAUDE_PRICES, entry.id) or TIER_PRICE[tier]
                v = claude_version(entry.id)
                penalty = min(0.08, 0.03 * (newest[v[0]] - v[1])) if v else 0.0
            else:
                efforts = tuple(e for e in info.get("efforts", EFFORTS) if e in EFFORTS) or EFFORTS
                price = TIER_PRICE[tier]
                lowered = desc.lower()
                penalty = max((p for word, p in _OLD if word in lowered), default=0.0)
                if info.get("upgrade"):
                    penalty = max(penalty, 0.04)
            out.append(Profile(engine=engine, id=entry.id, tier=tier, efforts=_capped(efforts, entry.max_effort),
                               skill=TIER_SKILL[tier] - penalty, price=price, order=order))
        profiles[engine] = out
    return profiles


def load_meta(path: Path) -> dict[str, dict[str, dict]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_meta(path: Path, meta: dict[str, dict[str, dict]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        log.warning("保存模型元数据失败：%s", e)


def latency_s(p: Profile, effort: str, mode: str) -> float:
    """一次回答大概要多久（秒）：首字开销 + 输出量 / 速度。只用来比较快慢。"""
    tokens = OUTPUT_TOKENS.get(mode, 600) * EFFORT_TOKENS.get(effort, 1.0)
    return OVERHEAD_S.get(p.engine, 3.0) + tokens / TIER_SPEED[p.tier]


def cost_usd(p: Profile, effort: str, mode: str) -> float:
    tokens = OUTPUT_TOKENS.get(mode, 600) * EFFORT_TOKENS.get(effort, 1.0)
    return (INPUT_TOKENS * p.price[0] + tokens * p.price[1]) / 1e6
