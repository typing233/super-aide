"""前置检查：Claude Code、Codex、DeepSeek Harness（DSH）装没装、模型配没配。

Super Aide 直接用这几个工具自己的模型配置（~/.claude、~/.codex、~/.dsh），所以一个引擎"能用" = 配好了模型
（两个 SDK 自带 CLI，引擎本身不靠全局安装的命令；但 DSH 没有 SDK，要装了才能用）。
这里只看文件和环境变量（几十毫秒，每次启动都能查），只看有没有，不读出、不记录任何密钥的值。
"""

from __future__ import annotations

import json
import os
import shutil
import tomllib
import winreg
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from ..i18n import tr
from . import dshconf

TOOLS = ("claude", "codex", "dsh")
NAMES = {"claude": "Claude Code", "codex": "Codex", "dsh": "DeepSeek Harness"}
#: 用第三方云平台的 Claude（这些开关打开时不需要 Anthropic 的令牌）
CLAUDE_CLOUD = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
#: Codex 自带的本地服务商，不需要密钥
CODEX_LOCAL = ("oss", "ollama", "lmstudio")


@dataclass(frozen=True)
class Places:
    """去哪儿找：家目录、%LOCALAPPDATA%、%APPDATA%，以及环境变量（名字大写）。测试里换成临时目录。"""

    home: Path
    local: Path
    roaming: Path
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def current(cls) -> Places:
        home = Path.home()
        env = user_env()
        env.update({k.upper(): v for k, v in os.environ.items()})  # 进程里的优先（启动时传进来的）
        # PATH：进程的 + 注册表里刚加上的（比如刚装完 Node.js，进程的 PATH 还是旧的）
        parts = os.environ.get("PATH", "").split(os.pathsep)
        extra = [p for p in os.path.expandvars(user_env().get("PATH", "")).split(os.pathsep) if p and p not in parts]
        env["PATH"] = os.pathsep.join(parts + extra)
        return cls(home=home, local=Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")),
                   roaming=Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")), env=env)

    def which(self, name: str) -> str:
        return shutil.which(name, path=self.env.get("PATH", "")) or ""


@dataclass
class Tool:
    name: str
    installed: bool = False
    where: str = ""        # 找到的命令或应用
    via: str = ""          # cli（命令行）| desktop（桌面版）| vscode（编辑器插件）
    configured: bool = False
    auth: str = ""         # account（账号登录）| custom（自定义服务地址）| apikey | cloud | local
    detail: str = ""       # 一句话：怎么配的，或者缺什么

    @property
    def title(self) -> str:
        return NAMES[self.name]


@dataclass
class Report:
    claude: Tool
    codex: Tool
    dsh: Tool

    def tool(self, name: str) -> Tool:
        return getattr(self, name)

    def missing(self) -> list[str]:
        """Claude Code、Codex 里还没装的。"""
        return [t.name for t in (self.claude, self.codex) if not t.installed]

    def unconfigured(self) -> list[str]:
        """装了但还没配模型的。"""
        return [t.name for t in (self.claude, self.codex, self.dsh) if t.installed and not t.configured]

    def usable(self, use_dsh: bool) -> list[str]:
        """现在就能回答问题的引擎。DSH 只有你选了用它时才算。"""
        found = [t.name for t in (self.claude, self.codex) if t.configured]
        if use_dsh and self.dsh.installed and self.dsh.configured:
            found.append("dsh")
        return found

    def as_dict(self) -> dict:
        return {name: asdict(self.tool(name)) | {"title": NAMES[name]} for name in TOOLS}


def scan(places: Places | None = None) -> Report:
    p = places or Places.current()
    return Report(claude=_claude(p), codex=_codex(p), dsh=_dsh(p))


# ---------- 工具函数 ----------

def user_env() -> dict[str, str]:
    """注册表里的用户环境变量（名字大写）。刚设上的也算：当前进程的环境是启动时的旧样子。"""
    out: dict[str, str] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            i = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, i)
                except OSError:
                    break
                out[name.upper()] = str(value)
                i += 1
    except OSError:
        pass
    return out


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def host(url: str) -> str:
    """只显示服务地址的主机名（界面上一眼看出连的是谁），不显示路径和参数。"""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.hostname or url


