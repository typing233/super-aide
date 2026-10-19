"""用这台电脑上 Claude Code / Codex 已配好的服务，跑安卓端模型客户端的真实冒烟测试（:core LiveProbeTest）。

地址和 key 只通过环境变量传给 Gradle 子进程，不打印、不落盘。
用法：python scripts/android/live_probe.py [--tests 'LiveProbeTest.anthropic']
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def pc_services() -> dict[str, str]:
    """读 ~/.claude/settings.json 的 env 和 ~/.codex/config.toml 里当前用的 provider。"""
    home = Path.home()
    out: dict[str, str] = {}
    try:
        env = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8")).get("env", {})
        key = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")
        if env.get("ANTHROPIC_BASE_URL") and key:
            out["AIDE_ANTHROPIC_BASE"] = env["ANTHROPIC_BASE_URL"]
            out["AIDE_ANTHROPIC_KEY"] = key
    except (OSError, ValueError):
        pass
    try:
        codex = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
        provider = (codex.get("model_providers") or {}).get(codex.get("model_provider", ""), {})
        key = provider.get("experimental_bearer_token") or os.environ.get(provider.get("env_key", ""), "")
        if provider.get("base_url") and key:
            out["AIDE_OPENAI_BASE"] = provider["base_url"]
            out["AIDE_OPENAI_KEY"] = key
    except (OSError, ValueError):
        pass
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests", default="*LiveProbeTest*")
    args = parser.parse_args()
    services = pc_services()
    if not services:
        print("这台电脑上没找到已配好的服务", file=sys.stderr)
        return 1
    print("用这些服务：", ", ".join(k for k in services if k.endswith("_BASE")))
    env = {
        **os.environ,
        **services,
        "AIDE_LIVE": "1",
        "JAVA_HOME": os.environ.get("JAVA_HOME", r"D:\Android\jdk"),
        "ANDROID_HOME": os.environ.get("ANDROID_HOME", r"D:\Android\sdk"),
    }
    gradlew = ROOT / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")
    cmd = [str(gradlew), "--console=plain", ":core:test", "--tests", args.tests, "--rerun", "-i"]
    proc = subprocess.run(cmd, cwd=ROOT / "android", env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    keep = ("[", "PASSED", "FAILED", "SKIPPED", "AssertionError", "ModelError", "Exception", "BUILD", "e: ")
    for line in proc.stdout.splitlines() + proc.stderr.splitlines():
        if any(k in line for k in keep) and not any(v in line for v in services.values()):
            print(line)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
