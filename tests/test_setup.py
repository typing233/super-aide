"""前置检查和准备：检测装没装、配没配，准备流程怎么走，自定义服务地址怎么写进各工具的配置。"""

from __future__ import annotations

import json
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from super_aide import config
from super_aide.setup import configure, detect, flow, install


@pytest.fixture
def places(tmp_path, monkeypatch):
    monkeypatch.setattr(detect, "_dsh_registered", lambda p: "")  # 不看这台机器真实的注册表
    home, local, roaming = tmp_path / "home", tmp_path / "local", tmp_path / "roaming"
    for d in (home, local, roaming):
        d.mkdir()
    return detect.Places(home=home, local=local, roaming=roaming, env={"PATH": str(tmp_path / "bin")})


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def with_env(places, **env):
    return detect.Places(places.home, places.local, places.roaming, {**places.env, **env})


# ---------- 检测：Claude Code ----------

def test_nothing_installed_or_configured(places):
    report = detect.scan(places)
    assert report.missing() == ["claude", "codex"]
    assert not report.dsh.installed
    assert report.usable(use_dsh=True) == []


def test_claude_custom_url_in_settings(places):
    write(places.home / ".local" / "bin" / "claude.exe", "")
    write(places.home / ".claude" / "settings.json", json.dumps(
        {"env": {"ANTHROPIC_BASE_URL": "https://relay.example.com/api", "ANTHROPIC_AUTH_TOKEN": "x"}}))
    tool = detect.scan(places).claude
    assert (tool.installed, tool.via, tool.configured, tool.auth) == (True, "cli", True, "custom")
    assert tool.detail == "自定义服务地址 relay.example.com"  # 只显示主机名


def test_claude_api_key_from_user_env_and_oauth_login(places):
    assert detect.claude_auth(with_env(places, ANTHROPIC_API_KEY="k"))[:2] == (True, "apikey")
    write(places.home / ".claude" / ".credentials.json", json.dumps({"claudeAiOauth": {"refreshToken": "r"}}))
    assert detect.claude_auth(places)[:2] == (True, "account")


def test_claude_cloud_provider_needs_no_token(places):
    write(places.home / ".claude" / "settings.json", json.dumps({"env": {"CLAUDE_CODE_USE_BEDROCK": "1"}}))
    assert detect.claude_auth(places)[:2] == (True, "cloud")


def test_claude_vscode_extension_counts_as_installed(places):
    (places.home / ".vscode" / "extensions" / "anthropic.claude-code-2.1.292-win32-x64").mkdir(parents=True)
    tool = detect.scan(places).claude
    assert tool.installed and tool.via == "vscode"


# ---------- 检测：Codex ----------

def test_codex_desktop_app_with_chatgpt_login(places):
    (places.local / "Packages" / "OpenAI.Codex_2p2nqsd0c76g0").mkdir(parents=True)
    write(places.home / ".codex" / "auth.json", json.dumps({"tokens": {"access_token": "a"}}))
    tool = detect.scan(places).codex
    assert (tool.installed, tool.via, tool.configured, tool.auth) == (True, "desktop", True, "account")


def test_codex_custom_provider_needs_its_env_key(places):
    write(places.home / ".codex" / "config.toml", 'model_provider = "relay"\n\n[model_providers.relay]\n'
          'base_url = "https://relay.example.com/v1"\nenv_key = "RELAY_KEY"\n')
    ok, auth, detail = detect.codex_auth(places)
    assert (ok, auth) == (False, "custom") and "RELAY_KEY" in detail
    assert detect.codex_auth(with_env(places, RELAY_KEY="k"))[:2] == (True, "custom")


def test_codex_profile_and_local_provider(places):
    write(places.home / ".codex" / "config.toml",
          'profile = "local"\n\n[profiles.local]\nmodel_provider = "ollama"\n')
    assert detect.codex_auth(places)[:2] == (True, "local")


def test_codex_home_override(places, tmp_path):
    write(tmp_path / "elsewhere" / "auth.json", json.dumps({"OPENAI_API_KEY": "k"}))
    assert detect.codex_auth(with_env(places, CODEX_HOME=str(tmp_path / "elsewhere")))[:2] == (True, "apikey")


# ---------- 检测：DeepSeek Harness ----------

def test_dsh_on_path_with_account_login(places, tmp_path):
    write(tmp_path / "bin" / "dsh.cmd", "@echo off\n")
    write(places.home / ".dsh" / ".credentials.yaml", "version: 1\nrecords:\n  deepseek-account-platform/default:\n"
          "    kind: grant\n    payload:\n      token: secret\n  other/thing:\n    kind: grant\n")
    tool = detect.scan(places).dsh
    assert (tool.installed, tool.via, tool.configured, tool.auth) == (True, "cli", True, "account")


def test_dsh_desktop_without_login(places):
    write(detect.dsh_desktop(places) / "resources" / "runtime" / "cli" / "bin" / "dsh.cmd", "")
    tool = detect.scan(places).dsh
    assert tool.installed and tool.via == "desktop" and not tool.configured


