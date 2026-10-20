"""Claude Code，经官方 Claude Agent SDK（SDK 自带 CLI）。

- 认证：沿用 ~/.claude/settings.json 里的服务地址和令牌，通过 env 传给 CLI。
- 问答：只读工具自动放行；命令行交给 can_use_tool，由 safety.is_read_only 判断，不弹窗。
- 操作：bypassPermissions 全放行 + PreToolUse 钩子静默拦截（P0 验证全放行下钩子仍生效）。
- 预热：提前连好一个会话，用掉一个就在后台再连一个（冷启动连接约 2.8s）。
- 后台对比（duel）：和问答一样只读，但不挂看界面、圈位置的工具（它在你看不见的地方跑，屏幕也已经变了）。
- 换配置：同一个对话里只换模型就地换（set_model）；换思考强度要带着会话 id 重连，对话历史还在。
"""

from __future__ import annotations

from collections.abc import Callable

import asyncio
import json
import logging
import os
import warnings
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

from .. import paths, safety
from ..i18n import tr
from . import computer, experience
from .base import Event, image_block

log = logging.getLogger(__name__)

# 只读工具放进 allowed_tools 后不再经过 can_use_tool，这正是想要的：它们直接放行，回调只管命令行
warnings.filterwarnings("ignore", message="can_use_tool will not be invoked")
# 用的是 SDK 自带的 CLI，版本一定对得上。SDK 每次连接前都会多起一个 `claude -v` 查版本（约 0.4 秒），
# 等它退出时还不设超时（2026-10-09 就卡死在这里，见 app._watch_child_exits）
os.environ.setdefault("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")

READ_ONLY_TOOLS = ["Read", "Grep", "Glob", "WebSearch", "WebFetch", "TodoWrite", "ToolSearch"]
ASK_DISALLOWED = ["Write", "Edit", "MultiEdit", "NotebookEdit", "Task", "Agent", "AskUserQuestion"]
ACT_DISALLOWED = ["AskUserQuestion"]
MAX_BUFFER = 16 * 1024 * 1024  # 默认 1MB 装不下截图
DELEGATE_TOOL = "mcp__aide__operate_ui"
ACT_COMPUTER_NOTE = computer.ACT_NOTE
ACT_DELEGATE_NOTE = (
    "\n\n【操作界面】你自己不能点击或输入。需要操作图形界面或浏览器时（点按钮、填写或提交表单、"
    "在网页或某个软件里执行操作、在浏览器里的 Notebook 中运行代码等），调用 operate_ui 工具，"
    "把要做的事、在哪个窗口或网页、做到什么程度算完成写清楚，交给能操作界面的助手去做，它会把结果告诉你。"
    "命令行和文件能解决的事自己直接做。")


class SessionSlot:
    """会话的入口：转交（fn）、想起经验（remember、lookup）。工具和钩子要在会话建立时注册，
    而会话是提前预热好的；具体属于哪个对话，等会话被某个对话领走时再由中枢填进来。"""

    def __init__(self) -> None:
        self.fn = None
        self.remember: Callable[[str], str] | None = None  # 工具结果里的报错行 → 要补给模型的经验（没有就空）
        self.lookup: Callable[[str], str] | None = None  # 模型主动问 → 相似的经验

    async def __call__(self, task: str) -> str:
        if self.fn is None:
            return "现在没法转交，请把需要在界面上做的步骤告诉用户。"
        return await self.fn(task)


def _delegate_server(slot: SessionSlot):
    @tool("operate_ui", "把需要操作图形界面或浏览器的事交给能操作界面的助手完成（它能像人一样点击、输入、"
                        "操作网页和各种软件），返回它的执行结果。", {"task": str})
    async def operate_ui(args: dict) -> dict:
        result = await slot(str(args.get("task", "")))
        return {"content": [{"type": "text", "text": result}]}

    return create_sdk_mcp_server(name="aide", tools=[operate_ui])


MEMORY_TOOL = "mcp__memory__recall"
#: 读文件、搜索这类工具的结果是内容本身，里面的 "error" 不是这次碰到的报错，不拿去想经验
NO_RECALL_TOOLS = {"Read", "Grep", "Glob", "TodoWrite", "Skill", "ToolSearch", "WebSearch", MEMORY_TOOL}


def _memory_server(slot: SessionSlot):
    @tool("recall", "查以前在相似问题上踩过的坑和总结的经验。碰到报错、卡住、准备绕路或者做没把握的操作之前用。"
                    "query 写现在的情况：报错原文、在做什么、用的什么软件或网站。", {"query": str})
    async def recall_tool(args: dict) -> dict:
        query = str(args.get("query", ""))
        text = slot.lookup(query) if slot.lookup is not None else experience.lookup(query)
        return {"content": [{"type": "text", "text": text or "没有相似的经验。"}]}

    return create_sdk_mcp_server(name="memory", tools=[recall_tool])


