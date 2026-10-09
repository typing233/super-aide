"""自研 Computer Use 的纯逻辑：按键解析、截图缩放和坐标换算、哪些控件算能操作、输入方式、官方/自研的判断。"""

import json
import tomllib

import pytest

from super_aide.cu import elements, inputs
from super_aide.cu.keys import parse_combo, vk_of
from super_aide.cu.observe import MAX_EDGE, MAX_PIXELS, Observation, describe, fit
from super_aide.engines import computer


def test_key_combos():
    assert parse_combo("ctrl+s") == [0x11, ord("S")]
    assert parse_combo("Alt + F4") == [0x12, 0x73]
    assert parse_combo("shift+tab") == [0x10, 0x09]
    assert parse_combo("ctrl+plus") == [0x11, 0xBB]
    assert vk_of("enter") == 0x0D and vk_of("pagedown") == 0x22
    with pytest.raises(ValueError):
        parse_combo("ctrl+nosuchkey")


@pytest.mark.parametrize(("w", "h"), [(1920, 1080), (3840, 2160), (800, 600), (2560, 1440)])
def test_screenshot_fits_model_limits(w, h):
    s = fit(w, h)
    assert s <= 1.0
    assert max(w, h) * s <= MAX_EDGE + 1 and w * h * s * s <= MAX_PIXELS * 1.01


def test_coordinates_round_trip_with_offset_origin():
    obs = Observation(hwnd=1, title="t", process="p.exe", origin=(-1920, 120), scale=0.5, size=(960, 540))
    assert obs.to_physical(100, 50) == (-1720, 220)
    assert obs.to_image(-1720, 220) == (100, 50)
    assert obs.to_physical(5000, -10) == (-1920 + 1918, 120)  # 越界的坐标夹回截图范围内


def test_describe_lists_elements_in_screenshot_coordinates():
    obs = Observation(hwnd=1, title="记事本", process="notepad.exe", origin=(100, 100), scale=0.5, size=(400, 300),
                      url="")
    el = elements.Element(id=3, role="Edit", name="文本编辑器", rect=(200, 200, 400, 300), value="hello",
                          states=("focused",))
    obs.elements = {3: el}
    obs.focused = el
    text = describe(obs)
    assert "[3] Edit \"文本编辑器\" value=\"hello\" (focused) @100,75" in text
    assert "焦点：[3]" in text


class FakeElement:
    def __init__(self, props: dict):
        self.props = props

    def GetCachedPropertyValue(self, pid):  # noqa: N802 - 模拟 COM 接口
        return self.props.get(pid)


def interactive(role, patterns=(), action=""):
    e = FakeElement({elements.P_DEFAULT_ACTION: action})
    return elements._is_interactive(e, role, frozenset(patterns))


def test_interactive_filter():
    assert interactive("Button")
    assert interactive("Edit")
    assert not interactive("Document")                       # 只读的文档区不算
    assert interactive("Document", {"value"})                # 可编辑的编辑器算
    assert not interactive("Text", {"invoke"}, "按")          # Qt 的标签：挂了 Invoke 也不算（实测）
    assert interactive("Text", {"invoke"}, "click")           # Chromium 里能点的文字
    assert not interactive("Text", (), "click ancestor")      # 链接里的文字
    assert interactive("Group", {"invoke"})                   # 能点的容器（网页里的卡片按钮）


def test_text_entry_method(monkeypatch):
    used = []
    monkeypatch.setattr(inputs, "paste_text", lambda text: used.append("paste"))
    monkeypatch.setattr(inputs, "type_text", lambda text, should_stop=None: used.append("type"))
    assert inputs.enter_text("hello world") == "键入"
    assert inputs.enter_text("中文") == "粘贴"        # 中文输入法开着时逐字输入会丢字（实测）
    assert inputs.enter_text("two\nlines") == "粘贴"
    assert inputs.enter_text("x" * 500) == "粘贴"
    assert used == ["type", "paste", "paste", "paste"]


def test_official_codex_detection(tmp_path):
    assert not computer.official_codex(tmp_path)  # 没有 auth.json
    (tmp_path / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "x", "tokens": None}), encoding="utf-8")
    assert not computer.official_codex(tmp_path)  # 只有 API Key
    (tmp_path / "auth.json").write_text(json.dumps({"tokens": {"access_token": "t"}}), encoding="utf-8")
    assert computer.official_codex(tmp_path)      # 官方账号、没配服务商
    (tmp_path / "config.toml").write_text('model_provider = "aifast"\n', encoding="utf-8")
    assert not computer.official_codex(tmp_path)  # 接了自定义服务地址


def test_codex_overrides_are_valid_toml_and_disable_native_gui():
    overrides = computer.codex_overrides(["KeePass.exe", "1Password.exe"])
    doc = tomllib.loads("\n".join(o for o in overrides if not o.startswith("plugins.")))
    server = doc["mcp_servers"]["computer"]
    assert server["args"][-1] == "super_aide.cu.server"
    assert server["env"]["AIDE_BLOCKED_APPS"] == "KeePass.exe;1Password.exe"
    assert doc["features"] == {"computer_use": False, "browser_use": False}
    assert any(o.startswith('plugins."chrome@openai-bundled".enabled=false') for o in overrides)


def test_status_lines():
    assert computer.status("mcp__computer__observe_window", {"window": "记事本"}) == "正在看「记事本」…"
    assert computer.status("act", {"actions": [{"do": "type", "text": "hi"}]}) == "正在输入…"
    assert computer.status("act", {"actions": [{"do": "click"}, {"do": "key", "keys": "enter"}]}) == "正在点击（共 2 步）…"
    assert computer.status("browser", {"command": "go", "value": "https://modelscope.cn"}) == "正在打开 https://modelscope.cn…"
