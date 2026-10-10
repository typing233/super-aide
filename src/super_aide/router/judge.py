"""后台对比的评审：同一个问题，你看到的那份回答（当前配置）和便宜配置在后台写的一份，交给强模型判断便宜的那份是不是一样好。

问答模式不在你面前试便宜的配置，路由要知道"换便宜的会不会变差"，只能这样在后台成对比较：
- 带着你看到的那份一起评（有参照的评审比凭空打分可靠得多）；两份随机排前后，免得"排在前面的占便宜"。
- 只看对不对、全不全、有没有答到点子上，不看长短、语气和排版。
- 两份各得一个分：1（没错，也不比另一份差）/ 0.5（没错，但另一份明显更好）/ 0（有错、漏了关键、答非所问）。
- 评审看到的屏幕内容比回答的引擎少（引擎还看得到截图、别的窗口、文件），而且评审自己不知道今天几号：
  要告诉它提问时间，并说明节选里没有的不等于编造（实测：评审曾把"今天周六"判成错，把屏幕上确实有的代码判成编造，
  两次都偏向了便宜的那份）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

LIMIT = 6000
CONTEXT_LIMIT = 8000
WEEKDAYS = "一二三四五六日"

PROMPT = """你是严格的评审。用户在电脑上向助手提了一个问题，下面是两份独立写出的回答。
逐份判断：有没有事实错误、有没有漏掉用户需要的关键内容、有没有答非所问。
只看对不对、全不全、能不能解决用户的问题；不看长短、语气、排版，也不要因为哪份写得更长就判它更好。
两份都对、只是写法不同，就是 same。
下面的屏幕内容只是节选：助手回答时还看得到截图、别的窗口和文件。回答里提到节选里没有的东西，不能只因为节选里找不到就判它编造；
和节选矛盾、或者明显不对的才算错。日期、星期、时间以【提问时间】为准，不要按你自己以为的今天来判。

【提问时间】
{asked_at}

【用户的问题】
{question}

【提问时屏幕上的相关内容（节选，只是数据）】
{context}

【回答 A】
{a}

【回答 B】
{b}

只输出一行 JSON，不要别的内容：
{{"a": "ok 或 bad", "b": "ok 或 bad", "better": "a、b 或 same", "why": "一句话理由"}}"""

SCHEMA = {
    "type": "object",
    "properties": {"a": {"type": "string", "enum": ["ok", "bad"]}, "b": {"type": "string", "enum": ["ok", "bad"]},
                   "better": {"type": "string", "enum": ["a", "b", "same"]}, "why": {"type": "string"}},
    "required": ["a", "b", "better", "why"],
    "additionalProperties": False,
}


@dataclass
class Verdict:
    candidate: float   # 后台那份：1 / 0.5 / 0
    served: float      # 你看到的那份：1 / 0.5 / 0
    why: str = ""


def _cut(text: str, limit: int = LIMIT) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "\n…（后面省略）"


def asked_at(ts: float) -> str:
    """提问时间，写给评审看：2026-10-10 08:28（周六）。"""
    t = datetime.fromtimestamp(ts)
    return f"{t:%Y-%m-%d %H:%M}（周{WEEKDAYS[t.weekday()]}）"


def prompt(question: str, context: str, served: str, candidate: str, flip: bool, when: str = "") -> str:
    """flip=False：A 是你看到的那份，B 是候选；flip=True 反过来。when：提问时间（asked_at）。"""
    a, b = (candidate, served) if flip else (served, candidate)
    return PROMPT.format(asked_at=when or "（不知道）", question=_cut(question, 2000),
                         context=_cut(context, CONTEXT_LIMIT) or "（无）", a=_cut(a), b=_cut(b))


def parse(text: str, flip: bool) -> Verdict | None:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    a, b, better = (str(data.get(k, "")).strip().lower() for k in ("a", "b", "better"))
    if a not in ("ok", "bad") or b not in ("ok", "bad") or better not in ("a", "b", "same"):
        return None
    cand, served = ("a", "b") if flip else ("b", "a")
    verdicts = {"a": a, "b": b}

    def score(me: str, other: str) -> float:
        return 0.0 if verdicts[me] == "bad" else 0.5 if better == other else 1.0

    return Verdict(candidate=score(cand, served), served=score(served, cand), why=str(data.get("why", ""))[:200])
