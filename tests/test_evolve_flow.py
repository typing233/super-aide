"""自我改进的流程（假的引擎和测试环境）：建议、失败 → 初筛 → 准备 → 修改 → 检查 → 复核 → 打包 → 待你确认生效；
断网续上、检查没过交回去改、模型不可用换一个、生效后的处理、版本更新后的搬迁；引擎中枢的触发；扩展包同步。"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from super_aide import app as app_module
from super_aide import paths
from super_aide.config import Config
from super_aide.decision import Decider
from super_aide.engines.hub import EVOLVE_HOLD, Conversation, EngineHub
from super_aide.evolve import agent, manager, prompts
from super_aide.evolve.agent import Outcome
from super_aide.evolve.jobs import Jobs
from super_aide.evolve.manager import EvolveManager
from super_aide.evolve.testenv import TestEnv, TestRun
from super_aide.router import Decision, Task

from test_evolve_core import fake_install

QCoreApplication.instance() or QCoreApplication([])

RESULT = {"action": "changed", "title_zh": "停下后把焦点还回去", "title_en": "Return focus after stop",
          "summary_zh": "改了 app.py。", "summary_en": "Changed app.py.", "cause": "app.main", "tests": "test_x",
          "risk": "小"}


class FakeAgent:
    """按要的结论（schema）给出回答；implement 时顺手改一下工作台里的代码。"""

    def __init__(self, work: Path) -> None:
        self.work = work
        self.calls: list[dict] = []
        self.script: dict[str, list[Outcome]] = {}  # 角色 → 先返回这些（比如断网），用完了再正常回答

    async def __call__(self, run, prompt, session, resume, on_step) -> Outcome:
        role = {id(prompts.TRIAGE_SCHEMA): "triage", id(prompts.REVIEW_SCHEMA): "review"}.get(id(run.schema), "implement")
        self.calls.append({"role": role, "prompt": prompt, "session": session, "resume": resume,
                           "model": run.choice.model, "read_only": run.read_only})
        on_step("正在读 app.py", "Read")
        queued = self.script.get(role)
        if queued:
            return queued.pop(0)
        if role == "triage":
            return Outcome(True, {"worth": True, "why": "代码的问题", "key": "停下后焦点"}, session=session)
        if role == "review":
            return Outcome(True, {"approve": True, "problems": [], "privacy": []}, session=session)
        (self.work / "src" / "super_aide" / "app.py").write_bytes(b"def main():\n    return 1\n")
        return Outcome(True, dict(RESULT), session=session, cost=1.5)


@pytest.fixture
def env(tmp_path, monkeypatch):
    env = SimpleNamespace(installed=fake_install(tmp_path / "inst"), test_results=[], tmp=tmp_path)
    monkeypatch.setattr(manager, "Installed", SimpleNamespace(current=lambda: env.installed))
    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(paths, "ROUTER", tmp_path / "router")
    runs = []

    def fake_run(self, select=None, timeout=0):
        runs.append(select)
        return env.test_results.pop(0) if env.test_results else TestRun(passed={"tests/test_x.py::test_x"})

    monkeypatch.setattr(TestEnv, "ensure", lambda self: None)
    monkeypatch.setattr(TestEnv, "run", fake_run)
    monkeypatch.setattr(TestEnv, "import_check", lambda self: [])
    monkeypatch.setattr(TestEnv, "node_check", lambda self, files: [])
    hub = SimpleNamespace(conversations={}, loop=None, _submit=lambda coro: coro.close())
    router = SimpleNamespace(ready={"claude", "codex"}, meta={})
    mgr = EvolveManager(Config(), hub, router, quit_app=lambda: None, root=tmp_path / "evolve")
    fake = FakeAgent(mgr.workshop.root)
    monkeypatch.setattr(agent, "run_claude", fake)
    notices = []
    mgr.notify.connect(lambda title, body: notices.append(title))
    env.mgr, env.agent, env.notices, env.runs = mgr, fake, notices, runs
    return env


def drive(mgr: EvolveManager, job, until=("ready", "done", "none", "covered", "failed", "held", "waiting", "login"),
          steps: int = 20) -> None:
    for _ in range(steps):
        asyncio.run(mgr._step())
        if job.status in until:
            return


def test_a_suggestion_ends_ready_and_waits_for_your_click(env):
    mgr = env.mgr
    resp = mgr.suggest("Esc 停下以后，我接着打的字丢了")
    job = mgr.jobs.get(resp["id"])
    drive(mgr, job)
    assert job.status == "ready" and job.version == "0.2.0+aide.1" and Path(job.wheel).exists()
    roles = [c["role"] for c in env.agent.calls]
    assert roles == ["implement", "review"]                    # 建议不初筛；复核另开一个只读会话
    assert env.agent.calls[1]["read_only"] and env.agent.calls[1]["session"] != env.agent.calls[0]["session"]
    assert "用户的建议" in env.agent.calls[0]["prompt"]
    patch = (mgr.jobs.folder(job) / "change.patch").read_text(encoding="utf-8")
    assert "+    return 1" in patch
    assert env.notices == ["超级助手开始自我改进", "自我改进好了：停下后把焦点还回去"]  # 不会自己装：等你点"生效"
    assert job.cost == 1.5 and mgr.snapshot()["items"][0]["status"] == "ready"
    second = mgr.suggest("回答再短一点")  # 待你确认的那个占着名额：下一个先排着
    asyncio.run(mgr._step())
    assert mgr.jobs.get(second["id"]).status == "queued"


def test_triage_says_not_our_problem(env):
    mgr = env.mgr
    env.agent.script["triage"] = [Outcome(True, {"worth": False, "why": "服务暂时不可用", "key": "服务不可用"})]
    data = {"conv": "k", "mode": "ask", "question": "这是什么", "foreground": "chrome.exe", "started": 1.0,
            "trouble": [{"kind": "failure", "error": "没完成：网页打不开"}], "record": []}
    job = mgr.submit(data)
    drive(mgr, job)
    assert job.status == "none" and "服务暂时不可用" in job.error
    assert env.notices == []  # 无需改进的不打扰
    again = mgr.submit(dict(data, conv="k2"))
    drive(mgr, again)
    assert again.status == "none" and len(env.agent.calls) == 1  # 同类问题记住了，不再初筛


def test_network_drop_waits_then_resumes_the_same_session(env):
    mgr = env.mgr
    env.agent.script["implement"] = [Outcome(False, kind="network", error="Connection reset")]
    job = mgr.jobs.get(mgr.suggest("建议")["id"])
    drive(mgr, job)
    assert job.status == "waiting" and job.retry_at > 0
    job.retry_at = 0
    drive(mgr, job)
    assert job.status == "ready"
    first, second = env.agent.calls[0], env.agent.calls[1]
    assert second["resume"] and second["session"] == first["session"] and second["prompt"] == prompts.RESUME


def test_failed_checks_go_back_to_the_same_session(env):
    mgr = env.mgr
    env.test_results += [TestRun(passed={"tests/test_x.py::test_x"}),                 # 基线
                         TestRun(passed=set(), failed={"tests/test_x.py::test_x"}),   # 改完：原来通过的失败了
                         TestRun(passed=set(), failed={"tests/test_x.py::test_x"})]   # 重跑一次还是失败
    job = mgr.jobs.get(mgr.suggest("建议")["id"])
    drive(mgr, job)
    assert job.status == "ready" and job.fixes == 1
    implement = [c for c in env.agent.calls if c["role"] == "implement"]
    assert "流程检查没有通过" in implement[1]["prompt"] and implement[1]["resume"]
    assert implement[1]["session"] == implement[0]["session"]


def test_unavailable_model_falls_back_to_the_next_best(env, monkeypatch):
    mgr = env.mgr
    env.agent.script["implement"] = [Outcome(False, kind="model", error="model not found")]
    codex_calls = []

    async def fake_codex(run, prompt, thread_id, on_step):
        codex_calls.append(run.choice)
        (mgr.workshop.root / "src" / "super_aide" / "app.py").write_bytes(b"def main():\n    return 2\n")
        return Outcome(True, dict(RESULT), session="thread-1")

    monkeypatch.setattr(agent, "run_codex", fake_codex)
    job = mgr.jobs.get(mgr.suggest("建议")["id"])
    drive(mgr, job)
    assert codex_calls and codex_calls[0].engine == "codex" and codex_calls[0].effort == "max"
    assert mgr.state["unavailable"]["claude|claude-opus-5-5"] > 0


def test_apply_writes_a_plan_and_starts_the_helper(env, monkeypatch):
    mgr = env.mgr
    job = mgr.jobs.get(mgr.suggest("建议")["id"])
    drive(mgr, job)
    started = []
    monkeypatch.setattr(manager.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    monkeypatch.setattr(manager.QTimer, "singleShot", lambda ms, fn: None)
    assert mgr.apply(job.id) == ""
    plan = json.loads((mgr.root / "apply-plan.json").read_text(encoding="utf-8"))
    assert plan["install"] == job.wheel and plan["fallback"] == job.prev_wheel
    assert plan["args"] == ["--evolved", job.id] and plan["fallback_args"] == ["--evolve-failed", job.id]
    assert (mgr.root / "apply.py").exists() and started[0][-2:] == [str(mgr.root / "apply.py"),
                                                                    str(mgr.root / "apply-plan.json")]
    assert job.status == "applying"


def test_after_restart_marks_applied_and_notifies(env, monkeypatch):
    mgr = env.mgr
    monkeypatch.setattr(manager.QTimer, "singleShot", lambda ms, fn: None)
    job = mgr.jobs.get(mgr.suggest("建议")["id"])
    drive(mgr, job)
    mgr.jobs.update(job, status="applying")
    mgr._after_apply(job.id, "", "")
    assert job.status == "done" and job.applied > 0 and "已完成自我改进" in env.notices
    assert not (mgr.jobs.folder(job) / "evidence").exists()  # 证据删掉，补丁留着
    monkeypatch.setattr(manager, "__version__", job.version)  # 重启以后跑的就是这次改进打出来的版本
    assert mgr.snapshot()["items"][0]["can_undo"]
    # 之后装了官方新版本（已经包含这个改进）：再撤销就是装回旧的包，等于把整个应用降回旧版本
    monkeypatch.setattr(manager, "__version__", "0.3.0")
    assert not mgr.snapshot()["items"][0]["can_undo"]
    assert mgr.undo(job.id) == "装过新版本以后，这次改进不能再单独撤销"


def test_official_update_queues_a_carry_over(env, monkeypatch):
    mgr = env.mgr
    monkeypatch.setattr(manager.QTimer, "singleShot", lambda ms, fn: None)
    job = mgr.jobs.get(mgr.suggest("建议")["id"])
    drive(mgr, job)
    mgr.jobs.update(job, status="done", applied=1.0)
    env.installed = fake_install(env.tmp / "v021", "0.2.1")  # 装了新的官方版本
    mgr._check_installed()
    carry = next(j for j in mgr.jobs.items if j.kind == "carry")
    assert carry.items == [job.id]
    drive(mgr, carry)
    assert carry.status == "ready" and carry.version.startswith("0.2.1+aide.")
    assert len(env.agent.calls) == 2  # 只有当初那次的修改和复核：补丁原样套上，搬迁不用再开模型
    assert "return 1" in (mgr.workshop.src / "app.py").read_text(encoding="utf-8")


def test_tests_that_cannot_run_are_never_a_baseline(env):
    """测试环境坏了（实测：漏装 pytest 的依赖），现有的测试一个都没跑起来：不能把空结果当基线，过一会儿重试。"""
    mgr = env.mgr
    env.test_results.append(TestRun(crashed="No module named 'pygments'"))
    job = mgr.jobs.get(mgr.suggest("建议")["id"])
    drive(mgr, job)
    assert job.phase == "prepare" and job.retry_at > 0 and "pygments" in job.error
    assert not mgr.state["baseline"]
    job.retry_at = 0
    drive(mgr, job)  # 修好了：这次跑出了基线，接着往下做
    assert job.status == "ready" and mgr.state["baseline"]


def test_a_new_install_mid_job_restarts_from_prepare(env):
    mgr = env.mgr
    job = mgr.jobs.get(mgr.suggest("建议")["id"])
    asyncio.run(mgr._step())  # 准备好了
    assert job.phase == "agent"
    env.installed = fake_install(env.tmp / "again", "0.2.0")
    env.installed.fingerprint = "fp-reinstalled"  # 重新装了一次（比如 install.cmd）
    asyncio.run(mgr._step())
    assert job.base_fp == "fp-reinstalled" and job.phase == "agent" and env.agent.calls == []


def test_running_from_source_holds_the_change(env):
    env.installed.editable = True
    env.mgr.editable = True
    job = env.mgr.jobs.get(env.mgr.suggest("建议")["id"])
    drive(env.mgr, job)
    assert job.status == "held" and "change.patch" in job.error


# ---------- 引擎中枢：攒信号、交出去 ----------

def fake_hub(evolve=None):
    loop = SimpleNamespace(call_later=lambda delay, fn, *a: SimpleNamespace(cancel=lambda: None))
    return SimpleNamespace(evolve=evolve, loop=loop, decider=Decider(Config()), _schedule_evolve=lambda conv: None,
                           _note_trouble=lambda conv, item: conv.trouble.append(item))


def live_hub(evolve):
    """用引擎中枢真的攒信号、交出去的那几个方法；计时器记下来，测试里手动触发（= 这么久没再接着问）。"""
    hub = SimpleNamespace(evolve=evolve, timers=[], decider=Decider(Config()))
    hub.loop = SimpleNamespace(call_later=lambda delay, fn, *a: hub.timers.append((fn, a))
                               or SimpleNamespace(cancel=lambda: None))
    for name in ("_note_trouble", "_schedule_evolve", "_hand_to_evolve"):
        setattr(hub, name, getattr(EngineHub, name).__get__(hub))
    return hub


def conversation_ends(hub) -> None:
    fn, args = hub.timers[-1]
    fn(*args)


def conv(home: Path | None = None) -> Conversation:
    c = Conversation(key="k1", mode="act", task=Task("act", "帮我卸载 XXX", "text", foreground="explorer.exe"),
                     decision=Decision(engine="claude", model="claude-opus-5-5", effort="high", reason="",
                                       mode="act", kind="agentic", domain="desktop"))
    c.home, c.question = home, "帮我卸载 XXX"
    c.record = [{"t": "2026-10-09T10:00:00", "question": "帮我卸载 XXX", "answer": "没完成：找不到卸载程序", "ok": False,
                 "error": "没完成：找不到卸载程序", "engine": "claude", "model": "m", "effort": "high", "trace": ["正在查注册表"],
                 "situation": {"text": "屏幕上的字"}}]
    return c


def test_failures_are_collected_but_outages_are_not():
    hub, c = fake_hub(), conv()
    EngineHub._watch_outcome(hub, c, {"ok": False, "reason": "reported", "error": "没完成：找不到卸载程序"})
    EngineHub._watch_outcome(hub, c, {"ok": False, "reason": "api_error", "error": ""})
    EngineHub._watch_outcome(hub, c, {"ok": True})
    assert [t["kind"] for t in c.trouble] == ["failure"]


def test_stop_and_thumbs_down_reasons():
    hub, c = fake_hub(), conv()
    EngineHub._on_reason(hub, c, "stop", "not_assistant", "")
    EngineHub._on_reason(hub, c, "stop", "", "我改主意了")
    assert c.trouble == []
    EngineHub._on_reason(hub, c, "stop", "slow", "卡在下载那一步")
    assert c.trouble[-1]["kind"] == "stopped" and c.trouble[-1]["text"] == "卡在下载那一步"
    reasons = []
    hub.evolve = SimpleNamespace(add_reason=lambda *a: reasons.append(a))
    EngineHub._on_reason(hub, c, "bad", "screen", "")
    assert reasons == [("k1", "screen", "")]  # 👎 一点就交出去了：原因补给那个任务


def test_hand_over_captures_the_conversation(tmp_path):
    got = []
    hub = fake_hub(SimpleNamespace(submit=lambda data, hold=0: got.append((data, hold))))
    c = conv(tmp_path)
    c.trouble = [{"kind": "failure", "error": "没完成：找不到卸载程序"}]  # 记下时就交出去了，在等对话结束
    EngineHub._hand_to_evolve(hub, c)
    data, hold = got[0]
    assert c.trouble == [] and hold == 0 and data["conv"] == "k1" and data["question"] == "帮我卸载 XXX"
    assert data["record"][0]["trace"] == ["正在查注册表"] and data["decision"]["model"] == "claude-opus-5-5"


def test_a_stop_reason_shows_up_at_once_and_starts_when_the_conversation_ends(env, tmp_path):
    """按 Esc 停下、说了原因：原来信号在内存里攒到对话结束（10 分钟没再接着问）才交出去，这期间设置里什么也看不到，
    像是没触发，中间退出了还会丢。现在马上排上（落盘），先不开始；对话结束时按整段对话补齐证据，再开始。"""
    mgr = env.mgr
    hub, c = live_hub(mgr), conv(tmp_path)
    EngineHub._on_reason(hub, c, "stop", "slow", "卡在下载那一步")
    job = mgr.jobs.recent(1)[0]
    assert job.kind == "stopped" and job.status == "queued" and "卡在下载那一步" in job.reason
    view = mgr.snapshot()["items"][0]
    assert view["held"] and view["can_cancel"]                 # 设置里马上看得到，也能"不要了"
    assert Jobs(mgr.root).get(job.id).hold_until > time.time()  # 落盘了：中间退出也不丢
    delay = asyncio.run(mgr._step())
    assert job.status == "queued" and env.agent.calls == [] and 0 < delay <= EVOLVE_HOLD  # 对话还没结束：先不开始
    c.record.append(dict(c.record[0], question="换个办法试试", answer="还是没找到"))  # 接着问了一轮
    EngineHub._schedule_evolve(hub, c)                                               # 这一轮结束
    assert mgr.snapshot()["items"][0]["held"] and len(mgr.jobs.items) == 1
    conversation_ends(hub)
    assert not mgr.snapshot()["items"][0]["held"]
    talk = (mgr.jobs.folder(job) / "evidence" / "对话.md").read_text(encoding="utf-8")
    assert "原因：太慢 / 卡住了；卡在下载那一步" in talk and "换个办法试试" in talk
    asyncio.run(mgr._step())
    assert [x["role"] for x in env.agent.calls] == ["triage"] and job.status == "running"


def test_a_waiting_signal_does_not_hold_up_other_improvements(env, tmp_path):
    mgr = env.mgr
    EngineHub._note_trouble(live_hub(mgr), conv(tmp_path), {"kind": "failure", "error": "没完成：找不到卸载程序"})
    waiting = mgr.jobs.recent(1)[0]
    resp = mgr.suggest("回答再短一点")
    assert resp["position"] == 1  # "收到了，马上开始"：等着对话结束的那个不算在前面
    later = mgr.jobs.get(resp["id"])
    asyncio.run(mgr._step())
    assert later.status == "running" and waiting.status == "queued"


def test_a_waiting_signal_starts_on_its_own_after_a_restart(env, tmp_path):
    """退出又打开：对话没了，没人放行。到点了自己开始。"""
    EngineHub._note_trouble(live_hub(env.mgr), conv(tmp_path), {"kind": "exception", "error": "KeyError: 'x'"})
    again = EvolveManager(Config(), env.mgr.hub, env.mgr.router, quit_app=lambda: None, root=env.mgr.root)
    job = again.jobs.recent(1)[0]
    assert job.status == "queued" and again.snapshot()["items"][0]["held"]
    again.jobs.update(job, hold_until=time.time() - 1)
    asyncio.run(again._step())
    assert job.status == "running" and env.agent.calls[0]["role"] == "triage"


def test_discarding_a_waiting_improvement_sticks(env, tmp_path):
    mgr = env.mgr
    mgr.hub.loop = SimpleNamespace(call_soon_threadsafe=lambda fn: fn())
    hub, c = live_hub(mgr), conv(tmp_path)
    EngineHub._on_reason(hub, c, "stop", "wrong", "")
    job = mgr.jobs.recent(1)[0]
    mgr.cancel(job.id)
    assert job.status == "discarded"
    conversation_ends(hub)
    assert [j.id for j in mgr.jobs.items] == [job.id]  # 对话结束时不会再冒出来


def test_thumbs_down_reason_reaches_the_evidence(env, tmp_path):
    mgr = env.mgr
    hub, c = live_hub(mgr), conv(tmp_path)
    EngineHub._note_trouble(hub, c, {"kind": "thumbs_down"})   # 点了 👎：马上交出去
    EngineHub._on_reason(hub, c, "bad", "screen", "看错了窗口")  # 接着选了原因
    job = mgr.jobs.recent(1)[0]
    assert job.kind == "thumbs_down" and "看错了窗口" in job.reason
    talk = (mgr.jobs.folder(job) / "evidence" / "对话.md").read_text(encoding="utf-8")
    assert "原因：没看懂屏幕；看错了窗口" in talk                  # 模型看的是证据：原因也在里面


# ---------- 扩展包同步：撤销回旧版本时能恢复，你改过的不覆盖 ----------

def test_workspace_sync_follows_the_template_but_keeps_your_edits(tmp_path, monkeypatch):
    template, workspace = tmp_path / "template", tmp_path / "workspace"
    monkeypatch.setattr(paths, "WORKSPACE_TEMPLATE", template)
    monkeypatch.setattr(paths, "WORKSPACE", workspace)
    (template / "skills").mkdir(parents=True)
    (template / "AGENTS.md").write_text("v1\n", encoding="utf-8")
    (template / "skills" / "a.md").write_text("a1\n", encoding="utf-8")
    app_module._sync_workspace()
    assert (workspace / "AGENTS.md").read_text(encoding="utf-8") == "v1\n"
    (template / "AGENTS.md").write_text("v2\n", encoding="utf-8")       # 自我改进改了指令
    app_module._sync_workspace()
    assert (workspace / "AGENTS.md").read_text(encoding="utf-8") == "v2\n"
    (template / "AGENTS.md").write_text("v1\n", encoding="utf-8")       # 撤销：模板回到旧内容
    app_module._sync_workspace()
    assert (workspace / "AGENTS.md").read_text(encoding="utf-8") == "v1\n"
    (workspace / "skills" / "a.md").write_text("mine\n", encoding="utf-8")  # 你自己改过
    (template / "skills" / "a.md").write_text("a2\n", encoding="utf-8")
    app_module._sync_workspace()
    assert (workspace / "skills" / "a.md").read_text(encoding="utf-8") == "mine\n"


def test_a_queued_improvement_can_be_cancelled(env):
    mgr = env.mgr
    mgr.hub.loop = SimpleNamespace(call_soon_threadsafe=lambda fn: fn())
    job = mgr.jobs.get(mgr.suggest("建议")["id"])
    assert mgr.snapshot()["items"][0]["can_cancel"]
    mgr.cancel(job.id)
    assert job.status == "discarded" and env.agent.calls == []  # 还没开始：直接结束，不跑模型


def test_a_running_improvement_stops_mid_session_and_restores_the_workshop(env, monkeypatch):
    """原来只能关掉整个自我改进让它暂停，再打开又接着做。现在点"不要了"：会话马上掐断，改到一半的还原。"""
    mgr = env.mgr
    mgr.hub.loop = SimpleNamespace(call_soon_threadsafe=lambda fn: fn())
    job = mgr.jobs.get(mgr.suggest("建议")["id"])
    app_py = mgr.workshop.root / "src" / "super_aide" / "app.py"
    stopped, shown = [], []
    mgr.changed.connect(lambda snap: shown.append((snap["active"] or {}).get("cancelling")))

    async def slow_agent(run, prompt, session, resume, on_step):
        app_py.write_bytes(b"def main():\n    return 'half done'\n")  # 改到一半
        mgr.cancel(job.id)                                              # 这时你点了"不要了"
        assert shown[-1] is True                                        # 设置里马上显示"正在停下…"
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            stopped.append(True)
            raise
        return Outcome(True, dict(RESULT), session=session)

    monkeypatch.setattr(agent, "run_claude", slow_agent)
    drive(mgr, job, until=("discarded", "ready", "failed"))
    assert job.status == "discarded" and stopped == [True]
    assert b"half done" not in app_py.read_bytes()   # 工作台还原了
    assert mgr.snapshot()["active"] is None
