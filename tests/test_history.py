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
    assert history.prune(keep_days=7) == 2
    assert sorted(p.name for p in old.iterdir()) == [history.FILE]
    assert not bare.exists()
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
