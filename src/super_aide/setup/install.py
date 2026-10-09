"""安装 Claude Code 和 Codex：用官方的 npm 包，官方源连不上或者装失败时，自动换国内镜像再装。

- 需要 Node.js 22 以上（Claude Code 的要求）。没有、或者版本太旧：先装一个便携版 Node.js
  （Node.js 官网 → 国内镜像，校验 SHA-256），放在 %LOCALAPPDATA%\\Programs\\node 并加进用户 PATH，
  Claude Code、Codex 也装在它下面。你自己装的 Node.js 不动。
- 每个源先花几秒探一下通不通，不通的直接跳过，不在连不上的源上干等。
- 装完把命令所在的目录加进用户 PATH（还不在的话），新开的命令行窗口里就能用 claude、codex。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ..i18n import tr
from . import winenv
from .detect import Places

log = logging.getLogger(__name__)

PACKAGES = {"claude": "@anthropic-ai/claude-code", "codex": "@openai/codex"}
REGISTRIES = (("官方源", "https://registry.npmjs.org"), ("国内镜像 npmmirror", "https://registry.npmmirror.com"))
NODE_DISTS = (("Node.js 官网", "https://nodejs.org/dist"),
              ("国内镜像 npmmirror", "https://registry.npmmirror.com/-/binary/node"))
NODE_MIN = 22
MARKER = ".installed-by-super-aide"  # 便携版 Node.js 是我们装的：以后可以放心覆盖
INSTALL_TIMEOUT = 20 * 60  # Claude Code 的 Windows 包两百多 MB，镜像慢的时候要好几分钟
PROBE_TIMEOUT = 6
#: npm 的报错码 → 一句人话
NPM_CODES = {
    "ETIMEDOUT": "连接超时", "ECONNRESET": "连接被重置", "ECONNREFUSED": "连接被拒绝", "ENOTFOUND": "找不到服务器",
    "EAI_AGAIN": "域名解析失败", "CERT_HAS_EXPIRED": "证书有问题", "UNABLE_TO_GET_ISSUER_CERT_LOCALLY": "证书有问题",
    "EPERM": "没有写入权限", "EACCES": "没有写入权限", "EBUSY": "文件被占用（先关掉正在运行的 {}）",
}

Progress = Callable[[str, str], None]  # (工具, 一行状态)


class InstallError(Exception):
    pass


@dataclass
class Npm:
    node: Path
    command: list[str]   # 运行 npm 的命令前缀
    prefix: Path | None  # 全局安装目录。None = 沿用你自己的 npm 设置


def node_dir() -> Path:
    return Places.current().local / "Programs" / "node"


def install(tools: list[str], progress: Progress) -> dict[str, str]:
    """装好这些工具（claude / codex）。→ {工具: 没装上的原因}，装好的是空字符串。阻塞调用，放在后台跑。"""

    def say(text: str) -> None:
        for tool in tools:
            progress(tool, text)

    try:
        npm = ensure_node(say)
    except InstallError as e:
        return {tool: str(e) for tool in tools}
    say(tr("正在挑一个连得上的下载源…"))
    registries = _reachable(REGISTRIES, "/-/ping")
    proxy = _system_proxy()
    for tool in tools[1:]:
        progress(tool, tr("排队中，等前一个装完…"))
    errors = {tool: _install_one(npm, tool, registries, proxy, progress) for tool in tools}
    if any(not e for e in errors.values()):
        bindir = _bin_dir(npm)
        if bindir is not None:
            try:
                winenv.add_user_path(bindir)
            except OSError as e:
                log.warning("没能把 %s 加进 PATH：%s", bindir, e)
    return errors


# ---------- npm ----------

def _install_one(npm: Npm, tool: str, registries: list[tuple[str, str]], proxy: str, progress: Progress) -> str:
    package = PACKAGES[tool]
    reason = ""
    for i, (label, url) in enumerate(registries):
        progress(tool, tr("正在从{source}安装…", source=tr(label)) if i == 0
                 else tr("{reason}，换{source}再装…", reason=reason, source=tr(label)))
        ok, reason = _npm_install(npm, package, url, proxy if url == REGISTRIES[0][1] else "", tool)
        if not ok and reason == tr(NPM_CODES["EPERM"]) and npm.prefix is None:
            # 全局目录在需要管理员权限的地方：改装到你自己的 %APPDATA%\npm
            npm.prefix = Places.current().roaming / "npm"
            ok, reason = _npm_install(npm, package, url, proxy if url == REGISTRIES[0][1] else "", tool)
        if ok:
            version = command_version(_bin_dir(npm), tool)
            if version:
                progress(tool, tr("已安装 {version}", version=version))
                return ""
            reason = tr("装完了却找不到命令")
        log.warning("从 %s 安装 %s 失败：%s", url, package, reason)
    return tr("没装上：{reason}", reason=reason) if reason else tr("没装上")


def _npm_install(npm: Npm, package: str, registry: str, proxy: str, tool: str) -> tuple[bool, str]:
    cmd = npm.command + ["install", "--global", f"{package}@latest", f"--registry={registry}", "--no-fund",
                         "--no-audit", "--loglevel=error", "--fetch-timeout=60000", "--fetch-retries=1"]
    if npm.prefix is not None:
        cmd.append(f"--prefix={npm.prefix}")
    if proxy:
        cmd += [f"--proxy={proxy}", f"--https-proxy={proxy}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=INSTALL_TIMEOUT, env=_npm_env(npm))
    except subprocess.TimeoutExpired:
        return False, tr("安装超时")
    except OSError as e:
        return False, tr("npm 运行不了（{error}）", error=e)
    if result.returncode == 0:
        return True, ""
    return False, npm_error(result.stderr or result.stdout, tool)


def _npm_env(npm: Npm) -> dict[str, str]:
    """安装脚本（postinstall）要找得到这个 node。"""
    return {**os.environ, "PATH": f"{npm.node.parent}{os.pathsep}{os.environ.get('PATH', '')}",
            "npm_config_update_notifier": "false"}


def npm_error(output: str, tool: str = "") -> str:
    """从 npm 的输出里挑出最能说明问题的一句。"""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in lines:
        if line.startswith(("npm error code ", "npm ERR! code ")):
            code = line.split()[-1]
            if code in NPM_CODES:
                return tr(NPM_CODES[code]).format({"claude": "Claude Code", "codex": "Codex"}.get(tool, tr("它")))
    noise = ("A complete log", "Log files were not written", "code ", "errno ", "syscall ", "path ", "dest ")
    useful = [line.split(" ", 2)[-1] for line in lines
              if line.startswith(("npm error", "npm ERR!")) and not line.split(" ", 2)[-1].startswith(noise)]
    text = useful[0] if useful else (lines[-1] if lines else tr("原因不明"))
    return text if len(text) <= 120 else text[:119] + "…"


def _bin_dir(npm: Npm) -> Path | None:
    """全局安装的命令放在哪（Windows 上就是全局目录本身）。"""
    if npm.prefix is not None:
        return npm.prefix
    try:
        out = subprocess.run(npm.command + ["prefix", "--global"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60, env=_npm_env(npm)).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(out.splitlines()[-1]) if out else None


def command_version(bindir: Path | None, tool: str) -> str:
    """运行一下装好的命令（--version），能跑起来才算装好。"""
    candidates = [bindir / f"{tool}.cmd", bindir / f"{tool}.exe"] if bindir else []
    found = shutil.which(tool)
    if found:
        candidates.append(Path(found))
    for exe in candidates:
        if not exe.exists():
            continue
        try:
            out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=90).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out:
            return out.splitlines()[0].replace("(Claude Code)", "").replace("codex-cli", "").strip()
    return ""


# ---------- Node.js ----------

def ensure_node(say: Callable[[str], None]) -> Npm:
    found = find_node()
    if found is not None:
        return found
    return _portable_node(say)


def find_node() -> Npm | None:
    """先用你自己的 Node.js（够新的话），再看以前装过的便携版。"""
    portable = node_dir()
    for exe, prefix in ((shutil.which("node"), None), (str(portable / "node.exe"), portable)):
        if exe and Path(exe).exists() and _node_major(exe) >= NODE_MIN:
            try:
                return Npm(Path(exe), _npm_command(Path(exe)), prefix)
            except InstallError:
                continue
    return None


def _node_major(exe: str) -> int:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        return int(out.lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


def _npm_command(node: Path) -> list[str]:
    cli = node.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if cli.exists():
        return [str(node), str(cli)]
    npm = shutil.which("npm")
    if npm:
        return [npm]
    raise InstallError(tr("找到了 Node.js，但没有 npm"))


def _portable_node(say: Callable[[str], None]) -> Npm:
    arch = "arm64" if platform.machine().upper() in ("ARM64", "AARCH64") else "x64"
    target = node_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for label, base in _reachable(NODE_DISTS, "/index.json"):
        try:
            say(tr("正在从{source}下载 Node.js（安装 Claude Code 和 Codex 需要）…", source=tr(label)))
            version = latest_lts(json.loads(_get(f"{base}/index.json")), arch)
            name = f"node-{version}-win-{arch}"
            sums = _get(f"{base}/{version}/SHASUMS256.txt").decode("utf-8", "replace")
            expected = next((line.split()[0] for line in sums.splitlines() if line.strip().endswith(f"{name}.zip")), "")
            with tempfile.TemporaryDirectory(prefix="super-aide-node-", dir=target.parent) as tmp:
                archive = Path(tmp) / f"{name}.zip"
                _download(f"{base}/{version}/{name}.zip", archive,
                          lambda pct, v=version: say(tr("正在下载 Node.js {version}…{percent}%", version=v, percent=pct)))
                if not expected or _sha256(archive) != expected.lower():
                    raise InstallError(tr("下载的文件校验不通过"))
                say(tr("正在解压 Node.js…"))
                with zipfile.ZipFile(archive) as z:
                    z.extractall(tmp)
                _replace_dir(Path(tmp) / name, target)
            (target / MARKER).write_text(version, encoding="utf-8")
            winenv.add_user_path(target)
            node = target / "node.exe"
            return Npm(node, _npm_command(node), target)
        except Exception as e:  # noqa: BLE001 - 换下一个源
            log.warning("从 %s 安装 Node.js 失败：%s", base, e)
            errors.append(f"{tr(label)}: {e}")
            say(tr("{source}没下载成功，换下一个…", source=tr(label)))
    raise InstallError(tr("没装上 Node.js（{reasons}）", reasons="; ".join(errors or [tr("下载源都连不上")])))


def latest_lts(index: list[dict], arch: str = "x64") -> str:
    """index.json 里最新的长期支持版（不低于 NODE_MIN，有 Windows 的 zip 包）。"""
    for item in index:
        version = str(item.get("version", ""))
        try:
            major = int(version.lstrip("v").split(".")[0])
        except ValueError:
            continue
        if item.get("lts") and major >= NODE_MIN and f"win-{arch}-zip" in item.get("files", []):
            return version
    raise InstallError(tr("下载源里没有合适的 Node.js 版本"))


def _replace_dir(src: Path, dst: Path) -> None:
    if dst.exists():
        if not (dst / MARKER).exists() and any(dst.iterdir()):
            raise InstallError(tr("{path} 里已经有别的东西，没有覆盖", path=dst))
        shutil.rmtree(dst)
    src.replace(dst)


# ---------- 下载 ----------

def _system_proxy() -> str:
    """系统代理（比如开着 Clash 的"系统代理"）：npm 自己不读，安装时显式传给它。"""
    proxies = urllib.request.getproxies()
    proxy = proxies.get("https") or proxies.get("http") or ""
    return proxy if "://" in proxy or not proxy else f"http://{proxy}"


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": "super-aide-setup"})


def _get(url: str, timeout: float = 30) -> bytes:
    with urllib.request.urlopen(_request(url), timeout=timeout) as resp:
        return resp.read()


def _probe(url: str) -> bool:
    try:
        with urllib.request.urlopen(_request(url), timeout=PROBE_TIMEOUT) as resp:
            resp.read(256)
        return True
    except Exception:  # noqa: BLE001
        return False


def _reachable(sources: tuple[tuple[str, str], ...], probe_path: str) -> list[tuple[str, str]]:
    """同时探一下每个源，通的按原来的先后排在前面；都不通就全试一遍（也许只是探测被拦了）。"""
    with ThreadPoolExecutor(len(sources)) as pool:
        ok = list(pool.map(lambda s: _probe(s[1] + probe_path), sources))
    found = [s for s, good in zip(sources, ok) if good]
    return found or list(sources)


def _download(url: str, path: Path, progress: Callable[[int], None]) -> None:
    with urllib.request.urlopen(_request(url), timeout=60) as resp, path.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done, shown = 0, -1
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            pct = done * 100 // total if total else 0
            if pct // 10 != shown:
                shown = pct // 10
                progress(pct)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()
