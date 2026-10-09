"""自己打 wheel（标准库 zipfile），不用 hatchling、不联网。

超级助手是纯 Python 包：wheel 就是 super_aide/ 加上 dist-info。dist-info 从已安装的那份复制，只改版本号，
所以依赖和启动入口一定和原来一样（换包时用 --no-deps，靠的就是这一点）。
"""

from __future__ import annotations

import base64
import hashlib
import re
import zipfile
from pathlib import Path

NAME = "super_aide"
#: 已安装的 dist-info 里这些是安装工具写的，不属于 wheel
INSTALLER_FILES = {"INSTALLER", "REQUESTED", "RECORD", "direct_url.json", "WHEEL", "uv_cache.json", "uv_build.json"}
WHEEL_META = "Wheel-Version: 1.0\nGenerator: super-aide-evolve\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
SKIP_DIRS = {"__pycache__"}


def _hash(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def set_version(metadata: str, version: str) -> str:
    """METADATA 里只换 Version 这一行（头部的第一处）。"""
    return re.sub(r"^Version: .*$", f"Version: {version}", metadata, count=1, flags=re.MULTILINE)


def wheel_name(version: str) -> str:
    return f"{NAME}-{version}-py3-none-any.whl"


def _package_files(pkg: Path) -> list[tuple[str, Path]]:
    out = []
    for path in sorted(pkg.rglob("*")):
        rel = path.relative_to(pkg)
        if path.is_file() and not SKIP_DIRS & set(rel.parts) and path.suffix not in (".pyc", ".pyo"):
            out.append((f"{NAME}/{rel.as_posix()}", path))
    return out


def build(pkg: Path, dist_info: Path, version: str, out_dir: Path,
          extra: dict[str, Path] | None = None) -> Path:
    """把包目录 pkg（加上 extra：wheel 里的路径 → 文件）和 dist_info 里的元数据打成 version 版的 wheel。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / wheel_name(version)
    info = f"{NAME}-{version}.dist-info"
    entries: list[tuple[str, bytes]] = [(name, path.read_bytes()) for name, path in _package_files(pkg)]
    seen = {name for name, _ in entries}
    for name, path in sorted((extra or {}).items()):
        if name not in seen:
            entries.append((name, path.read_bytes()))
    for path in sorted(dist_info.rglob("*")):
        rel = path.relative_to(dist_info).as_posix()
        if not path.is_file() or rel in INSTALLER_FILES:
            continue
        data = path.read_bytes()
        if rel == "METADATA":
            data = set_version(data.decode("utf-8"), version).encode("utf-8")
        entries.append((f"{info}/{rel}", data))
    entries.append((f"{info}/WHEEL", WHEEL_META.encode("ascii")))
    record = "".join(f"{name},{_hash(data)},{len(data)}\n" for name, data in entries) + f"{info}/RECORD,,\n"
    tmp = target.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
        z.writestr(f"{info}/RECORD", record)
    tmp.replace(target)
    return target


def version_of(wheel: Path) -> str:
    m = re.match(rf"{NAME}-([^-]+)-", wheel.name)
    return m.group(1) if m else ""
