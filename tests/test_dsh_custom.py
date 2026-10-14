"""DeepSeek Harness 用自定义服务地址（2026-10-14：你在 DSH 里配了中转服务，Super Aide 却一直用 DeepSeek 账号，
准备窗口里 DSH 也没有"自定义服务地址"和"更改"）。

- 照 DSH 自己的模型设置来：默认用的是自定义的服务，就把它的路由定义带进 ACP 的配置；
- 准备窗口里填的写进 DSH 的模型设置（路由 super-aide），DSH 桌面版里看得到；密钥写进 ~/.dsh/.env；
- 测试连接时自己认出是哪种接口（Responses / Chat Completions / Anthropic Messages）。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from super_aide.config import EngineSettings, ModelEntry
from super_aide.engines import dsh
from super_aide.setup import configure, detect, dshconf, flow

#: 照着 2026-10-14 你机器上 DSH 桌面版的模型设置（地址换掉了）
DESKTOP = """# Your patch layer for this dsh profile, applied after every bundle layer:
# a top-level YAML array of loader patch entries (id-targeted config
# overrides, disables, and insert lists; `!!js` expressions allowed).
- id: agent-default-model
  name: "@deepseek-ai/dsh-agent-default-model"
  config:
    provider: self
    model: DeepSeek-V4.1-Flash
    reasoningEffort: max
- id: ui-chat
  name: "@deepseek-ai/dsh-client-ui-chat"
  config:
    transcriptView: compact
- id: llm-pi-ai
  name: "@deepseek-ai/dsh-llm-pi-ai"
  config:
    providers:
      # Custom gateway speaking the OpenAI Responses protocol.
      self:
        displayName: DeepSeek V4.1 Flash
        apiKeyEnv: SELF_API_KEY
        api: openai-responses
        baseURL: https://gw.example.cn:58043/v1
        # Default thinking level; the composer can override it per session.
        reasoning: high
        models:
          - id: DeepSeek-V4.1-Flash
            name: DeepSeek-V4.1-Flash
            contextWindow: 1048576
            input:
              - text
              - image
            reasoningEfforts:
              off:
              low: low
              high: high
"""


@pytest.fixture
def home(tmp_path):
    return tmp_path / ".dsh"


def desktop(home, text=DESKTOP):
    path = dshconf.patch_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------- 读 DSH 的模型设置 ----------

def test_reads_the_custom_route_dsh_is_set_to(home):
    desktop(home)
    r = dshconf.read(home)
    assert (r.provider, r.model, r.custom) == ("self", "DeepSeek-V4.1-Flash", True)
    assert (r.base, r.key_env, r.models) == ("https://gw.example.cn:58043/v1", "SELF_API_KEY", ("DeepSeek-V4.1-Flash",))
    assert r.block.startswith("- id: llm-pi-ai\n") and "reasoningEfforts:" in r.block and "ui-chat" not in r.block


def test_builtin_providers_and_missing_files_are_not_custom(home):
    assert dshconf.read(home) == dshconf.Route()
    desktop(home, DESKTOP.replace("provider: self", "provider: deepseek-account"))
    r = dshconf.read(home)
    assert r.provider == "deepseek-account" and not r.custom and not r.block


def test_the_acp_patch_carries_the_route(tmp_path, home):
    desktop(home)
    text = dsh.patch_text("ask", dshconf.read(home), "指令", tmp_path)
    assert 'provider: "self"' in text and 'model: "DeepSeek-V4.1-Flash"' in text
    assert "\n- id: llm-pi-ai\n" in text and "apiKeyEnv: SELF_API_KEY" in text
    assert 'provider: "deepseek-account"' in dsh.patch_text("ask", "deepseek-account", "指令", tmp_path)


# ---------- 写 DSH 的模型设置 ----------

def test_saving_adds_our_route_and_keeps_everything_else(home):
    path = desktop(home)
    dshconf.save_route(home, "https://relay.example.com/v1", dshconf.KEY_ENV, "openai-completions", ["ds-chat", "ds-r1"])
    text = path.read_text(encoding="utf-8")
    assert "# Custom gateway speaking" in text and "transcriptView: compact" in text and "reasoningEffort: max" in text
    assert "      self:\n        displayName: DeepSeek V4.1 Flash" in text  # 你自己的路由原样还在
    r = dshconf.read(home)
    assert (r.provider, r.model, r.custom, r.base) == ("super-aide", "ds-chat", True, "https://relay.example.com/v1")
    assert r.models == ("ds-chat", "ds-r1") and r.key_env == dshconf.KEY_ENV
    assert path.with_name(path.name + ".super-aide.bak").read_text(encoding="utf-8") == DESKTOP
    # 再存一次：换掉我们的那一条，不会多出一条
    dshconf.save_route(home, "https://other.example.com/v1", dshconf.KEY_ENV, "openai-responses", ["m"])
    text = path.read_text(encoding="utf-8")
    assert text.count("super-aide:") == 1 and "relay.example.com" not in text
    assert dshconf.read(home).models == ("m",)
    # 改回 DeepSeek 官方：默认模型改回去，路由留着（DSH 里还能选）
    dshconf.use_builtin(home, "deepseek-official", "deepseek-flash")
    r = dshconf.read(home)
    assert (r.provider, r.model, r.custom) == ("deepseek-official", "deepseek-flash", False)


def test_saving_into_a_fresh_profile(home):
    dshconf.save_route(home, "https://relay.example.com", dshconf.KEY_ENV, "anthropic-messages", ["claude-x"])
    text = dshconf.patch_path(home).read_text(encoding="utf-8")
    assert text.startswith("# Your patch layer") and text.count("- id: ") == 2
    assert dshconf.read(home).custom


def test_a_file_in_another_format_is_left_alone(home):
    desktop(home, '[{"id": "agent-default-model", "config": {"provider": "self"}}]\n')
    with pytest.raises(dshconf.DshConfigError):
        dshconf.save_route(home, "https://x/v1", dshconf.KEY_ENV, "openai-responses", ["m"])
    path = desktop(home, '- id: agent-default-model\n  config: {provider: self, model: X}\n')  # config 写成了一行
    with pytest.raises(dshconf.DshConfigError):
        dshconf.save_route(home, "https://x/v1", dshconf.KEY_ENV, "openai-responses", ["m"])
    assert path.read_text(encoding="utf-8") == '- id: agent-default-model\n  config: {provider: self, model: X}\n'


def test_hand_edited_four_space_files_stay_valid(home):
    """手改过、下一层缩进四格的文件：新加的行跟着文件的缩进走（实测原来插到了更深的行上面，YAML 就坏了）。"""
    yaml = pytest.importorskip("yaml")
    path = desktop(home, "- id: agent-default-model\n  config:\n      provider: self\n      reasoningEffort: max\n"
                         "- id: llm-pi-ai\n  config:\n      foo: 1\n")
    dshconf.save_route(home, "https://x/v1", dshconf.KEY_ENV, "openai-responses", ["m"])
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    default, pi = data[0]["config"], data[1]["config"]
    assert default == {"provider": "super-aide", "model": "m", "reasoningEffort": "max"}
    assert pi["foo"] == 1 and list(pi["providers"]) == ["super-aide"]
    assert pi["providers"]["super-aide"]["models"] == [{"id": "m"}]
    assert dshconf.read(home).custom


def test_the_written_file_is_valid_yaml(home):
    yaml = pytest.importorskip("yaml")
    path = desktop(home)
    dshconf.save_route(home, "https://relay.example.com/v1", dshconf.KEY_ENV, "openai-completions", ["a", "b"])
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    providers = next(x for x in data if x["id"] == "llm-pi-ai")["config"]["providers"]
    assert set(providers) == {"self", "super-aide"} and providers["self"]["apiKeyEnv"] == "SELF_API_KEY"
    assert next(x for x in data if x["id"] == "agent-default-model")["config"]["provider"] == "super-aide"


def test_env_file_keeps_other_lines(home):
    env = home / ".env"
    env.parent.mkdir(parents=True)
    env.write_text("# 我的\nOTHER=1\nSUPER_AIDE_DSH_API_KEY=old\n", encoding="utf-8")
    dshconf.set_env(env, dshconf.KEY_ENV, "sk-new")
    assert env.read_text(encoding="utf-8") == "# 我的\nOTHER=1\nSUPER_AIDE_DSH_API_KEY=sk-new\n"


# ---------- 检测：配没配好 ----------

def places(tmp_path, monkeypatch, **env):
    monkeypatch.setattr(detect, "_dsh_registered", lambda p: "")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return detect.Places(home=home, local=tmp_path, roaming=tmp_path, env=env)


def test_custom_route_counts_as_configured_once_its_key_exists(tmp_path, monkeypatch):
    p = places(tmp_path, monkeypatch)
    desktop(detect.dsh_dir(p))
    assert detect.dsh_auth(p) == (False, "", "自定义服务地址还没有密钥（SELF_API_KEY）")
    (detect.dsh_dir(p) / ".credentials.yaml").write_text("refs:\n  SELF_API_KEY: x\n", encoding="utf-8")
    assert detect.dsh_auth(p) == (True, "custom", "自定义服务地址 gw.example.cn")
    assert dsh.route(p).provider == "self"


# ---------- 测试连接：认出是哪种接口 ----------

class Gateway(BaseHTTPRequestHandler):
    """只有 Chat Completions 的中转（很常见）。"""
    paths: list[str] = []
    status = 200

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        Gateway.paths.append(self.path)
        ok = self.path.endswith("/chat/completions")
        code = Gateway.status if ok or Gateway.status == 401 else 404
        if ok and body.get("model") == "nope":
            code = 400
        payload = json.dumps({"choices": [{"message": {"content": "pong"}}]} if code == 200
                             else {"error": {"message": "model not found"}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def gateway():
    server = HTTPServer(("127.0.0.1", 0), Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    Gateway.paths, Gateway.status = [], 200
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


def test_check_finds_the_protocol_that_works(gateway):
    result = configure.check("dsh", gateway, "sk-1", "ds-chat, ds-r1")
    assert result.ok and result.api == "openai-completions"
    assert Gateway.paths == ["/v1/responses", "/v1/chat/completions"]


def test_wrong_key_stops_at_the_first_try(gateway):
    Gateway.status = 401
    result = configure.check("dsh", gateway, "sk-bad", "ds-chat")
    assert not result.ok and result.message.startswith("密钥不对") and Gateway.paths == ["/v1/responses"]


def test_a_wrong_model_is_reported_as_such(gateway):
    """只有 Chat Completions 的中转、模型名填错了：说模型不对，不说"这个地址上没有对应的接口"（那会让人去改地址）。"""
    result = configure.check("dsh", gateway, "sk-1", "nope")
    assert not result.ok and "没有模型 nope" in result.message


def test_model_is_required_with_an_address():
    assert configure.check("dsh", "https://x/v1", "sk", "").message.startswith("请在“模型”里填")


def test_save_writes_dsh_config_and_key(tmp_path, monkeypatch):
    p = places(tmp_path, monkeypatch)
    used, _ = configure.save("dsh", "relay.example.com", "sk-9", "ds-chat，ds-r1", places=p, api="openai-completions")
    assert used == "ds-chat,ds-r1"
    r = dshconf.read(detect.dsh_dir(p))
    assert r.base == "https://relay.example.com/v1" and r.models == ("ds-chat", "ds-r1")
    assert "SUPER_AIDE_DSH_API_KEY=sk-9" in (detect.dsh_dir(p) / ".env").read_text(encoding="utf-8")
    assert detect.dsh_auth(p)[:2] == (True, "custom")
    engine = EngineSettings(models=[ModelEntry("deepseek-flash", True)])
    flow.only_model(engine, used)  # 填的几个模型都打开，原来的 DeepSeek 模型关掉
    assert [(m.id, m.enabled) for m in engine.models] == [("ds-chat", True), ("ds-r1", True), ("deepseek-flash", False)]


# ---------- 思考强度：只设模型支持的那一档 ----------

def test_only_legal_efforts_are_sent():
    session = dsh.DshSession.__new__(dsh.DshSession)
    session.efforts = ["off", "low", "high", "max"]
    assert [session._legal(e) for e in ("low", "medium", "high", "xhigh", "max")] == ["low", "low", "high", "high", "max"]
    session.efforts = []  # 不是推理模型：不设，用它自己的默认
    assert session._legal("high") == ""
