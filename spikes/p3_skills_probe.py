"""技能接入探针：同一份 SKILL.md，Claude 通过本地插件、Codex 通过 skills/extraRoots/set 能不能读到。

只连接、不提问（不花 token）。

    uv run --no-sync python -X utf8 spikes/p3_skills_probe.py
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from openai_codex import AsyncCodex, CodexConfig
from openai_codex.generated.v2_all import SkillsExtraRootsSetResponse, SkillsListResponse

from super_aide import paths
from super_aide.engines.claude import claude_env

SKILL = """---
name: probe-skill
description: 测试用技能。用户说"探针"时使用。
---

# 探针

回复"探针收到"。
"""


def make_plugin(root: Path) -> Path:
    plugin = root / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "aide-probe", "version": "0.0.1", "description": "probe"}), encoding="utf-8")
    skill = plugin / "skills" / "probe-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL, encoding="utf-8")
    return plugin


async def claude(plugin: Path) -> None:
    opts = ClaudeAgentOptions(cwd=str(paths.SESSIONS), env=claude_env(), model="claude-opus-5-5",
                              plugins=[{"type": "local", "path": str(plugin)}], skills="all",
                              permission_mode="default", allowed_tools=["Read"])
    client = ClaudeSDKClient(options=opts)
    await client.connect()
    try:
        info = await client.get_server_info() or {}
        text = json.dumps(info, ensure_ascii=False)
        print("Claude server_info keys:", sorted(info))
        print("  提到 probe-skill:", "probe-skill" in text)
        for key in ("commands", "skills", "plugins"):
            if key in info:
                items = info[key]
                names = [i.get("name") if isinstance(i, dict) else i for i in items][:60]
                print(f"  {key}:", names)
        usage = await client.get_context_usage()
        print("  context usage 提到 probe-skill:", "probe-skill" in str(usage))
    finally:
        await client.disconnect()


async def codex(plugin: Path) -> None:
    client = AsyncCodex(CodexConfig(cwd=str(paths.SESSIONS)))
    await client.__aenter__()
    try:
        before = await client._client.request("skills/list", {"cwds": [str(paths.SESSIONS)], "forceReload": True},
                                              response_model=SkillsListResponse)
        names_before = [(s.name, s.scope.value) for e in before.data for s in e.skills]
        print("Codex 原有技能:", names_before)
        await client._client.request("skills/extraRoots/set", {"extraRoots": [str(plugin / "skills")]},
                                     response_model=SkillsExtraRootsSetResponse)
        after = await client._client.request("skills/list", {"cwds": [str(paths.SESSIONS)], "forceReload": True},
                                             response_model=SkillsListResponse)
        for entry in after.data:
            for s in entry.skills:
                if s.name == "probe-skill":
                    print("Codex 读到 probe-skill:", s.scope.value, s.path, s.enabled)
            for err in entry.errors:
                print("Codex 技能错误:", err)
        print("  加了以后共:", sum(len(e.skills) for e in after.data))
    finally:
        await client.close()


async def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="aide-skills-"))
    plugin = make_plugin(root)
    await claude(plugin)
    await codex(plugin)


if __name__ == "__main__":
    asyncio.run(main())
