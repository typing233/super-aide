"""技能接入自检：用真实的引擎代码连接两边（问答、操作两种模式），确认 6 个 aide: 技能都在。

只连接、不提问（不花 token）。

    uv run --no-sync python -X utf8 spikes/p3_skills_check.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from openai_codex.generated.v2_all import SkillsListResponse

from super_aide import app, paths
from super_aide.engines import prompts
from super_aide.engines.claude import ClaudeEngine
from super_aide.engines.codex import CodexEngine

EXPECTED = {f"aide:{n}" for n in ("uninstall-software", "python-env", "jupyter-debug", "network-proxy",
                                  "disk-cleanup", "office-automation")}


async def main() -> int:
    paths.ensure()
    app._sync_workspace()
    ok = True

    claude = ClaudeEngine(prompts.shared_instructions(), blocklist=False)
    for mode in ("ask", "act"):
        client, _slot = await claude._connect(mode, "claude-opus-5-5", "low")
        try:
            info = await client.get_server_info() or {}
            names = {c.get("name") for c in info.get("commands", []) if isinstance(c, dict)}
            missing = EXPECTED - names
            print(f"Claude {mode}: {'全部 6 个都在' if not missing else '缺 ' + json.dumps(sorted(missing))}")
            ok &= not missing
        finally:
            await client.disconnect()

    codex = CodexEngine(prompts.shared_instructions(), blocklist=False)
    try:
        for mode in ("ask", "act"):
            client = await codex.client(mode)
            resp = await client._client.request("skills/list", {"cwds": [str(paths.SESSIONS)], "forceReload": True},
                                                response_model=SkillsListResponse)
            names = {s.name for e in resp.data for s in e.skills if s.enabled}
            missing = EXPECTED - names
            print(f"Codex {mode}: {'全部 6 个都在' if not missing else '缺 ' + json.dumps(sorted(missing))}")
            ok &= not missing
    finally:
        await codex.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
