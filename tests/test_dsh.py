"""DeepSeek Harness 引擎：怎么启动、给它的 patch、ACP 的模型选项和会话更新怎么变成界面事件。"""

from __future__ import annotations

import asyncio
import json

import pytest

from super_aide import paths
from super_aide.engines import dsh


def test_launch_command_for_desktop_build(tmp_path):
    root = tmp_path / "DeepSeek Harness"
    shim = root / "resources" / "runtime" / "cli" / "bin" / "dsh.cmd"
    shim.parent.mkdir(parents=True)
    shim.write_text("@echo off\n")
    (root / "DeepSeek Harness.exe").write_bytes(b"")
    (root / "resources" / "app.asar").write_bytes(b"")
    command, env = dsh.launch_command(str(shim))
    assert command[0] == str(root / "DeepSeek Harness.exe") and command[1] == "--expose-internals"
    assert command[2].endswith(r"dsh-desktop-host\lib\cli.js") and env == {"ELECTRON_RUN_AS_NODE": "1"}


def test_launch_command_for_npm_install(tmp_path):
    shim = tmp_path / "npm" / "dsh.cmd"
    bin_js = tmp_path / "npm" / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    bin_js.parent.mkdir(parents=True)
    bin_js.write_text("")
    shim.write_text("")
    (tmp_path / "npm" / "node.exe").write_bytes(b"")
    assert dsh.launch_command(str(shim)) == ([str(tmp_path / "npm" / "node.exe"), str(bin_js)], {})


def test_patch_is_read_only_for_ask_and_full_access_for_act(tmp_path):
    ask = dsh.patch_text("ask", "deepseek-account", "共享指令 {{不是变量}}", tmp_path)
    assert 'mode: "read-only"' in ask and 'defaultPreset: "read-only"' in ask and 'policy: "never"' in ask
    assert "{{不是变量}}" not in ask and "{ {不是变量} }" in ask  # DSH 的提示词模板认不出的变量会让请求失败
    assert "{{model}}" in ask and "{{cwd}}" in ask
    assert "- id: session-log-deepseek" in ask and "enabled: false" in ask  # 不上传会话日志
    assert 'provider: "deepseek-account"' in ask
    assert "customSkillDirs" in ask  # 技能目录存在时才加
    act = dsh.patch_text("act", "deepseek-official", "x")
    assert 'mode: "danger-full-access"' in act and 'defaultPreset: "danger-full-access"' in act
    assert "customSkillDirs" not in act


def test_patch_values_are_valid_yaml_scalars():
    text = dsh.patch_text("ask", "deepseek-account", 'C:\\路径 "引号"\n第二行')
    line = next(x for x in text.splitlines() if x.strip().startswith("personaSuffix:"))
    value = json.loads(line.split(":", 1)[1].strip())  # JSON 写法的字符串也是合法的 YAML
    assert value.endswith('C:\\路径 "引号"\n第二行') and value.startswith("Your working directory is {{cwd}}.")


def test_mcp_servers_match_the_other_engines():
    ask = {s["name"]: s for s in dsh.mcp_servers("ask", ["KeePass.exe"])}
    assert set(ask) == {"computer", "memory"}
    env = {e["name"]: e["value"] for e in ask["computer"]["env"]}
    assert env["AIDE_MODE"] == "ask" and env["AIDE_BLOCKED_APPS"] == "KeePass.exe"
    assert ask["computer"]["args"][-1] == "super_aide.cu.server"
    assert [s["name"] for s in dsh.mcp_servers("duel", [])] == ["memory"]  # 后台对比不看实时界面
    act = {s["name"]: s for s in dsh.mcp_servers("act", [])}
    assert {e["name"]: e["value"] for e in act["computer"]["env"]}["AIDE_MODE"] == "act"


