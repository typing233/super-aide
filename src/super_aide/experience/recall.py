"""想起经验：只在碰到相似情况时想起，平时一条也不带（发一句"你好"不会带上任何经验）。

这次的情况（Situation）= 问题 + 框选区域的原文和选中的文字 + 前台窗口里的报错行 + 程序名、网址、窗口标题。

每条经验有三种线索：
- 报错特征（errors）：最强，对上一个就放行；
- 提示词（triggers）：总结经验时由模型写好，包括中英文同义词，对上两个就放行；
- 程序、网站（apps、domains）：单独对上不够（不然在 Edge 里问什么都会想起 Edge 的经验），
  只能把"对上一个提示词"补成放行，并且加分。
报错特征和提示词只拿"问题本身"（问题、框选的原文、报错行）去对，不拿网址和窗口标题去对：
网址、标题是环境，只通过程序、网站那一项起作用（实测：经验的提示词里写了 modelscope，
在 modelscope.cn 上问一句翻译也被想起来了）。

放行的按"线索分 + BM25"排序，最多给 MAX_RECALL 条。BM25 里中文按相邻两个字切分（不用分词词典），
英文按词切，驼峰名再拆开（AutoTokenizer → auto、tokenizer）。
字面对不上、意思一样的，由本地向量模型补（semantic.py，模型下载好之后才有），每次最多补 1 条。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlparse

from .store import Lesson, Store

MAX_RECALL = 2  # ReasoningBank 实测：想起的条数越多，成功率反而越低（默认只取 1 条）
SEMANTIC_BASE = 0.85
CJK_RUN = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")
LATIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")
CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
NON_WORD = re.compile(r"[\W_]+")
ERROR_LINE = re.compile(r"error|exception|traceback|fail|fatal|denied|not found|cannot|can't|unable|invalid|refused"
                        r"|timed? ?out|错误|失败|异常|报错|找不到|无法|拒绝|未定义|不存在|超时|出错|未找到|0x[0-9a-f]{8}",
                        re.IGNORECASE)
STOP = {
    "the", "and", "for", "you", "are", "this", "that", "with", "what", "why", "how", "can", "not", "but", "was",
    "什么", "怎么", "为什", "为何", "一下", "这个", "那个", "可以", "如何", "是不", "不是", "我的", "你的", "现在",
    "还是", "但是", "然后", "就是", "没有", "一个", "这是", "帮我", "请问", "我们", "他们", "这样", "那样", "时候",
}
#: 太宽泛的提示词，对上了也不算（总结时也要求模型别写这些）
GENERIC = {"报错", "错误", "问题", "失败", "异常", "安装", "软件", "电脑", "程序", "运行", "打不开", "怎么办", "不行",
           "error", "errors", "exception", "failed", "failure", "problem", "issue", "install", "windows", "run"}


def tokens(text: str) -> list[str]:
    """中英文混排切成检索用的词：英文整词（小写）+ 驼峰和点、下划线拆开的部分；中文相邻两个字。"""
    out: list[str] = []
    for m in LATIN.finditer(text):
        word = m.group(0).strip("._-")
        low = word.lower()
        if len(low) >= 2 and low not in STOP:
            out.append(low)
        parts = [p.lower() for p in CAMEL.findall(word)]
        parts += [p.lower() for p in re.split(r"[._\-]+", word)] if re.search(r"[._\-]", word) else []
        out += [p for p in dict.fromkeys(parts) if len(p) >= 3 and p != low and p not in STOP]
    for m in CJK_RUN.finditer(text):
        run = m.group(0)
        grams = [run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)]
        out += [g for g in grams if g not in STOP]
    return out


def text_of(value, limit: int = 20_000) -> str:
    """工具结果里的文字（跳过图片这类二进制大块）。"""
    out: list[str] = []

    def walk(v, depth: int) -> None:
        if depth > 6 or sum(map(len, out)) > limit:
            return
        if isinstance(v, str):
            out.append(v[:limit])
        elif isinstance(v, dict):
            if v.get("type") == "image":
                return
            for k, x in v.items():
                if k not in ("data", "source", "image", "base64"):
                    walk(x, depth + 1)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x, depth + 1)

    walk(value, 0)
    return "\n".join(out)[:limit]


def compact(text: str) -> str:
    return NON_WORD.sub("", text.lower())


def error_lines(text: str, limit: int = 30) -> str:
    """一大段文字里像报错的行（前台窗口的完整内容很长，只取这些去匹配）。"""
    picked = [line.strip()[:200] for line in text.splitlines() if ERROR_LINE.search(line)]
    return "\n".join(dict.fromkeys(picked))[:6000] if picked else ""


@dataclass
class Situation:
    question: str = ""
    text: str = ""  # 框选区域的原文、选中的文字
    errors: str = ""  # 前台窗口里的报错行
    app: str = ""  # 前台程序的 exe 名
    url: str = ""
    title: str = ""

    def problem(self) -> str:
        """问题本身：问题、框选的原文、报错行（不含网址、标题这些环境）。"""
        return "\n".join(x for x in (self.question, self.text, self.errors) if x)

    def gist(self) -> str:
        """给向量模型的一小段：问题加上报错（框选的原文可能是一大段代码，整段放进去反而冲淡了）。"""
        errors = self.errors or error_lines(self.text, limit=8)
        return "\n".join(x for x in (self.question, errors) if x)[:600]

    def query(self) -> str:
        return "\n".join(x for x in (self.problem(), self.title, self.url) if x)

    def domain(self) -> str:
        host = urlparse(self.url if "://" in self.url else f"http://{self.url}").hostname if self.url else ""
        return (host or "").lower().removeprefix("www.")


class _Query:
    def __init__(self, situation: Situation) -> None:
        problem = situation.problem()
        self.tokens = set(tokens(problem))  # 对线索只用问题本身
        self.compact = compact(problem)
        self.ranking = set(tokens(situation.query()))  # 排序时连环境一起算
        self.app = situation.app.lower()
        self.domain = situation.domain()


def _hit(cue: str, q: _Query, min_len: int = 2) -> bool:
    """一条线索对不对得上：中文看相邻两字的重合（不要求一字不差）；英文单词按整词，短语按去掉空格标点后的子串。"""
    flat = compact(cue)
    if len(flat) < min_len or cue.strip().lower() in GENERIC or flat in GENERIC:
        return False
    if CJK_RUN.search(cue):
        if len(flat) <= 2:
            return flat in q.compact
        grams = [g for g in tokens(cue) if g not in STOP]
        hits = sum(g in q.tokens or g in q.compact for g in grams)
        return bool(grams) and hits >= max(2, math.ceil(0.6 * len(grams)))
    words = LATIN.findall(cue)
    if len(words) == 1:
        return words[0].lower().strip("._-") in q.tokens
    return flat in q.compact


def _context(lesson: Lesson, q: _Query) -> bool:
    if q.app and q.app in (a.lower() for a in lesson.apps):
        return True
    return bool(q.domain) and any(q.domain == d.lower().removeprefix("www.")
                                  or q.domain.endswith("." + d.lower().removeprefix("www."))
                                  for d in lesson.domains if d)


def _document(lesson: Lesson) -> list[str]:
    """参与 BM25 的字段（做法不参与：里面"装包""重启"这类词会把不相干的经验带出来）。"""
    return (tokens(lesson.title) * 2 + tokens(lesson.when) + tokens(" ".join(lesson.triggers)) * 2
            + tokens(" ".join(lesson.errors)) * 2)


def _bm25(docs: list[list[str]], query: set[str], k1: float = 1.2, b: float = 0.5) -> list[float]:
    n = len(docs)
    avg = sum(map(len, docs)) / n if n else 0
    df = Counter(t for doc in docs for t in set(doc))
    scores = []
    for doc in docs:
        tf = Counter(doc)
        score = 0.0
        for t in query & tf.keys():
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(doc) / (avg or 1)))
        scores.append(score)
    return scores


def recall(store: Store, situation: Situation, exclude: set[str] | frozenset = frozenset(),
           limit: int = MAX_RECALL, semantic=None) -> list[Lesson]:
    """和这次情况相似的经验，最多 limit 条；都对不上就返回空列表。
    semantic：本地向量模型（semantic.Semantic），有的话字面没对上的再按意思找一条。"""
    lessons = [x for x in store.all() if x.id not in exclude]
    q = _Query(situation)
    if not lessons or not q.tokens:
        return []
    scored = []
    for lesson, bm in zip(lessons, _bm25([_document(x) for x in lessons], q.ranking)):
        strong = sum(_hit(e, q, min_len=6) for e in lesson.errors)
        medium = sum(_hit(t, q) for t in lesson.triggers)
        context = _context(lesson, q)
        if strong or medium >= 2 or (medium and context):
            scored.append((3 * strong + 1.5 * medium + context + bm, lesson))
    if semantic is not None:
        passed = {lesson.id for _score, lesson in scored}
        try:
            hit = semantic.best([x for x in lessons if x.id not in passed], situation.gist())
        except Exception:  # noqa: BLE001 - 模型出问题不能耽误回答，字面那一半照常
            hit = None
        if hit is not None:
            scored.append((1.5 + 10 * (hit[1] - SEMANTIC_BASE), hit[0]))  # 排在字面对上的后面，除非意思特别接近
    scored.sort(key=lambda s: s[0], reverse=True)
    return [lesson for _score, lesson in scored[:limit]]


def render(lessons: list[Lesson]) -> str:
    """交给引擎的写法：每条一行，短。"""
    return "\n".join(f"- {x.title}：{x.advice}（适用：{x.when}）" for x in lessons)
