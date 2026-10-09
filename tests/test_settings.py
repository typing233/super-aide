"""设置的实时生效：快捷键换不上时回退、模型改动触发重建、隐私名单同步、无控制台时隐藏子进程窗口；
浏览器操作那一行只在没接通时出现。"""

from __future__ import annotations

import json
import re
import subprocess
from types import SimpleNamespace

import pytest

from super_aide import app, config
from super_aide.shell import settings as settings_ui


class FakeHotkeys:
    def __init__(self, taken: set[str] = frozenset()) -> None:
        self.taken = set(taken)
        self.registered: dict[str, str] = {}

    @property
    def active(self) -> bool:
        return bool(self.registered)

    def register(self, name: str, spec: str) -> bool:
        if spec in self.taken:
            return False
        self.registered[name] = spec
        return True

    def unregister_all(self) -> None:
        self.registered.clear()

    def available(self, spec: str) -> bool:
        return spec not in self.taken


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __getattr__(self, name: str):
        return lambda *args: self.calls.append((name, *args))


@pytest.fixture
def aide(monkeypatch):
    saved: list[config.Config] = []
    monkeypatch.setattr(config, "save", lambda cfg, path=None: saved.append(cfg))
    a = app.SuperAide.__new__(app.SuperAide)
    a.cfg = config.Config()
    a.hotkeys = FakeHotkeys()
    a.hotkeys.register("ask", a.cfg.hotkey_ask)
    a.hotkeys.register("act", a.cfg.hotkey_act)
    a.collector = SimpleNamespace(blocked=set())
    a.hub = Recorder()
    a.tray = Recorder()
    a.evolve = Recorder()
    a.ctrl = SimpleNamespace(panel=Recorder(), theme=lambda: "dark")
    a.settings = None
    a.warm_pending = False
    a.fresh = {}
    a.saved = saved
    return a


def edited(cfg: config.Config, **changes) -> config.Config:
    new = config.from_dict(config.to_dict(cfg))
    for key, value in changes.items():
        setattr(new, key, value)
    return new


def test_hotkey_change_registers_new_keys(aide):
    cfg = aide.cfg
    assert aide.apply_settings(edited(cfg, hotkey_ask="Ctrl+Alt+A")) == []
    assert aide.cfg is cfg  # 原地更新，各部分拿着的还是同一个对象
    assert cfg.hotkey_ask == "Ctrl+Alt+A"
    assert aide.hotkeys.registered == {"ask": "Ctrl+Alt+A", "act": "Alt+W"}
    assert aide.saved and aide.tray.calls[-1][0] == "refresh"


def test_hotkey_taken_rolls_back(aide):
    aide.hotkeys.taken.add("Ctrl+Alt+B")
    errors = aide.apply_settings(edited(aide.cfg, hotkey_ask="Ctrl+Alt+B", theme="light"))
    assert errors and "Ctrl+Alt+B" in errors[0]
    assert aide.cfg.hotkey_ask == "Alt+Q"
    assert aide.hotkeys.registered == {"ask": "Alt+Q", "act": "Alt+W"}
    assert aide.cfg.theme == "light"  # 其它改动照常生效


def test_model_change_rebuilds_router_and_warms_on_close(aide):
    new = edited(aide.cfg)
    new.claude.models.append(config.ModelEntry("claude-sonnet-5-5", True, "high"))
    aide.apply_settings(new)
    assert ("reconfigure",) in aide.hub.calls
    assert aide.warm_pending
    assert [m.id for m in aide.cfg.claude.enabled_models()] == ["claude-opus-5-5", "claude-sonnet-5-5"]
    aide.settings_closed()
    assert ("warm_up",) in aide.hub.calls and not aide.warm_pending


def test_non_routing_change_does_not_rebuild(aide):
    aide.apply_settings(edited(aide.cfg, theme="light", clipboard_max_age_s=60))
    assert ("reconfigure",) not in aide.hub.calls
    assert not aide.warm_pending


def test_blocked_apps_reach_collector(aide):
    aide.apply_settings(edited(aide.cfg, blocked_apps=["WeChat.exe", "KeePass.exe"]))
    assert aide.collector.blocked == {"wechat.exe", "keepass.exe"}


def test_closing_settings_resumes_paused_hotkeys(aide):
    aide.pause_hotkeys()
    assert not aide.hotkeys.active
    aide.settings_closed()
    assert aide.hotkeys.registered == {"ask": "Alt+Q", "act": "Alt+W"}


