"""把这台电脑上 Claude Code / Codex 已配好的服务写进手机上的调试版超级助手。

key 经 `adb exec-in run-as` 的标准输入写进 App 私有目录（不出现在命令行、不打印），
App 收到 provision 命令后加密保存并删掉明文。只对 debug / staging 版本有效（需要可调试）。
用法：python scripts/android/provision.py [--package io.github.typing233.superaide.debug]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_probe import pc_services  # noqa: E402

ADB = r"D:\Android\sdk\platform-tools\adb.exe"

# 手机端默认可路由的模型（和桌面版一样，旗舰/主力/轻量各一）
CLAUDE_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
OPENAI_MODELS = ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna"]


def build(deepseek: bool = False) -> dict:
    env = pc_services()
    services = []
    if deepseek:
        # 只用 deepseek-flash（OpenAI Chat 协议），和用户手机上的配置一样
        if "AIDE_OPENAI_BASE" in env:
            services.append({
                "service": {"id": "ds", "name": "deepseek", "wire": "OPENAI_CHAT", "baseUrl": env["AIDE_OPENAI_BASE"]},
                "key": env["AIDE_OPENAI_KEY"],
                "models": [{"service": "ds", "id": "deepseek-flash"}],
            })
        return {"services": services}
    if "AIDE_ANTHROPIC_BASE" in env:
        services.append({
            "service": {"id": "claude", "name": "Claude", "wire": "ANTHROPIC", "baseUrl": env["AIDE_ANTHROPIC_BASE"], "bearer": True},
            "key": env["AIDE_ANTHROPIC_KEY"],
            "models": [{"service": "claude", "id": m} for m in CLAUDE_MODELS],
        })
    if "AIDE_OPENAI_BASE" in env:
        services.append({
            "service": {"id": "openai", "name": "OpenAI", "wire": "OPENAI_RESPONSES", "baseUrl": env["AIDE_OPENAI_BASE"]},
            "key": env["AIDE_OPENAI_KEY"],
            "models": [{"service": "openai", "id": m} for m in OPENAI_MODELS],
        })
    return {"services": services}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", default="io.github.typing233.superaide.debug")
    parser.add_argument("--deepseek", action="store_true", help="只写 deepseek-flash（OpenAI Chat 协议）")
    args = parser.parse_args()
    data = build(args.deepseek)
    if not data["services"]:
        print("这台电脑上没找到已配好的服务", file=sys.stderr)
        return 1
    payload = json.dumps(data).encode()
    write = subprocess.run(
        [ADB, "exec-in", "run-as", args.package, "sh", "-c", "cat > files/provision.json"],
        input=payload, capture_output=True,
    )
    if write.returncode != 0:
        print("写入失败：", write.stderr.decode(errors="replace"), file=sys.stderr)
        return 1
    subprocess.run(
        [ADB, "shell", "am", "broadcast", "-a", "io.github.typing233.superaide.DEBUG", "-p", args.package, "--es", "cmd", "provision"],
        check=True, capture_output=True,
    )
    print("已写入：", ", ".join(f"{s['service']['name']}（{len(s['models'])} 个模型）" for s in data["services"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