def test_read_options_groups_by_provider():
    options = [
        {"id": "model", "type": "select", "currentValue": '["deepseek-account","deepseek-flash"]', "options": [
            {"group": "deepseek-account", "name": "DeepSeek", "options": [
                {"value": '["deepseek-account","deepseek-flash"]', "name": "DeepSeek-V41-Flash"},
                {"value": '["deepseek-account","deepseek-v4-pro"]', "name": "DeepSeek-V4-Pro"}]},
            {"group": "deepseek-official", "options": [{"value": '["deepseek-official","deepseek-flash"]'}]}]},
        {"id": "reasoning_effort", "category": "thought_level", "currentValue": "high",
         "options": [{"value": "off"}, {"value": "low"}, {"value": "high"}, {"value": "max"}]},
    ]
    models, efforts = dsh.read_options(options, "deepseek-account")
    assert models == {"deepseek-flash": '["deepseek-account","deepseek-flash"]',
                      "deepseek-v4-pro": '["deepseek-account","deepseek-v4-pro"]'}
    assert efforts == ["off", "low", "high", "max"]


class FakeProc:
    provider = "deepseek-account"
    image = True

    def __init__(self) -> None:
        self.sessions: dict = {}


def test_updates_become_ui_events():
    session = dsh.DshSession(FakeProc(), "s1", "deepseek-flash", "high")
    kinds = []
    for update in (
        {"sessionUpdate": "agent_thought_chunk", "messageId": "m1", "content": {"type": "text", "text": "想一想"}},
        {"sessionUpdate": "agent_message_chunk", "messageId": "m1", "content": {"type": "text", "text": "我先看看。"}},
        {"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "pwsh", "rawInput": {"command": "Get-Date"}},
        {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed"},
        {"sessionUpdate": "agent_message_chunk", "messageId": "m2", "content": {"type": "text", "text": "今天是"}},
        {"sessionUpdate": "agent_message_chunk", "messageId": "m2", "content": {"type": "text", "text": "周五。"}},
        {"sessionUpdate": "usage_update", "used": 100, "size": 1000},
    ):
        kinds += [(ev.type, ev.text) for ev in session.events(update)]
    # 工具调用之前的话是过程说明（撤掉）；同一段话分几块来的不重复开新段
    assert kinds == [("new_message", ""), ("delta", "我先看看。"), ("retract", ""), ("status", "正在运行 Get-Date"),
                     ("new_message", ""), ("delta", "今天是"), ("delta", "周五。")]


def test_images_only_for_models_that_can_see(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG")
    session = dsh.DshSession(FakeProc(), "s1", "deepseek-flash", "high")
    assert [b["type"] for b in session._content("看图", [image])] == ["image", "text"]
    session.model = "deepseek-v4-pro"
    assert [b["type"] for b in session._content("看图", [image])] == ["text"]


def test_tool_status_lines():
    assert dsh.tool_status("mcp__memory__recall", {}) == "正在回想以前的经验…"
    assert dsh.tool_status("read", {"file_path": r"C:\a\b.txt"}) == "正在读 b.txt"
    assert dsh.tool_status("mcp__computer__observe_window", {"window": "记事本"}) == "正在看「记事本」…"
    assert dsh.tool_status("whatever", {}) == "正在使用 whatever…"


def test_engine_reuses_the_warm_session(monkeypatch):
    created = []

    class Proc(FakeProc):
        alive = True

    async def new_session(self, mode):
        created.append(mode)
        return dsh.DshSession(Proc(), f"s{len(created)}", "", "")

    monkeypatch.setattr(dsh.DshEngine, "_new_session", new_session)

    async def run():
        engine = dsh.DshEngine("")
        await engine.warm("ask")
        first = await engine.open("ask", "deepseek-flash", "low")
        await asyncio.sleep(0)  # 让后台再建一个
        second = await engine.open("ask", "deepseek-v4-pro", "max")
        return first, second, engine

    first, second, engine = asyncio.run(run())
    assert (first.session_id, first.model, first.effort) == ("s1", "deepseek-flash", "low")
    assert (second.session_id, second.model) == ("s2", "deepseek-v4-pro")
    assert created == ["ask", "ask", "ask"]  # 预热一个，用掉一个补一个


@pytest.fixture(autouse=True)
def sessions_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SESSIONS", tmp_path / "sessions")
