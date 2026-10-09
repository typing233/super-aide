"""自我改进用哪个工具、哪个模型，以及怎么跑一次会话（可以续上）。

- 默认 Claude Code + claude-opus-5-5 + max。只有 Claude Code 没装或没配好、或者服务不提供 Opus 5.5
  （发现的模型列表里没有，或者调用时报模型不存在）时，才按"档次 → 工具（Claude Code 优先）"挑最强的，
  思考强度取它支持的最高档（比如 Codex + gpt-6-astra + max）。
- 权限用工具自己的 auto 模式：Claude Code 的 permission_mode="auto"（不支持时退回 bypassPermissions），
  Codex 的 auto_review + workspace-write 沙箱。复核、审社区 PR 只读。
- 每次跑完都返回结果的类别：network（等网络再续）、auth（要登录）、model（模型不可用，换一个）、
  effort（这档强度不支持，降一档）、missing（会话记录不在了，重开）、permission_mode（不支持 auto）、other。
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..config import EFFORTS, ENGINES, Config
from ..router import catalog

log = logging.getLogger(__name__)

PREFERRED = ("claude", "claude-opus-5-5", "max")
ENGINE_ORDER = {"claude": 0, "codex": 1}
MAX_BUFFER = 16 * 1024 * 1024
UNAVAILABLE_S = 24 * 3600

AUTH = re.compile(r"\b(401|403)\b|unauthori[sz]ed|forbidden|authentication|invalid (api )?key|not logged in|login",
                  re.IGNORECASE)
MODEL_MISSING = re.compile(r"model.{0,40}(not.?found|does not exist|not (available|supported)|unknown|invalid)"
                           r"|(unknown|invalid|unsupported) model|not_found_error", re.IGNORECASE)
EFFORT_REJECTED = re.compile(r"effort|reasoning", re.IGNORECASE)
NETWORK = re.compile(r"\b(408|429|500|502|503|504|520|522|524|529)\b|overloaded|timed? ?out|timeout|connection|network"
                     r"|getaddrinfo|ssl|proxy|eof|reset by peer|temporarily|unavailable|rate.?limit", re.IGNORECASE)
MISSING = re.compile(r"no conversation found|session.{0,30}not found|could not (find|load) session", re.IGNORECASE)
PERMISSION_MODE = re.compile(r"permission.?mode|auto mode|--permission-mode", re.IGNORECASE)


@dataclass(frozen=True)
class Choice:
    engine: str
    model: str
    effort: str

    def lower(self) -> Choice | None:
        """思考强度降一档（服务不支持这一档时）。"""
        i = EFFORTS.index(self.effort) if self.effort in EFFORTS else 0
        return Choice(self.engine, self.model, EFFORTS[i - 1]) if i > 0 else None


@dataclass
class Outcome:
    ok: bool
    data: dict | None = None    # 按 JSON Schema 给的结论
    text: str = ""
    session: str = ""
    cost: float = 0.0
    kind: str = ""              # 见模块说明
    error: str = ""


def _key(engine: str, model: str) -> str:
    return f"{engine}|{model}"


def choose(ready: set[str], cfg: Config, found: dict[str, list[str]], meta: dict[str, dict[str, dict]],
           unavailable: dict[str, float]) -> Choice | None:
    """选工具和模型。ready：装好、配好了的引擎；found：发现模型时服务报来的清单（没发现过就是空）。"""
    now = time.time()

    def usable(engine: str, model: str) -> bool:
        return unavailable.get(_key(engine, model), 0) < now

    engine, model, effort = PREFERRED
    if engine in ready and usable(engine, model) and (not found.get(engine) or model in found[engine]):
        return Choice(*PREFERRED)
    ranked = []
    for engine in ("claude", "codex"):
        if engine not in ready:
            continue
        ids = list(found.get(engine) or [m.id for m in cfg.engine(engine).models])
        for order, model in enumerate(ids):
            if not usable(engine, model):
                continue
            info = meta.get(engine, {}).get(model, {})
            tier = catalog.tier_of(model, str(info.get("desc", "")))
            if engine == "claude":
                efforts = catalog.claude_efforts(model)
                version = catalog.claude_version(model)
                newer = -(version[1] if version else 0.0)
            else:
                efforts = tuple(e for e in info.get("efforts", EFFORTS) if e in EFFORTS) or EFFORTS
                desc = str(info.get("desc", "")).lower()
                newer = 1.0 if any(w in desc for w in ("older", "previous", "legacy")) or info.get("upgrade") else 0.0
            best = max(efforts, key=EFFORTS.index)
            ranked.append(((tier, ENGINE_ORDER[engine], newer, order), Choice(engine, model, best)))
    return min(ranked, key=lambda r: r[0])[1] if ranked else None


def ready_engines(router) -> set[str]:
    """配好了模型的引擎（自我改进不看设置里路由开了哪些模型）。DeepSeek Harness 这一版不支持。"""
    ready = router.ready if router.ready is not None else set(ENGINES)
    return {e for e in ready if e in ENGINE_ORDER}


def classify(text: str, status: int | None = None, api_error: bool = False) -> str:
    if MISSING.search(text):
        return "missing"
    if PERMISSION_MODE.search(text) and "auto" in text.lower():
        return "permission_mode"
    if status in (401, 403) or AUTH.search(text) and not NETWORK.search(text):
        return "auth"
    if status == 404 or MODEL_MISSING.search(text):
        return "model"
    if status == 400 and EFFORT_REJECTED.search(text):
        return "effort"
    if status == 400:
        return "other"
    if api_error or (status and status >= 408) or NETWORK.search(text):
        return "network"
    return "other"


def parse_json(text: str) -> dict | None:
    """从回答里取出 JSON 结论（结构化输出没生效时的兜底）。"""
    for candidate in (text, *re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S), *re.findall(r"\{.*\}", text, re.S)):
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


# ---------- Claude Code ----------

@dataclass
class ClaudeRun:
    choice: Choice
    cwd: Path
    system: str
    env: dict[str, str]
    add_dirs: list[Path] = field(default_factory=list)
    schema: dict | None = None
    read_only: bool = False
    permission: str = "auto"


async def run_claude(run: ClaudeRun, prompt: str, session: str, resume: bool,
                     on_step: Callable[[str, str], None]) -> Outcome:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, ResultMessage, ToolUseBlock

    from ..engines import claude as claude_engine

    common = dict(cwd=str(run.cwd), env=run.env, model=run.choice.model, effort=run.choice.effort,
                  add_dirs=[str(d) for d in run.add_dirs], max_buffer_size=MAX_BUFFER,
                  system_prompt={"type": "preset", "preset": "claude_code", "append": run.system},
                  output_format={"type": "json_schema", "schema": run.schema} if run.schema else None,
                  **({"resume": session} if resume else {"session_id": session}))
    if run.read_only:
        options = ClaudeAgentOptions(
            **common, permission_mode="default", allowed_tools=list(claude_engine.READ_ONLY_TOOLS),
            disallowed_tools=list(claude_engine.ASK_DISALLOWED), can_use_tool=claude_engine._readonly_gate,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[claude_engine._readonly_hook])]})
    else:
        options = ClaudeAgentOptions(**common, permission_mode=run.permission, disallowed_tools=["AskUserQuestion"])
    client = ClaudeSDKClient(options=options)
    text = ""
    try:
        await client.connect()
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage) and not msg.parent_tool_use_id:
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        on_step(claude_engine.tool_status(block.name, block.input), block.name)
                    elif getattr(block, "text", ""):
                        text = block.text
            elif isinstance(msg, ResultMessage):
                detail = " ".join(msg.errors or []) + " " + (msg.result or "")
                if msg.is_error or msg.terminal_reason == "api_error":
                    kind = classify(detail, msg.api_error_status, msg.terminal_reason == "api_error")
                    return Outcome(False, None, detail.strip(), msg.session_id, msg.total_cost_usd or 0.0, kind,
                                   detail.strip()[:500] or msg.subtype)
                data = msg.structured_output if isinstance(msg.structured_output, dict) else parse_json(
                    msg.result or text)
                return Outcome(data is not None, data, msg.result or text, msg.session_id, msg.total_cost_usd or 0.0,
                               "" if data is not None else "other", "" if data is not None else "没有给出结论")
        return Outcome(False, None, text, session, 0.0, "network", "会话中断了")
    except Exception as e:  # noqa: BLE001 - 分类后由调用方决定等网络、换模型还是记失败
        detail = f"{type(e).__name__}: {e} {getattr(e, 'stderr', '') or ''}"
        return Outcome(False, None, text, session, 0.0, classify(detail), detail[:500])
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


# ---------- Codex（兜底） ----------

async def run_codex(run: ClaudeRun, prompt: str, thread_id: str, on_step: Callable[[str, str], None]) -> Outcome:
    from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox, TextInput
    from openai_codex.generated.v2_all import (
        AgentMessageThreadItem, CommandExecutionThreadItem, ErrorNotification, FileChangeThreadItem,
        ItemCompletedNotification, ItemStartedNotification, MessagePhase, TurnCompletedNotification)

    from ..engines import computer, experience
    from ..i18n import tr

    client = AsyncCodex(CodexConfig(cwd=str(run.cwd), env=run.env, config_overrides=experience.CODEX_MEMORIES_OFF))
    text, error, session = "", "", thread_id
    try:
        await client.__aenter__()
        common = dict(approval_mode=ApprovalMode.deny_all if run.read_only else ApprovalMode.auto_review,
                      sandbox=Sandbox.read_only if run.read_only else Sandbox.workspace_write, cwd=str(run.cwd),
                      developer_instructions=run.system, model=run.choice.model)
        thread = await (client.thread_resume(thread_id, **common) if thread_id else client.thread_start(**common))
        session = thread.id
        handle = await thread.turn(TextInput(prompt), effort=run.choice.effort, output_schema=run.schema)
        async for ev in handle.stream():
            p = ev.payload
            if isinstance(p, ItemStartedNotification):
                item = getattr(p.item, "root", p.item)
                if isinstance(item, CommandExecutionThreadItem):
                    on_step(computer.command_status(item.command.split(" -Command ", 1)[-1].strip().strip("'\"")),
                            "Bash")
                elif isinstance(item, FileChangeThreadItem) and item.changes:
                    on_step(tr("正在修改 {name}", name=Path(item.changes[0].path).name), "Edit")
            elif isinstance(p, ItemCompletedNotification):
                item = getattr(p.item, "root", p.item)
                if isinstance(item, AgentMessageThreadItem) and item.phase != MessagePhase.commentary:
                    text = item.text or text
            elif isinstance(p, ErrorNotification) and not p.will_retry:
                error = p.error.message or "Codex 出错"
            elif isinstance(p, TurnCompletedNotification):
                status = getattr(p.turn.status, "value", str(p.turn.status))
                if status != "completed":
                    detail = error or (p.turn.error.message if p.turn.error else "") or status
                    return Outcome(False, None, text, session, 0.0, classify(detail), detail[:500])
        data = parse_json(text)
        return Outcome(data is not None, data, text, session, 0.0, "" if data is not None else "other",
                       "" if data is not None else "没有给出结论")
    except Exception as e:  # noqa: BLE001
        detail = f"{type(e).__name__}: {e}"
        return Outcome(False, None, text, session, 0.0, classify(detail), detail[:500])
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass
