"""Codex，经官方 openai-codex Python SDK（底层是 app-server，SDK 自带固定版本的 CLI）。

- 配置：沿用 ~/.codex/config.toml（服务商、插件），只用启动参数和会话参数覆盖。
- 问答：只读沙箱 + 不审批，并在进程级关闭 Computer Use / Browser Use
  （它们以 MCP 方式运行，不受沙箱约束，所以必须关掉）。
- 操作：完全访问 + 不审批（全放行）+ 原生 PreToolUse 钩子静默拦截。钩子通过启动参数注入，
  再用 hooks/list 拿到它的 key 和哈希，只信任这一个钩子（P0 验证）。
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, LocalImageInput, Sandbox, TextInput
from openai_codex.generated.v2_all import (
    AgentMessageDeltaNotification,
    AgentMessageThreadItem,
    CommandExecutionThreadItem,
    ErrorNotification,
    HooksListResponse,
    SkillsExtraRootsSetResponse,
    ItemCompletedNotification,
    ItemStartedNotification,
    McpToolCallThreadItem,
    MessagePhase,
    ReasoningThreadItem,
    TurnCompletedNotification,
)

from .. import paths
from ..i18n import tr
from . import computer, experience
from .base import Event, short

log = logging.getLogger(__name__)

ASK_OVERRIDES = ("features.computer_use=false", "features.browser_use=false")
#: 预热会话：只读说明、初始化运行环境，不列出也不读取任何应用窗口（不把你的窗口信息发出去）
PRIMER = ("接下来可能要操作这台电脑上的软件和浏览器。请现在按 Computer Use 和 Browser Use 插件的要求，"
          "读完它们的说明并完成运行环境的初始化。不要列出或读取任何应用和窗口，不要点击、输入、"
          "启动或关闭任何东西。完成后只回复“就绪”。")


def _hook_command(module: str = "super_aide.engines.codex_hook") -> str:
    """钩子命令。Codex 在 Windows 上经 PowerShell 运行它：开头带引号的路径会被当成字符串而不是命令，
    钩子因此"失败"并放行。所以路径不加引号；有空格时换成不含空格的 8.3 短路径。"""
    exe = sys.executable
    if " " in exe:
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(exe, buf, len(buf)):
            exe = buf.value
    return f"{exe} -m {module}"


def _hook_override() -> str:
    return "hooks.PreToolUse=[{hooks=[{type=\"command\", command='" + _hook_command() + "'}]}]"


def _recall_hook_override() -> str:
    """执行后钩子：命令输出里有报错时想起相似的经验。只挂在命令行上（每次调用都要起一个 Python 进程，
    界面工具调用很频繁，不挂）。"""
    return ("hooks.PostToolUse=[{matcher=\"Bash\", hooks=[{type=\"command\", command='"
            + _hook_command("super_aide.experience.codex_hook") + "'}]}]")


def _decline_all(method: str, _params: dict | None) -> dict:
    """问答模式的第二道保险：万一有审批请求发过来，一律拒绝。"""
    if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
        return {"decision": "decline"}
    return {}


async def _add_skills(client: AsyncCodex) -> None:
    """把我们的技能目录加给这个 Codex 进程（只在运行时生效，不改你的全局配置；P3 实测）。"""
    root = paths.PLUGIN / "skills"
    if not root.exists():
        return
    try:
        await client._client.request("skills/extraRoots/set", {"extraRoots": [str(root)]},
                                     response_model=SkillsExtraRootsSetResponse)
    except Exception as e:  # noqa: BLE001 - 没有这个接口的版本只是用不上我们的技能
        log.warning("Codex 技能目录设置失败：%s", e)


class CodexEngine:
    name = "codex"

    def __init__(self, instructions: str, blocklist: bool, gui: str = "ours",
                 blocked_apps: Callable[[], list[str]] = list) -> None:
        self.instructions = instructions
        self.blocklist = blocklist
        self.gui = gui  # official：用 Codex 自带的 Computer Use / Browser Use；ours：挂自研的工具服务器
        self.blocked_apps = blocked_apps
        self._clients: dict[str, AsyncCodex] = {}
        self._client_locks: dict[str, asyncio.Lock] = {}  # 预热、模型发现、提问可能同时要同一个客户端
        self._primed: dict[str, str] = {}  # 模型 → 已初始化好 Computer Use 的会话 id
        self._priming: dict[str, asyncio.Task] = {}

    async def _start(self, overrides: tuple[str, ...]) -> AsyncCodex:
        client = AsyncCodex(CodexConfig(cwd=str(paths.SESSIONS), config_overrides=overrides))
        await client.__aenter__()
        await _add_skills(client)
        return client

    async def _hook_overrides(self, mode: str) -> tuple[str, ...]:
        """注入的钩子要被信任才会运行：先带着钩子起一个探测用的 Codex，读出每个钩子的标识和哈希，
        再连同信任记录一起传进正式的 Codex。只在这次运行里生效，不改你的全局配置。"""
        hooks = (_recall_hook_override(),) + ((_hook_override(),) if mode == "act" and self.blocklist else ())
        probe = await self._start(hooks)
        try:
            resp = await probe._client.request("hooks/list", {"cwds": [str(paths.SESSIONS)]},
                                               response_model=HooksListResponse)
        finally:
            await probe.close()
        data = resp.model_dump(by_alias=True, exclude_none=True, mode="json")
        ours = [h for e in data.get("data", []) for h in e.get("hooks", []) if h.get("source") == "sessionFlags"]
        if len(ours) < len(hooks):
            log.warning("Codex 只识别到 %d / %d 个注入的钩子", len(ours), len(hooks))
        if not ours:
            return hooks
        trust = "hooks.state={" + ",".join(f"{json.dumps(h['key'])}={{trusted_hash={json.dumps(h['currentHash'])}}}"
                                           for h in ours) + "}"
        return hooks + (trust,)

    async def client(self, mode: str) -> AsyncCodex:
        async with self._client_locks.setdefault(mode, asyncio.Lock()):
            if mode not in self._clients:
                overrides = await self._hook_overrides(mode) + experience.CODEX_MEMORIES_OFF
                if mode == "ask":
                    overrides += ASK_OVERRIDES + computer.codex_overrides(self.blocked_apps(), "ask")
                elif mode == "duel":
                    overrides += ASK_OVERRIDES  # 后台对比：只读，不看实时界面、不在屏幕上圈位置
                elif self.gui != "official":
                    overrides += computer.codex_overrides(self.blocked_apps())
                overrides += experience.codex_overrides()  # 只读的 recall：查以前踩过的坑
                client = await self._start(overrides)
                if mode != "act" and hasattr(client._client, "_approval_handler"):
                    client._client._approval_handler = _decline_all
                self._clients[mode] = client
        return self._clients[mode]

    async def warm(self, mode: str = "ask") -> None:
        try:
            await self.client(mode)
        except Exception as e:  # noqa: BLE001
            log.warning("Codex 预热失败：%s", e)

    async def prime(self, model: str) -> None:
        """后台建一个会话，把 Computer Use / Browser Use 初始化好（P0：每个新会话要花约 1 分钟）。
        之后每次操作都从它分叉出来，省掉这段准备。"""
        if model in self._primed or model in self._priming or self.gui != "official":
            return  # 用自研工具时没有要初始化的插件
        self._priming[model] = asyncio.current_task()
        try:
            client = await self.client("act")
            thread = await client.thread_start(
                sandbox=Sandbox.full_access, approval_mode=ApprovalMode.deny_all, cwd=str(paths.SESSIONS),
                developer_instructions=self.instructions, model=model)
            result = await (await thread.turn(TextInput(PRIMER), effort="low")).run()
            if getattr(result.status, "value", result.status) == "completed":
                self._primed[model] = thread.id
                log.info("Codex 操作环境已预热（%s）", model)
        except Exception as e:  # noqa: BLE001 - 预热失败不影响使用，只是第一次操作会慢一些
            log.warning("Codex 操作环境预热失败：%s", e)
        finally:
            self._priming.pop(model, None)

    async def open(self, mode: str, model: str, effort: str) -> CodexSession:
        client = await self.client(mode)
        note = computer.ACT_NOTE if mode == "act" and self.gui != "official" else ""
        common = dict(sandbox=Sandbox.full_access if mode == "act" else Sandbox.read_only,
                      approval_mode=ApprovalMode.deny_all, cwd=str(paths.SESSIONS),
                      developer_instructions=self.instructions + note, model=model)
        primed = self._primed.get(model) if mode == "act" else None
        if primed:
            try:
                return CodexSession(await client.thread_fork(primed, **common), effort)
            except Exception as e:  # noqa: BLE001 - 分叉失败就新开一个
                log.warning("从预热会话分叉失败，改为新建：%s", e)
                self._primed.pop(model, None)
        return CodexSession(await client.thread_start(**common), effort)

    @staticmethod
    async def switch(session: CodexSession, mode: str, model: str, effort: str) -> CodexSession:
        """同一个对话换配置：Codex 每一轮都可以指定模型和思考强度，下一轮生效。"""
        session.model, session.effort = model, effort
        return session

    async def complete(self, prompt: str, model: str, schema: dict | None = None) -> str:
        """一次性的小活（总结经验）：只读、不审批、低思考强度，返回最终回答。没有 Claude 时才用它。"""
        client = await self.client("ask")
        thread = await client.thread_start(sandbox=Sandbox.read_only, approval_mode=ApprovalMode.deny_all,
                                           cwd=str(paths.SESSIONS), model=model)
        result = await thread.run(TextInput(prompt), effort="low", output_schema=schema)
        return result.final_response or ""

    async def close(self) -> None:
        # 先摘下来再关：关的这一会儿里预热、模型发现要客户端的，按新配置另起，拿不到正在关的旧进程
        clients, self._clients = list(self._clients.values()), {}
        for client in clients:
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass

    async def reload(self) -> None:
        """登录方式或服务地址改了：关掉按旧配置起的 Codex 进程，下次用时按新配置起。"""
        await self.close()
        self._primed.clear()


class CodexSession:
    engine = "codex"

    def __init__(self, thread, effort: str) -> None:
        self.thread = thread
        self.effort = effort
        self.model: str | None = None  # 中途换了模型时才有（下一轮起生效）
        self.handle = None
        self.session_id = thread.id

    async def send(self, text: str, images: list[Path]) -> AsyncIterator[Event]:
        inputs = [LocalImageInput(str(p)) for p in images] + [TextInput(text)]
        self.handle = await self.thread.turn(inputs, effort=self.effort, model=self.model)
        commentary: set[str] = set()
        async for ev in self.handle.stream():
            p = ev.payload
            if isinstance(p, ItemStartedNotification):
                item = getattr(p.item, "root", p.item)
                if isinstance(item, AgentMessageThreadItem):
                    if item.phase == MessagePhase.commentary:
                        commentary.add(item.id)
                    else:
                        yield Event("new_message")
                elif isinstance(item, ReasoningThreadItem):
                    yield Event("status", tr("正在思考…"), {"transient": True})  # 不算一步，不进步骤列表
                elif isinstance(item, CommandExecutionThreadItem):
                    script = item.command.split(" -Command ", 1)[-1].strip().strip("'\"")
                    yield Event("status", computer.command_status(script))
                elif isinstance(item, McpToolCallThreadItem):
                    if item.server == computer.SERVER_NAME:
                        label = computer.status(item.tool, item.arguments)
                    elif item.server == experience.SERVER_NAME:
                        label = experience.status()
                    elif item.server == "node_repl":
                        label = tr("正在操作界面…")
                    else:
                        label = tr("正在使用 {name}…", name=item.server)
                    yield Event("status", label, {"tool": f"mcp__{item.server}__{item.tool}"})
            elif isinstance(p, AgentMessageDeltaNotification):
                if p.item_id in commentary:
                    continue
                yield Event("delta", p.delta)
            elif isinstance(p, ItemCompletedNotification):
                item = getattr(p.item, "root", p.item)
                if isinstance(item, AgentMessageThreadItem) and item.phase == MessagePhase.commentary:
                    if item.id not in commentary:
                        yield Event("retract")
                    yield Event("status", short(item.text.strip().splitlines()[-1] if item.text.strip() else "", 60))
            elif isinstance(p, ErrorNotification) and not p.will_retry:
                yield Event("error", short(p.error.message or tr("Codex 出错"), 120))
            elif isinstance(p, TurnCompletedNotification):
                turn = p.turn
                status = getattr(turn.status, "value", str(turn.status))
                yield Event("done", data={
                    "ok": status == "completed", "engine": "codex", "session": self.thread.id,
                    "reason": status, "error": (turn.error.message if turn.error else "") or "",
                })

    async def interrupt(self) -> None:
        if self.handle is not None:
            await self.handle.interrupt()

    async def close(self) -> None:
        pass  # 会话保留在 Codex 的历史里，可以在 Codex 里接着看