def _recall_hooks(slot: SessionSlot) -> dict:
    """工具结果里出现报错时，想起以前在相似报错上踩过的坑，附在这次工具结果后面交给模型。对不上就什么也不加。"""

    async def after(input_data: dict, _tool_use_id, _ctx) -> dict:
        event = input_data.get("hook_event_name") or "PostToolUse"
        if slot.remember is None or input_data.get("tool_name") in NO_RECALL_TOOLS:
            return {}
        raw = input_data.get("error") if event == "PostToolUseFailure" else input_data.get("tool_response")
        lines = experience.error_lines(experience.text_of(raw))
        # 想起经验可能要问一次判断模型（联网，最多一两秒）：放到线程里，不卡住其它对话
        note = await asyncio.get_running_loop().run_in_executor(None, slot.remember, lines) if lines else ""
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": note}} if note else {}

    return {"PostToolUse": [HookMatcher(matcher=None, hooks=[after])],
            "PostToolUseFailure": [HookMatcher(matcher=None, hooks=[after])]}


def claude_env() -> dict[str, str]:
    settings = Path.home() / ".claude" / "settings.json"
    try:
        env = json.loads(settings.read_text(encoding="utf-8")).get("env", {})
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: str(v) for k, v in env.items() if k.startswith("ANTHROPIC_")}


