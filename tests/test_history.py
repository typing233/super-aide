"""历史记录：存、列、搜、只认会话文件夹名、过期清理只留问答。"""

import json
import os
import time
from types import SimpleNamespace

import pytest

from super_aide import history, paths
from super_aide.engines.hub import Conversation, EngineHub
from super_aide.router import Task


@pytest.fixture(autouse=True)
def sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SESSIONS", tmp_path)
    return tmp_path


def make(sessions, name, question, answer, ok=True, mode="ask", age_days=0):
    folder = sessions / name
    (folder / "windows").mkdir(parents=True)
    (folder / "screen.jpg").write_bytes(b"x" * 10)
    (folder / "windows" / "00_app.jpg").write_bytes(b"x")
    history.save(folder, {"mode": mode, "started": "2026-10-08T07:37:08", "foreground": "msedge.exe",
                          "turns": [{"question": question, "answer": answer, "ok": ok}]})
    if age_days:
        old = time.time() - age_days * 86400
        for path in [*folder.rglob("*"), folder]:
            os.utime(path, (old, old))
    return folder


def test_summaries_newest_first_and_search(sessions):
    make(sessions, "20261007-101010-aaaa", "怎么装 pandas", "运行 `pip install pandas`")
    make(sessions, "20261008-073708-097e", "帮我修好它", "没完成：浏览器操作还没接通", ok=False, mode="act")
    items = history.summaries()
    assert [i["id"] for i in items] == ["20261008-073708-097e", "20261007-101010-aaaa"]
    assert items[0]["ok"] is False and items[0]["mode"] == "act"
    assert items[1]["preview"] == "运行 pip install pandas"
    assert [i["id"] for i in history.summaries("PANDAS")] == ["20261007-101010-aaaa"]  # 不分大小写，也搜回答


def test_load_only_accepts_session_ids(sessions):
    make(sessions, "20261008-073708-097e", "q", "a")
    assert history.load("20261008-073708-097e")["turns"][0]["question"] == "q"
    assert history.load("../../etc") is None
    assert history.folder("..\\config") is None


def test_prune_keeps_only_the_conversation(sessions):
    old = make(sessions, "20260901-080000-0001", "旧问题", "旧回答", age_days=30)
    bare = sessions / "20260901-090000-0002"  # 没有问答（比如召唤后没提问）
    bare.mkdir()
    (bare / "screen.jpg").write_bytes(b"x")
    os.utime(bare, (time.time() - 30 * 86400,) * 2)
    recent = make(sessions, "20261008-073708-097e", "新问题", "新回答")
    unused = sessions / "20261010-110628-010c"  # 今天上午召唤了没提问：截图和窗口文字没用了，不用等 7 天
    unused.mkdir()
    (unused / "screen.jpg").write_bytes(b"x")
    os.utime(unused, (time.time() - 13 * 3600,) * 2)
    asking = sessions / "20261010-120000-0003"  # 刚提问、还在答（问答记录答完才写）：不能删
    asking.mkdir()
    (asking / "screen.jpg").write_bytes(b"x")
    assert history.prune(keep_days=7) == 3
    assert sorted(p.name for p in old.iterdir()) == [history.FILE]
    assert not bare.exists() and not unused.exists() and (asking / "screen.jpg").exists()
    assert (recent / "screen.jpg").exists()
    assert history.load(old.name)["turns"][0]["answer"] == "旧回答"


def test_hub_records_each_turn(sessions):
    folder = sessions / "20261008-073708-097e"
    folder.mkdir()
    conv = Conversation(key="k", mode="act", task=Task("act", "帮我修好它", "text", "msedge.exe"),
                        decision=SimpleNamespace(engine="codex", model="gpt-6-astra", effort="medium"),
                        home=folder, question="帮我修好它")
    EngineHub._save_history(None, conv, {"ok": False, "hint": "浏览器操作还没接通：…"}, "没完成：…\n")
    conv.question = "那现在呢"
    EngineHub._save_history(None, conv, {"ok": True}, "已完成：好了")
    saved = json.loads((folder / history.FILE).read_text(encoding="utf-8"))
    assert [t["question"] for t in saved["turns"]] == ["帮我修好它", "那现在呢"]
    assert saved["turns"][0]["error"].startswith("浏览器操作还没接通")
    assert saved["turns"][1]["ok"] is True and saved["mode"] == "act"


def test_failures_without_an_answer_show_the_reason_in_plain_words(sessions):
    folder = sessions / "20261010-095904-ab12"
    folder.mkdir()
    raw = "exceeded retry limit, last status: 429 Too Many Requests"
    history.save(folder, {"mode": "act", "started": "2026-10-10T09:59:04", "foreground": "Notepad.exe",
                          "turns": [{"question": "新建 e.txt", "answer": "", "ok": False, "error": raw}]})
    item = history.summaries()[0]
    assert item["preview"] == "引擎被限流了，稍后再试。"   # 不再是一个空的"没完成 ·"
    assert history.load(folder.name)["turns"][0]["error"] == "引擎被限流了，稍后再试。"
    assert raw in (folder / "conversation.json").read_text(encoding="utf-8")  # 记录里还是原文


def test_stopped_turns_say_stopped_not_the_engine_diagnostic(sessions):
    folder = sessions / "20261010-104248-3ffa"
    folder.mkdir()
    diag = "[ede_diagnostic] result_type=user last_content_type=n/a stop_reason=null"
    history.save(folder, {"mode": "act", "started": "2026-10-10T10:42:48", "foreground": "Notepad.exe",
                          "turns": [{"question": "统计 dll", "answer": "", "ok": False, "reason": "interrupted",
                                     "error": diag}]})
    assert history.summaries()[0]["preview"] == "已停止"
    assert history.load(folder.name)["turns"][0]["error"] == "已停止"


def test_delete_can_be_undone_then_is_gone_for_good(sessions):
    keep = make(sessions, "20261010-090000-aaaa", "留着的", "回答")
    a = make(sessions, "20261010-091000-bbbb", "删掉的 1", "回答")
    b = make(sessions, "20261010-092000-cccc", "删掉的 2", "回答")
    assert history.delete([a.name, b.name, "../evil", "20261010-099999-zzzz"]) == [a.name, b.name]
    assert [i["id"] for i in history.summaries()] == [keep.name]  # 列表里马上没了
    assert history.restore([a.name]) == [a.name]                    # 撤销：挪回来
    assert sorted(i["id"] for i in history.summaries()) == [keep.name, a.name]
    assert history.load(a.name)["turns"][0]["question"] == "删掉的 1"
    assert history.empty_trash(older_than_s=3600) == 0               # 撤销时间里不真删
    assert history.empty_trash(older_than_s=0) == 1 and history.restore([b.name]) == []  # 过了时间：真删了
    assert not (sessions / history.TRASH / b.name).exists()


def test_prune_also_empties_old_trash(sessions):
    gone = make(sessions, "20261010-093000-dddd", "q", "a")
    history.delete([gone.name])
    old = time.time() - 2 * history.UNDO_S
    os.utime(sessions / history.TRASH / gone.name, (old, old))
    history.prune()
    assert not (sessions / history.TRASH / gone.name).exists()
