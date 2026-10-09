"""选区内容类型 → 推荐问题（设计 3.2 节）。纯本地规则，不调用模型。"""

from __future__ import annotations

import re

from .. import i18n

ERROR_RE = re.compile(
    r"Traceback \(most recent call last\)|\b\w*(?:Error|Exception)\b|\bfailed\b|\bdenied\b"
    r"|\bnot found\b|错误|失败|异常|无法|拒绝访问|找不到|未找到|0x[0-9A-Fa-f]{8}",
    re.IGNORECASE,
)
CODE_LINE_RE = re.compile(
    r"^\s*(?:def |class |import |from \S+ import|function\b|const |let |var |public |private "
    r"|#include|SELECT\b|INSERT\b|UPDATE\b|return\b|if\s*\(|for\s*\()|[{};]\s*$|=>",
    re.IGNORECASE,
)
CJK_RE = re.compile(r"[一-鿿]")
LATIN_RE = re.compile(r"[A-Za-z]")

PLACEHOLDERS = {
    "error": ("这个报错是什么原因？", "帮我修好它"),
    "code": ("解释这段代码", "帮我改好"),
    "foreign": ("翻译并解释", "翻译并替换成中文"),  # 英文界面里"外文"是中文这类，英文版说的是换成英文
    "dialog": ("这是什么意思，该怎么选？", "帮我按推荐设置好"),
    "text": ("这是什么？", "帮我处理"),
}

DIALOG_CLASSES = {"#32770"}


def classify(text: str, *, source: str = "selection", window_class: str = "") -> str:
    """source 为 "selection"（用户选中/框选的内容）或 "window"（整个窗口的文字）。

    整窗文字里英文界面很常见，所以只有选中的内容才会被判为"外文"。
    "外文"按界面语言算：中文界面里是成段的英文这类，英文界面里是成段的中文。
    """
    sample = (text or "")[:6000]
    if ERROR_RE.search(sample):
        return "error"
    if window_class in DIALOG_CLASSES:
        return "dialog"
    lines = [line for line in sample.splitlines() if line.strip()]
    if lines and sum(1 for line in lines if CODE_LINE_RE.search(line)) / len(lines) >= 0.3:
        return "code"
    if source == "selection":
        cjk, latin = len(CJK_RE.findall(sample)), len(LATIN_RE.findall(sample))
        if i18n.lang() == "en":
            if cjk >= 10 and cjk >= latin * 0.5:
                return "foreign"
        elif latin >= 30 and cjk <= latin * 0.02:
            return "foreign"
    return "text"


def placeholders(kind: str) -> dict[str, str]:
    ask, act = PLACEHOLDERS.get(kind, PLACEHOLDERS["text"])
    return {"ask": i18n.tr(ask), "act": i18n.tr(act)}
