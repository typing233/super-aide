"""从踩过的坑里总结经验。

什么时候总结：一次对话结束（最后一轮之后 LEARN_DELAY 秒没有追问），而且走了弯路的才总结：
没办成、被纠正（追问里说"不对""还是不行"、点了 👎）、一轮里绕了很久（工具调用多或者用时长）、
你明确说了"记住""以后别…"。顺利的对话不总结，库里不会堆一堆没用的东西。

怎么总结：把这次对话（问题、框选区域的原文、助手做了哪些步骤、回答、结果、你的反馈）和库里最相似的几条经验
交给模型，让它判断有没有以后用得上的经验、是新加还是更新已有的一条，并写好触发线索（中英文同义词）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

from ..snapshot import redact
from . import recall
from .store import Store

LEARN_DELAY = 120.0  # 最后一轮之后这么久没有追问，就当这次对话结束了
LONG_TURN_S = 120
MANY_TOOLS = 12
REMEMBER = re.compile(r"记住|以后|下次|别再|不要再|每次都")
INFRA = ("401", "403", "429", "timeout", "timed out", "network", "connection", "rate limit", "认证", "限流")
SIMILAR = 5

PROMPT = """你在帮一个 Windows 桌面助手积累"经验"。下面是它刚处理完的一次对话（{reason}）。
请判断里面有没有值得记住、以后遇到相似情况能少走弯路的经验。

好的经验：
- 可复用：换一台电脑、换一个具体的文件或网页，相似的情况下照样适用，不是这一次的流水账；
- 具体可执行：说清楚遇到什么情况、该怎么做或别怎么做，带上能一眼认出这种情况的特征（报错原文、软件、网站）；
- 是真正的坑或者捷径：助手判断错了、绕了远路、被用户纠正了、费了很大劲才找到办法，或者用户明确要求以后怎么做。
不要记：常识、这次碰巧的偶发问题（网络抖动、服务暂时不可用）、用户的隐私（人名、账号、文件和聊天的内容）。
原因要有记录支撑：记录里看不出确切原因时（比如某一步卡了很久、窗口突然没了、程序没响应），不要猜一个原因写成经验，宁可不记。

库里已有的相似经验（可能为空）：
{similar}

和某条已有经验说的是同一件事，就用 update 把它改得更准、补上新的线索；是新的经验用 add；没有值得记的用 none。
只输出一个 JSON 对象，不要别的文字：
{{"action": "none 或 add 或 update", "id": "update 时填已有经验的编号",
 "title": "一句话说清是什么坑，20 字以内（对话是英文的就用英文写，10 个词以内；它会显示给用户）",
 "when": "什么情况下适用，具体到能判断",
 "advice": "该怎么做、别怎么做，1～3 句",
 "triggers": ["能认出这种情况的问题特征：报错里固定的说法、症状的各种说法，6～15 个，中英文同义词都写（比如 找不到模块、No module named、ModuleNotFoundError、导入失败）。不要写：报错、错误、问题、安装、软件这类太宽泛的词；软件名、网站名（写到 apps、domains 里）；这一次具体的包名、变量名、文件名"],
 "errors": ["报错里固定不变、最有辨识度的部分，比如 ModuleNotFoundError、No module named、0x80070643；不要带这一次具体的名字；没有就留空"],
 "apps": ["相关程序的 exe 名，比如 msedge.exe；和具体程序无关就留空"],
 "domains": ["相关网站的域名，比如 modelscope.cn；和网站无关就留空"],
 "why": "为什么值得记，一句话"}}

