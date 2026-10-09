"""检查更新、更新（设置 → 通用 → 版本）。

- 最新版本：GitHub 的最新发布 → PyPI → 国内镜像（阿里云），哪个先答上用哪个；国内连不上 GitHub 也能查到。
- 更新交给安装器（SuperAideSetup.exe /update）：Super Aide 自己正在运行，文件被占着没法替换自己。
  安装器先等 Super Aide 退出，再下载、安装新版本，装好重新打开。安装器优先用 GitHub 上最新的，下不到就用
  安装时留在 %LOCALAPPDATA%\\Programs\\Super Aide 里的那一份。
- 从源码装的（scripts/install.ps1、开发时直接运行）没有发布信息：只能查，不自动更新，用 install.cmd 更新。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .i18n import tr

PACKAGE = "super-aide"
RELEASE_DIR = Path(__file__).resolve().parent / "_release"
INSTALLER = "SuperAideSetup.exe"
MIRROR = "https://mirrors.aliyun.com/pypi/simple"
TIMEOUT = 8
#: 自我改进装上的本地版本带 "+aide.N"（PEP 440 的本地版本号）：比较时只看前面的官方版本
_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)(?:\+[0-9A-Za-z.]+)?$")
_LOCAL = re.compile(r"\+aide\.(\d+)$")
_WHEEL = re.compile(r"super_aide-(\d+(?:\.\d+)*)-py3-none-any\.whl")


class UpdateError(Exception):
    pass


@dataclass
class Release:
    version: str
    source: str                      # GitHub | PyPI | 阿里云镜像
    installer_url: str = ""          # GitHub 上这个版本的安装器
    notes_url: str = ""


@dataclass
class Check:
    current: str
    latest: str = ""
    newer: bool = False
    source: str = ""
    error: str = ""
    managed: bool = True             # 是安装器装的发布版（能自动更新）
    release: Release | None = field(default=None, repr=False)

    def as_dict(self) -> dict:
        return {"current": self.current, "latest": self.latest, "newer": self.newer, "source": self.source,
                "error": self.error, "managed": self.managed,
                "notes_url": self.release.notes_url if self.release else ""}


def release_info() -> dict:
    """发版时随包写进去的信息（scripts/release/prepare.py）：版本、GitHub 仓库。从源码装的没有。"""
    try:
        return json.loads((RELEASE_DIR / "release.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def parse(version: str) -> tuple[int, ...] | None:
    """"0.2.0" / "v0.2.0" / "0.2.0+aide.3" → (0, 2, 0)。预发布版（0.2.0rc1 之类）不认：只提示正式版。"""
    m = _VERSION.match(version.strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def base_version(version: str) -> str:
    """"0.2.0+aide.3" → "0.2.0"：自我改进前的官方版本。"""
    return version.split("+", 1)[0]


def evolved_count(version: str) -> int:
    """在官方版本上自我改进了几次（"0.2.0+aide.3" → 3）。"""
    m = _LOCAL.search(version)
    return int(m.group(1)) if m else 0


def is_newer(latest: str, current: str) -> bool:
    a, b = parse(latest), parse(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def _get(url: str, timeout: float = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"super-aide/{__version__}",
                                               "Accept": "application/json, text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def from_github(repo: str) -> Release:
    data = json.loads(_get(f"https://api.github.com/repos/{repo}/releases/latest"))
    version = str(data.get("tag_name", "")).lstrip("v")
    if parse(version) is None:
        raise UpdateError(tr("GitHub 上最新发布的版本号看不懂：{tag}", tag=data.get("tag_name")))
    url = next((a.get("browser_download_url", "") for a in data.get("assets") or []
                if a.get("name") == INSTALLER), "")
    return Release(version, "GitHub", url, str(data.get("html_url", "")))


def from_pypi() -> Release:
    data = json.loads(_get(f"https://pypi.org/pypi/{PACKAGE}/json"))
    return Release(str(data["info"]["version"]), "PyPI")


def from_mirror(index: str = MIRROR) -> Release:
    page = _get(f"{index}/{PACKAGE}/").decode("utf-8", "replace")
    versions = [v for v in _WHEEL.findall(page) if parse(v) is not None]
    if not versions:
        raise UpdateError(tr("镜像里还没有超级助手"))
    return Release(max(versions, key=parse), tr("阿里云镜像"))


def latest(repo: str = "") -> Release:
    """问一圈：GitHub → PyPI → 国内镜像。都问不到就报错（附上原因）。"""
    errors = []
    sources = ([lambda: from_github(repo)] if repo else []) + [from_pypi, from_mirror]
    for source in sources:
        try:
            return source()
        except Exception as e:  # noqa: BLE001 - 换下一个来源
            errors.append(str(getattr(e, "reason", e)) or type(e).__name__)
    raise UpdateError(tr("连不上更新服务器（{reasons}）", reasons="; ".join(errors[-2:])))


def check() -> Check:
    info = release_info()
    result = Check(current=__version__, managed=bool(info))
    try:
        release = latest(str(info.get("repo", "")))
    except UpdateError as e:
        result.error = str(e)
        return result
    result.latest, result.source, result.release = release.version, release.source, release
    result.newer = is_newer(release.version, __version__)
    return result


def installer_path() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local / "Programs" / "Super Aide" / INSTALLER


def start_update(release: Release | None) -> None:
    """把更新交给安装器，然后由调用方退出 Super Aide。优先下载 GitHub 上最新的安装器，下不到用本机那一份。"""
    exe = installer_path()
    if release is not None and release.installer_url:
        target = Path(tempfile.gettempdir()) / f"SuperAideSetup-{release.version}.exe"
        try:
            target.write_bytes(_get(release.installer_url, timeout=60))
            exe = target
        except Exception:  # noqa: BLE001 - 用本机那一份
            pass
    if not exe.exists():
        raise UpdateError(tr("没找到安装器：请到发布页下载最新的 SuperAideSetup.exe 运行"))
    subprocess.Popen([str(exe), "/update", "/pid", str(os.getpid())], close_fds=True)