def test_check_hotkey_messages(aide):
    aide.hotkeys.taken.add("Ctrl+Alt+T")
    assert aide.check_hotkey("Ctrl+Alt+Y") == ""
    assert "占用" in aide.check_hotkey("Ctrl+Alt+T")


def test_discovered_models_merged_disabled(aide):
    aide.settings = Recorder()
    aide._on_models_found({"found": {"claude": ["claude-opus-5-5", "claude-new"]}, "errors": []})
    new = [m for m in aide.cfg.claude.models if m.id == "claude-new"]
    assert new and not new[0].enabled
    assert aide.saved
    assert aide.settings.calls == [("models_refreshed", {"added": 1, "errors": []})]


def test_bridge_save_and_load(monkeypatch):
    monkeypatch.setattr(settings_ui.autostart, "is_enabled", lambda: False)
    host = SimpleNamespace(cfg=config.Config(), applied=[], resolved_theme=lambda: "light",
                           evolve=SimpleNamespace(snapshot=lambda: {"enabled": True, "items": []}))
    host.apply_settings = lambda new: host.applied.append(new) or []
    bridge = settings_ui.SettingsBridge(host, window=None)

    state = json.loads(bridge.load())
    assert state["hotkeys"] == {"ask": "Alt+Q", "act": "Alt+W"}
    assert state["autostart"] is False and state["resolved_theme"] == "light"

    state["appearance"]["theme"] = "dark"
    resp = json.loads(bridge.save(json.dumps(state)))
    assert resp["errors"] == [] and host.applied[-1].theme == "dark"

    state["privacy"]["clipboard_max_age_s"] = "很久"
    resp = json.loads(bridge.save(json.dumps(state)))
    assert resp["errors"] and len(host.applied) == 1  # 不合法的不会交给宿主


def test_browser_row_only_when_there_is_something_to_fix(monkeypatch):
    """原来"通用"里总有一行"界面操作"，说用的是自研的还是官方的，用户觉得多余：你什么也不用做。
    现在平时不显示；只有用 Codex 官方账号、它的浏览器操作没接通时才出现，写着怎么接通。"""
    page = settings_ui.SETTINGS_PAGE.read_text(encoding="utf-8")
    row = re.search(r'<div[^>]*\bid="browser-row"[^>]*>', page)
    assert row and " hidden" in row.group(0)  # 页面默认藏着：宿主说没接通（ready 为 false）才放出来

    monkeypatch.setattr(settings_ui.autostart, "is_enabled", lambda: False)
    host = SimpleNamespace(cfg=config.Config(), resolved_theme=lambda: "light",
                           evolve=SimpleNamespace(snapshot=lambda: {"enabled": True, "items": []}))
    bridge = settings_ui.SettingsBridge(host, window=None)
    checked: list[str] = []
    missing = settings_ui.browser_use.Status(False, "浏览器操作还没接通：先装上示例插件。")
    monkeypatch.setattr(settings_ui.browser_use, "status", lambda process="": checked.append(process) or missing)

    monkeypatch.setattr(settings_ui.computer, "official_codex", lambda: False)
    assert bridge._state()["browser"] == {"ready": True, "problem": ""}  # 自研的：浏览器直接能操作，不显示
    assert checked == []  # 用不上 Codex 的 Chrome 插件，也就不去查它

    monkeypatch.setattr(settings_ui.computer, "official_codex", lambda: True)
    assert bridge._state()["browser"] == {"ready": False, "problem": missing.problem}  # 显示修法

    monkeypatch.setattr(settings_ui.browser_use, "status", lambda process="": settings_ui.browser_use.Status(True))
    assert bridge._state()["browser"] == {"ready": True, "problem": ""}  # 官方的、已经接通：也不显示


def test_child_consoles_hidden_without_console(monkeypatch):
    seen: list[int] = []

    def fake_init(self, *args, creationflags=0, **kwargs):
        self._child_created = False
        seen.append(creationflags)

    monkeypatch.setattr(subprocess.Popen, "__init__", fake_init)
    monkeypatch.setattr(app, "_has_console", lambda: False)
    app._hide_child_consoles()
    subprocess.Popen(["anything"])
    subprocess.Popen(["anything"], creationflags=app.CREATE_NEW_CONSOLE)
    assert seen[0] & app.CREATE_NO_WINDOW
    assert seen[1] == app.CREATE_NEW_CONSOLE  # 明确要新控制台的不改


def test_config_update_from_keeps_identity():
    cfg = config.Config()
    other = config.Config(hotkey_ask="Ctrl+1", theme="light")
    before = id(cfg)
    cfg.update_from(other)
    assert id(cfg) == before and cfg.hotkey_ask == "Ctrl+1" and cfg.theme == "light"
