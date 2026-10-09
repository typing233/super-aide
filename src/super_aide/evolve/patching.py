"""统一格式的补丁（unified diff）：生成、解析、应用、反向检查。不依赖 git。

- 生成：两棵目录树逐个文件比（difflib），路径用 a/ b/ 前缀，和 git diff 的格式一样，人和模型都看得懂。
- 应用：按上下文精确匹配，允许行号偏移（新版本里前面多了几行也能套上）。套不上的整块报出来，不半套。
- 反向：能把补丁反着套上，说明目标里已经包含这次改动（比如已经合进了主版本）。
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".aide-tmp", ".pytest_cache", ".git", ".venv"}
SKIP_FILES = {".aide.json"}
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(Exception):
    pass


def files(root: Path) -> dict[str, Path]:
    """目录树里要比较的文件：相对路径（/ 分隔）→ 路径。"""
    out = {}
    if not root.exists():
        return out
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if path.is_file() and not SKIP_DIRS & set(rel.parts) and rel.name not in SKIP_FILES \
                and path.suffix not in (".pyc", ".pyo"):
            out[rel.as_posix()] = path
    return out


def _read(path: Path | None) -> list[str] | None:
    """文本按行读出（保留换行）；不是 UTF-8 文本的返回 None（二进制文件）。"""
    if path is None:
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (UnicodeDecodeError, ValueError):
        return None


def diff_trees(old: Path, new: Path) -> str:
    """old → new 的补丁。二进制文件只写一行说明。"""
    a, b = files(old), files(new)
    out: list[str] = []
    for rel in sorted(set(a) | set(b)):
        pa, pb = a.get(rel), b.get(rel)
        if pa and pb and pa.read_bytes() == pb.read_bytes():
            continue
        la, lb = _read(pa), _read(pb)
        if la is None or lb is None:
            out.append(f"Binary files a/{rel} and b/{rel} differ\n")
            continue
        out.extend(_ensure_newline(difflib.unified_diff(
            la, lb, fromfile=f"a/{rel}" if pa else "/dev/null", tofile=f"b/{rel}" if pb else "/dev/null", n=3)))
    return "".join(out)


def _ensure_newline(lines):
    for line in lines:
        yield line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"


def changed_paths(patch: str) -> list[str]:
    return [fp.path for fp in parse(patch)]


@dataclass
class Hunk:
    old_start: int
    lines: list[str] = field(default_factory=list)  # 带前缀的行：' '、'-'、'+'

    def old(self) -> list[str]:
        return [ln[1:] for ln in self.lines if ln[:1] in (" ", "-")]

    def new(self) -> list[str]:
        return [ln[1:] for ln in self.lines if ln[:1] in (" ", "+")]


@dataclass
class FilePatch:
    path: str          # 相对路径（/ 分隔）
    created: bool = False
    deleted: bool = False
    binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)


def parse(patch: str) -> list[FilePatch]:
    result: list[FilePatch] = []
    current: FilePatch | None = None
    hunk: Hunk | None = None
    lines = patch.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("Binary files "):
            m = re.match(r"Binary files a/(.+?) and b/(.+?) differ", line)
            if m:
                result.append(FilePatch(m.group(2), binary=True))
            current, hunk = None, None
        elif line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            old_name = line[4:].strip()
            new_name = lines[i + 1][4:].strip()
            path = new_name[2:] if new_name != "/dev/null" else old_name[2:]
            current = FilePatch(path, created=old_name == "/dev/null", deleted=new_name == "/dev/null")
            result.append(current)
            hunk = None
            i += 1
        elif (m := _HUNK.match(line)) and current is not None:
            hunk = Hunk(int(m.group(1)))
            current.hunks.append(hunk)
        elif hunk is not None and line[:1] in (" ", "-", "+"):
            hunk.lines.append(line)
        elif hunk is not None and line.startswith("\\"):
            # 上一行没有换行结尾
            if hunk.lines:
                hunk.lines[-1] = hunk.lines[-1].rstrip("\n").rstrip("\r")
        i += 1
    return result


def _find(text: list[str], needle: list[str], hint: int) -> int:
    """在 text 里找 needle（从 hint 附近往两边找），返回起始行；找不到返回 -1。"""
    if not needle:
        return min(max(hint, 0), len(text))
    limit = len(text) - len(needle)
    for offset in range(0, len(text) + 1):
        for pos in (hint + offset, hint - offset) if offset else (hint,):
            if 0 <= pos <= limit and text[pos:pos + len(needle)] == needle:
                return pos
    return -1


def _runs(hunk: Hunk, sign: str) -> list[list[str]]:
    """一处改动里连续加上（sign='+'）或删掉（'-'）的那几段，每行去掉行尾空白。"""
    runs: list[list[str]] = []
    current: list[str] = []
    for ln in hunk.lines + [" "]:
        if ln[:1] == sign:
            current.append(ln[1:].rstrip())
        elif ln[:1] != ("-" if sign == "+" else "+") and current:  # 中间夹着另一种符号不算断开
            runs.append(current)
            current = []
    return [r for r in runs if any(r)]


def included(patch: str, root: Path) -> bool:
    """这份改动是不是已经在 root 里了：加上的每一段都在、只删不加的那几段都不在了，不管周围的上下文。
    反着套补丁更严格：改动合进主线以后主线又动了旁边几行，就对不上了（2026-10-09 因此又搬迁了一遍）。"""
    parsed = parse(patch)
    if not parsed:
        return False
    for fp in parsed:
        target = root / fp.path
        if fp.binary:
            return False
        if fp.deleted:
            if target.exists():
                return False
            continue
        text = _read(target) if target.exists() else None
        if text is None:
            return False
        lines = [ln.rstrip() for ln in text]
        for hunk in fp.hunks:
            added = _runs(hunk, "+")
            if any(_find(lines, run, 0) < 0 for run in added):
                return False
            if not added and any(_find(lines, run, 0) >= 0 for run in _runs(hunk, "-")):
                return False
    return True


def apply_to_text(original: list[str], fp: FilePatch, reverse: bool = False) -> list[str]:
    """把一个文件的补丁套到 original 上，返回新内容。套不上抛 PatchError。"""
    out = list(original)
    shift = 0
    for hunk in fp.hunks:
        old, new = (hunk.new(), hunk.old()) if reverse else (hunk.old(), hunk.new())
        pos = _find(out, old, hunk.old_start - 1 + shift)
        if pos < 0:
            raise PatchError(f"{fp.path}：第 {hunk.old_start} 行附近对不上")
        out[pos:pos + len(old)] = new
        shift += len(new) - len(old)
    return out


def apply(patch: str, root: Path, reverse: bool = False, check: bool = False) -> list[str]:
    """把补丁套到目录 root 上（check=True 只检查不写）。返回改到的文件；有一处套不上就抛 PatchError，不半套。"""
    planned: list[tuple[Path, list[str] | None]] = []
    for fp in parse(patch):
        if fp.binary:
            raise PatchError(f"{fp.path}：二进制文件，没法自动套")
        target = root / fp.path
        created, deleted = (fp.deleted, fp.created) if reverse else (fp.created, fp.deleted)
        if created:
            if target.exists():
                raise PatchError(f"{fp.path}：已经存在")
            planned.append((target, apply_to_text([], fp, reverse)))
            continue
        current = _read(target) if target.exists() else None
        if current is None:
            raise PatchError(f"{fp.path}：找不到或不是文本文件")
        updated = apply_to_text(current, fp, reverse)
        planned.append((target, None if deleted else updated))
    if not check:
        for target, content in planned:
            if content is None:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("".join(content), encoding="utf-8", newline="")
    return [str(t.relative_to(root)).replace("\\", "/") for t, _ in planned]


def applies(patch: str, root: Path, reverse: bool = False) -> bool:
    try:
        apply(patch, root, reverse=reverse, check=True)
        return True
    except PatchError:
        return False
