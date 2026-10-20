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


def test_guide_labels_stay_on_screen_at_the_edges():
    """框贴着屏幕上沿、右沿时（窗口右上角的关闭按钮、浏览器标签页），编号标签原来整个画到屏幕外。"""
    from super_aide.cu import guide

    def label_pixels(target, scale=1.25):
        (bx0, by0, bx1, by1), _ = target
        x0, y0 = bx0 - guide.PAD - round(220 * scale), by0 - guide.PAD - round(40 * scale)
        size = (bx1 + guide.PAD + round(220 * scale) - x0, by1 + guide.PAD + round(40 * scale) - y0)
        img = guide.render([target], (x0, y0), size, scale, screen=lambda r: (0, 0, 1920, 1080))
        px = img.load()
        return [(x + x0, y + y0) for y in range(img.height) for x in range(img.width)
                if px[x, y][3] > 200 and px[x, y][0] > 120 and px[x, y][2] > 200 and px[x, y][1] < 130]

    corner = label_pixels(((1874, 0, 1920, 40), "点这里关闭窗口"))
    assert corner and all(0 <= x <= 1920 and 40 < y < 1080 for x, y in corner)  # 挪到框下面、往左收
    menu = label_pixels(((207, 230, 260, 262), "文件"))
    assert menu and all(y < 230 for _, y in menu)  # 有地方时照旧在框上面


def test_wait_says_how_long_it_really_waited(monkeypatch):
    """wait 一次最多等 WAIT_MAX_S 秒：要的更久时照实说只等了多久（原来说"等了 300 秒"，模型以为等够了）。"""
    from super_aide.cu import actions

    monkeypatch.setattr(actions, "WAIT_MAX_S", 0.05)
    runner = actions.Runner.__new__(actions.Runner)
    assert runner._wait(actions.Action(do="wait", seconds=0.01)) == "等了 0.01 秒"
    said = runner._wait(actions.Action(do="wait", seconds=300))
    assert said.startswith("只等了 0.05 秒") and "300" in said and "再调一次" in said


def test_wait_gone_returns_when_the_text_goes_away(monkeypatch):
    """wait_gone：等"中断""正在下载"这类只在做事时才有的字消失；控件里找不到了还要认图确认一次。"""
    from super_aide.cu import actions

    runner = actions.Runner.__new__(actions.Runner)
    runner.s = type("S", (), {"hwnd": 1})()
    present = iter([True, True, False])
    monkeypatch.setattr(actions.elements, "search", lambda hwnd, text, limit=1: [1] if next(present) else [])
    monkeypatch.setattr(actions, "_seen_on_screen", lambda hwnd, text: False)
    monkeypatch.setattr(actions.time, "sleep", lambda s: None)
    assert runner._wait_gone(actions.Action(do="wait_gone", text="中断", seconds=30)).startswith("「中断」不见了")
    monkeypatch.setattr(actions.elements, "search", lambda hwnd, text, limit=1: [])
    assert "不用等" in runner._wait_gone(actions.Action(do="wait_gone", text="中断"))
    monkeypatch.setattr(actions, "_seen_on_screen", lambda hwnd, text: True)  # 控件里没有、图上还在：没消失
    monkeypatch.setattr(actions, "WAIT_FOR_MAX_S", 0.01)
    with pytest.raises(RuntimeError, match="还在"):
        runner._wait_gone(actions.Action(do="wait_gone", text="中断", seconds=0.01))


def test_text_from_richedit_keeps_its_line_breaks():
    """新版记事本这类 RichEdit 控件只用 \r 分行：统一成 \n，模型才看得出分行。"""
    from super_aide.snapshot.uia import newlines

    assert newlines("会议纪要\r下午三点开会\r\n地点") == "会议纪要\n下午三点开会\n地点"


def test_hidden_input_boxes_are_not_reported_as_failed_typing():
    """网页终端、代码编辑器的隐藏输入框（几乎没有大小）打完会自己清空：不报"可能没输进去"。"""
    from super_aide.cu import actions
    from super_aide.cu.elements import Element

    assert actions._hidden_input(Element(1, "Edit", "Terminal input", (-9999, -9999, -9999, -9999)))
    assert actions._hidden_input(Element(2, "Edit", "", (100, 200, 101, 201)))  # Monaco 的 1×1 输入框
    assert not actions._hidden_input(Element(3, "Edit", "搜索", (100, 200, 400, 230)))
