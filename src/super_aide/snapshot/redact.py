"""发给引擎之前给文本打码：密钥、令牌、密码一类的值。"""

from __future__ import annotations

import re

MASK = "[已打码]"

_TOKEN_PATTERNS = [
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]
# "password: xxx"、"api_key=xxx" 这类键值对只遮住值
_KEY_VALUE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_\-]?key|access[_\-]?key|auth[_\-]?token)"
    r"(\s*[:=]\s*)([\"']?)([^\s\"']{4,})\3"
)


def redact(text: str) -> str:
    if not text:
        return text
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(MASK, text)
    return _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{MASK}{m.group(3)}", text)
