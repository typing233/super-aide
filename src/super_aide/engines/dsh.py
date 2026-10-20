"""DeepSeek Harness（DSH），经它的 ACP 模式（Agent Client Protocol：stdio 上一行一个 JSON-RPC 2.0 消息）。

可选的替代引擎：没装 Claude Code / Codex、你选了先用它时才参与路由。
- 进程：一个常驻进程管多个会话（起一次约 5 秒）。问答一个（只读沙箱、不审批），操作一个（完全访问、不审批）：
  DSH 的权限在会话建立时就定死了，不能一轮一换。后台对比、后台小活也走问答那个。
- 预热：建一个会话要十几秒（实测，主要是挂工具服务器），所以提前建好一个，用掉一个就在后台再建一个。
- 配置：用一份 --patch 覆盖（~/.super_aide/dsh/*.yml，每次启动重写）：用哪个服务、权限、我们的共享指令和技能；
  关掉 DSH 默认的"上传会话日志"和插件清单上报（会话里有你屏幕上的内容）。不改 ~/.dsh 里你自己的设置。
- 用哪个服务：照 DSH 自己的模型设置（setup/dshconf.py）。默认用的是自定义的服务（中转、自己部署的）时，
  把它的路由定义一起带上；否则登录了 DeepSeek 账号用账号，没有就用 API Key。
- 模型、思考强度：每轮用 session/set_config_option 设（和当前一样就不发）。DSH 的思考强度只有 low / high / max。
- 工具：每个会话挂上和另外两个引擎一样的 MCP 工具服务器（自研的看界面、动界面，想起经验）。
- 文字：DSH 一步做完才把这一步的文字整段发过来（不是逐字）；工具调用之前的那段是过程说明，撤掉。
- 账号：DeepSeek 账号（在 DSH 里登录，凭据在 ~/.dsh，和 DSH 共用）、环境变量 DEEPSEEK_API_KEY，
  或者自定义服务的密钥（DSH 按 apiKeyEnv 的名字从 ~/.dsh 里取）。
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import logging
import os
import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from .. import __version__, paths
from ..config import EFFORTS as LEVELS
from ..i18n import tr
from ..setup import detect, dshconf
from . import computer, experience
from .base import Event, short

log = logging.getLogger(__name__)

#: DSH 自带的 DeepSeek 模型（会话建立时它会报来实际能用的清单，以那个为准）
MODELS = ({"id": "deepseek-flash", "desc": "DeepSeek-V41-Flash，能看图"},
          {"id": "deepseek-v4-pro", "desc": "DeepSeek-V4-Pro，只认文字"})
IMAGE_MODELS = {"deepseek-flash"}
EFFORTS = ("low", "high", "max")  # DSH 的 off / low / high / max 里，路由用得上的
MAX_LINE = 64 * 1024 * 1024
START_TIMEOUT = 90
ELECTRON_NOTE = ("\n\n【命令行启动程序】这个环境里 ELECTRON_RUN_AS_NODE=1：用命令行启动桌面程序之前先执行 "
                 "`Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue`，"
                 "否则 VS Code 这类程序会打不开。")


class AcpError(Exception):
    pass


def launch_command(where: str) -> tuple[list[str], dict[str, str]]:
    """怎么启动 dsh。桌面版的命令（不管加没加进 PATH）在 …\\resources\\runtime\\cli\\bin\\dsh.cmd：
    直接用它自带的运行时（DeepSeek Harness.exe 当 Node 用），不经过 .cmd（停不干净、参数转义也不可靠）；
    npm 装的：用 Node 跑包里的 lib/bin.js。"""
    shim = Path(where)
    resources = shim.parent.parent.parent.parent
    exe = resources.parent / "DeepSeek Harness.exe"
    if exe.exists() and (resources / "app.asar").exists():
        cli = resources / "app.asar" / "dsh" / "node_modules" / "@deepseek-ai" / "dsh-desktop-host" / "lib" / "cli.js"
        return [str(exe), "--expose-internals", str(cli)], {"ELECTRON_RUN_AS_NODE": "1"}
    bin_js = shim.parent / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    if bin_js.exists():
        node = shim.parent / "node.exe"
        return [str(node) if node.exists() else (shutil.which("node") or "node"), str(bin_js)], {}
    return [str(shim)], {}


def route(places: detect.Places | None = None) -> dshconf.Route:
    """用哪个服务：DSH 自己的模型设置里默认用的是自定义的服务就用它；否则登录了 DeepSeek 账号就用账号，
    没有再用 API Key（DEEPSEEK_API_KEY）。"""
    places = places or detect.Places.current()
    found = dshconf.read(detect.dsh_dir(places))
    if found.custom:
        return found
    _ok, auth, _detail = detect.dsh_auth(places)
    return dshconf.Route(provider="deepseek-official" if auth == "apikey" else "deepseek-account")


def provider(places: detect.Places | None = None) -> str:
    return route(places).provider


def _q(value) -> str:
    """YAML 的值：JSON 的写法也是合法的 YAML（双引号字符串、列表）。"""
    return json.dumps(value, ensure_ascii=False)


def patch_text(mode: str, provider_id: str | dshconf.Route, instructions: str, skills: Path | None = None) -> str:
    """给 dsh 的 --patch：问答只读、操作完全访问，都不审批；带上我们的指令和技能，关掉上传。
    用的是自定义的服务时，带上它在 DSH 模型设置里的路由定义（acp 这套配置里没有）。"""
    chosen = provider_id if isinstance(provider_id, dshconf.Route) else dshconf.Route(provider=provider_id)
    sandbox = "danger-full-access" if mode == "act" else "read-only"
    # {{名字}} 是 DSH 提示词模板的变量，认不出的会让每次请求都失败：指令里的花括号拆开
    text = instructions.replace("{{", "{ {").replace("}}", "} }")
    lines = [
        "# Super Aide 生成，每次启动重写。" + ("操作：完全访问、不审批。" if mode == "act" else "问答：只读、不审批。"),
        "- id: acp", "  config:", f"    provider: {_q(chosen.provider)}", f"    model: {_q(chosen.model or MODELS[0]['id'])}",
        "- id: sandbox-policy", "  config:", f"    mode: {_q(sandbox)}", f"    workspaceRoot: {_q(str(paths.SESSIONS))}",
        "- id: approval", "  config:", '    policy: "never"',
        "- id: permission", "  config:", "    presets:",
        '      read-only: {sandbox: "read-only", approval: "never"}',
        '      workspace-write: {sandbox: "workspace-write", approval: "ask"}',
        '      danger-full-access: {sandbox: "danger-full-access", approval: "never"}',
        f"    defaultPreset: {_q(sandbox)}",
        "- id: system-prompt", "  config:",
        # 模板变量只用 DSH 自己提供的（provider、model）。工作目录不写：DSH 新版每次都自己带上，也不再注册 {{cwd}}，
        # 原来照它旧的默认在开头写的 "Your working directory is {{cwd}}." 让每次请求都失败（2026-10-19）
        f"    personaPrefix: {_q('You are Super Aide, a Windows desktop assistant powered by the {{model}} model.')}",
        f"    personaSuffix: {_q(text)}",
        "- id: session-log-deepseek", "  config:", "    enabled: false",
        "- id: plugin-package-inventory-deepseek", "  config:", "    enabled: false",
    ]
    if skills is not None and skills.exists():
        lines += ["- id: skill-filesystem", "  config:", f"    customSkillDirs: {_q([str(skills)])}"]
    if chosen.custom and chosen.block:
        lines += chosen.block.rstrip("\n").splitlines()
    return "\n".join(lines) + "\n"


def _stdio_server(name: str, args: list[str], env: dict[str, str]) -> dict:
    return {"name": name, "command": computer._python(), "args": args,
            "env": [{"name": k, "value": v} for k, v in env.items()]}


def mcp_servers(mode: str, blocked_apps: list[str]) -> list[dict]:
    """和另外两个引擎一样的工具：问答只看、只指；后台对比不看实时界面；操作能动界面。都能想起经验。"""
    memory_env = {"PYTHONIOENCODING": "utf-8"} | (
        {"AIDE_LESSONS": os.environ["AIDE_LESSONS"]} if os.environ.get("AIDE_LESSONS") else {})
    servers = [_stdio_server(experience.SERVER_NAME, ["-X", "utf8", "-m", "super_aide.experience.server"], memory_env)]
    if mode != "duel":
        servers.insert(0, _stdio_server(computer.SERVER_NAME, ["-X", "utf8", "-m", "super_aide.cu.server"],
                                        computer.server_env(blocked_apps, "act" if mode == "act" else "ask")))
    return servers


def _values(node) -> list[dict]:
    """configOptions 里一个选项的所有可选值（可能按服务商分组，嵌套一层）。"""
    out = []
    for item in node or []:
        if isinstance(item, dict) and "value" in item:
            out.append(item)
        elif isinstance(item, dict):
            out += _values(item.get("options"))
    return out


def read_options(options: list[dict] | None, provider_id: str) -> tuple[dict[str, str], list[str]]:
    """→ ({模型: 设置时要传的值}, 当前模型支持的思考强度)。模型的值是 JSON 写的 [服务商, 模型]。"""
    models: dict[str, str] = {}
    efforts: list[str] = []
    for option in options or []:
        if not isinstance(option, dict):
            continue
        if option.get("id") == "model":
            for item in _values(option.get("options")):
                try:
                    owner, model = json.loads(item["value"])
                except (TypeError, ValueError):
                    continue
                if owner == provider_id:
                    models[str(model)] = str(item["value"])
        elif option.get("id") == "reasoning_effort":
            efforts = [str(item["value"]) for item in _values(option.get("options"))]
    return models, efforts


def tool_status(name: str, inp: dict) -> str:
    inp = inp if isinstance(inp, dict) else {}
    if name.startswith(f"mcp__{computer.SERVER_NAME}__"):
        return computer.status(name, inp)
    if name.startswith(f"mcp__{experience.SERVER_NAME}__"):
        return experience.status()
    if name in ("pwsh", "bash", "shell"):
        return computer.command_status(str(inp.get("command", "")))
    if name in ("read", "read_image"):
        return tr("正在读 {name}", name=Path(str(inp.get("file_path") or inp.get("path") or "")).name)
    if name in ("write", "edit", "str_replace_editor"):
        return tr("正在修改 {name}", name=Path(str(inp.get("file_path") or inp.get("path") or "")).name)
    if name in ("grep", "glob", "search", "fs_search", "ls"):
        return tr("正在查找文件…")
    if name == "web_search":
        return computer.search_status(str(inp.get("query", "")))
    if name in ("web_fetch", "fetch"):
        return tr("正在打开网页…")
    return tr("正在使用 {name}…", name=name)


class AcpProcess:
    """一个 `dsh --profile acp` 进程：发请求、收回复，把会话的更新分给各个会话。"""

    def __init__(self, mode: str, command: list[str], env: dict[str, str], patch: Path, provider_id: str) -> None:
        self.mode, self.command, self.env, self.patch = mode, command, env, patch
        self.provider = provider_id
        self.proc: asyncio.subprocess.Process | None = None
        self.image = False
        self.sessions: dict[str, asyncio.Queue] = {}
        self._pending: dict[int, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._write = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []
        self._stderr: list[str] = []

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self) -> None:
        env = {**os.environ, **self.env, "DSH_TELEMETRY_DISABLED": "1"}
        env.pop("CLAUDECODE", None)
        self.proc = await asyncio.create_subprocess_exec(
            *self.command, "--profile", "acp", "--patch", str(self.patch),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(paths.SESSIONS), env=env, limit=MAX_LINE)
        self._tasks = [asyncio.create_task(self._read()), asyncio.create_task(self._drain())]
        try:
            init = await asyncio.wait_for(self.request("initialize", {
                "protocolVersion": 1, "clientInfo": {"name": "super-aide", "version": __version__},
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}),
                START_TIMEOUT)
        except BaseException:  # 包括被取消：别留下一个没人管的进程
            await self.close()
            raise
        caps = (init or {}).get("agentCapabilities") or {}
        self.image = bool((caps.get("promptCapabilities") or {}).get("image"))

    async def _send(self, message: dict) -> None:
        if not self.alive:
            raise AcpError(self._why())
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        async with self._write:
            self.proc.stdin.write(data)
            await self.proc.stdin.drain()

    async def request(self, method: str, params: dict) -> dict:
        rid = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._pending[rid] = future
        try:
            await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            return await future
        finally:
            self._pending.pop(rid, None)

    async def notify(self, method: str, params: dict) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _read(self) -> None:
        try:
            while line := await self.proc.stdout.readline():
                try:
                    message = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    continue  # 不是协议帧（插件打印的东西）：跳过
                if not isinstance(message, dict):
                    continue
                if "method" not in message:
                    self._resolve(message)
                elif "id" in message:
                    await self._answer(message)
                elif message["method"] == "session/update":
                    params = message.get("params") or {}
                    queue = self.sessions.get(params.get("sessionId", ""))
                    if queue is not None:
                        queue.put_nowait(params.get("update") or {})
        except Exception as e:  # noqa: BLE001
            log.warning("DSH 输出读取出错：%s", e)
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(AcpError(self._why()))
            for queue in self.sessions.values():
                queue.put_nowait(None)  # 进程没了：正在等更新的会话别干等

    def _resolve(self, message: dict) -> None:
        future = self._pending.get(message.get("id"))
        if future is None or future.done():
            return
        if "error" in message:
            error = message["error"] or {}
            future.set_exception(AcpError(str(error.get("message") or error)))
        else:
            future.set_result(message.get("result") or {})

    async def _answer(self, message: dict) -> None:
        """DSH 反过来问我们的：权限请求按模式答（问答拒绝、操作允许）；别的说不支持。"""
        if message["method"] == "session/request_permission":
            kind = "allow_once" if self.mode == "act" else "reject_once"
            options = (message.get("params") or {}).get("options") or []
            chosen = next((o.get("optionId") for o in options if o.get("kind") == kind), None)
            outcome = {"outcome": "selected", "optionId": chosen} if chosen else {"outcome": "cancelled"}
            await self._send({"jsonrpc": "2.0", "id": message["id"], "result": {"outcome": outcome}})
        else:
            await self._send({"jsonrpc": "2.0", "id": message["id"],
                              "error": {"code": -32601, "message": "Method not found"}})

    async def _drain(self) -> None:
        """一直读 stderr（不读的话管道满了 DSH 会卡住），留最后几行，出错时说明原因。"""
        while line := await self.proc.stderr.readline():
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                self._stderr = (self._stderr + [text])[-20:]
                log.debug("dsh: %s", text)

    def _why(self) -> str:
        tail = next((line for line in reversed(self._stderr) if "dsh:" in line or "rror" in line), "")
        return tr("DeepSeek Harness 退出了：{detail}", detail=short(tail, 160)) if tail else tr("DeepSeek Harness 退出了")

    async def close(self) -> None:
        if self.proc is None:
            return
        if self.proc.returncode is None:
            try:
                self.proc.stdin.close()  # 关掉输入，DSH 自己收尾退出
                await asyncio.wait_for(self.proc.wait(), 4)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except ProcessLookupError:
                    pass
        for task in self._tasks:
            task.cancel()


class DshEngine:
    name = "dsh"

    def __init__(self, instructions: str, blocked_apps: Callable[[], list[str]] = list) -> None:
        self.instructions = instructions
        self.blocked_apps = blocked_apps
        self._procs: dict[str, AcpProcess] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._catalog: dict[str, dict] = {m["id"]: dict(m) for m in MODELS}
        self._ready: dict[str, DshSession] = {}  # 模式 → 提前建好的会话
        self._warming: dict[str, asyncio.Task] = {}  # 模式 → 正在提前建的

    async def process(self, mode: str) -> AcpProcess:
        key = "act" if mode == "act" else "ask"  # 后台对比、后台小活也只读
        async with self._locks.setdefault(key, asyncio.Lock()):
            proc = self._procs.get(key)
            if proc is None or not proc.alive:
                proc = await self._start(key)
                self._procs[key] = proc
            return proc

    async def _start(self, mode: str) -> AcpProcess:
        tool = detect.scan().dsh
        if not tool.installed:
            raise AcpError(tr("没找到 DeepSeek Harness"))
        command, env = launch_command(tool.where)
        note = ""
        if mode == "act":
            note = computer.ACT_NOTE + (ELECTRON_NOTE if env.get("ELECTRON_RUN_AS_NODE") else "")
        chosen = route()
        patch = paths.DSH / f"{mode}.yml"
        patch.parent.mkdir(parents=True, exist_ok=True)
        patch.write_text(patch_text(mode, chosen, self.instructions + note, paths.PLUGIN / "skills"),
                         encoding="utf-8")
        proc = AcpProcess(mode, command, env, patch, chosen.provider)
        await proc.start()
        log.info("DeepSeek Harness 已启动（%s，%s）", "操作" if mode == "act" else "问答", chosen.provider)
        return proc

    async def warm(self, mode: str = "ask") -> None:
        """起好进程，再提前建好一个会话。"""
        self._rewarm(mode)
        task = self._warming.get(mode)
        if task is not None:
            await asyncio.shield(task)

    def _rewarm(self, mode: str) -> None:
        if mode not in self._ready and mode not in self._warming:
            self._warming[mode] = asyncio.get_running_loop().create_task(self._prepare(mode))

    async def _prepare(self, mode: str) -> None:
        try:
            self._ready[mode] = await self._new_session(mode)
        except Exception as e:  # noqa: BLE001 - 预热失败不影响正式提问，那时会再建
            log.warning("DeepSeek Harness 预热失败：%s", e)
        finally:
            if self._warming.get(mode) is asyncio.current_task():
                self._warming.pop(mode)

    async def _new_session(self, mode: str) -> DshSession:
        proc = await self.process(mode)
        result = await proc.request("session/new", {"cwd": str(paths.SESSIONS),
                                                    "mcpServers": mcp_servers(mode, self.blocked_apps())})
        session = DshSession(proc, str(result["sessionId"]), "", "")
        session.learn(result.get("configOptions"), self._remember)
        return session

    async def open(self, mode: str, model: str, effort: str, rewarm: bool = True) -> DshSession:
        warming = self._warming.get(mode)
        if warming is not None and mode not in self._ready:  # 正在提前建：等它，不再另建一个
            await asyncio.shield(warming)
        session = self._ready.pop(mode, None)
        if session is None or not session.proc.alive:
            session = await self._new_session(mode)
        session.model, session.effort = model, effort  # 第一次发问之前设上
        if rewarm and mode in ("ask", "act"):
            self._rewarm(mode)
        return session

    def _remember(self, models: dict[str, str], efforts: list[str]) -> None:
        """会话报来的模型清单：发现模型时用它（不额外开会话去问）。"""
        for model in models:
            self._catalog.setdefault(model, {"id": model, "desc": ""})
        legal = [e for e in EFFORTS if e in efforts]
        if legal:
            for info in self._catalog.values():
                info.setdefault("efforts", legal)

    @staticmethod
    async def switch(session: DshSession, mode: str, model: str, effort: str) -> DshSession:
        """同一个对话换配置：下一轮发问之前设上。"""
        session.model, session.effort = model, effort
        return session

    async def models(self) -> list[dict]:
        """能用的模型。用的是自定义的服务时只列它的模型（DSH 自带的 DeepSeek 模型在那里用不了）。"""
        chosen = route()
        ids = list(chosen.models) if chosen.custom else list(self._catalog)
        for model in ids:
            self._catalog.setdefault(model, {"id": model, "desc": ""})
        return [{"efforts": list(EFFORTS), **self._catalog[m]} for m in ids]

    async def complete(self, prompt: str, model: str, schema: dict | None = None) -> str:
        """一次性的小活（总结经验、后台对比的评审）：只读、不挂界面工具，返回最后的回答。"""
        if schema:
            prompt += ("\n\n只输出一个 JSON 对象，不要别的文字，符合这个 JSON Schema：\n"
                       + json.dumps(schema, ensure_ascii=False))
        session = await self.open("duel", model, "high", rewarm=False)
        text, error = "", ""
        try:
            async for ev in session.send(prompt, []):
                if ev.type in ("new_message", "retract"):
                    text = ""
                elif ev.type == "delta":
                    text += ev.text
                elif ev.type == "done" and not ev.data.get("ok"):
                    error = ev.data.get("error") or "没有完成"
        finally:
            await session.close()
        if error and not text:
            raise AcpError(error)
        return text

    async def reload(self) -> None:
        """登录方式或 API Key 改了：关掉按旧配置起的进程，下次用时重新起。"""
        await self.close()

    async def close(self) -> None:
        for task in self._warming.values():
            task.cancel()
        self._warming.clear()
        self._ready.clear()  # 提前建好的会话属于这些进程，进程关了它们也就没了
        procs, self._procs = list(self._procs.values()), {}
        await asyncio.gather(*(proc.close() for proc in procs), return_exceptions=True)


class DshSession:
    engine = "dsh"

    def __init__(self, proc: AcpProcess, session_id: str, model: str, effort: str) -> None:
        self.proc = proc
        self.session_id = session_id
        self.model, self.effort = model, effort
        self.values: dict[str, str] = {}   # 模型 → 设置时要传的值
        self.efforts: list[str] = []       # 当前模型能设的思考强度（自定义服务的模型可能一档都没有）
        self.applied: tuple[str, str] = ("", "")
        self.queue: asyncio.Queue = asyncio.Queue()
        self.current: str | None = None    # 正在显示的那段话（DSH 的 messageId）
        proc.sessions[session_id] = self.queue

    def learn(self, options: list[dict] | None, remember: Callable[[dict[str, str], list[str]], None] | None = None) -> None:
        models, efforts = read_options(options, self.proc.provider)
        self.values.update(models)
        if options is not None:
            self.efforts = efforts
        current = {o.get("id"): o.get("currentValue") for o in options or [] if isinstance(o, dict)}
        model = next((m for m, v in models.items() if v == current.get("model")), "")
        self.applied = (model, str(current.get("reasoning_effort") or ""))
        if remember is not None:
            remember(models, efforts)

    async def _apply(self) -> None:
        model, effort = self.applied
        if self.model and self.model != model:
            value = self.values.get(self.model) or json.dumps([self.proc.provider, self.model], separators=(",", ":"))
            result = await self.proc.request("session/set_config_option", {
                "sessionId": self.session_id, "configId": "model", "value": value})
            self.learn(result.get("configOptions"))
        effort = self._legal(self.effort)
        if effort and effort != self.applied[1]:
            result = await self.proc.request("session/set_config_option", {
                "sessionId": self.session_id, "configId": "reasoning_effort", "value": effort})
            self.learn(result.get("configOptions"))

    def _legal(self, effort: str) -> str:
        """这个模型能设的那一档：有就用它，没有就用不超过它的最高一档（都比它高就用最低的）；
        一档都设不了（不是推理模型，或者 DSH 没报上来）就不设，用它自己的默认。"""
        known = [e for e in self.efforts if e in LEVELS]
        if not effort or not known:
            return ""
        if effort in known:
            return effort
        lower = [e for e in known if LEVELS.index(e) <= LEVELS.index(effort)] if effort in LEVELS else []
        return lower[-1] if lower else known[0]

    def _content(self, text: str, images: list[Path]) -> list[dict]:
        blocks = []
        if self.proc.image and self.model in IMAGE_MODELS:
            for path in images:
                mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
                blocks.append({"type": "image", "mimeType": mime,
                               "data": base64.b64encode(path.read_bytes()).decode()})
        return blocks + [{"type": "text", "text": text}]

    async def send(self, text: str, images: list[Path]) -> AsyncIterator[Event]:
        await self._apply()
        prompt = asyncio.ensure_future(self.proc.request(
            "session/prompt", {"sessionId": self.session_id, "prompt": self._content(text, images)}))
        self.current = None
        while True:
            getter = asyncio.ensure_future(self.queue.get())
            done, _ = await asyncio.wait({prompt, getter}, return_when=asyncio.FIRST_COMPLETED)
            if getter not in done:
                getter.cancel()
                break
            update = getter.result()
            if update is None:
                break
            for ev in self.events(update):
                yield ev
        while not self.queue.empty():  # 回复之前发来的更新都已经在队列里了
            update = self.queue.get_nowait()
            if update is None:
                break
            for ev in self.events(update):
                yield ev
        stop, error = "", ""
        try:
            stop = str((await prompt).get("stopReason") or "")
        except AcpError as e:
            error = str(e).replace("Internal error: turn failed: ", "")
        reason = "interrupted" if stop == "cancelled" else (stop or "error")
        yield Event("done", data={"ok": stop == "end_turn" and not error, "engine": "dsh", "session": self.session_id,
                                  "reason": reason, "error": error or (tr("回答太长被截断了") if stop == "max_tokens" else "")})

    def events(self, update: dict) -> list[Event]:
        """一条会话更新 → 界面认的事件。每一步做完 DSH 才把这一步的话整段发来；后面跟着工具调用的，是过程说明。"""
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = update.get("content") or {}
            if content.get("type") != "text" or not content.get("text"):
                return []
            message = update.get("messageId") or "?"
            head = [Event("new_message")] if message != self.current else []
            self.current = message
            return head + [Event("delta", str(content["text"]))]
        if kind == "tool_call":
            self.current = None
            name = str(update.get("title") or update.get("kind") or "")
            return [Event("retract"), Event("status", tool_status(name, update.get("rawInput") or {}), {"tool": name})]
        return []

    async def interrupt(self) -> None:
        await self.proc.notify("session/cancel", {"sessionId": self.session_id})

    async def close(self) -> None:
        self.proc.sessions.pop(self.session_id, None)
        try:
            await self.proc.request("session/close", {"sessionId": self.session_id})
        except Exception:  # noqa: BLE001 - 进程已经没了也无所谓
            pass
