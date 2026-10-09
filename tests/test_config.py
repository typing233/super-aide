from super_aide import config


def test_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.load(path)  # 不存在时写入默认配置
    assert path.exists()
    assert cfg.hotkey_ask == "Alt+Q" and cfg.hotkey_act == "Alt+W"
    assert [m.id for m in cfg.claude.enabled_models()] == ["claude-opus-5-5"]

    cfg.hotkey_ask = "Ctrl+Alt+Q"
    cfg.codex.merge_discovered(["gpt-6-astra", "gpt-6.1-sol"])
    config.save(cfg, path)
    again = config.load(path)
    assert again.hotkey_ask == "Ctrl+Alt+Q"
    assert [(m.id, m.enabled) for m in again.codex.models] == [("gpt-6-astra", True), ("gpt-6.1-sol", False)]


def test_merge_discovered_keeps_existing_and_defaults_off():
    eng = config.EngineSettings(models=[config.ModelEntry("a", True)])
    assert eng.merge_discovered(["a", "b", "c"]) == 2
    assert [(m.id, m.enabled) for m in eng.models] == [("a", True), ("b", False), ("c", False)]


def test_disabled_engine_has_no_models():
    eng = config.EngineSettings(enabled=False, models=[config.ModelEntry("a", True)])
    assert eng.enabled_models() == []