def test_credential_names_only_reads_record_names(tmp_path):
    path = write(tmp_path / "c.yaml", "version: 1\nrecords:\n  a/b:\n    payload:\n      token: x\n"
                 "  'c/d':\n    kind: grant\nrefs:\n  DEEPSEEK_API_KEY: secret\nother:\n  e/f:\n")
    assert detect._yaml_keys(path, "records") == {"a/b", "c/d"}
    assert detect._yaml_keys(path, "refs") == {"DEEPSEEK_API_KEY"}


def test_dsh_api_key_sources(places):
    assert detect.dsh_auth(with_env(places, DEEPSEEK_API_KEY="k"))[:2] == (True, "apikey")
    write(places.home / ".dsh" / ".env", "# 注释\nDEEPSEEK_API_KEY=sk-x\n")
    assert detect.dsh_auth(places)[:2] == (True, "apikey")


# ---------- 流程 ----------

def report_of(claude=(True, True), codex=(True, True), dsh=(False, False)) -> detect.Report:
    def tool(name, state):
        return detect.Tool(name, installed=state[0], configured=state[1])
    return detect.Report(tool("claude", claude), tool("codex", codex), tool("dsh", dsh))


def test_ready_machine_needs_no_setup():
    assert not flow.needs_setup(report_of(), use_dsh=False, done=False)


def test_first_run_with_missing_codex_and_no_dsh_installs_it():
    r = report_of(codex=(False, False))
    assert flow.needs_setup(r, use_dsh=False, done=False)
    assert flow.auto_install(r) == ["codex"]
    assert not flow.should_ask(r, decided=False)
    # 准备过一次以后：Claude 能用就不再打扰
    assert not flow.needs_setup(r, use_dsh=False, done=True)


def test_dsh_present_asks_instead_of_installing_and_can_be_used_alone():
    r = report_of(claude=(False, False), codex=(False, False), dsh=(True, True))
    assert flow.auto_install(r) == []
    assert flow.should_ask(r, decided=False)
    assert not flow.should_ask(r, decided=True)
    # 别的都用不了而 DSH 能用：直接能开始，DSH 参与
    assert flow.use_dsh(r, chose_dsh=False, enabled=False)
    assert flow.can_start(r, chose_dsh=False, enabled=False)


def test_dsh_stays_optional_when_core_engines_work():
    r = report_of(dsh=(True, True))
    assert not flow.use_dsh(r, chose_dsh=False, enabled=False)
    assert flow.use_dsh(r, chose_dsh=True, enabled=False)
    assert flow.use_dsh(r, chose_dsh=False, enabled=True)


def test_nothing_usable_always_needs_setup():
    r = report_of(claude=(True, False), codex=(True, False), dsh=(True, False))
    assert flow.needs_setup(r, use_dsh=True, done=True)
    assert not flow.can_start(r, chose_dsh=True, enabled=True)


def test_typed_model_becomes_the_only_enabled_one():
    eng = config.EngineSettings(models=[config.ModelEntry("claude-opus-5-5", True)])
    flow.only_model(eng, "claude-sonnet-5-5")
    assert [(m.id, m.enabled) for m in eng.models] == [("claude-sonnet-5-5", True), ("claude-opus-5-5", False)]


def test_fit_models_turns_off_unserved_and_picks_strongest():
    eng = config.EngineSettings(models=[config.ModelEntry("claude-opus-5-5", True)])
    found = ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-sonnet-5-5"]
    eng.merge_discovered(found)
    assert flow.fit_models(eng, "claude", found)
    assert [m.id for m in eng.enabled_models()] == ["claude-sonnet-5-5"]
    # 服务确实提供打开着的模型：不动
    assert not flow.fit_models(eng, "claude", found)


# ---------- 自定义服务地址：写配置 ----------

def test_base_url_normalization():
    assert configure.claude_base("relay.example.com/v1/") == "https://relay.example.com"
    assert configure.openai_base("https://relay.example.com") == "https://relay.example.com/v1"
    assert configure.openai_base("https://relay.example.com/openai/v1/") == "https://relay.example.com/openai/v1"
    assert configure.claude_base("") == configure.openai_base("") == ""


def test_save_claude_merges_env_and_keeps_other_settings(tmp_path):
    path = write(tmp_path / "settings.json", json.dumps(
        {"env": {"ANTHROPIC_API_KEY": "old", "OTHER": "1"}, "model": "opus", "permissions": {"allow": ["Read"]}}))
    configure.save_claude(path, "relay.example.com", "new-key")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["env"] == {"OTHER": "1", "ANTHROPIC_BASE_URL": "https://relay.example.com",
                           "ANTHROPIC_AUTH_TOKEN": "new-key"}
    assert data["model"] == "opus" and data["permissions"] == {"allow": ["Read"]}
    assert (tmp_path / "settings.json.super-aide.bak").exists()


def test_save_claude_refuses_broken_json(tmp_path):
    path = write(tmp_path / "settings.json", "{not json")
    with pytest.raises(configure.ConfigError):
        configure.save_claude(path, "", "k")
    assert path.read_text(encoding="utf-8") == "{not json"


