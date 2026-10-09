"""配置模型：用账号登录（打开登录窗口，浏览器里完成），或者填自定义服务地址和密钥。

Super Aide 自己不存密钥，都写进工具自己的配置里，和你手动配的效果一样：
- Claude Code：~/.claude/settings.json 的 env（ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN；官方 API 用 ANTHROPIC_API_KEY）。
- Codex：~/.codex/config.toml 里加一个服务商（model_providers.super_aide），密钥放在用户环境变量里
  （Codex 按服务商的 env_key 从环境变量取密钥）；官方 API Key 用 `codex login --with-api-key` 存。
- DeepSeek Harness：账号在它自己的界面里登录（没有命令行登录）；API Key 放在用户环境变量 DEEPSEEK_API_KEY。
改文件之前各留一份备份（*.super-aide.bak），只改这几项，别的设置和注释原样保留。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import tr
from . import winenv
from .detect import NAMES, Places, Report, claude_dir, codex_dir, dsh_desktop

log = logging.getLogger(__name__)

CODEX_PROVIDER = "super_aide"
CODEX_KEY_ENV = "SUPER_AIDE_CODEX_API_KEY"
CLAUDE_OFFICIAL = "https://api.anthropic.com"
OPENAI_OFFICIAL = "https://api.openai.com/v1"
DEEPSEEK_OFFICIAL = "https://api.deepseek.com"
_HEADER = re.compile(r"^\s*\[\[?\s*[^\]]+\]\]?\s*(#.*)?$")  # TOML 的表头：[x] 或 [[x]]


class ConfigError(Exception):
    pass


@dataclass
class Check:
    ok: bool
    message: str
    models: list[str] = field(default_factory=list)
    verified: bool = False  # 真的验证了密钥（列出了模型）；False = 连上了，但这个服务没法确认密钥


# ---------- 账号登录 ----------

def bundled_cli(tool: str) -> str:
    """两个 SDK 自带的 CLI：没装全局命令（比如只装了桌面版）时用它登录，登录结果两边共用。"""
    if tool == "claude":
        import claude_agent_sdk

        return str(Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude.exe")
    from codex_cli_bin import bundled_codex_path

    return str(bundled_codex_path())


def login_command(tool: str, report: Report) -> list[str]:
    t = report.tool(tool)
    exe = t.where if t.via == "cli" and t.where else bundled_cli(tool)
    return [exe, "auth", "login"] if tool == "claude" else [exe, "login"]


def open_login(tool: str, report: Report) -> None:
    """新开一个命令行窗口登录（浏览器会自己打开）。登录成功窗口自己关；出错就停住，看得到原因。"""
    exe, *args = login_command(tool, report)
    line = " ".join([f'"{exe}"', *args])
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    subprocess.Popen(f'cmd.exe /s /c "title {tr("登录 {name}", name=NAMES[tool])} & {line} || pause"',
                     creationflags=subprocess.CREATE_NEW_CONSOLE, env=env, cwd=str(Path.home()))


def open_dsh_login(report: Report) -> None:
    """DSH 没有命令行登录：桌面版直接打开它（在它的账号设置里登录）；npm 装的开一个 `dsh web`（会给出一个本机网址）。"""
    exe = dsh_desktop(Places.current()) / "DeepSeek Harness.exe"
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "ELECTRON_RUN_AS_NODE")}
    if exe.exists():
        subprocess.Popen([str(exe)], env=env, cwd=str(exe.parent))
        return
    where = report.dsh.where
    if not where:
        raise ConfigError(tr("没找到 DeepSeek Harness"))
    subprocess.Popen(f'cmd.exe /s /c "title {tr("登录 {name}", name="DeepSeek Harness")} & "{where}" web || pause"',
                     creationflags=subprocess.CREATE_NEW_CONSOLE, env=env, cwd=str(Path.home()))


# ---------- 自定义服务地址：检查 ----------

def claude_base(url: str) -> str:
    """Claude Code 自己会在后面加 /v1/messages：去掉多余的 /v1 和斜杠，没写协议的补上 https。"""
    url = url.strip().rstrip("/")
    if url and "://" not in url:
        url = f"https://{url}"
    return re.sub(r"/v1$", "", url)


def openai_base(url: str) -> str:
    """Codex 会在后面加 /responses：只写了域名的补上 /v1。"""
    url = url.strip().rstrip("/")
    if url and "://" not in url:
        url = f"https://{url}"
    if url and not re.match(r"^https?://[^/]+/.+", url):
        url += "/v1"
    return url


def _list(url: str, headers: dict[str, str], timeout: float) -> Check:
    req = urllib.request.Request(url, headers={**headers, "User-Agent": "super-aide-setup"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return Check(False, tr("密钥不对（服务地址返回 {code}）", code=e.code))
        if e.code in (404, 405, 501):
            return Check(True, tr("连上了，但这个服务不支持列出模型，没法提前确认密钥"))
        return Check(False, tr("服务地址返回 {code}，请检查地址", code=e.code))
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        reason = getattr(e, "reason", e)
        return Check(False, tr("连不上这个地址（{reason}）", reason=reason))
    except ValueError:
        return Check(True, tr("连上了，但返回的不是模型列表，没法提前确认密钥"))
    items = data.get("data") if isinstance(data, dict) else None
    models = [str(m.get("id")) for m in items or [] if isinstance(m, dict) and m.get("id")]
    return Check(True, tr("连接成功，找到 {n} 个模型", n=len(models)) if models else tr("连接成功"), models, True)


def check_claude(base: str, key: str, timeout: float = 15) -> Check:
    root = claude_base(base) or CLAUDE_OFFICIAL
    result = _list(f"{root}/v1/models?limit=1000", {
        "x-api-key": key, "Authorization": f"Bearer {key}", "anthropic-version": "2023-06-01"}, timeout)
    result.models = [m for m in result.models if m.startswith("claude-")]
    return result


def check_openai(base: str, key: str, timeout: float = 15) -> Check:
    root = openai_base(base) or OPENAI_OFFICIAL
    return _list(f"{root}/models", {"Authorization": f"Bearer {key}"}, timeout)


def check(tool: str, base: str, key: str) -> Check:
    if not key.strip():
        return Check(False, tr("请填写密钥"))
    if tool == "claude":
        return check_claude(base, key.strip())
    if tool == "dsh":
        return check_openai(DEEPSEEK_OFFICIAL, key.strip())  # DeepSeek 官方 API 的模型列表
    return check_openai(base, key.strip())


# ---------- 自定义服务地址：写配置 ----------

def save(tool: str, base: str, key: str, model: str = "", places: Places | None = None) -> None:
    p = places or Places.current()
    key, model = key.strip(), model.strip()
    if not key:
        raise ConfigError(tr("请填写密钥"))
    if tool == "claude":
        save_claude(claude_dir(p) / "settings.json", base, key, model)
    elif tool == "dsh":
        winenv.set_user_env("DEEPSEEK_API_KEY", key)  # DSH 的 deepseek-official 服务商从这里取
    else:
        save_codex(codex_dir(p) / "config.toml", base, key, model)


def save_claude(path: Path, base: str, key: str, model: str = "") -> None:
    data = _read_json(path)
    env = {k: v for k, v in (data.get("env") or {}).items()
           if k not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")}
    root = claude_base(base)
    if root and root != CLAUDE_OFFICIAL:
        env.update(ANTHROPIC_BASE_URL=root, ANTHROPIC_AUTH_TOKEN=key)
    else:
        env["ANTHROPIC_API_KEY"] = key
    data["env"] = env
    if model:
        data["model"] = model
    _backup(path)
    _write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def save_codex(path: Path, base: str, key: str, model: str = "") -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    root = openai_base(base)
    official = not root or root == OPENAI_OFFICIAL
    if official:
        text = set_top_key(text, "model_provider", "openai")
    else:
        text = set_top_key(text, "model_provider", CODEX_PROVIDER)
        text = replace_table(text, f"model_providers.{CODEX_PROVIDER}", (
            f"[model_providers.{CODEX_PROVIDER}]\n"
            'name = "Custom"\n'
            f"base_url = {json.dumps(root)}\n"
            f'env_key = "{CODEX_KEY_ENV}"\n'
            'wire_api = "responses"\n'))
    if model:
        text = set_top_key(text, "model", model)
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(tr("没法自动修改 {path}（{error}），请手动配置", path=path, error=e)) from e
    if official:
        _login_api_key(key)
    else:
        winenv.set_user_env(CODEX_KEY_ENV, key)
    _backup(path)
    _write(path, text)


def _login_api_key(key: str) -> None:
    """官方 OpenAI API Key：用 Codex 自己的方式存（auth.json）。"""
    try:
        result = subprocess.run([bundled_cli("codex"), "login", "--with-api-key"], input=key, text=True,
                                capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ConfigError(tr("Codex 没能保存 API Key（{error}）", error=e)) from e
    if result.returncode != 0:
        raise ConfigError(tr("Codex 没能保存 API Key（{error}）", error=(result.stderr or result.stdout).strip()[:120]))


def set_top_key(text: str, key: str, value: str) -> str:
    """改 TOML 顶层的一个字符串键（在第一个表头之前）；没有就加上。其它行原样保留。"""
    lines = text.splitlines()
    end = next((i for i, line in enumerate(lines) if _HEADER.match(line)), len(lines))
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    entry = f"{key} = {json.dumps(value, ensure_ascii=False)}"
    for i in range(end):
        if pattern.match(lines[i]):
            lines[i] = entry
            break
    else:
        at = end
        while at > 0 and not lines[at - 1].strip():  # 加在顶层最后一个非空行后面
            at -= 1
        lines.insert(at, entry)
    return "\n".join(lines) + "\n"


def replace_table(text: str, name: str, block: str) -> str:
    """把 [name] 这张表整个换成 block；没有就加在文件末尾。"""
    lines = text.splitlines()
    header = re.compile(rf"^\s*\[\s*{re.escape(name)}\s*\]\s*(#.*)?$")
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    new = block.rstrip("\n").splitlines()
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ([""] if lines else []) + new
    else:
        end = next((i for i in range(start + 1, len(lines)) if _HEADER.match(lines[i])), len(lines))
        tail = [""] if end < len(lines) else []
        lines[start:end] = new + tail
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except ValueError as e:
        raise ConfigError(tr("{path} 不是有效的 JSON，没有改动它（{error}）", path=path, error=e)) from e
    if not isinstance(data, dict):
        raise ConfigError(tr("{path} 的内容不是对象，没有改动它", path=path))
    return data


def _backup(path: Path) -> None:
    if path.exists():
        path.with_name(path.name + ".super-aide.bak").write_bytes(path.read_bytes())


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
