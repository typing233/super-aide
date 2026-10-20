"""操作界面用谁的：Codex 官方的 Computer Use / Browser Use，还是我们自研的（cu 工具服务器）。

官方的只有在 Codex 用官方账号（ChatGPT）登录、没有接自定义服务地址时才完整可用；接自定义地址时只能
非常有限地用（用户实测）。所以：官方账号 → 用官方的（Claude 需要动界面时转交 Codex）；否则两个引擎都
用自研的工具服务器，Codex 自带的那两个插件关掉，免得它在半残的功能上浪费时间。
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

from ..i18n import tr
from .base import short

CODEX_HOME = Path.home() / ".codex"
SERVER_NAME = "computer"  # 工具在 Claude 里叫 mcp__computer__*
#: 关掉 Codex 自带的界面操作（用自研的时候）
CODEX_NATIVE_OFF = ("features.computer_use=false", "features.browser_use=false",
                    'plugins."computer-use@openai-bundled".enabled=false',
                    'plugins."browser@openai-bundled".enabled=false',
                    'plugins."chrome@openai-bundled".enabled=false')


def official_codex(home: Path = CODEX_HOME) -> bool:
    """Codex 是不是用官方账号登录、走官方服务。"""
    try:
        auth = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not (auth.get("tokens") or {}).get("access_token"):
        return False  # 只有 API Key、没有 ChatGPT 账号登录
    try:
        provider = tomllib.loads((home / "config.toml").read_text(encoding="utf-8")).get("model_provider", "")
    except (OSError, tomllib.TOMLDecodeError):
        provider = ""
    return provider in ("", "openai")


def _python() -> str:
    """工具服务器用带控制台的 python.exe（走 stdio）；没有窗口：引擎的 CLI 本身在隐藏的控制台里运行，子进程沿用。"""
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return str(console if console.exists() else exe)


#: 操作模式下告诉引擎界面怎么动（两个引擎用同一句：没有它 Codex 会自己写 UI Automation 脚本去点，又慢又点错，实测）
ACT_NOTE = (
    "\n\n【操作界面】需要操作图形界面或浏览器时（点按钮、填写或提交表单、在网页或某个软件里执行操作、"
    "在浏览器里的 Notebook 中运行代码等），用 computer 工具自己动手：observe_window 看窗口 → act 用控件编号操作"
    "（可以一次给几步）→ 看返回的新画面确认结果。不要自己写 UI Automation 或模拟键鼠的脚本去点界面。"
    "浏览器就是用户正在用的那个，已经登录的网站都在；browser 工具能读网址、打开网址、切换标签页。"
    "命令行和文件能解决的事直接做，不用界面。")

#: 问答模式能用的工具：只看、只指，不改动任何东西（服务器在问答模式下也只注册这些）
ASK_TOOLS = tuple(f"mcp__{SERVER_NAME}__{t}" for t in ("observe_window", "find", "zoom", "read", "windows", "point"))


def server_env(blocked_apps: list[str], mode: str = "act") -> dict[str, str]:
    return {"AIDE_APP_PID": str(os.getpid()), "AIDE_BLOCKED_APPS": ";".join(blocked_apps), "AIDE_MODE": mode,
            "PYTHONIOENCODING": "utf-8"}


def claude_server(blocked_apps: list[str], mode: str = "act") -> dict:
    return {"type": "stdio", "command": _python(), "args": ["-X", "utf8", "-m", "super_aide.cu.server"],
            "env": server_env(blocked_apps, mode)}


#: act 第一步的进度。中文原文是 tr() 的键，显示时才翻译（界面语言随时可以换）
ACT_VERBS = {"click": "正在点击", "double_click": "正在双击", "right_click": "正在右键点击", "hover": "正在移动鼠标",
             "type": "正在输入", "scroll": "正在滚动", "drag": "正在拖动", "toggle": "正在勾选", "focus": "正在切换窗口",
             "wait": "正在等待"}


def looks_at_screen(tool: str) -> bool:
    """这个工具要看实时的屏幕（看窗口、圈位置、读界面……）。后台对比的会话没有这些工具，用过它们的问答不比。"""
    return tool.startswith(f"mcp__{SERVER_NAME}__")


def status(tool: str, args: dict | None) -> str:
    """工具调用 → 界面上的一行进度（两个引擎共用）。tool 可以带 mcp__computer__ 前缀。"""
    tool = tool.rsplit("__", 1)[-1]
    args = args if isinstance(args, dict) else {}
    if tool == "observe_window":
        return tr("正在看「{window}」…", window=args["window"]) if args.get("window") else tr("正在看窗口…")
    if tool == "act":
        actions = args.get("actions") or []
        first = actions[0] if actions and isinstance(actions[0], dict) else {}
        do = first.get("do", "")
        if do == "key":
            text = tr("正在按 {keys}", keys=first.get("keys", ""))
        elif do == "select":
            text = tr("正在选择「{target}」", target=first.get("text", ""))
        elif do == "wait_for":
            text = tr("正在等「{target}」出现", target=first.get("text", ""))
        elif do == "wait_gone":
            text = tr("正在等「{target}」消失", target=first.get("text", ""))
        else:
            text = tr(ACT_VERBS.get(do, "正在操作界面"))
        return f"{text}…" if len(actions) <= 1 else tr("{action}（共 {count} 步）…", action=text, count=len(actions))
    if tool == "browser":
        command, value = args.get("command", ""), args.get("value", "")
        return tr("正在打开 {url}…", url=value[:50]) if command in ("go", "new_tab") and value else tr("正在操作浏览器…")
    if tool == "find":
        return tr("正在找「{target}」…", target=args.get("text", ""))
    labels = {"zoom": tr("正在放大看细节…"), "read": tr("正在读窗口里的文字…"), "windows": tr("正在查看打开的窗口…"),
              "point": tr("正在屏幕上圈出位置…")}
    return labels.get(tool) or tr("正在操作界面…")


def command_status(command: str) -> str:
    """跑命令行的那一行进度（三个引擎共用）。"""
    return _one_ellipsis(tr("正在运行 {command}", command=short(command, 50)))


def search_status(query: str) -> str:
    """搜网页的那一行进度。"""
    return _one_ellipsis(tr("正在搜索 {query}", query=short(query, 40)))


def _one_ellipsis(text: str) -> str:
    """英文的进度行以"…"结尾：前面的命令、搜索词被截短过（short 也加了"…"）时只留一个。中文这两行不加"…"，不受影响。"""
    return text[:-1] if text.endswith("……") else text


def codex_overrides(blocked_apps: list[str], mode: str = "act") -> tuple[str, ...]:
    """给 Codex 的 -c 配置：挂上自研工具服务器，关掉自带的界面操作。"""
    env = ",".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in server_env(blocked_apps, mode).items())
    prefix = f"mcp_servers.{SERVER_NAME}"
    return (f"{prefix}.command={json.dumps(_python())}",
            f'{prefix}.args=["-X", "utf8", "-m", "super_aide.cu.server"]',
            f"{prefix}.env={{{env}}}",
            f"{prefix}.startup_timeout_sec=30",
            f"{prefix}.tool_timeout_sec=600",
            *CODEX_NATIVE_OFF)
