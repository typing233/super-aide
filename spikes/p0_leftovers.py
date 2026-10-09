"""P0 收尾验证。

1. Claude 侧能否自动拿到可用模型：SDK 的 get_server_info()，以及服务地址的 /v1/models。
2. Codex 原生 PreToolUse 钩子：通过启动参数（-c）注入，不改全局配置；在全放行
   （完全访问 + 不审批）下，普通命令照常执行、命中暗号的命令被拦下。

用法：uv run python spikes/p0_leftovers.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from p0_common import claude_env_from_settings, strip_nested_session_env

strip_nested_session_env()

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient  # noqa: E402
from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox  # noqa: E402

from p0_codex import SERVER_REQUESTS, approval_handler, run_turn  # noqa: E402

HERE = Path(__file__).resolve().parent
HOOK_LOG = HERE / "out" / "codex_hook_log.jsonl"
CANARY = "SUPER_AIDE_CANARY_BLOCK"


async def claude_models() -> None:
    print("=== 1. Claude 可用模型 ===")
    env = claude_env_from_settings()
    async with ClaudeSDKClient(options=ClaudeAgentOptions(env=env)) as client:
        info = await client.get_server_info() or {}
    print(f"  get_server_info 字段：{sorted(info.keys())}")
    models = info.get("models") or []
    if models:
        print(f"  SDK 报告的模型：{[m.get('value') or m.get('id') for m in models]}")

    base = env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    token = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY", "")
    req = urllib.request.Request(f"{base}/v1/models", headers={
        "Authorization": f"Bearer {token}", "x-api-key": token, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ids = [m.get("id") for m in data.get("data", [])]
        print(f"  服务地址 /v1/models：{len(ids)} 个 → {ids[:20]}")
    except Exception as e:  # noqa: BLE001
        print(f"  服务地址 /v1/models 不可用：{type(e).__name__} {str(e)[:120]}")


def codex_hook() -> None:
    print("\n=== 2. Codex 原生 PreToolUse 钩子（全放行）===")
    HOOK_LOG.unlink(missing_ok=True)
    hook_cmd = f"{sys.executable} {HERE / 'codex_hook_blocklist.py'}"
    override = "hooks.PreToolUse=[{hooks=[{type=\"command\", command='" + hook_cmd + "'}]}]"
    tmp = Path(tempfile.mkdtemp(prefix="super_aide_p0_hook_"))
    with Codex(CodexConfig(cwd=str(tmp), config_overrides=(override,))) as codex:
        codex._client._approval_handler = approval_handler
        thread = codex.thread_start(sandbox=Sandbox.full_access, approval_mode=ApprovalMode.deny_all,
                                    ephemeral=True, cwd=str(tmp))
        run_turn(thread, (
            "按顺序用命令行执行，每条单独执行，不要合并：\n"
            "1. echo hello\n"
            f"2. echo {CANARY}\n"
            "最后用中文简短汇报每条的结果。"
        ), "钩子拦截", effort="low", timeout_s=180)
    lines = HOOK_LOG.read_text(encoding="utf-8").splitlines() if HOOK_LOG.exists() else []
    print(f"  钩子被调用 {len(lines)} 次")
    for line in lines[:4]:
        try:
            payload = json.loads(line)
            print(f"    字段 {sorted(payload.keys())}；tool_name={payload.get('tool_name')}；"
                  f"tool_input={str(payload.get('tool_input'))[:100]}")
        except json.JSONDecodeError:
            print(f"    （非 JSON）{line[:120]}")
    print(f"  服务端请求：{SERVER_REQUESTS or '无'}")


if __name__ == "__main__":
    t = time.perf_counter()
    asyncio.run(claude_models())
    codex_hook()
    print(f"\n总耗时 {time.perf_counter() - t:.0f}s")
