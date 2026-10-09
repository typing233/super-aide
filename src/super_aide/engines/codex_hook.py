"""Codex 的执行前钩子：每次工具调用前由 Codex 启动一次，命中拦截清单就拒绝。

协议与 Claude Code 的钩子一致：调用信息以 JSON 从标准输入传入。
Windows 上 Codex 经 PowerShell 运行钩子，退出码 2 会被吞成 1（算作钩子失败、放行），
所以拒绝只能用"正常退出 + 标准输出里的 JSON 决定"；输出必须是 UTF-8（P0 验证）。
"""

import json
import sys

from super_aide.safety import blocked_reason


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        tool_input = json.dumps(json.loads(payload).get("tool_input", {}), ensure_ascii=False)
    except json.JSONDecodeError:
        tool_input = payload
    reason = blocked_reason(tool_input)
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (f"这个操作在静默拦截清单里（{reason}）。不要执行，也不要换个写法绕过；"
                                         "告诉用户这一步需要他自己来做。"),
        }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
