"""经验库：~/.super_aide/experience/lessons.json。

不是记事本：经验不会每次都塞进提示词，只有碰到相似情况时才会被想起（recall.py）。
库有上限（MAX_LESSONS）：新经验和旧经验相似时由模型决定合并更新还是新加（learn.py）；
超过上限时先淘汰"用了总不管用"和"很久没用到"的。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .. import paths

MAX_LESSONS = 200
HALF_LIFE_DAYS = 90  # 这么久没被想起，分量减半
DROP_AFTER_FAILS = 3  # 想起之后那一轮还是没办成，累计这么多次、而且几乎每次都这样，就删掉


@dataclass
class Lesson:
    id: str
    title: str  # 一句话：什么坑
    when: str  # 什么情况下适用
    advice: str  # 该怎么做、别怎么做
    triggers: list[str] = field(default_factory=list)  # 提示词：关键词、报错片段、软件名（中英文同义词）
    errors: list[str] = field(default_factory=list)  # 报错特征：ModuleNotFoundError、0x80070643……
    apps: list[str] = field(default_factory=list)  # 相关程序的 exe 名
    domains: list[str] = field(default_factory=list)  # 相关网站的域名
    source: str = ""  # 从哪次会话学到的
    created: float = 0.0
    updated: float = 0.0
    uses: int = 0  # 被想起并交给引擎的次数
    fails: int = 0  # 想起之后那一轮还是没办成的次数
    last_used: float = 0.0

    def utility(self, now: float) -> float:
        """留不留的分数：成功率（新经验先给机会）× 多久没被想起。"""
        success = (self.uses - self.fails + 1) / (self.uses + 2)
        idle = (now - max(self.last_used, self.created)) / 86400
        return success * 0.5 ** (idle / HALF_LIFE_DAYS)


_FIELDS = {f.name for f in fields(Lesson)}


def _clean(items) -> list[str]:
    out: list[str] = []
    for item in items or []:
        text = " ".join(str(item).split())[:80]
        if text and text.lower() not in (o.lower() for o in out):
            out.append(text)
    return out[:24]


class Store:
    def __init__(self, path: Path | None = None) -> None:
        # AIDE_LESSONS：自检时指到临时文件（Codex 的工具服务器是另一个进程，靠它跟着换）
        self.path = path or Path(os.environ.get("AIDE_LESSONS") or paths.HOME / "experience" / "lessons.json")
        self._lock = threading.Lock()
        self._mtime = -1.0
        self._lessons: dict[str, Lesson] = {}

    # ---- 读 ----

    def _load(self) -> None:
        """文件比内存里的新就重新读（工具服务器是另一个进程，只读这个文件）。"""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._lessons, self._mtime = {}, -1.0
            return
        if mtime == self._mtime:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self._lessons = {}
        for item in raw.get("lessons", []):
            data = {k: v for k, v in item.items() if k in _FIELDS}
            if data.get("id") and data.get("title"):
                self._lessons[data["id"]] = Lesson(**data)
        self._mtime = mtime

    def all(self) -> list[Lesson]:
        with self._lock:
            self._load()
            return list(self._lessons.values())

    def get(self, lesson_id: str) -> Lesson | None:
        with self._lock:
            self._load()
            return self._lessons.get(lesson_id)

    # ---- 写 ----

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        payload = {"version": 1, "lessons": [asdict(x) for x in self._lessons.values()]}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
        self._mtime = self.path.stat().st_mtime

    def add(self, title: str, when: str, advice: str, source: str = "", **cues) -> Lesson:
        now = time.time()
        lesson = Lesson(id=time.strftime("L%Y%m%d-") + uuid.uuid4().hex[:6], title=title.strip(), when=when.strip(),
                        advice=advice.strip(), source=source, created=now, updated=now,
                        **{k: _clean(cues.get(k)) for k in ("triggers", "errors", "apps", "domains")})
        with self._lock:
            self._load()
            self._lessons[lesson.id] = lesson
            self._evict(now)
            self._save()
        return lesson

    def update(self, lesson_id: str, **changes) -> Lesson | None:
        """合并更新：文字类字段换成新的，线索取并集，用过的次数保留。"""
        with self._lock:
            self._load()
            lesson = self._lessons.get(lesson_id)
            if lesson is None:
                return None
            for key in ("title", "when", "advice"):
                if str(changes.get(key) or "").strip():
                    setattr(lesson, key, str(changes[key]).strip())
            for key in ("triggers", "errors", "apps", "domains"):
                if changes.get(key):
                    setattr(lesson, key, _clean(list(changes[key]) + getattr(lesson, key)))
            if changes.get("source"):
                lesson.source = changes["source"]
            lesson.updated = time.time()
            self._save()
            return lesson

    def used(self, lesson_ids: list[str], ok: bool | None) -> None:
        """这些经验被交给了引擎；ok 是那一轮的结果（None = 不算数，比如网络问题、你中途停止）。"""
        if not lesson_ids:
            return
        now = time.time()
        with self._lock:
            self._load()
            for lesson_id in lesson_ids:
                lesson = self._lessons.get(lesson_id)
                if lesson is None:
                    continue
                lesson.last_used = now
                if ok is None:
                    continue
                lesson.uses += 1
                if ok is False:
                    lesson.fails += 1
                if lesson.fails >= DROP_AFTER_FAILS and lesson.fails >= lesson.uses * 0.75:
                    del self._lessons[lesson_id]  # 几乎每次想起都没帮上忙：多半是条错误的经验
            self._save()

    def failed(self, lesson_ids: list[str]) -> None:
        """事后发现那一轮没答好（你说"不对"、点了 👎）：已经记过一次使用，只补记失败。"""
        with self._lock:
            self._load()
            for lesson_id in lesson_ids:
                lesson = self._lessons.get(lesson_id)
                if lesson is not None and lesson.fails < lesson.uses:
                    lesson.fails += 1
            self._save()

    def remove(self, lesson_id: str) -> bool:
        with self._lock:
            self._load()
            if self._lessons.pop(lesson_id, None) is None:
                return False
            self._save()
            return True

    def _evict(self, now: float) -> None:
        while len(self._lessons) > MAX_LESSONS:
            worst = min(self._lessons.values(), key=lambda x: x.utility(now))
            del self._lessons[worst.id]
