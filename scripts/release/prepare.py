"""发版前生成随包发布的两个文件（GitHub Actions 发版时运行；本地想试安装器也可以跑）：

- src/super_aide/_release/constraints.txt：依赖的确切版本（由 uv.lock 导出）。安装器和"检查更新"从网上装时用它
  锁定版本：别人装到的和这里测过的是同一套（两个 SDK 用到了内部接口，自动升级可能就坏了）。
- src/super_aide/_release/release.json：版本号、GitHub 仓库（检查更新、下载安装器用）。有这个文件的才算发布版，
  设置里才会提供"更新"；从源码装的没有它。

    uv run python scripts/release/prepare.py [--repo 用户名/仓库名] [--tag v0.2.0]

给了 --tag 就核对它和 pyproject.toml 里的版本号一致（防止发版时忘了改版本号）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "src" / "super_aide" / "_release"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # GitHub Actions 的 Windows 机器输出编码是 cp1252，打印中文会出错
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default="", help="GitHub 仓库，例如 someone/super_aide")
    parser.add_argument("--tag", default="", help="发版的标签，例如 v0.2.0")
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if args.tag and args.tag.removeprefix("v") != version:
        print(f"标签 {args.tag} 和 pyproject.toml 里的版本 {version} 对不上：先改版本号再打标签", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run(["uv", "export", "--project", str(ROOT), "--frozen", "--no-dev", "--no-hashes", "--no-emit-project",
                    "--quiet", "--output-file", str(OUT / "constraints.txt")], check=True)
    info = {"version": version, "repo": args.repo, "built": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (OUT / "release.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"已生成 {OUT.relative_to(ROOT)}：版本 {version}，仓库 {args.repo or '未设置'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
