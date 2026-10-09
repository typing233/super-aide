"""Codex 的执行后钩子：命令的输出里有报错时，想起以前在相似报错上踩过的坑，附在这次结果后面交给模型。

协议和 Claude Code 的钩子一样：调用信息以 JSON 从标准输入传入，标准输出给 JSON（additionalContext）。
每次工具调用 Codex 都启动一次这个脚本，所以只导入经验库这几个轻的模块。
同一个会话里给过的经验、已经补过几次，记在临时文件里：不重复给，一个会话最多补 MAX_PER_SESSION 次。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from super_aide.experience.recall import Situation, error_lines, recall, render, text_of
from super_aide.experience.store import Store

MAX_PER_SESSION = 4
NOTE = "【以前踩过的坑】刚才的结果里有报错。以前遇到相似情况时总结的经验，只在和这次情况相符时参考：\n"


def respond(payload: dict, store: Store | None = None) -> str:
    """→ 要补给模型的话（没有就空字符串）。"""
    lines = error_lines(text_of(payload.get("tool_response")))
    if not lines:
        return ""
    session = "".join(c for c in str(payload.get("session_id") or "") if c.isalnum() or c in "-_")[:64]
    state_file = Path(tempfile.gettempdir()) / f"aide-recall-{session}.json" if session else None
    state = {"seen": [], "count": 0}
    if state_file is not None and state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    if state["count"] >= MAX_PER_SESSION:
        return ""
    found = recall(store or Store(), Situation(text=lines), exclude=set(state["seen"]))
    if not found:
        return ""
    if state_file is not None:
        state = {"seen": state["seen"] + [x.id for x in found], "count": state["count"] + 1}
        state_file.write_text(json.dumps(state), encoding="utf-8")
    return NOTE + render(found)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        return 0
    note = respond(payload)
    if note:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
