"""操作模式"回合结束 ≠ 办成了"：看汇报第一行；浏览器操作没接通时附修法、不计入学习。"""

from types import SimpleNamespace

from super_aide.engines import browser_use
from super_aide.engines.base import reported_failure
from super_aide.engines.hub import Conversation, EngineHub
from super_aide.router import Task
from super_aide.snapshot.uia import _url_like


def test_reported_failure_reads_the_first_line():
    assert reported_failure("没完成：Browser Use 未连接\n本次未修改任何东西") == "没完成：Browser Use 未连接"
    assert reported_failure("**没完成**：网址检查没通过") == "没完成**：网址检查没通过"
    assert reported_failure("暂未修复：Computer Use 被安全检查停止。") == "暂未修复：Computer Use 被安全检查停止。"
    assert reported_failure("已完成：装好了 modelscope，单元格运行正常。") == ""
    assert reported_failure("") == ""


calls: list = []  # 假路由收到的学习记录


def fake_hub(problem: str = "") -> SimpleNamespace:
    return SimpleNamespace(_browser_problem=lambda conv: problem,
                           router=SimpleNamespace(record=lambda *a, **k: calls.append(a)))


def conversation(mode: str = "act", fg: str = "msedge.exe") -> Conversation:
    return Conversation(key="k", mode=mode, task=Task(mode, "帮我修好它", "text", fg), decision=object())


def test_failure_report_turns_a_completed_turn_into_a_failure():
    done = {"ok": True}
    EngineHub._check_outcome(fake_hub(), conversation(), done, "没完成：缺少权限\n…")
    assert done["ok"] is False and done["error"] == "没完成：缺少权限" and "hint" not in done


def test_browser_not_connected_adds_the_fix_and_skips_learning():
    done = {"ok": True}
    hub = fake_hub("浏览器操作还没接通：……")
    EngineHub._check_outcome(hub, conversation(), done, "没完成：浏览器操作还没接通")
    assert done["hint"].startswith("浏览器操作还没接通")
    calls.clear()
    EngineHub._learn_from_turn(hub, conversation(), done)
    assert calls == []  # 环境问题不算模型不行


def test_success_and_ask_mode_untouched():
    done = {"ok": True}
    EngineHub._check_outcome(fake_hub(), conversation(), done, "已完成：好了")
    assert done == {"ok": True}
    done = {"ok": True}
    EngineHub._check_outcome(fake_hub(), conversation("ask"), done, "没完成也只是问答里的一句话")
    assert done == {"ok": True}


def test_browser_status_messages(monkeypatch):
    monkeypatch.setattr(browser_use, "plugin_enabled", lambda: True)
    monkeypatch.setattr(browser_use, "host_installed", lambda: False)
    status = browser_use.status("msedge.exe")
    assert not status.ready and "「Chrome」插件" in status.problem
    monkeypatch.setattr(browser_use, "host_installed", lambda: True)
    monkeypatch.setattr(browser_use, "plugin_enabled", lambda: False)
    assert not browser_use.status("msedge.exe").ready  # 连接组件在、插件没开也不行
    monkeypatch.setattr(browser_use, "plugin_enabled", lambda: True)
    monkeypatch.setattr(browser_use, "extension_installed", lambda process: False)
    status = browser_use.status("msedge.exe")
    assert not status.ready and "Microsoft Edge" in status.problem
    monkeypatch.setattr(browser_use, "extension_installed", lambda process: None)
    assert browser_use.status("firefox.exe").ready


def test_url_like():
    assert _url_like("https://modelscope.cn/code/workspace") == "https://modelscope.cn/code/workspace"
    assert _url_like("localhost:8888") == "localhost:8888"
    assert _url_like("搜索或输入网址") == ""
