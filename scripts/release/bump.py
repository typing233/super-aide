"""合并拉取请求后自动发版用（.github/workflows/auto-release.yml）：定下这次发哪个版本，改好版本号。

- pyproject.toml 里的版本已经比最新的 v 标签新（PR 自己改了版本号）：就发它，不再加；
- 否则补丁号加一（0.4.1 → 0.4.2），pyproject.toml 和 uv.lock 里 super-aide 那一条一起改（和手动发版一样）。

    python scripts/release/bump.py            # 打印要发的版本；在 GitHub Actions 里同时写进 $GITHUB_OUTPUT
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_VERSION = re.compile(r'(?m)^(version\s*=\s*")([^"]+)(")')
LOCK_ENTRY = re.compile(r'(?m)^(name = "super-aide"\r?\nversion = ")([^"]+)(")')


def parse(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version.split("+")[0])[:3])


def bumped(version: str) -> str:
    major, minor, patch = (parse(version) + (0, 0, 0))[:3]
    return f"{major}.{minor}.{patch + 1}"


def project_version(text: str) -> str:
    """[project] 里的 version（它在文件里第一个出现）。"""
    match = PROJECT_VERSION.search(text)
    if not match:
        raise ValueError("pyproject.toml 里没有版本号")
    return match.group(2)


def set_project_version(text: str, version: str) -> str:
    return PROJECT_VERSION.sub(lambda m: m.group(1) + version + m.group(3), text, count=1)


def set_lock_version(text: str, version: str) -> str:
    new, n = LOCK_ENTRY.subn(lambda m: m.group(1) + version + m.group(3), text, count=1)
    if n != 1:
        raise ValueError("uv.lock 里没有 super-aide 这一条")
    return new


def latest_tag() -> str:
    out = subprocess.run(["git", "tag", "--list", "v*"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    tags = [t.strip() for t in out.splitlines() if re.fullmatch(r"v\d+\.\d+\.\d+", t.strip())]
    return max(tags, key=lambda t: parse(t[1:]), default="v0.0.0")


def plan(current: str, latest: str) -> str:
    """→ 这次要发的版本。"""
    return current if parse(current) > parse(latest.lstrip("v")) else bumped(max(current, latest.lstrip("v"), key=parse))


def main() -> int:
    pyproject, lock = ROOT / "pyproject.toml", ROOT / "uv.lock"
    current = project_version(pyproject.read_text(encoding="utf-8"))
    version = plan(current, latest_tag())
    if version != current:
        pyproject.write_bytes(set_project_version(pyproject.read_bytes().decode("utf-8"), version).encode("utf-8"))
        lock.write_bytes(set_lock_version(lock.read_bytes().decode("utf-8"), version).encode("utf-8"))
    print(version)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"version={version}\nchanged={'true' if version != current else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
