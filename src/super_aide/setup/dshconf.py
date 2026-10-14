"""DeepSeek Harness（DSH）自己的模型配置。Super Aide 用 DSH 时照它的设置来，和 Claude Code、Codex 一样。

DSH 桌面版的"模型"设置写在 ~/.dsh/profiles/desktop/cordis.patch.yml（一个 YAML 列表，每项按 id 改一个插件的配置）：
- agent-default-model：默认用哪个服务商路由（provider）和模型（model）；
- llm-pi-ai：自定义的服务（providers 下每个路由：apiKeyEnv、api 接口类型、baseURL、models 模型清单）。
  密钥不写在这里：apiKeyEnv 只是个名字，值在 ~/.dsh/.credentials.yaml 的 refs、~/.dsh/.env 或环境变量里。

Super Aide 以 `dsh --profile acp` 运行 DSH，那个配置里没有这些：默认路由是自定义的服务时，把 llm-pi-ai 那一项原样带上
（见 engines/dsh.py 的 patch_text）。准备窗口里填的自定义服务地址也写到这里（路由名 super-aide，密钥写进 ~/.dsh/.env），
DSH 桌面版里看得到、改得了，效果和在 DSH 里自己配的一样。

不引入 YAML 库：DSH 写的这个文件是块状的 YAML，按缩进找到要的几行就够了；我们写的路由用一行 JSON（也是合法的 YAML）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROUTE = "super-aide"                 # 准备窗口里填的自定义服务地址：DSH 里的路由名
KEY_ENV = "SUPER_AIDE_DSH_API_KEY"   # 它的密钥在 ~/.dsh/.env 里的名字
BUILTIN = ("deepseek-account", "deepseek-official")  # DSH 自带的服务商路由（不是自定义的）
PI_AI = "@deepseek-ai/dsh-llm-pi-ai"
DEFAULT_MODEL = "@deepseek-ai/dsh-agent-default-model"
HEADER = ("# Your patch layer for this dsh profile, applied after every bundle layer:\n"
          "# a top-level YAML array of loader patch entries (id-targeted config\n"
          "# overrides, disables, and insert lists; `!!js` expressions allowed).\n")

_KEY = re.compile(r"^(\s*)(-\s+)?([\w.@/-]+|\"[^\"]*\"|'[^']*'):\s*(.*?)\s*$")


class DshConfigError(Exception):
    pass


@dataclass
class Route:
    provider: str = ""        # 默认用的服务商路由
    model: str = ""           # 默认模型
    custom: bool = False      # 是 llm-pi-ai 里自定义的路由
    block: str = ""           # llm-pi-ai 那一项的原文：带进 ACP 的配置
    base: str = ""            # 自定义路由的服务地址
    key_env: str = ""         # 自定义路由的密钥名字（apiKeyEnv）
    models: tuple[str, ...] = field(default_factory=tuple)  # 自定义路由的模型清单


def patch_path(home: Path) -> Path:
    return home / "profiles" / "desktop" / "cordis.patch.yml"


def _scalar(value: str) -> str:
    """YAML 的一个标量值：去掉行尾注释和引号。"""
    value = value.strip()
    if value[:1] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end] if end > 0 else value[1:]
    return value.split(" #", 1)[0].strip()


def _editable(head: list[str]) -> None:
    """开头除了注释还有别的（比如写成了一行的列表）：不是 DSH 写的那种格式，不硬改。"""
    if any(x.strip() and not x.lstrip().startswith("#") for x in head):
        raise DshConfigError("format")


def split_items(text: str) -> tuple[list[str], list[list[str]]]:
    """→ (开头的注释行, 每一项的行)。顶层每一项从第 0 列的 "- " 开始。"""
    head: list[str] = []
    items: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith("- ") or line == "-":
            items.append([line])
        elif items:
            items[-1].append(line)
        elif line.strip() != "[]":
            head.append(line)
    return head, items


def item_field(item: list[str], name: str) -> str:
    """一项本身的 id、name（"- id: x" 或者两格缩进的 "  name: x"）。"""
    for line in item:
        m = _KEY.match(line)
        if m and m.group(3) == name and ((m.group(2) and not m.group(1)) or (not m.group(2) and len(m.group(1)) == 2)):
            return _scalar(m.group(4))
    return ""


def _find(items: list[list[str]], item_id: str, name: str) -> int:
    return next((i for i, item in enumerate(items) if item_field(item, "id") == item_id
                 or item_field(item, "name") == name), -1)


def _config(item: list[str]) -> tuple[int, int, int, bool]:
    """一项里的 config：→ (config 那一行, 这一段到哪儿为止, 下一层的缩进, 是不是写成了一行)。
    缩进照文件里的来（DSH 写的是两格，手改的可能是四格）；没有 config 是 (-1, -1, 4, False)。"""
    for i, line in enumerate(item):
        m = _KEY.match(line)
        if not (m and not m.group(2) and m.group(3) == "config" and len(m.group(1)) == 2):
            continue
        inline = bool(m.group(4)) and not m.group(4).startswith("#")
        end, depth = len(item), 0
        for j in range(i + 1, len(item)):
            x = item[j]
            if not x.strip() or x.lstrip().startswith("#"):
                continue
            d = len(x) - len(x.lstrip())
            if d <= 2:
                end = j
                break
            depth = depth or d
        return i, end, depth or 4, inline
    return -1, -1, 4, False


def _config_value(item: list[str], key: str) -> str:
    """config 下一层的一个值（agent-default-model 的 provider、model）。"""
    start, end, depth, inline = _config(item)
    if start < 0 or inline:
        return ""
    for line in item[start + 1:end]:
        m = _KEY.match(line)
        if m and not m.group(2) and m.group(3) == key and len(m.group(1)) == depth:
            return _scalar(m.group(4))
    return ""


def _providers(item: list[str]) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """llm-pi-ai 里 providers 这一段：→ (providers 那一行, 路由的缩进, {路由名: (起, 止)})；没有是 (-1, 0, {})。"""
    start = next((i for i, line in enumerate(item) if re.match(r"^\s+providers:\s*(#.*)?$", line)), -1)
    if start < 0:
        return -1, 0, {}
    outer = len(item[start]) - len(item[start].lstrip())
    routes: dict[str, tuple[int, int]] = {}
    indent, current = 0, ""
    for i in range(start + 1, len(item)):
        line = item[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        depth = len(line) - len(line.lstrip())
        if depth <= outer:
            break
        if not indent:
            indent = depth
        if depth == indent:
            m = _KEY.match(line)
            current = _scalar(m.group(3)) if m else ""
            if current:
                routes[current] = (i, i + 1)
        elif current:
            routes[current] = (routes[current][0], i + 1)
    return start, indent or outer + 2, routes


def _route_info(lines: list[str]) -> tuple[str, str, list[str]]:
    """一个路由的 (baseURL, apiKeyEnv, 模型)。块状写法或者一行 JSON 都认。"""
    first = _KEY.match(lines[0])
    inline = first.group(4) if first else ""
    if inline.startswith("{"):
        try:
            data = json.loads(inline)
        except ValueError:
            data = {}
        models = [str(m.get("id") if isinstance(m, dict) else m) for m in data.get("models") or []]
        return str(data.get("baseURL") or ""), str(data.get("apiKeyEnv") or ""), models
    base = key = ""
    models: list[str] = []
    models_at = entry_at = -1  # "models:" 那一行的缩进、正在读的那个模型（"- "）的缩进
    for line in lines[1:]:
        m = _KEY.match(line)
        if not m:
            continue
        depth, dash, name, value = len(m.group(1)), bool(m.group(2)), _scalar(m.group(3)), m.group(4)
        if models_at >= 0 and depth <= models_at and not dash:
            models_at = -1  # models 那一段完了
        if models_at >= 0:
            if dash:
                entry_at = depth
            if name == "id" and (dash or depth == entry_at + 2):
                models.append(_scalar(value))
        elif name == "models" and not dash:
            models_at = depth
        elif name == "baseURL":
            base = _scalar(value)
        elif name == "apiKeyEnv":
            key = _scalar(value)
    return base, key, models


def read(home: Path) -> Route:
    """DSH 现在默认用哪个服务、哪个模型。没配过（或者读不了）是空的 Route。"""
    try:
        text = patch_path(home).read_text(encoding="utf-8")
    except OSError:
        return Route()
    _head, items = split_items(text)
    at = _find(items, "agent-default-model", DEFAULT_MODEL)
    if at < 0:
        return Route()
    route = Route(provider=_config_value(items[at], "provider"), model=_config_value(items[at], "model"))
    pi = _find(items, "llm-pi-ai", PI_AI)
    if route.provider and route.provider not in BUILTIN and pi >= 0:
        _start, _indent, routes = _providers(items[pi])
        if route.provider in routes:
            a, b = routes[route.provider]
            base, key, models = _route_info(items[pi][a:b])
            route.custom, route.base, route.key_env = True, base, key
            route.models = tuple(dict.fromkeys(([route.model] if route.model else []) + models))
            route.block = "\n".join(items[pi]).rstrip() + "\n"
    return route


def save_route(home: Path, base: str, key_env: str, api: str, models: list[str]) -> None:
    """把自定义服务地址写进 DSH 的模型设置：llm-pi-ai 里加（或换掉）路由 super-aide，默认模型设成它的第一个模型。
    别的路由、别的设置和注释原样保留；改之前留一份备份（*.super-aide.bak）。"""
    if not models:
        raise DshConfigError("没有模型")
    entry = {"displayName": "Super Aide", "apiKeyEnv": key_env, "api": api, "baseURL": base,
             "models": [{"id": m} for m in models]}
    path = patch_path(home)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    head, items = split_items(text)
    _editable(head)
    pi = _find(items, "llm-pi-ai", PI_AI)
    line = json.dumps(entry, ensure_ascii=False)
    if pi < 0:
        items.append(["- id: llm-pi-ai", f"  name: {json.dumps(PI_AI)}", "  config:", "    providers:",
                      f"      {ROUTE}: {line}"])
    else:
        item = items[pi]
        start, indent, routes = _providers(item)
        if start < 0:
            config, _end, depth, inline = _config(item)
            # providers 或 config 写成了一行（{} 之类）：不硬改
            if inline or any(re.match(r"^\s+providers:", x) for x in item):
                raise DshConfigError("providers")
            if config < 0:
                item += ["  config:"]
                config, depth = len(item) - 1, 4
            item[config + 1:config + 1] = [f"{' ' * depth}providers:", f"{' ' * (depth + 2)}{ROUTE}: {line}"]
        else:
            new = f"{' ' * indent}{ROUTE}: {line}"
            if ROUTE in routes:
                a, b = routes[ROUTE]
                item[a:b] = [new]
            else:
                item.insert(start + 1, new)
    _set_default(items, ROUTE, models[0])
    _write(path, head, items)


def use_builtin(home: Path, provider: str, model: str) -> None:
    """改回 DSH 自带的服务（DeepSeek 官方 API Key）：只在默认用的是我们写的路由时才改默认模型。"""
    path = patch_path(home)
    if read(home).provider != ROUTE:
        return
    head, items = split_items(path.read_text(encoding="utf-8"))
    _editable(head)
    _set_default(items, provider, model)
    _write(path, head, items)


def _set_default(items: list[list[str]], provider: str, model: str) -> None:
    at = _find(items, "agent-default-model", DEFAULT_MODEL)
    if at < 0:
        items.insert(0, ["- id: agent-default-model", f"  name: {json.dumps(DEFAULT_MODEL)}", "  config:",
                         f"    provider: {json.dumps(provider)}", f"    model: {json.dumps(model)}"])
        return
    item = items[at]
    start, end, depth, inline = _config(item)
    if inline:
        raise DshConfigError("config")  # 写成了一行：不硬改
    if start < 0:
        item.append("  config:")
        start, end, depth = len(item) - 1, len(item), 4
    for key, value in (("provider", provider), ("model", model)):
        row = next((i for i in range(start + 1, end) if (m := _KEY.match(item[i])) and not m.group(2)
                    and m.group(3) == key and len(m.group(1)) == depth), -1)
        if row >= 0:
            item[row] = f"{' ' * depth}{key}: {json.dumps(value)}"
        else:
            item.insert(start + 1, f"{' ' * depth}{key}: {json.dumps(value)}")
            end += 1


def _write(path: Path, head: list[str], items: list[list[str]]) -> None:
    lines = head if head else HEADER.rstrip("\n").splitlines()
    text = "\n".join(lines + [x for item in items for x in item]).rstrip("\n") + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.with_name(path.name + ".super-aide.bak").write_bytes(path.read_bytes())
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def set_env(path: Path, name: str, value: str) -> None:
    """~/.dsh/.env 里设一个值（有就换掉，别的行原样保留）。DSH 按名字从这里取密钥。"""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    quoted = value if re.fullmatch(r"[\w.:/+=@-]*", value) else json.dumps(value)
    entry = f"{name}={quoted}"
    pattern = re.compile(rf"^\s*(export\s+)?{re.escape(name)}\s*=")
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = entry
            break
    else:
        lines.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