def _first(*candidates: tuple[str, Path | str]) -> tuple[str, str]:
    """→ (位置, 方式)：第一个存在的。"""
    for via, path in candidates:
        if path and Path(path).exists():
            return str(path), via
    return "", ""


def _glob(root: Path, pattern: str) -> Path | str:
    try:
        return next(iter(sorted(root.glob(pattern), reverse=True)), "")
    except OSError:
        return ""


# ---------- Claude Code ----------

def claude_dir(p: Places) -> Path:
    return p.home / ".claude"


def _claude(p: Places) -> Tool:
    where, via = _first(
        ("cli", p.which("claude")),
        ("cli", p.home / ".local" / "bin" / "claude.exe"),           # 官方安装方式（native）
        ("cli", p.roaming / "npm" / "claude.cmd"),                   # npm 默认的全局目录
        ("cli", p.local / "Microsoft" / "WinGet" / "Links" / "claude.exe"),
        ("vscode", _glob(p.home / ".vscode" / "extensions", "anthropic.claude-code-*")),
    )
    tool = Tool("claude", installed=bool(where), where=where, via=via)
    tool.configured, tool.auth, tool.detail = claude_auth(p)
    return tool


def claude_auth(p: Places) -> tuple[bool, str, str]:
    settings = _json(claude_dir(p) / "settings.json")
    env = {**p.env, **{str(k).upper(): str(v) for k, v in (settings.get("env") or {}).items()}}
    if any(env.get(k, "").lower() in ("1", "true") for k in CLAUDE_CLOUD):
        return True, "cloud", tr("第三方云平台（Bedrock / Vertex / Foundry）")
    if env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY") or settings.get("apiKeyHelper"):
        base = env.get("ANTHROPIC_BASE_URL", "")
        if base:
            return True, "custom", tr("自定义服务地址 {host}", host=host(base))
        return True, "apikey", "Anthropic API Key"
    if env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return True, "account", tr("Claude 账号（长期令牌）")
    oauth = _json(claude_dir(p) / ".credentials.json").get("claudeAiOauth") or {}
    if oauth.get("refreshToken") or oauth.get("accessToken"):
        return True, "account", tr("Claude 账号登录")
    if _json(p.home / ".claude.json").get("primaryApiKey"):
        return True, "apikey", tr("Anthropic Console 账号")
    return False, "", tr("还没配置模型")


# ---------- Codex ----------

def codex_dir(p: Places) -> Path:
    return Path(p.env["CODEX_HOME"]) if p.env.get("CODEX_HOME") else p.home / ".codex"


def _codex(p: Places) -> Tool:
    where, via = _first(
        ("cli", p.which("codex")),
        ("cli", p.roaming / "npm" / "codex.cmd"),
        ("cli", p.local / "Microsoft" / "WinGet" / "Links" / "codex.exe"),
        ("desktop", _glob(p.local / "Packages", "OpenAI.Codex_*")),   # 微软商店的 Codex 桌面版
        ("vscode", _glob(p.home / ".vscode" / "extensions", "openai.chatgpt-*")),
    )
    tool = Tool("codex", installed=bool(where), where=where, via=via)
    tool.configured, tool.auth, tool.detail = codex_auth(p)
    return tool


def codex_provider(cfg: dict) -> str:
    """现在用的服务商：配置里选了 profile 的，以 profile 里的为准。"""
    profile = (cfg.get("profiles") or {}).get(cfg.get("profile") or "") or {}
    return str(profile.get("model_provider") or cfg.get("model_provider") or "openai")


