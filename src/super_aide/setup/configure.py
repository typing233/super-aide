"""配置模型：用账号登录（打开登录窗口，浏览器里完成），或者填自定义服务地址和密钥。

Super Aide 自己不存密钥，都写进工具自己的配置里，和你手动配的效果一样：
- Claude Code：~/.claude/settings.json 的 env（ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN；官方 API 用 ANTHROPIC_API_KEY）。
- Codex：~/.codex/config.toml 里加一个服务商（model_providers.super_aide），密钥写在服务商的 experimental_bearer_token 里；
  官方 API Key 用 `codex login --with-api-key` 存。原来放在用户环境变量里（服务商的 env_key），可已经开着的 Codex 桌面版、
  VS Code 插件、终端拿不到新变量，一用就报 "Missing environment variable"（2026-10-10 实测），现在不用环境变量了。
- DeepSeek Harness：账号在它自己的界面里登录（没有命令行登录）；DeepSeek 官方的 API Key 放在用户环境变量 DEEPSEEK_API_KEY；
  自定义服务地址写进 DSH 自己的模型设置（setup/dshconf.py：路由 super-aide，DSH 桌面版里看得到），密钥写进 ~/.dsh/.env。
  DSH 能走 Responses、Chat Completions、Anthropic Messages 三种接口：测试连接时按这个顺序试，哪种通就记哪种。
改文件之前各留一份备份（*.super-aide.bak），只改这几项，别的设置和注释原样保留。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import tr
from . import dshconf, winenv
from .detect import NAMES, Places, Report, claude_dir, codex_dir, dsh_desktop, dsh_dir

log = logging.getLogger(__name__)

CODEX_PROVIDER = "super_aide"
CODEX_KEY_ENV = "SUPER_AIDE_CODEX_API_KEY"  # 以前放密钥的用户环境变量：保存时顺手删掉
PROBE_TIMEOUT = 30  # 服务列不出模型时，用你填的模型真发一个很小的请求，最多等这么久（秒）
#: 流式回答里看得出成败的事件：模型开始写了算成；报错、失败算不成。只看到"开始了"不算：
#: 实测有的中转先回 response.created，过几秒才发 error（服务器过载）
STREAM_OK = ("response.output_item.added", "response.content_part.added", "response.output_text.delta",
             "response.reasoning_summary_text.delta", "response.completed")
STREAM_FAILED = ("error", "response.failed", "response.incomplete")
STREAM_ERROR = 599  # _post 用它表示"流里报了错"
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
    api: str = ""           # 走通的接口（给 DSH 的自定义服务用）：openai-responses | openai-completions | anthropic-messages
    fatal: bool = False     # 密钥不对、连不上：换哪种接口都一样
    missing: bool = False   # 这个地址上没有这种接口（404、405）：换一种接口试


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


def _open(req: urllib.request.Request, timeout: float):
    """打开请求；连接刚连上就被掐断（中转服务偶尔这样，比如 SSL 握手时断开）就隔半秒再试一次，超时不重试。"""
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
            raise
        time.sleep(0.5)
        return urllib.request.urlopen(req, timeout=timeout)


def _list(url: str, headers: dict[str, str], timeout: float) -> Check:
    req = urllib.request.Request(url, headers={**headers, "User-Agent": "super-aide-setup"})
    try:
        with _open(req, timeout) as resp:
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


def _read_stream(resp, deadline: float) -> tuple[int, str]:
    """一行行读流式回答，读到第一个看得出成败的事件就停（不等它写完）。"""
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if line.startswith("data:"):
            try:
                event = json.loads(line[5:])
            except ValueError:
                event = {}
            kind = str(event.get("type", "")) if isinstance(event, dict) else ""
            if kind in STREAM_FAILED:
                error = event.get("error") or (event.get("response") or {}).get("error") or {}
                return STREAM_ERROR, json.dumps(error, ensure_ascii=False)
            if kind in STREAM_OK:
                return resp.status, kind
        if time.monotonic() > deadline:
            break
    return -1, ""  # 开了头却一直等不到结果：当没回应


def _post(url: str, headers: dict[str, str], body: dict, timeout: float) -> tuple[int, str]:
    """发一个 JSON 请求，返回 (状态码, 响应开头)。连不上是 (0, 原因)，超时是 (-1, "")，流里报了错是 (STREAM_ERROR, 错误)。"""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        **headers, "Content-Type": "application/json", "User-Agent": "super-aide-setup"})
    try:
        with _open(req, timeout) as resp:
            if "event-stream" in (resp.headers.get("Content-Type") or ""):
                return _read_stream(resp, time.monotonic() + timeout)
            return resp.status, resp.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            text = e.read(2000).decode("utf-8", "replace")
        except OSError:
            text = ""
        return e.code, text
    except TimeoutError:
        return -1, ""
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        reason = getattr(e, "reason", e)
        return (-1, "") if isinstance(reason, TimeoutError) else (0, str(reason))


def _probe(url: str, headers: dict[str, str], body: dict, model: str, timeout: float) -> Check:
    """用你填的模型真发一个很小的请求：密钥、地址、模型都对才算过（服务列不出模型时只能这样确认）。"""
    code, text = _post(url, headers, body, timeout)
    if 200 <= code < 300:
        return Check(True, tr("连接成功，{model} 能用", model=model), [model], True)
    if code == STREAM_ERROR:
        try:
            error = json.loads(text) if text else {}
        except ValueError:
            error = {}
        error = error if isinstance(error, dict) else {}
        reason = " ".join(str(error.get("message") or text or "-").split())[:160]
        kind = error.get("code") or error.get("type") or ""
        return Check(False, tr("用 {model} 试了一下，服务报错：{reason}", model=model,
                               reason=f"{reason}（{kind}）" if kind else reason))
    if code in (401, 403):
        return Check(False, tr("密钥不对（服务地址返回 {code}）", code=code), fatal=True)
    if code in (404, 405):
        return Check(False, missing=True, message=tr("这个地址上没有对应的接口（返回 {code}），请检查地址", code=code))
    if code == -1:
        return Check(False, tr("用 {model} 试了 {seconds} 秒没有回应：这个服务可能没有这个模型，或者地址不对",
                               model=model, seconds=int(timeout)))
    if code == 0:
        return Check(False, tr("连不上这个地址（{reason}）", reason=text), fatal=True)
    detail = " ".join(text.split())[:160]
    if code in (400, 422) and "model" in text.lower():
        return Check(False, tr("这个服务好像没有模型 {model}（返回 {code}：{detail}）", model=model, code=code, detail=detail))
    return Check(False, tr("服务地址返回 {code}：{detail}", code=code, detail=detail or "-"))


def probe_openai(base: str, key: str, model: str, timeout: float = PROBE_TIMEOUT) -> Check:
    """和 Codex 一样走 Responses 接口、流式。"""
    root = openai_base(base) or OPENAI_OFFICIAL
    return _probe(f"{root}/responses", {"Authorization": f"Bearer {key}"},
                  {"model": model, "input": "ping", "stream": True}, model, timeout)


def probe_claude(base: str, key: str, model: str, timeout: float = PROBE_TIMEOUT) -> Check:
    root = claude_base(base) or CLAUDE_OFFICIAL
    return _probe(f"{root}/v1/messages", {"x-api-key": key, "Authorization": f"Bearer {key}",
                                          "anthropic-version": "2023-06-01"},
                  {"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": "ping"}]}, model, timeout)


def probe_chat(base: str, key: str, model: str, timeout: float = PROBE_TIMEOUT) -> Check:
    """Chat Completions 接口（不流式：流里的每一块没有 type，看不出成败）。"""
    root = openai_base(base) or OPENAI_OFFICIAL
    return _probe(f"{root}/chat/completions", {"Authorization": f"Bearer {key}"},
                  {"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": "ping"}]}, model, timeout)


def models_of(text: str) -> list[str]:
    """模型那一栏：可以填几个，用逗号（中英文都行）或空格隔开。"""
    return list(dict.fromkeys(m for m in re.split(r"[,，;；\s]+", text or "") if m))


def check_route(base: str, key: str, model: str, timeout: float = PROBE_TIMEOUT) -> Check:
    """给 DSH 用的自定义服务：用第一个模型按 Responses → Chat Completions → Anthropic Messages 的顺序试，
    哪种接口通就记下哪种。密钥不对的话哪种都一样，不再往下试。"""
    first = models_of(model)[:1]
    if not first:
        return Check(False, tr("请在“模型”里填这个服务提供的模型（可以填几个，用逗号隔开）"))
    failed: Check | None = None
    for api, probe in (("openai-responses", probe_openai), ("openai-completions", probe_chat),
                       ("anthropic-messages", probe_claude)):
        result = probe(base, key, first[0], timeout)
        if result.ok:
            result.api = api
            return result
        if result.fatal:
            return result
        if failed is None or (failed.missing and not result.missing):
            failed = result  # 说的最有用的那个：有这种接口、但模型不对，比"没有这种接口"更说明问题
    return failed


def check(tool: str, base: str, key: str, model: str = "") -> Check:
    """测试连接：先列模型；列不出来（不少中转服务不支持）或者你填的模型不在里面，就用你填的模型真发一个很小的请求。
    Codex 列不出模型时一定要填模型：Codex 原来的默认模型多半是上一个服务商的，换过来就用不了。"""
    key, model = key.strip(), model.strip()
    if not key:
        return Check(False, tr("请填写密钥"))
    if tool == "dsh":
        if base.strip():
            return check_route(base, key, model)
        return check_openai(DEEPSEEK_OFFICIAL, key)  # DeepSeek 官方 API 的模型列表
    listed = check_claude(base, key) if tool == "claude" else check_openai(base, key)
    if listed.verified and (not model or model in listed.models):
        return listed
    if model:
        probe = probe_claude(base, key, model) if tool == "claude" else probe_openai(base, key, model)
        if probe.ok or not listed.verified:
            return probe
        sample = tr("、").join(listed.models[:8])
        return Check(False, tr("{problem}。这个服务提供的有：{models}", problem=probe.message, models=sample))
    if listed.ok and tool == "codex":
        return Check(False, tr("这个服务没法列出模型：请在“模型”里填一个它提供的模型（看服务商的说明或请求示例），"
                               "再点测试并保存"))
    return listed  # 连不上、密钥不对；或者 Claude 列不出模型（Claude Code 会用它自己的默认模型）


# ---------- 自定义服务地址：写配置 ----------

def save(tool: str, base: str, key: str, model: str = "", places: Places | None = None,
         offered: list[str] | None = None, api: str = "") -> tuple[str, str]:
    """写进工具自己的配置。offered：服务列出来的模型（列不出来就是空）；api：DSH 的自定义服务走通的接口。
    返回 (实际用的默认模型, 换掉的原默认模型)：你没填、原来的默认模型这个服务又不提供时，会换成它提供的最强的那个。
    DSH 填了几个模型时，"实际用的"是逗号隔开的这几个。"""
    p = places or Places.current()
    key, model = key.strip(), model.strip()
    if not key:
        raise ConfigError(tr("请填写密钥"))
    if tool == "claude":
        save_claude(claude_dir(p) / "settings.json", base, key, model)
        return model, ""
    if tool == "dsh":
        return save_dsh(dsh_dir(p), base, key, model, api)
    return save_codex(codex_dir(p) / "config.toml", base, key, model, offered or [])


def save_dsh(home: Path, base: str, key: str, model: str = "", api: str = "") -> tuple[str, str]:
    """没填服务地址：DeepSeek 官方 API Key（DSH 的 deepseek-official 从 DEEPSEEK_API_KEY 取），默认模型原来是我们写的
    自定义服务的话改回官方的。填了：写进 DSH 的模型设置（路由 super-aide + 默认模型），密钥写进 ~/.dsh/.env。"""
    try:
        if not base.strip():
            winenv.set_user_env("DEEPSEEK_API_KEY", key)
            from ..engines.dsh import MODELS

            dshconf.use_builtin(home, "deepseek-official", MODELS[0]["id"])
            return "", ""
        models = models_of(model)
        root = claude_base(base) if api == "anthropic-messages" else openai_base(base)
        dshconf.save_route(home, root, dshconf.KEY_ENV, api or "openai-responses", models)
        dshconf.set_env(home / ".env", dshconf.KEY_ENV, key)
    except (dshconf.DshConfigError, OSError) as e:
        raise ConfigError(tr("没法自动修改 {path}（{error}），请在 DeepSeek Harness 的模型设置里手动添加",
                             path=dshconf.patch_path(home), error=e)) from e
    return ",".join(models), ""


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


def save_codex(path: Path, base: str, key: str, model: str = "", offered: list[str] | None = None) -> tuple[str, str]:
    """返回 (实际用的默认模型, 换掉的原默认模型)，见 save。"""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    root = openai_base(base)
    official = not root or root == OPENAI_OFFICIAL
    replaced = ""
    if not model and offered:
        try:
            current = str(tomllib.loads(text).get("model") or "") if text else ""
        except tomllib.TOMLDecodeError:
            current = ""
        if current not in offered:  # 原来的默认模型是上一个服务商的：换成这个服务提供的最强的那个
            from .flow import strongest

            model, replaced = strongest("codex", offered), current
    if official:
        text = set_top_key(text, "model_provider", "openai")
    else:
        text = set_top_key(text, "model_provider", CODEX_PROVIDER)
        text = replace_table(text, f"model_providers.{CODEX_PROVIDER}", (
            f"[model_providers.{CODEX_PROVIDER}]\n"
            'name = "Custom"\n'
            f"base_url = {json.dumps(root)}\n"
            f"experimental_bearer_token = {json.dumps(key)}\n"
            'wire_api = "responses"\n'))
    if model:
        text = set_top_key(text, "model", model)
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(tr("没法自动修改 {path}（{error}），请手动配置", path=path, error=e)) from e
    if official:
        _login_api_key(key)
    _backup(path)
    _write(path, text)
    if not official:
        winenv.delete_user_env(CODEX_KEY_ENV)  # 以前版本放密钥的环境变量：密钥已经在配置里了
    return model, replaced


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