def test_save_codex_adds_provider_and_keeps_the_rest(tmp_path, monkeypatch):
    saved = {}
    monkeypatch.setattr(configure.winenv, "set_user_env", lambda name, value: saved.update({name: value}))
    original = ('# 我的配置\nmodel = "gpt-6-astra"\nmodel_provider = "old"\n\n[model_providers.old]\n'
                'base_url = "https://old.example.com/v1"\nenv_key = "OLD"\n\n[features]\nfoo = true # 注释\n')
    path = write(tmp_path / "config.toml", original)
    configure.save_codex(path, "https://relay.example.com", "k", "gpt-6-sol")
    text = path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["model_provider"] == configure.CODEX_PROVIDER and data["model"] == "gpt-6-sol"
    assert data["model_providers"][configure.CODEX_PROVIDER] == {
        "name": "Custom", "base_url": "https://relay.example.com/v1", "env_key": configure.CODEX_KEY_ENV,
        "wire_api": "responses"}
    assert data["model_providers"]["old"]["env_key"] == "OLD" and data["features"] == {"foo": True}
    assert "# 我的配置" in text and "# 注释" in text
    assert saved == {configure.CODEX_KEY_ENV: "k"}
    # 再配一次：替换同一张表，不重复
    configure.save_codex(path, "https://other.example.com/v1", "k2")
    text = path.read_text(encoding="utf-8")
    assert text.count(f"[model_providers.{configure.CODEX_PROVIDER}]") == 1
    assert tomllib.loads(text)["model_providers"][configure.CODEX_PROVIDER]["base_url"] == "https://other.example.com/v1"


def test_set_top_key_inserts_before_first_table():
    text = configure.set_top_key("[a]\nx = 1\n", "model_provider", "p")
    assert text.startswith('model_provider = "p"\n') and tomllib.loads(text)["a"] == {"x": 1}
    assert configure.set_top_key("", "model", "m") == 'model = "m"\n'


# ---------- 自定义服务地址：测试连接 ----------

class FakeService(BaseHTTPRequestHandler):
    status = 200
    body = {"data": [{"id": "claude-opus-5-5"}, {"id": "gpt-6-astra"}]}
    seen: list[dict] = []

    def do_GET(self):  # noqa: N802
        FakeService.seen.append({"path": self.path, **dict(self.headers)})
        payload = json.dumps(self.body).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def service():
    server = HTTPServer(("127.0.0.1", 0), FakeService)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FakeService.status, FakeService.seen = 200, []
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_check_lists_models(service):
    result = configure.check("claude", service, "k")
    assert result.ok and result.verified and result.models == ["claude-opus-5-5"]
    assert FakeService.seen[-1]["path"].startswith("/v1/models")
    result = configure.check("codex", service, "k")
    assert result.ok and result.models == ["claude-opus-5-5", "gpt-6-astra"]
    assert FakeService.seen[-1]["Authorization"] == "Bearer k"


def test_check_reports_bad_key_and_unlisted_service(service):
    FakeService.status = 401
    assert not configure.check("codex", service, "k").ok
    FakeService.status = 404
    result = configure.check("codex", service, "k")
    assert result.ok and not result.verified


def test_check_unreachable_and_missing_key():
    assert not configure.check("claude", "http://127.0.0.1:9", "k").ok
    assert configure.check("claude", "", " ").message == "请填写密钥"


# ---------- 安装 ----------

def test_npm_error_picks_a_readable_reason():
    out = "npm error code ETIMEDOUT\nnpm error errno ETIMEDOUT\nnpm error A complete log of this run can be found"
    assert install.npm_error(out) == "连接超时"
    out = "npm error code E404\nnpm error 404 Not Found - GET https://x/@a%2fb - Not found\nnpm error A complete log"
    assert install.npm_error(out).startswith("404 Not Found")
    assert install.npm_error("npm error code EBUSY\n", "codex") == "文件被占用（先关掉正在运行的 Codex）"


def test_latest_lts_skips_current_and_old_releases():
    index = [{"version": "v26.1.0", "lts": False, "files": ["win-x64-zip"]},
             {"version": "v24.21.0", "lts": "Krypton", "files": ["win-x64-zip", "win-arm64-zip"]},
             {"version": "v20.19.0", "lts": "Iron", "files": ["win-x64-zip"]}]
    assert install.latest_lts(index) == "v24.21.0"
    with pytest.raises(install.InstallError):
        install.latest_lts(index[2:])


def test_unreachable_sources_are_skipped(monkeypatch):
    monkeypatch.setattr(install, "_probe", lambda url: "mirror" in url)
    sources = (("官方源", "https://official"), ("镜像", "https://mirror"))
    assert install._reachable(sources, "/-/ping") == [("镜像", "https://mirror")]
    monkeypatch.setattr(install, "_probe", lambda url: False)
    assert install._reachable(sources, "/-/ping") == list(sources)  # 都探不通：全试一遍
