"""诊断：通过 -c 注入的 Codex 钩子是否被识别、信任状态如何。只读，不发起对话。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from openai_codex import Codex, CodexConfig
from openai_codex.generated.v2_all import HooksListResponse

HERE = Path(__file__).resolve().parent
HOOK_CMD = f"{sys.executable} {HERE / 'codex_hook_blocklist.py'}"

VARIANTS = {
    "PreToolUse 数组": "hooks.PreToolUse=[{hooks=[{type=\"command\", command='" + HOOK_CMD + "'}]}]",
    "pre_tool_use 数组": "hooks.pre_tool_use=[{hooks=[{type=\"command\", command='" + HOOK_CMD + "'}]}]",
}

tmp = Path(tempfile.mkdtemp(prefix="super_aide_hookdiag_"))
for label, override in VARIANTS.items():
    print(f"\n=== {label} ===")
    with Codex(CodexConfig(cwd=str(tmp), config_overrides=(override,))) as codex:
        resp = codex._client.request("hooks/list", {"cwds": [str(tmp)]}, response_model=HooksListResponse)
        data = resp.model_dump(by_alias=True, exclude_none=True)
        entries = data.get("data", [])
        for entry in entries:
            for hook in entry.get("hooks", []):
                print(f"  {hook.get('eventName')}  来源={hook.get('source')}  信任={hook.get('trustStatus')}  "
                      f"启用={hook.get('enabled')}  文件={hook.get('sourcePath')}  命令={str(hook.get('command'))[:60]}")
            for key in ("warnings", "errors"):
                if entry.get(key):
                    print(f"  {key}: {entry[key]}")
        if not any(e.get("hooks") for e in entries):
            print(f"  没有识别到钩子；原始返回：{str(data)[:400]}")
        tail = codex._client._stderr_tail(10)
        if tail.strip():
            print(f"  stderr：{tail[-400:]}")
