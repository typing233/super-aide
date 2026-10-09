"""路由的学习记录：每个结果一条（~/.super_aide/router/outcomes.jsonl），决策时按"和这次任务有多相关"加权，
得到每个配置（引擎 × 模型 × 思考强度）的成功次数和失败次数，再和先验合成 Beta 后验（见 policy.py）。

和 llmrouter 的分层后验是同一个思路（数据少时听先验，细的格子有数据就听细的），改了三处：
- 相关度代替固定层级。同一类任务（类型#子类）全算；同类型不同子类、意思很像的旧任务（有任务向量时，kNN 路由的做法：
  数据少时最稳）、别的类型，各算一部分，而且各有上限。llmrouter 的"整个模型"那一层会让一类任务上的失败把别的类型
  也拖下水（实测：一次浏览器操作失败，开发任务也全换了引擎）；这里别的类型最多只算 2 次的分量。
- 单调共享。同一个模型低档办成了，高档也算办成（打折）；高档办不成，低档也算办不成（打折）；反方向不传。
  同一引擎里，弱的模型办成了算强的也能办成，强的办不成算弱的也办不成。所以便宜的配置只能靠它自己的成功
  证明自己，失败却会立刻让它变差——这正是"先保证办成"需要的不对称。
- 旧记录慢慢淡化（半衰期 90 天）：模型会悄悄更新，你的任务也会变。
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import EFFORTS

log = logging.getLogger(__name__)

HALF_LIFE_DAYS = 90.0
KEEP = 5000
#: 相关度：同一类任务 1；同类型不同子类 0.5；别的类型 0.15。意思很像的旧任务按相似度给（见 semantic）
SAME_KIND = 0.5
OTHER_KIND = 0.15
#: 每一组旁证最多抵几次真实结果（同一类任务本身不封顶）
CAPS = {"cell": None, "kind": 6.0, "near": 5.0, "mode": 2.0}
#: 共享折扣：同模型不同强度、同引擎不同档次、同引擎同档次的别的模型（比如新一代接上一代）
EFFORT_SHARE = 0.75
TIER_SHARE = 0.5
SIBLING_SHARE = 0.3
#: multilingual-e5 的余弦相似度挤在 0.8～1 之间：0.88 以下不算像，0.95 以上算同一件事
SIM_LOW, SIM_HIGH = 0.88, 0.95


@dataclass
class Outcome:
    t: float
    mode: str
    kind: str
    domain: str
    engine: str
    model: str
    effort: str
    y: float        # 1 办成 / 0 没办成（后台对比可以是 0.5）
    w: float        # 这个信号的可信度
    source: str
    vec: Any = None  # 任务向量（numpy，单位长度），没有就是 None

    def to_json(self) -> dict:
        d = asdict(self)
        d["vec"] = _pack(self.vec)
        return d

    @classmethod
    def from_json(cls, d: dict) -> Outcome:
        fields = {k: d[k] for k in ("t", "mode", "kind", "domain", "engine", "model", "effort", "y", "w", "source")}
        return cls(**fields, vec=_unpack(d.get("vec")))


def _pack(vec) -> str | None:
    if vec is None:
        return None
    import numpy as np

    return base64.b64encode(np.asarray(vec, dtype=np.float16).tobytes()).decode()


def _unpack(text: str | None):
    if not text:
        return None
    try:
        import numpy as np

        return np.frombuffer(base64.b64decode(text), dtype=np.float16).astype(np.float32)
    except Exception:  # noqa: BLE001 - 坏了就当没有向量
        return None


def semantic(sim: float) -> float:
    return max(0.0, min(1.0, (sim - SIM_LOW) / (SIM_HIGH - SIM_LOW)))


def effort_index(effort: str) -> int:
    return EFFORTS.index(effort) if effort in EFFORTS else EFFORTS.index("high")


#: 汇总后的一格：(引擎, 模型, 强度档, 办成没有, 分组) → [加权的成功分, 加权的失败分]
Buckets = dict[tuple[str, str, int, bool, str], list[float]]


def transfer(o_engine: str, o_model: str, o_eidx: int, ok: bool, o_tier: int,
             engine: str, model: str, tier: int, eidx: int) -> float:
    """一个结果（o_…）对"engine·model·第 eidx 档"这个配置算几分（0～1）。只在同一个引擎里传，而且只按单调的方向传。"""
    if o_engine != engine:
        return 0.0
    if o_model == model:
        if o_eidx == eidx:
            return 1.0
        return EFFORT_SHARE if (ok and o_eidx < eidx) or (not ok and o_eidx > eidx) else 0.0
    if o_tier == tier:
        return SIBLING_SHARE if (ok and o_eidx <= eidx) or (not ok and o_eidx >= eidx) else 0.0
    if ok and o_tier > tier and o_eidx <= eidx:
        return TIER_SHARE  # 更弱的模型办成了
    if not ok and o_tier < tier and o_eidx >= eidx:
        return TIER_SHARE  # 更强的模型都没办成
    return 0.0


class Evidence:
    def __init__(self, path: Path, keep: int = KEEP) -> None:
        self.path = path
        self.keep = keep
        self.items: list[Outcome] = []
        try:
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        self.items.append(Outcome.from_json(json.loads(line)))
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
            log.warning("路由学习记录读取不完整（%s），读到的照用", e)
        self.items = self.items[-keep:]
        self._matrix: tuple[int, object, list[int]] | None = None  # (记录条数, 向量矩阵, 对应的下标)

    def add(self, o: Outcome) -> None:
        self.items.append(o)
        self._matrix = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(o.to_json(), ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("保存路由学习记录失败：%s", e)
        if len(self.items) > self.keep * 1.2:
            self.items = self.items[-self.keep:]
            self._rewrite()
            self._matrix = None

    def _rewrite(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(o.to_json(), ensure_ascii=False) + "\n" for o in self.items),
                           encoding="utf-8")
            tmp.replace(self.path)
        except OSError as e:
            log.warning("整理路由学习记录失败：%s", e)

    def _similarities(self, vec) -> dict[int, float]:
        """这次任务和每条带向量的旧记录有多像（一次矩阵乘法算完）。"""
        if vec is None:
            return {}
        import numpy as np

        if self._matrix is None or self._matrix[0] != len(self.items):
            idx = [i for i, o in enumerate(self.items) if o.vec is not None and len(o.vec) == len(vec)]
            self._matrix = (len(self.items), np.stack([self.items[i].vec for i in idx]) if idx else None, idx)
        _, matrix, idx = self._matrix
        if matrix is None or matrix.shape[1] != len(vec):
            return {}
        return dict(zip(idx, (matrix @ np.asarray(vec, dtype=np.float32)).tolist()))

    def gather(self, mode: str, kind: str, domain: str, vec=None, now: float | None = None) -> Buckets:
        """这次任务用得上的结果，按 (引擎, 模型, 强度档, 办成没有, 分组) 汇总：权重 = 相关度 × 可信度 × 新旧。
        分组用来给旁证封顶；汇总以后每个候选配置只要看几十格，不用把几千条记录挨个过一遍。"""
        now = time.time() if now is None else now
        sims = self._similarities(vec)
        buckets: Buckets = {}
        for i, o in enumerate(self.items):
            if o.mode != mode:
                continue
            if o.kind == kind and o.domain == domain:
                rel, group = 1.0, "cell"
            else:
                rel, group = (SAME_KIND, "kind") if o.kind == kind else (OTHER_KIND, "mode")
                near = semantic(sims[i]) if i in sims else 0.0
                if near > rel:
                    rel, group = near, "near"
            weight = rel * o.w * 0.5 ** (max(0.0, now - o.t) / 86400 / HALF_LIFE_DAYS)
            if weight > 1e-4:
                cell = buckets.setdefault((o.engine, o.model, effort_index(o.effort), o.y >= 0.5, group), [0.0, 0.0])
                cell[0] += weight * o.y
                cell[1] += weight * (1.0 - o.y)
        return buckets

    @staticmethod
    def counts(buckets: Buckets, engine: str, model: str, tier: int, eidx: int,
               tier_of: Callable[[str, str], int]) -> tuple[float, float]:
        """→ (加权成功数, 加权失败数)。每组旁证超过上限时按比例缩小。"""
        groups: dict[str, list[float]] = {}
        for (o_engine, o_model, o_eidx, ok, group), (ws, wf) in buckets.items():
            if o_engine != engine:
                continue
            k = transfer(o_engine, o_model, o_eidx, ok, tier_of(o_engine, o_model), engine, model, tier, eidx)
            if k <= 0:
                continue
            g = groups.setdefault(group, [0.0, 0.0])
            g[0] += ws * k
            g[1] += wf * k
        s = f = 0.0
        for group, (gs, gf) in groups.items():
            cap, n = CAPS.get(group), gs + gf
            scale = min(1.0, cap / n) if cap and n > 0 else 1.0
            s += gs * scale
            f += gf * scale
        return s, f
