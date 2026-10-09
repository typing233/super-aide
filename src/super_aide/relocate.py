"""换数据位置（设置 → 通用 → 数据位置）：会话（每次召唤的截图）、日志、学到的经验、向量模型、自我改进的工作台
都放到你选的文件夹，比如 D 盘。

- 设置（config.toml）和"数据在哪"的记录（location.json）一直留在 ~/.super_aide：启动时先读它，才知道数据在哪。
- 换的时候先把数据复制过去（运行中也能复制；中途出错什么都不变），记下新位置，重启；新的进程起来以后删掉旧的那份。
- 选的文件夹是空的、或者本来就是我们的数据文件夹，直接用；不然在里面建一个 SuperAide 文件夹，不把东西撒在 D:\\ 根上。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path

from . import paths
from .i18n import tr

log = logging.getLogger(__name__)

#: 数据文件夹里我们的东西：只搬、只删这些，你自己放进去的别的文件不碰
ITEMS = ("sessions", "workspace", "router", "logs", "evolve", "models", "experience", "dsh", "system_profile.json")
FOLDER = "SuperAide"
SPARE = 200 * 1024 * 1024  # 搬过去以后新位置至少还要剩这么多空间


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _inside(child: Path, parent: Path) -> bool:
    c, p = os.path.normcase(os.path.abspath(child)), os.path.normcase(os.path.abspath(parent))
    return c.startswith(p.rstrip("\\/") + os.sep)


def _files(root: Path) -> list[Path]:
    out: list[Path] = []
    for item in ITEMS:
        path = root / item
        if path.is_file():
            out.append(path)
        elif path.is_dir():
            out += [p for p in path.rglob("*") if p.is_file()]
    return out


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:  # 刚被清理掉（比如过期的会话截图）
        return 0


def size(root: Path | None = None) -> int:
    return sum(_size(p) for p in _files(root or paths.DATA))


def _ours(folder: Path) -> bool:
    """本来就是我们的数据文件夹（只认我们自己才会写的文件）。"""
    return (folder / "logs" / "super_aide.log").exists() or (folder / "router" / "outcomes.jsonl").exists()


def target_for(chosen: Path) -> Path:
    """你选的文件夹 → 数据真正放的地方。"""
    chosen = Path(os.path.abspath(chosen))
    if _same(chosen, paths.HOME) or _ours(chosen):
        return chosen  # 默认位置，或者本来就是我们的数据文件夹
    try:
        empty = not any(chosen.iterdir())
    except OSError:
        empty = False
    return chosen if empty else chosen / FOLDER


def problem(target: Path, total: int) -> str:
    """不能搬过去的原因，空 = 可以。"""
    old = paths.DATA
    if _same(target, old):
        return tr("数据已经在这里了")
    if _inside(target, old) or _inside(old, target):
        return tr("新位置和现在的数据文件夹不能一个套着一个")
    here = target  # 只是检查，先不建文件夹（你点了"取消"不留下空文件夹）：在已经有的那一层试着写一下
    while not here.exists() and here.parent != here:
        here = here.parent
    try:
        probe = here / f".super-aide-write-test-{uuid.uuid4().hex[:8]}"
        probe.write_bytes(b"")
        probe.unlink()
        free = shutil.disk_usage(here).free
    except OSError as e:
        return tr("这个文件夹写不进去：{error}", error=e)
    if free < total + SPARE:
        return tr("{drive} 空间不够：要 {need}，只剩 {free}", drive=target.anchor or str(target),
                  need=human(total + SPARE), free=human(free))
    return ""


def copy(target: Path, progress: Callable[[int, int], None] | None = None) -> None:
    """把数据复制到 target（同名的覆盖）。出错就抛，旧的那份不受影响。"""
    old = paths.DATA
    files = _files(old)
    total = sum(_size(p) for p in files)
    done = 0
    for src in files:
        dst = target / src.relative_to(old)
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except FileNotFoundError:
            continue  # 复制的时候刚被清理掉（比如过期的会话截图）
        done += dst.stat().st_size
        if progress is not None:
            progress(done, total)


def commit(target: Path) -> None:
    """记下新位置（下次启动起生效）。旧位置也记下：新的进程起来以后把那份删掉。"""
    record = {"data": str(Path(os.path.abspath(target))), "previous": str(paths.DATA)}
    paths.LOCATION.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")


def cleanup() -> None:
    """启动时：上次换了位置的话，删掉旧位置里我们的东西（旧位置是 ~/.super_aide 时，设置文件留着）。"""
    try:
        record = json.loads(paths.LOCATION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    previous = record.pop("previous", "")
    if not previous:
        return
    old = Path(previous)
    if not _same(old, paths.DATA):
        for item in ITEMS:
            path = old / item
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            except OSError as e:
                log.warning("没删干净旧位置的 %s：%s", path, e)
        if not _same(old, paths.HOME):
            try:
                old.rmdir()  # 空了才删得掉
            except OSError:
                pass
        log.info("数据已经移到 %s，删掉了 %s 里的旧数据", paths.DATA, old)
    paths.LOCATION.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")


def human(n: float) -> str:
    """338 MB、1.2 GB 这样的写法。"""
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