def list_models(timeout: float = 15) -> list[str]:
    """服务地址 /v1/models 返回的完整模型名（P0：你的服务地址返回 32 个）。阻塞调用，放在后台跑。"""
    import urllib.request

    env = claude_env()
    base = env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    token = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY", "")
    req = urllib.request.Request(f"{base}/v1/models", headers={
        "Authorization": f"Bearer {token}", "x-api-key": token, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [m["id"] for m in data.get("data", []) if m.get("id", "").startswith("claude-")]


def complete(prompt: str, model: str, max_tokens: int = 1500, timeout: float = 120) -> str:
    """直接调一次 Messages 接口，返回文字。总结经验这类后台小活用，不用起一个 Claude Code 进程。阻塞调用，放在后台跑。"""
    import time
    import urllib.error
    import urllib.request

    env = claude_env()
    base = env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    token = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY", "")
    if not token:
        raise RuntimeError("没有 Claude 的服务令牌")
    body = json.dumps({"model": model, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
    req = urllib.request.Request(f"{base}/v1/messages", data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "x-api-key": token, "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    for attempt in range(3):  # 网络偶尔断一下（实测 SSL EOF）：歇一会儿再试
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429 or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
        time.sleep(2 * (attempt + 1))
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def tool_status(name: str, inp: dict) -> str:
    if name == "Read":
        return tr("正在读 {name}", name=Path(str(inp.get("file_path", ""))).name)
    if name in ("Grep", "Glob"):
        return tr("正在查找文件…")
    if name in ("Bash", "PowerShell"):
        return computer.command_status(str(inp.get("command", "")))
    if name == "WebSearch":
        return computer.search_status(str(inp.get("query", "")))
    if name == "WebFetch":
        return tr("正在打开网页…")
    if name in ("Write", "Edit", "MultiEdit"):
        return tr("正在修改 {name}", name=Path(str(inp.get("file_path", ""))).name)
    if name == DELEGATE_TOOL:
        return tr("交给 Codex 操作界面…")
    if name.startswith(f"mcp__{computer.SERVER_NAME}__"):
        return computer.status(name, inp)
    if name == MEMORY_TOOL:
        return experience.status()
    return tr("正在使用 {name}…", name=name)


READ_ONLY_DENIED = ("问答模式只能读取信息、运行只读命令。需要修改的话，把步骤告诉用户，"
                    "并提示他在追问框按 Tab 切到操作模式让你来做。")


#: 会话要求按 JSON Schema 交结论（output_format）时，CLI 让模型调这个工具交出来：只是交结论，不改任何东西。
#: 只读会话（自我改进的初筛、复核，审社区 PR）原来被下面的钩子挡掉它，结论交不上，只能指望模型再把 JSON 写进正文
#: （2026-10-10 实测：复核两次交"不通过"都被挡，最后一句话里没有 JSON，白花一轮重新复核）
OUTPUT_TOOL = "StructuredOutput"


def _read_only_allows(tool_name: str, tool_input: dict) -> bool:
    if tool_name in READ_ONLY_TOOLS or tool_name in ("Skill", OUTPUT_TOOL):  # 加载技能只是读它的说明
        return True
    if tool_name in computer.ASK_TOOLS or tool_name == MEMORY_TOOL:  # 看窗口、圈位置、回想经验：不改动任何东西
        return True
    return tool_name in ("Bash", "PowerShell") and safety.is_read_only(str(tool_input.get("command", "")))


async def _readonly_gate(tool_name: str, tool_input: dict, _ctx) -> PermissionResultAllow | PermissionResultDeny:
    return PermissionResultAllow() if _read_only_allows(tool_name, tool_input) else PermissionResultDeny(
        message=READ_ONLY_DENIED)


async def _readonly_hook(input_data: dict, _tool_use_id, _ctx) -> dict:
    """问答模式的硬保证。技能的 allowed-tools 和设置里的放行规则会跳过上面的权限回调，但跳不过钩子。"""
    if _read_only_allows(input_data.get("tool_name", ""), input_data.get("tool_input") or {}):
        return {}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": READ_ONLY_DENIED}}


async def _blocklist_hook(input_data: dict, _tool_use_id, _ctx) -> dict:
    reason = safety.blocked_reason(json.dumps(input_data.get("tool_input", {}), ensure_ascii=False))
    if not reason:
        return {}
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (f"这个操作在静默拦截清单里（{reason}）。不要执行，也不要换个写法绕过；"
                                     "告诉用户这一步需要他自己来做。"),
    }}


class ClaudeEngine:
    name = "claude"

    def __init__(self, instructions: str, blocklist: bool, gui: str = "ours",
                 blocked_apps: Callable[[], list[str]] = list) -> None:
        self.env = self._env()
        self.instructions = instructions
        self.blocklist = blocklist
        self.gui = gui  # official：动界面转交 Codex 官方的；ours：自己用自研的 computer 工具
        self.blocked_apps = blocked_apps
        self._warm: dict[tuple[str, str, str], tuple[ClaudeSDKClient, SessionSlot]] = {}
        self._warming: set[tuple[str, str, str]] = set()

    def _options(self, mode: str, model: str, effort: str, slot: SessionSlot) -> ClaudeAgentOptions:
        # 技能：我们的技能包当本地插件加载；skills="all" 同时打开你自己装的技能。
        # 问答模式下技能自带的工具放行不起作用：只读由钩子兜底（_readonly_hook）
        plugins = [{"type": "local", "path": str(paths.PLUGIN)}] if (paths.PLUGIN / "skills").exists() else []
        common = dict(cwd=str(paths.SESSIONS), env=self.env, model=model, effort=effort,
                      include_partial_messages=True, max_buffer_size=MAX_BUFFER, plugins=plugins, skills="all")
        memory = {"memory": _memory_server(slot)}
        if mode in ("ask", "duel"):
            screen = mode == "ask"  # 后台对比不看实时界面、不在屏幕上圈位置
            servers = ({computer.SERVER_NAME: computer.claude_server(self.blocked_apps(), "ask")} if screen else {}) | memory
            return ClaudeAgentOptions(
                **common, permission_mode="default",
                allowed_tools=READ_ONLY_TOOLS + (list(computer.ASK_TOOLS) if screen else []) + [MEMORY_TOOL],
                mcp_servers=servers,
                disallowed_tools=ASK_DISALLOWED, can_use_tool=_readonly_gate,
                hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[_readonly_hook])]} | _recall_hooks(slot),
                system_prompt={"type": "preset", "preset": "claude_code", "append": self.instructions})
        hooks = _recall_hooks(slot)
        if self.blocklist:
            hooks["PreToolUse"] = [HookMatcher(matcher=None, hooks=[_blocklist_hook])]
        if self.gui == "official":
            servers, note = {"aide": _delegate_server(slot)} | memory, ACT_DELEGATE_NOTE
        else:
            servers, note = {computer.SERVER_NAME: computer.claude_server(self.blocked_apps())} | memory, ACT_COMPUTER_NOTE
        return ClaudeAgentOptions(
            **common, permission_mode="bypassPermissions", disallowed_tools=ACT_DISALLOWED, hooks=hooks,
            mcp_servers=servers,
            system_prompt={"type": "preset", "preset": "claude_code", "append": self.instructions + note})

    @staticmethod
    def _env() -> dict[str, str]:
        # 操作界面可能要几分钟，调长 MCP 工具超时，免得中途被判超时
        # 关掉 Claude Code 自带的自动记忆：它每次都把 MEMORY.md 整个塞进上下文，越积越多；经验由我们按需想起
        return {**claude_env(), "MCP_TOOL_TIMEOUT": "1800000", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}

    async def reload(self) -> None:
        """登录方式或服务地址改了：重新读 settings.json，按旧配置预热的连接不要了。"""
        self.env = self._env()
        await self.prune(set())

    async def _connect(self, mode: str, model: str, effort: str) -> tuple[ClaudeSDKClient, SessionSlot]:
        slot = SessionSlot()
        client = ClaudeSDKClient(options=self._options(mode, model, effort, slot))
        await client.connect()
        return client, slot

    async def warm(self, mode: str, model: str, effort: str) -> None:
        key = (mode, model, effort)
        if key in self._warm or key in self._warming:
            return
        self._warming.add(key)
        try:
            self._warm[key] = await self._connect(mode, model, effort)
        except Exception as e:  # noqa: BLE001 - 预热失败不影响正式提问，那时会再连一次
            log.warning("Claude 预热失败：%s", e)
        finally:
            self._warming.discard(key)

    async def open(self, mode: str, model: str, effort: str, rewarm: bool = True) -> ClaudeSession:
        key = (mode, model, effort)
        client, slot = self._warm.pop(key, None) or await self._connect(mode, model, effort)
        if rewarm:
            asyncio.get_running_loop().create_task(self.warm(mode, model, effort))
        return ClaudeSession(client, slot, model, effort)

    async def switch(self, session: ClaudeSession, mode: str, model: str, effort: str) -> ClaudeSession:
        """同一个对话换配置（上一轮没办成时加强）。只换模型：就地换；换思考强度：带着会话 id 重连，
        对话历史还在，转交、想起经验的入口（slot）也照旧。"""
        if effort == session.effort:
            await session.client.set_model(model)
            session.model = model
            return session
        if not session.session_id:
            raise RuntimeError("这个会话还没有 id，没法续上")
        options = replace(self._options(mode, model, effort, session.slot), resume=session.session_id)
        client = ClaudeSDKClient(options=options)
        await client.connect()
        await session.close()
        switched = ClaudeSession(client, session.slot, model, effort)
        switched.session_id = session.session_id
        return switched

    async def prune(self, models: set[str]) -> None:
        """关掉已停用模型的预热连接（每个连接是一个常驻的 CLI 进程）。"""
        for key in [k for k in self._warm if k[1] not in models]:
            client, _slot = self._warm.pop(key)
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass

    async def close(self) -> None:
        await self.prune(set())


