"""技能包格式：两边都按 Agent Skills 的规范读 SKILL.md（name 和目录名一致、description 必填且不超过 1024 字）。"""

from __future__ import annotations

import json
import re

import pytest

from super_aide import paths

PLUGIN = paths.WORKSPACE_TEMPLATE / "plugin"
SKILLS = sorted((PLUGIN / "skills").iterdir())
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def frontmatter(path) -> dict[str, str]:
    match = FRONTMATTER.match(path.read_text(encoding="utf-8"))
    assert match, f"{path} 缺少 --- 包起来的 frontmatter"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_plugin_manifest():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "aide"


def test_first_batch_present():
    assert {s.name for s in SKILLS} == {"uninstall-software", "python-env", "jupyter-debug", "network-proxy",
                                        "disk-cleanup", "office-automation"}


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_skill_frontmatter(skill):
    fields = frontmatter(skill / "SKILL.md")
    assert fields.get("name") == skill.name
    assert re.fullmatch(r"[a-z0-9-]{1,64}", fields["name"])
    assert 0 < len(fields.get("description", "")) <= 1024


def test_shared_instructions_point_to_every_skill():
    text = (paths.WORKSPACE_TEMPLATE / "AGENTS.md").read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) < 32 * 1024  # Codex 读 AGENTS.md 的上限
    for skill in SKILLS:
        assert f"aide:{skill.name}" in text