def codex_auth(p: Places) -> tuple[bool, str, str]:
    home = codex_dir(p)
    cfg = _toml(home / "config.toml")
    auth = _json(home / "auth.json")
    tokens = auth.get("tokens") or {}
    login = bool(tokens.get("access_token") or tokens.get("refresh_token"))
    key = bool(auth.get("OPENAI_API_KEY"))
    provider = codex_provider(cfg)
    if provider == "openai":
        if login:
            return True, "account", tr("ChatGPT 账号登录")
        if key or p.env.get("OPENAI_API_KEY"):
            return True, "apikey", "OpenAI API Key"
        return False, "", tr("还没配置模型")
    if provider in CODEX_LOCAL:
        return True, "local", tr("本地模型")
    info = (cfg.get("model_providers") or {}).get(provider)
    if not isinstance(info, dict):
        return False, "", tr("配置里选的服务商 {provider} 没有定义", provider=provider)
    where = host(str(info.get("base_url", ""))) or provider
    if info.get("experimental_bearer_token"):
        return True, "custom", tr("自定义服务地址 {host}", host=where)
    env_key = str(info.get("env_key") or "")
    if env_key:
        if p.env.get(env_key.upper()):
            return True, "custom", tr("自定义服务地址 {host}", host=where)
        return False, "custom", tr("{host} 的密钥（环境变量 {name}）没有设置", host=where, name=env_key)
    if info.get("requires_openai_auth"):
        if login or key:
            return True, "custom", tr("自定义服务地址 {host}", host=where)
        return False, "custom", tr("{host} 需要先登录", host=where)
    return True, "custom", tr("自定义服务地址 {host}", host=where)


# ---------- DeepSeek Harness ----------

def dsh_dir(p: Places) -> Path:
    return Path(p.env["DSH_HOME"]) if p.env.get("DSH_HOME") else p.home / ".dsh"


def dsh_desktop(p: Places) -> Path:
    return p.local / "Programs" / "DeepSeek Harness"


def _dsh_registered(p: Places) -> str:
    """桌面版"把 dsh 加到命令行"时记下的目录。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\DeepSeekHarness\Command") as key:
            directory = str(winreg.QueryValueEx(key, "Directory")[0])
    except OSError:
        return ""
    return str(Path(directory) / "dsh.cmd") if directory else ""


def _dsh(p: Places) -> Tool:
    where, via = _first(
        ("cli", p.which("dsh")),
        ("cli", p.roaming / "npm" / "dsh.cmd"),
        ("desktop", _dsh_registered(p)),
        ("desktop", dsh_desktop(p) / "resources" / "runtime" / "cli" / "bin" / "dsh.cmd"),
    )
    tool = Tool("dsh", installed=bool(where), where=where, via=via)
    tool.configured, tool.auth, tool.detail = dsh_auth(p)
    return tool


def dsh_auth(p: Places) -> tuple[bool, str, str]:
    """DSH 的凭据。DSH 自己的模型设置里默认用的是自定义的服务（dshconf.py）：它的密钥名字（apiKeyEnv）
    在环境变量、~/.dsh/.credentials.yaml 的 refs 或 ~/.dsh/.env 里就算配好了。否则看 DeepSeek 账号登录
    （记在同一个文件的 records 下）和 DEEPSEEK_API_KEY。只看名字在不在，不读值。"""
    credentials = dsh_dir(p) / ".credentials.yaml"

    def has_key(name: str) -> bool:
        return bool(p.env.get(name)) or name in _yaml_keys(credentials, "refs")             or name in _env_file_keys(dsh_dir(p) / ".env")

    route = dshconf.read(dsh_dir(p))
    if route.custom:
        if route.key_env and not has_key(route.key_env):
            return False, "", tr("自定义服务地址还没有密钥（{name}）", name=route.key_env)
        return True, "custom", tr("自定义服务地址 {host}", host=host(route.base)) if route.base             else tr("自定义服务 {name}", name=route.provider)
    if "deepseek-account-platform/default" in _yaml_keys(credentials, "records"):
        return True, "account", tr("DeepSeek 账号登录")
    if has_key("DEEPSEEK_API_KEY"):
        return True, "apikey", "DeepSeek API Key"
    return False, "", tr("还没登录 DeepSeek 账号")


def _yaml_keys(path: Path, section: str) -> set[str]:
    """YAML 文件里某个顶层段落下一级的键名（两格缩进、冒号前面的部分）。只取名字，冒号后面的值直接丢掉。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    names, inside = set(), False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            inside = line.split(":", 1)[0].strip() == section
            continue
        if inside and line.startswith("  ") and not line.startswith("   ") and ":" in line:
            names.add(line.split(":", 1)[0].strip().strip("'\""))
    return names


def _env_file_keys(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {line.split("=", 1)[0].strip().removeprefix("export ").strip()
            for line in lines if "=" in line and not line.lstrip().startswith("#")}
