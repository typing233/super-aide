"""P0-② Claude Agent SDK 验证（走你 settings.json 里的自定义服务地址）。

1. 问答模式：dontAsk + 只读允许清单。带图提问能答；让它写文件会被自动拒绝，不弹窗。
2. 操作模式：bypassPermissions（全放行）+ PreToolUse 钩子静默拦截。普通命令照常执行，
   命中拦截清单的命令（用无害的暗号代替真正的危险命令）被拦下。
3. 延迟：冷启动连接、首字时间、预热后第二问的首字时间。

用法：uv run python spikes/p0_claude.py
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from p0_common import claude_env_from_settings, strip_nested_session_env, synthetic_error_b64

strip_nested_session_env()

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

CANARY = "SUPER_AIDE_CANARY_BLOCK"
ASK_APPEND = "当前是问答模式：只回答，不修改任何东西。用中文回答，第一句就是结论，越短越好。"
ACT_APPEND = "当前是操作模式：可以直接执行。用中文简短汇报结果。"


async def image_message(text: str):
    yield {
        "type": "user",
        "message": {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": synthetic_error_b64()}},
            {"type": "text", "text": text},
        ]},
        "parent_tool_use_id": None,
        "session_id": "default",
    }


async def run_turn(client: ClaudeSDKClient, prompt, label: str) -> ResultMessage | None:
    t0 = time.perf_counter()
    first_text = None
    await client.query(prompt)
    result = None
    async for msg in client.receive_response():
        if isinstance(msg, StreamEvent):
            if first_text is None and msg.event.get("type") == "content_block_delta" \
                    and msg.event.get("delta", {}).get("type") == "text_delta":
                first_text = time.perf_counter() - t0
        elif isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, ToolUseBlock):
                    print(f"    · 调用工具 {block.name}: {str(block.input)[:120]}")
                elif isinstance(block, TextBlock) and block.text.strip():
                    print(f"    回答：{block.text.strip()[:300]}")
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    status = "出错/被拒" if block.is_error else "成功"
                    print(f"    · 工具结果（{status}）：{str(block.content)[:160]}")
        elif isinstance(msg, ResultMessage):
            result = msg
    total = time.perf_counter() - t0
    ft = f"{first_text:.1f}s" if first_text is not None else "-"
    if result:
        print(f"  [{label}] 首字 {ft}，总计 {total:.1f}s，轮数 {result.num_turns}，"
              f"费用估算 ${result.total_cost_usd or 0:.4f}，"
              f"被拒绝的工具调用 {len(result.permission_denials or [])} 次，"
              f"结束原因 {result.terminal_reason}")
    return result


async def blocklist_hook(input_data, tool_use_id, context):
    command = str(input_data.get("tool_input", {}).get("command", ""))
    if CANARY in command:
        print(f"    ⛔ 钩子拦下：{command[:80]}")
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "命中静默拦截清单，换一种做法。",
        }}
    return {}


async def ask_mode(workdir: Path) -> None:
    print("\n=== 1. 问答模式（dontAsk + 只读允许清单）===")
    options = ClaudeAgentOptions(
        cwd=str(workdir),
        env=claude_env_from_settings(),
        permission_mode="dontAsk",
        allowed_tools=["Read", "Grep", "Glob"],
        disallowed_tools=["AskUserQuestion"],
        system_prompt={"type": "preset", "preset": "claude_code", "append": ASK_APPEND},
        effort="low",
        include_partial_messages=True,
        max_buffer_size=10 * 1024 * 1024,
    )
    t = time.perf_counter()
    async with ClaudeSDKClient(options=options) as client:
        print(f"  冷启动连接 {time.perf_counter() - t:.1f}s")
        await run_turn(client, image_message("这张截图里的报错是什么原因？"), "带图提问")
        await run_turn(client, f"在当前目录创建 note.txt，内容写 hello。", "尝试写文件")
        print(f"  note.txt 是否被创建：{(workdir / 'note.txt').exists()}")
        await run_turn(client, "用一句话说说 Python 的 GIL 是什么。", "预热后第二问")


async def ask_mode_enforcement(workdir: Path) -> None:
    """不靠提示词：去掉"问答模式"说明，直接要求写文件，看 dontAsk 是否在技术上拒绝。"""
    print("\n=== 1b. 问答模式的技术拦截（无提示词约束）===")
    options = ClaudeAgentOptions(
        cwd=str(workdir),
        env=claude_env_from_settings(),
        permission_mode="dontAsk",
        allowed_tools=["Read", "Grep", "Glob"],
        disallowed_tools=["AskUserQuestion"],
        effort="low",
        max_buffer_size=10 * 1024 * 1024,
    )
    async with ClaudeSDKClient(options=options) as client:
        await run_turn(client, "用 Write 工具在当前目录创建 note.txt，内容写 hello；"
                               "如果 Write 不行就用 PowerShell 写。", "直接要求写文件")
    print(f"  note.txt 是否被创建：{(workdir / 'note.txt').exists()}")


async def act_mode(workdir: Path) -> None:
    print("\n=== 2. 操作模式（bypassPermissions 全放行 + PreToolUse 静默拦截）===")
    options = ClaudeAgentOptions(
        cwd=str(workdir),
        env=claude_env_from_settings(),
        permission_mode="bypassPermissions",
        disallowed_tools=["AskUserQuestion"],
        hooks={"PreToolUse": [HookMatcher(matcher="Bash|PowerShell", hooks=[blocklist_hook])]},
        system_prompt={"type": "preset", "preset": "claude_code", "append": ACT_APPEND},
        effort="low",
        include_partial_messages=True,
        max_buffer_size=10 * 1024 * 1024,
    )
    async with ClaudeSDKClient(options=options) as client:
        await run_turn(client, (
            "按顺序做三件事，每件都用命令行执行，不要合并：\n"
            "1. 执行 echo hello\n"
            f"2. 执行 echo {CANARY}\n"
            "3. 在当前目录创建 done.txt，内容写 ok\n"
            "最后简短汇报每一步的结果。"
        ), "全放行 + 拦截")
        print(f"  done.txt 是否被创建：{(workdir / 'done.txt').exists()}")


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="super_aide_p0_") as tmp:
        ask_dir, act_dir = Path(tmp, "ask"), Path(tmp, "act")
        ask_dir.mkdir()
        act_dir.mkdir()
        await ask_mode(ask_dir)
        await act_mode(act_dir)


if __name__ == "__main__":
    asyncio.run(main())
