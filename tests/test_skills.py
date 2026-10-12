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
                                        "disk-cleanup", "office-automation", "document-translation"}


def test_translating_a_whole_document_uses_a_ready_made_tool():
    """"把这篇论文翻译成中文 PDF"原来没有技能可循：助手自己下了 LaTeX 源码换中文字体重新编译，MiKTeX 一直在装宏包，
    7 分钟还没开始翻，被按 Esc 停下（2026-10-10）。技能要指向保留排版的现成工具、先试译几页，并写明那条弯路。"""
    skill = PLUGIN / "skills" / "document-translation" / "SKILL.md"
    description = frontmatter(skill)["description"]
    assert "翻译" in description and "PDF" in description  # 模型按描述挑技能
    body = skill.read_text(encoding="utf-8")
    assert "pdf2zh_next" in body and "--pages" in body
    assert "LaTeX" in body
    # 免费的翻译服务会把全文经维护者的中转服务器发给硅基流动：写明去向，私人文件不直接用、先问，汇报里说清发到了哪里
    assert "中转服务器" in body and "私人" in body and "先问用户" in body and "发到了哪里" in body
    assert "winget install --id=astral-sh.uv -e" in body  # 装 uv 不往用户自己的 Python 里装


def test_act_mode_prefers_ready_made_tools_and_trying_a_small_part_first():
    text = (paths.WORKSPACE_TEMPLATE / "AGENTS.md").read_text(encoding="utf-8")
    act = text.split("**操作模式**", 1)[1].split("\n## ", 1)[0]
    assert "现成的成熟办法" in act and "先拿一小部分试通" in act
    # 现成的工具可能是第三方服务：私人文件交出去也算对外动作
    assert "第三方服务" in act and "也算对外动作" in act


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
