"""意思相近的那一半"想起"：本地向量模型（字面那一半在 recall.py）。

字面对不上、意思一样的情况靠它，比如"下载依赖一直卡在 Collecting，最后连接失败"对上"pip 装包超时先查代理"。
只靠向量会把"同一个话题"当成"同一种情况"："pip 是什么"和那条经验也很像（实测相似度 0.90）。
所以要两条都满足才算：
- 和某条经验足够像（SIMILAR_MIN）；
- 这次确实是碰到了问题：和几句典型的"出问题"描述比，比和"是什么、怎么用"这类请求更像（PROBLEM_MIN）。
两个门槛在 multilingual-e5-small 上标定（spikes/p8_embed_bench.py）：换了说法的 9 条全部对上、相似度最低 0.885；
18 条不相干或同话题的问题一条都不放行。向量只补字面漏掉的，每次最多补 1 条。
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path

from .embed import Embedder
from .store import Lesson

log = logging.getLogger(__name__)

SIMILAR_MIN = 0.875
PROBLEM_MIN = 0.008
PROBLEM = ["运行报错了", "安装失败了", "程序卡住没反应", "打开以后全是乱码", "命令被拒绝了", "出错了怎么办", "一直超时连不上",
           "突然崩溃重启了", "提示找不到", "it fails with an error", "connection timed out", "permission denied"]
INFO = ["这是什么", "怎么打开", "怎么新建一个", "在哪里查看", "是什么意思", "介绍一下", "怎么用", "帮我翻译", "帮我写",
        "帮我总结", "how to use it", "what is this"]


def lesson_text(lesson: Lesson) -> str:
    """做向量的是"什么情况"：标题、适用情况、提示词（做法不算：情况相似才该想起，做法相似不算）。"""
    return f"{lesson.title}。{lesson.when}。{' '.join(lesson.triggers)}"


class Semantic:
    def __init__(self, embedder: Embedder, cache: Path) -> None:
        self.embedder = embedder
        self.cache = cache  # 经验的向量存起来，重启不用重算
        self._vectors: dict[str, tuple[float, object]] = {}
        self._loaded = False
        self._prototypes = None

    def ready(self) -> bool:
        return self.embedder.ready()

    # ---- 经验的向量 ----

    def _load_cache(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            import numpy as np

            raw = json.loads(self.cache.read_text(encoding="utf-8"))
            if raw.get("model") != self.embedder.name:
                return  # 换了模型：旧向量不能用
            for lesson_id, item in raw.get("items", {}).items():
                vec = np.frombuffer(base64.b64decode(item["vec"]), dtype=np.float16).astype(np.float32)
                self._vectors[lesson_id] = (item["updated"], vec)
        except (OSError, ValueError, KeyError):
            pass

    def _save_cache(self) -> None:
        import numpy as np

        items = {k: {"updated": u, "vec": base64.b64encode(np.asarray(v, dtype=np.float16).tobytes()).decode()}
                 for k, (u, v) in self._vectors.items()}
        try:
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache.with_name(self.cache.name + ".tmp")
            tmp.write_text(json.dumps({"model": self.embedder.name, "items": items}), encoding="utf-8")
            os.replace(tmp, self.cache)
        except OSError as e:
            log.warning("经验向量没存上：%s", e)

    def _matrix(self, lessons: list[Lesson]):
        import numpy as np

        self._load_cache()
        stale = [x for x in lessons if self._vectors.get(x.id, (None,))[0] != x.updated]
        if stale:
            vectors = self.embedder.encode([lesson_text(x) for x in stale], "passage")
            if vectors is None:
                return None
            for lesson, vec in zip(stale, vectors):
                self._vectors[lesson.id] = (lesson.updated, vec)
            self._save_cache()  # 删掉的经验留下的向量不清理：一条不到 1KB，库本身也有上限
        return np.stack([self._vectors[x.id][1] for x in lessons])

    # ---- 想起 ----

    def problemness(self, vec) -> float:
        """像"碰到问题了"多少：和出问题的描述最像的那句，减去和"是什么、怎么用"最像的那句。"""
        if self._prototypes is None:
            self._prototypes = (self.embedder.encode(PROBLEM, "query"), self.embedder.encode(INFO, "query"))
        problem, info = self._prototypes
        return float((problem @ vec).max() - (info @ vec).max())

    def best(self, lessons: list[Lesson], text: str) -> tuple[Lesson, float] | None:
        """意思上最像的一条经验和相似度；不够像、或者这次不像是碰到了问题，返回 None。"""
        if not lessons or not text.strip() or not self.ready():
            return None
        query = self.embedder.encode([text], "query")
        if query is None:
            return None
        q = query[0]
        if self.problemness(q) < PROBLEM_MIN:
            return None
        matrix = self._matrix(lessons)
        if matrix is None:
            return None
        sims = matrix @ q
        i = int(sims.argmax())
        return (lessons[i], float(sims[i])) if sims[i] >= SIMILAR_MIN else None