这次对话：
{conversation}"""

#: Codex 兜底时要它按这个结构输出
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {k: {"type": "string"} for k in ("action", "id", "title", "when", "advice", "why")}
    | {k: {"type": "array", "items": {"type": "string"}} for k in ("triggers", "errors", "apps", "domains")},
    "required": ["action", "id", "title", "when", "advice", "why", "triggers", "errors", "apps", "domains"],
}


def worth_learning(turns: list[dict], negative: bool = False) -> str:
    """这次对话值不值得总结，值得就返回原因（写进提示词）。"""
    if negative:
        return "用户说上一轮没答好"
    for t in turns:
        error = str(t.get("error", "")).lower()
        if not t.get("ok", True) and t.get("reason") != "interrupted" and not any(k in error for k in INFRA):
            return "没办成"
    for t in turns:
        if REMEMBER.search(str(t.get("question", ""))):
            return "用户要求以后照着做"
        if t.get("seconds", 0) >= LONG_TURN_S or t.get("tools", 0) >= MANY_TOOLS:
            return "绕了很久才办完"
    return ""


def situation_of(turns: list[dict]) -> recall.Situation:
    """用对话里的问题和当时的情况去找相似的已有经验。"""
    first = turns[0] if turns else {}
    env = first.get("situation") or {}
    return recall.Situation(question="\n".join(str(t.get("question", "")) for t in turns),
                            text=str(env.get("text", "")), errors=str(env.get("errors", "")),
                            app=str(env.get("app", "")), url=str(env.get("url", "")), title=str(env.get("title", "")))


def describe(turns: list[dict], feedback: str = "") -> str:
    """给模型看的对话经过。长的地方截断，统一打码。"""
    parts = []
    for i, t in enumerate(turns, 1):
        env = t.get("situation") or {}
        lines = [f"【第 {i} 轮】问题：{t.get('question', '')}"]
        where = "，".join(x for x in (env.get("app"), env.get("title") and f"「{env['title']}」",
                                      env.get("url") and f"网址 {env['url']}") if x)
        if where:
            lines.append(f"当时的前台：{where}")
        if env.get("text"):
            lines.append(f"框选区域的原文：\n{str(env['text'])[:1500]}")
        if env.get("errors"):
            lines.append(f"前台窗口里的报错行：\n{str(env['errors'])[:1000]}")
        trace = t.get("trace") or []
        if trace:
            lines.append("助手的步骤：" + "；".join(f"{n}. {s}" for n, s in enumerate(trace[:40], 1)))
        lines.append(f"回答：\n{str(t.get('answer', ''))[:2000]}")
        result = "办成了" if t.get("ok", True) else f"没办成（{t.get('error') or t.get('reason') or '原因不明'}）"
        lines.append(f"结果：{result}；用时 {t.get('seconds', 0):.0f} 秒，调用工具 {t.get('tools', 0)} 次")
        parts.append("\n".join(lines))
    if feedback:
        parts.append(f"用户事后的反馈：{feedback}")
    return redact.redact("\n\n".join(parts))


def parse(text: str) -> dict | None:
    """从模型的回答里取出 JSON（可能包在代码块或者前后有话）。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def learn(store: Store, turns: list[dict], reason: str, llm: Callable[[str], Awaitable[str]],
                feedback: str = "", source: str = "", semantic=None) -> str:
    """总结一次对话，写进经验库。返回做了什么（写日志用）。"""
    similar = recall.recall(store, situation_of(turns), limit=SIMILAR, semantic=semantic)
    listing = "\n".join(f"[{x.id}] {x.title} / 适用：{x.when} / 做法：{x.advice}" for x in similar) or "（无）"
    data = parse(await llm(PROMPT.format(reason=reason, similar=listing, conversation=describe(turns, feedback))))
    if data is None:
        return "模型没给出能解析的结果"
    action = str(data.get("action", "none")).strip().lower()
    fields = {k: data.get(k) for k in ("title", "when", "advice", "triggers", "errors", "apps", "domains")}
    if action == "update" and store.get(str(data.get("id", ""))):
        lesson = store.update(str(data["id"]), source=source, **fields)
        return f"更新经验 {lesson.id}：{lesson.title}" if lesson else "更新失败"
    if action in ("add", "update") and str(fields["title"] or "").strip() and str(fields["advice"] or "").strip():
        lesson = store.add(str(fields["title"]), str(fields["when"] or ""), str(fields["advice"]), source=source,
                           **{k: fields[k] for k in ("triggers", "errors", "apps", "domains")})
        return f"新经验 {lesson.id}：{lesson.title}"
    return f"没有值得记的经验（{str(data.get('why', ''))[:60]}）"