class ClaudeSession:
    engine = "claude"

    def __init__(self, client: ClaudeSDKClient, slot: SessionSlot, model: str = "", effort: str = "") -> None:
        self.client = client
        self.slot = slot  # 操作模式下由中枢填入转交函数
        self.model, self.effort = model, effort
        self.session_id = ""

    async def send(self, text: str, images: list[Path]) -> AsyncIterator[Event]:
        content = [image_block(p) for p in images] + [{"type": "text", "text": text}]

        async def message():
            yield {"type": "user", "message": {"role": "user", "content": content},
                   "parent_tool_use_id": None, "session_id": "default"}

        await self.client.query(message())
        async for msg in self.client.receive_response():
            if isinstance(msg, StreamEvent):
                if msg.parent_tool_use_id:  # 子代理内部的流，不展示
                    continue
                ev = msg.event
                kind = ev.get("type")
                block = ev.get("content_block", {}).get("type") if kind == "content_block_start" else ""
                if kind == "message_start":
                    yield Event("new_message")
                elif block in ("thinking", "redacted_thinking"):
                    # 思考强度高时要想一阵才开口：告诉你它在想（不算一步，不进步骤列表）
                    yield Event("status", tr("正在思考…"), {"transient": True})
                elif block == "tool_use":
                    yield Event("retract")  # 工具调用之前那段话是过程说明
                elif kind == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                    yield Event("delta", ev["delta"].get("text", ""))
            elif isinstance(msg, AssistantMessage) and not msg.parent_tool_use_id:
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        yield Event("status", tool_status(block.name, block.input), {"tool": block.name})
            elif isinstance(msg, ResultMessage):
                self.session_id = msg.session_id
                yield Event("done", data={
                    "ok": not msg.is_error, "engine": "claude", "session": msg.session_id,
                    "cost": msg.total_cost_usd, "reason": msg.terminal_reason or msg.subtype,
                    "error": "; ".join(msg.errors or []) if msg.is_error else "",
                    "api_error_status": msg.api_error_status,  # 接口故障（限流、过载、认证）时的状态码：不算能力失败
                })

    async def interrupt(self) -> None:
        await self.client.interrupt()

    async def close(self) -> None:
        try:
            await self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass
