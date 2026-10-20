"""模型服务出问题时换模型接着做（2026-10-14 实测：Codex 换成中转服务后，deepseek-flash 连着四问都是 502，
可别的引擎都没在路由里，路由只会"换引擎"，同一个引擎的别的模型一次也没试）。

- 这个模型用不了（没提供、没开通、没渠道）只歇这个模型；限流、过载只有一个引擎时也只歇这个模型，有别的引擎就歇整个引擎；
- 首问换模型从头答，追问换到同一个引擎的模型时对话接着来、原样再问，换了引擎就带上前面的问答；
- "这个模型用不了"不算能力失败（路由、自我改进都不记）。"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from super_aide import paths
from super_aide.config import Config, EngineSettings, ModelEntry
from super_aide.decision import Decider
from super_aide.engines import hub as hub_module
from super_aide.engines.base import MODEL_UNAVAILABLE, Event, friendly_text
from super_aide.engines.hub import Conversation, EngineHub, failure_kind
from super_aide.evolve import triggers
from super_aide.router import EngineRouter, Task

BAD_GATEWAY = "unexpected status 502 Bad Gateway: <html><head><title>502 Bad Gateway</title></head></html>"
NO_MODEL = "The model `deepseek-flash` does not exist or you do not have access to it."
CODEX_META = {"gpt-6-astra": {"desc": "Frontier intelligence for the most demanding work."},
              "gpt-6.1-sol": {"desc": "Latest workhorse model for coding and everyday work."}}


@pytest.fixture(autouse=True)
def isolated_router_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ROUTER", tmp_path)
    (tmp_path / "models.json").write_text(json.dumps({"codex": CODEX_META}), encoding="utf-8")


def codex_only(*models: str) -> EngineRouter:
    cfg = Config(claude=EngineSettings(models=[ModelEntry("claude-opus-5-5", True)]),
                 codex=EngineSettings(models=[ModelEntry(m, True) for m in models]))
    router = EngineRouter(cfg, gui_official=False)
    router.set_ready(["codex"])
    return router


# ---------- 认出是哪种问题 ----------

@pytest.mark.parametrize("text", [
    NO_MODEL,
    "The 'gpt-5.5' model is not supported when using Codex with a ChatGPT account.",
    'API Error: 404 {"type":"error","error":{"type":"not_found_error","message":"model: claude-opus-9"}}',
    "当前分组 default 下对于模型 deepseek-flash 无可用渠道",
    "no available channel for group default and model deepseek-flash",
    "UNKNOWN_MODEL: deepseek-flash is not configured on route self",
    "There's an issue with the selected model (claude-x). It may not exist or you may not have access to it.",
])
def test_model_unavailable_messages(text):
    assert MODEL_UNAVAILABLE.search(text)
    assert failure_kind({"ok": False, "reason": "failed", "error": text}) == "model"
    assert triggers.is_infra({"ok": False, "reason": "failed", "error": text})  # 不算能力失败
    assert friendly_text(text).startswith("这个模型现在用不了")


@pytest.mark.parametrize("text", [
    "ModuleNotFoundError: No module named 'pandas'",
    "没完成：模型文件下载失败",
    "Your input exceeds the context window of this model",
])
def test_ordinary_errors_are_not_model_unavailable(text):
    assert not MODEL_UNAVAILABLE.search(text)


def test_failure_kinds():
    assert failure_kind({"ok": False, "reason": "failed", "error": BAD_GATEWAY}) == "service"
    assert failure_kind({"ok": False, "api_error_status": 529}) == "service"
    assert failure_kind({"ok": False, "api_error_status": 404}) == "model"
    assert failure_kind({"ok": False, "error": "401 Unauthorized: invalid api key"}) == "auth"
    assert failure_kind({"ok": False, "reason": "reported", "error": "没完成：网络设置里找不到"}) == ""
    assert failure_kind({"ok": False, "stopped": True, "error": BAD_GATEWAY}) == ""
    assert failure_kind({"ok": False, "error": "KeyError: 'x'"}) == ""
    assert failure_kind({"ok": True}) == ""


# ---------- 路由：放一边 ----------

def test_a_missing_model_is_benched_and_the_next_one_is_chosen():
    r = codex_only("gpt-6-astra", "gpt-6.1-sol")
    task = Task("ask", "这是什么", "text")
    assert r.decide(task).model == "gpt-6-astra"
    assert r.sideline("codex", "gpt-6-astra", "model")
    assert r.available() == ["codex"] and r.decide(task).model == "gpt-6.1-sol"
    assert r.best_model("codex") == "gpt-6.1-sol"
    r.set_ready(["codex"])  # 重新配了服务：之前用不了的模型再试
    assert r.decide(task).model == "gpt-6-astra"


def test_outage_with_one_engine_benches_only_the_model():
    r = codex_only("gpt-6-astra", "gpt-6.1-sol")
    assert r.sideline("codex", "gpt-6-astra", "service")
    assert "codex" in r.available() and r.best_model("codex") == "gpt-6.1-sol"


def test_outage_with_another_engine_benches_the_whole_engine():
    r = codex_only("gpt-6-astra", "gpt-6.1-sol")
    r.set_ready(["codex", "claude"])
    assert r.sideline("codex", "gpt-6-astra", "service")
    assert r.available() == ["claude"]


def test_the_last_model_is_never_benched():
    r = codex_only("gpt-6-astra")
    assert not r.sideline("codex", "gpt-6-astra", "model")
    assert not r.sideline("codex", "gpt-6-astra", "auth")
    assert r.available() == ["codex"] and r.best_model("codex") == "gpt-6-astra"


# ---------- 中枢：同一问换模型接着做 ----------

class Session:
    def __init__(self, model, script):
        self.model, self.script, self.sent, self.closed = model, script, [], False

    async def send(self, text, images):
        self.sent.append(text)
        if self.script == "down":
            yield Event("error", BAD_GATEWAY)
            yield Event("done", data={"ok": False, "reason": "failed", "error": BAD_GATEWAY})
            return
        yield Event("new_message")
        yield Event("delta", f"{self.model} 的回答")
        yield Event("done", data={"ok": True})

    async def close(self):
        self.closed = True


class Engine:
    """每个模型一个会话脚本：down = 502，ok = 答完。"""

    def __init__(self, scripts):
        self.scripts, self.opened, self.switched = scripts, [], []

    async def open(self, mode, model, effort):
        self.opened.append(model)
        return Session(model, self.scripts[model])

    async def switch(self, session, mode, model, effort):
        self.switched.append(model)
        session.model, session.script = model, self.scripts[model]
        return session


class Hub:
    _first_turn, _followup, _open, _turn = EngineHub._first_turn, EngineHub._followup, EngineHub._open, EngineHub._turn
    _sideline, _hand_over, _emit_route = EngineHub._sideline, EngineHub._hand_over, EngineHub._emit_route
    is_busy, _drop_sessions = EngineHub.is_busy, EngineHub._drop_sessions

    def __init__(self, router, engines):
        self.router, self.engines, self.conversations, self.gui = router, engines, {}, "ours"
        self.loop, self.events = asyncio.get_running_loop(), []
        self.decider = Decider(Config())  # 没配置判断模型：照原来的做法

    def _emit(self, key, ev):
        self.events.append(ev)

    def _recall(self, conv, situation):
        return []

    _understand = _recall

    def _vector(self, question, text):
        return None

    def _notes(self, conv):
        return []

    def _save_history(self, conv, done, answer, trace=None):
        conv.record.append({"question": conv.question, "answer": answer, "ok": bool(done.get("ok"))})

    def _noop(self, *args, **kwargs):
        return None

    _check_reask = _check_outcome = _watch_outcome = _learn_from_turn = _after_first_turn = _noop
    _lessons_used = _schedule_learning = _schedule_evolve = _crashed = _noop

    async def _escalate(self, conv):
        return None


def snapshot():
    ctx = SimpleNamespace(images=[])
    return SimpleNamespace(dir=None, url="", finalize=lambda: ctx,
                           situation=lambda q: SimpleNamespace(text="", errors=""))


def test_first_question_moves_to_another_model_of_the_same_engine(monkeypatch):
    monkeypatch.setattr(hub_module.prompts, "first_message", lambda q, ctx, mode, notes=None, lessons=None: "消息")
    codex = Engine({"gpt-6-astra": "down", "gpt-6.1-sol": "ok"})

    async def scenario():
        hub = Hub(codex_only("gpt-6-astra", "gpt-6.1-sol"), {"codex": codex})
        conv = Conversation(key="k", mode="ask", task=Task("ask", "这是什么", "text"), busy=True)
        await hub._first_turn(conv, "这是什么", snapshot())
        return hub, conv

    hub, conv = asyncio.run(asyncio.wait_for(scenario(), 5))
    done = [e for e in hub.events if e.type == "done"]
    assert len(done) == 1 and done[0].data["ok"]                         # 你只看到换过去的那个答完了
    assert not any(e.type == "error" for e in hub.events)                # 前一个的 502 不出现在界面上
    assert codex.opened == ["gpt-6-astra", "gpt-6.1-sol"] and conv.decision.model == "gpt-6.1-sol"
    status = [e.text for e in hub.events if e.type == "status"]
    assert "gpt-6-astra 服务暂时不可用，换 gpt-6.1-sol 接着做…" in status
    assert [e.data["model"] for e in hub.events if e.type == "route"] == ["gpt-6-astra", "gpt-6.1-sol"]


def test_gives_up_after_a_few_tries_and_says_why(monkeypatch):
    monkeypatch.setattr(hub_module.prompts, "first_message", lambda q, ctx, mode, notes=None, lessons=None: "消息")
    models = ("gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna", "gpt-6-mini")
    codex = Engine({m: "down" for m in models})

    async def scenario():
        hub = Hub(codex_only(*models), {"codex": codex})
        conv = Conversation(key="k", mode="ask", task=Task("ask", "这是什么", "text"), busy=True)
        await hub._first_turn(conv, "这是什么", snapshot())
        return hub

    hub = asyncio.run(asyncio.wait_for(scenario(), 5))
    assert len(codex.opened) == 1 + hub_module.MAX_HANDOVERS               # 最多试三个，不会一直换下去
    done = [e for e in hub.events if e.type == "done"]
    assert len(done) == 1 and not done[0].data["ok"]
    assert done[0].data["error"] == "模型服务暂时不可用，稍后再试。"


def test_followup_switches_model_in_the_same_session(monkeypatch):
    monkeypatch.setattr(hub_module.prompts, "followup_message", lambda q, ctx, mode, notes=None, lessons=None: q)
    codex = Engine({"gpt-6-astra": "down", "gpt-6.1-sol": "ok"})

    async def scenario():
        router = codex_only("gpt-6-astra", "gpt-6.1-sol")
        hub = Hub(router, {"codex": codex})
        conv = Conversation(key="k", mode="ask", task=Task("ask", "这是什么", "text"), busy=True)
        conv.decision = router.decide(conv.task)
        conv.session = Session("gpt-6-astra", "down")
        await hub._followup(conv, "再说详细点", snapshot())
        return hub, conv

    hub, conv = asyncio.run(asyncio.wait_for(scenario(), 5))
    assert codex.switched == ["gpt-6.1-sol"] and codex.opened == []      # 对话接着来，没有新开会话
    assert conv.session.sent == ["再说详细点", "再说详细点"]                 # 原样再问一遍
    assert [e for e in hub.events if e.type == "done"][0].data["ok"]


def test_followup_on_another_engine_carries_the_conversation(monkeypatch):
    seen = []
    monkeypatch.setattr(hub_module.prompts, "followup_message",
                        lambda q, ctx, mode, notes=None, lessons=None: seen.append(list(notes or [])) or q)
    codex, claude = Engine({"gpt-6-astra": "down"}), Engine({"claude-opus-5-5": "ok"})

    async def scenario():
        router = codex_only("gpt-6-astra")
        router.set_ready(["codex", "claude"])
        hub = Hub(router, {"codex": codex, "claude": claude})
        conv = Conversation(key="k", mode="ask", task=Task("ask", "这是什么", "text"), busy=True)
        conv.decision = router.decide(conv.task)
        conv.decision.engine, conv.decision.model = "codex", "gpt-6-astra"
        conv.session = Session("gpt-6-astra", "down")
        conv.record = [{"question": "这是什么", "answer": "这是一个报错提示。", "ok": True}]
        await hub._followup(conv, "怎么修", snapshot())
        return hub, conv

    hub, conv = asyncio.run(asyncio.wait_for(scenario(), 5))
    assert claude.opened == ["claude-opus-5-5"] and conv.decision.engine == "claude"
    assert seen[0] == [] and "问：这是什么\n答：这是一个报错提示。" in seen[1][0]  # 新引擎看得到前面的问答
    assert "Codex 服务暂时不可用，换 Claude 接着做…" in [e.text for e in hub.events if e.type == "status"]
