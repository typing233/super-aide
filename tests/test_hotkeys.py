import pytest

from super_aide.hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, HotkeyManager, parse


@pytest.mark.parametrize(("spec", "expected"), [
    ("Alt+Q", (MOD_ALT, ord("Q"))),
    ("alt + w", (MOD_ALT, ord("W"))),
    ("Ctrl+Alt+E", (MOD_CONTROL | MOD_ALT, ord("E"))),
    ("Ctrl+Shift+Space", (MOD_CONTROL | MOD_SHIFT, 0x20)),
    ("Win+Alt+1", (MOD_WIN | MOD_ALT, ord("1"))),
    ("Alt+F2", (MOD_ALT, 0x71)),
    ("Alt+`", (MOD_ALT, 0xC0)),
    ("F13", (0, 0x7C)),  # F13~F24 不会和打字冲突，允许单独使用
])
def test_parse(spec, expected):
    assert parse(spec) == expected


@pytest.mark.parametrize("spec", ["", "Q", "Space", "Hyper+Q", "Alt+NotAKey", "Alt+F25"])
def test_parse_rejects(spec):
    with pytest.raises(ValueError):
        parse(spec)


def test_available_probe_and_own_keys():
    """试注册后立即释放；自己已注册的组合键算可用；写法不合法抛 ValueError。"""
    manager = HotkeyManager(lambda *_: None)
    spec = "Ctrl+Alt+Shift+F23"
    assert manager.available(spec)
    assert manager.register("ask", spec)
    try:
        assert manager.active
        assert manager.available(spec)
    finally:
        manager.unregister_all()
    assert not manager.active
    assert manager.available(spec)  # 释放之后别人（或下次）还能注册
    with pytest.raises(ValueError):
        manager.available("Hyper+Q")
