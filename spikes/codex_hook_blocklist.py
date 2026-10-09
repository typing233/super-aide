"""Codex PreToolUse 钩子（P0 验证用）：记录收到的请求；命中暗号就拒绝。

Codex 在执行工具前运行本脚本，把这次调用的 JSON 从标准输入传进来。
退出码 2 表示拒绝，标准错误里的文字会作为拒绝理由交给模型。
"""

import json
import sys
from pathlib import Path

LOG = Path(__file__).parent / "out" / "codex_hook_log.jsonl"
CANARY = "SUPER_AIDE_CANARY_BLOCK"

# Windows 下子进程默认按 GBK 输出；Codex 按 UTF-8 解析，中文理由会变成乱码导致钩子"失败"
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
LOG.parent.mkdir(parents=True, exist_ok=True)
with LOG.open("a", encoding="utf-8") as f:
    f.write(raw.strip() + "\n")

# Windows 上 Codex 经 PowerShell 运行钩子，退出码 2 会被吞成 1（算作钩子失败、放行），
# 所以拒绝只能靠"正常退出 + 标准输出里的 JSON 决定"。
if CANARY in raw:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "命中静默拦截清单，换一种做法。",
    }}, ensure_ascii=False))
sys.exit(0)
