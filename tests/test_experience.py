"""经验：只在碰到相似情况时想起；库有上限、会合并；走了弯路才总结。模型调用都用假的。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from super_aide.engines import prompts
from super_aide.experience import learn, recall, store
from super_aide.experience.recall import Situation
from super_aide.snapshot import collector
from super_aide.snapshot.win32 import WindowInfo


@pytest.fixture
def lib(tmp_path):
    s = store.Store(tmp_path / "lessons.json")
    s.add("Notebook 里 ModuleNotFoundError 先核对拼写",
          "Jupyter / 云端 Notebook 的单元格报 ModuleNotFoundError，或者后面的单元格报 NameError 说变量没定义",
          "先逐字母核对模块名（modescope 应为 modelscope），拼错就改代码，别急着装包；后面的 NameError 是 import 失败的连锁反应。",
          triggers=["找不到模块", "No module named", "ModuleNotFoundError", "NameError", "is not defined", "未定义",
                    "notebook", "jupyter", "拼写", "import"],
          errors=["ModuleNotFoundError", "NameError"], domains=["modelscope.cn"])
    s.add("pip 装包超时先查代理", "pip install 一直超时、ProxyError 或 SSLError",
          "先确认系统代理和 pip 的代理设置一致，或者换国内镜像源。",
          triggers=["pip install", "ProxyError", "代理", "超时", "镜像源", "清华源"],
          errors=["ProxyError", "ReadTimeoutError"])
    s.add("云端 Notebook 页面别靠截图读代码", "在浏览器里的 Notebook（ModelScope、Kaggle）上排查代码",
          "用 read 读页面的完整文字，代码和报错以文字为准。",
          triggers=["notebook", "jupyterlab", "iframe", "框架", "截图"], apps=["msedge.exe"],
          domains=["modelscope.cn", "kaggle.com"])
    s.add("Excel 自动化先关掉受保护的视图", "用脚本改 Excel 文件时报 0x800A03EC 或者文件处于受保护的视图",
          "先让用户启用编辑或者把文件复制到受信任位置。",
          triggers=["受保护的视图", "Protected View", "excel", "win32com", "openpyxl"], apps=["EXCEL.EXE"],
          errors=["0x800A03EC"])
    return s


def titles(lessons) -> list[str]:
    return [x.title for x in lessons]


NOTEBOOK_TEXT = ("from modescope import AutoModelForCausalLM, AutoTokenizer\n"
                 "ModuleNotFoundError: No module named 'modescope'\ntokenizer\n"
                 "NameError: name 'tokenizer' is not defined")


@pytest.mark.parametrize("question", ["你好", "今天天气怎么样", "帮我写一段周报", "报错了怎么办", "jupyter 怎么安装"])
def test_nothing_comes_to_mind_for_unrelated_or_vague_questions(lib, question):
    assert recall.recall(lib, Situation(question=question)) == []


def test_same_app_and_site_alone_are_not_enough(lib):
    """在同一个浏览器、同一个网站上问不相干的事：不该想起那个网站上的坑。"""
    s = Situation(question="帮我翻译这段英文", app="msedge.exe", url="https://www.modelscope.cn/my/mynotebook/123")
    assert recall.recall(lib, s) == []


def test_the_modelscope_case_recalls_the_spelling_lesson_first(lib):
    s = Situation(question="为什么运行tokenizer报错", text=NOTEBOOK_TEXT, app="msedge.exe",
                  url="https://www.modelscope.cn/my/mynotebook/123")
    found = recall.recall(lib, s)
    assert found and found[0].title == "Notebook 里 ModuleNotFoundError 先核对拼写"
    assert "pip 装包超时先查代理" not in titles(found)


def test_paraphrases_match_through_triggers(lib):
    assert titles(recall.recall(lib, Situation(question="pip install torch 一直超时怎么办"))) == ["pip 装包超时先查代理"]
    assert titles(recall.recall(lib, Situation(question="excel 打开的文件是受保护的视图，脚本改不了", app="EXCEL.EXE"))) \
        == ["Excel 自动化先关掉受保护的视图"]
    # 只有报错原文、没有问句：报错特征最强，对上一个就够
    assert titles(recall.recall(lib, Situation(question="这是什么", text="pywintypes.com_error: (-2146827284, 0x800A03EC)"))) \
        == ["Excel 自动化先关掉受保护的视图"]


def test_at_most_three_and_already_seen_are_skipped(lib):
    s = Situation(question="为什么运行tokenizer报错", text=NOTEBOOK_TEXT, app="msedge.exe",
                  url="https://www.modelscope.cn/x")
    first = recall.recall(lib, s)
    assert len(first) <= recall.MAX_RECALL
    again = recall.recall(lib, s, exclude={x.id for x in first})
    assert not {x.id for x in again} & {x.id for x in first}


def test_tokens_handle_mixed_chinese_english_and_camel_case():
    toks = recall.tokens("运行AutoTokenizer报错：ModuleNotFoundError")
    assert {"autotokenizer", "tokenizer", "modulenotfounderror", "运行", "报错"} <= set(toks)


# ---- 经验库 ----


def test_update_merges_and_keeps_counts(lib):
    lesson = lib.all()[0]
    lib.used([lesson.id], ok=True)
    lib.update(lesson.id, advice="新的做法", triggers=["modelscope"])
    again = lib.get(lesson.id)
    assert again.advice == "新的做法" and "modelscope" in again.triggers and "notebook" in again.triggers
    assert again.uses == 1


def test_unhelpful_lessons_get_dropped(lib):
    lesson = lib.all()[1]
    for _ in range(store.DROP_AFTER_FAILS):
        lib.used([lesson.id], ok=False)
    assert lib.get(lesson.id) is None


def test_results_that_do_not_count_leave_scores_alone(lib):
    lesson = lib.all()[0]
    lib.used([lesson.id], ok=None)  # 网络问题、你中途停止
    assert lib.get(lesson.id).uses == 0 and lib.get(lesson.id).last_used > 0


def test_library_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MAX_LESSONS", 5)
    s = store.Store(tmp_path / "l.json")
    for i in range(8):
        s.add(f"经验 {i}", "情况", "做法")
    assert len(s.all()) == 5


def test_other_processes_see_new_lessons(tmp_path):
    a, b = store.Store(tmp_path / "l.json"), store.Store(tmp_path / "l.json")
    assert b.all() == []
    a.add("新经验", "情况", "做法")
    assert titles(b.all()) == ["新经验"]


# ---- 总结 ----


def turn(**kw):
    base = {"question": "为什么运行tokenizer报错", "answer": "缺少 modelscope 包，装上就好", "ok": True, "seconds": 30,
            "tools": 3, "trace": ["正在运行 pip install modelscope"], "situation": {"text": NOTEBOOK_TEXT}}
    return base | kw


def test_only_detours_are_worth_learning():
    assert learn.worth_learning([turn()]) == ""
    assert learn.worth_learning([turn(ok=False, error="没完成：找不到原因")]) == "没办成"
    assert learn.worth_learning([turn(ok=False, reason="interrupted")]) == ""  # 你中途停止
    assert learn.worth_learning([turn(ok=False, error="429 rate limit")]) == ""  # 限流不算
    assert learn.worth_learning([turn(seconds=300)]) == "绕了很久才办完"
    # 跑了很久、被你按 Esc 停下的：过程不完整，不拿去总结（实测：停下的长任务被当成"绕了很久才办完"）
    assert learn.worth_learning([turn(seconds=300, ok=False, reason="interrupted", answer="")]) == ""
    assert learn.worth_learning([turn(question="以后别再用截图读代码")]) == "用户要求以后照着做"
    assert learn.worth_learning([turn()], negative=True) == "用户说上一轮没答好"


def test_parse_tolerates_fences_and_chatter():
    assert learn.parse('好的：\n```json\n{"action": "none", "why": "x"}\n```') == {"action": "none", "why": "x"}
    assert learn.parse("没有 JSON") is None


def fake_llm(reply: dict, seen: list):
    async def llm(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps(reply, ensure_ascii=False)
    return llm


def test_learn_adds_a_lesson_and_shows_similar_ones(lib):
    seen: list[str] = []
    reply = {"action": "add", "id": "", "title": "装包前先看报错里的名字", "when": "ModuleNotFoundError",
             "advice": "核对拼写", "triggers": ["No module named"], "errors": ["ModuleNotFoundError"],
             "apps": [], "domains": [], "why": "走了弯路"}
    result = asyncio.run(learn.learn(lib, [turn(), turn(question="不对，是 modescope 拼错了")], "用户说上一轮没答好",
                                     fake_llm(reply, seen), source="20261008-1"))
    assert result.startswith("新经验")
    assert "Notebook 里 ModuleNotFoundError 先核对拼写" in seen[0]  # 相似的已有经验给了模型，好让它决定合并
    assert "modescope" in seen[0]  # 框选区域的原文也给了
    assert any(x.title == "装包前先看报错里的名字" and x.source == "20261008-1" for x in lib.all())


def test_learn_updates_instead_of_duplicating(lib):
    target = lib.all()[0]
    reply = {"action": "update", "id": target.id, "title": "", "when": "", "advice": "更准的做法",
             "triggers": ["拼错"], "errors": [], "apps": [], "domains": [], "why": "同一件事"}
    count = len(lib.all())
    asyncio.run(learn.learn(lib, [turn(ok=False)], "没办成", fake_llm(reply, [])))
    assert len(lib.all()) == count and lib.get(target.id).advice == "更准的做法"


def test_learn_none_writes_nothing(lib):
    count = len(lib.all())
    reply = {"action": "none", "id": "", "title": "", "when": "", "advice": "", "triggers": [], "errors": [],
             "apps": [], "domains": [], "why": "偶发的网络问题"}
    assert "没有值得记" in asyncio.run(learn.learn(lib, [turn(ok=False)], "没办成", fake_llm(reply, [])))
    assert len(lib.all()) == count


# ---- 接到提问流程里 ----


def test_first_message_only_mentions_lessons_when_there_are_some(lib):
    ctx = collector.Context(dir=Path("."), index="- 时间：现在")
    assert "以前踩过的坑" not in prompts.first_message("你好", ctx, "ask", lessons=[])
    text = prompts.first_message("为什么报错", ctx, "ask", lessons=lib.all()[:1])
    assert "【以前踩过的坑】" in text and "只在和这次情况相符时参考" in text and "modescope 应为 modelscope" in text


def _snapshot(question_kind: str, tmp_path: Path):
    s = object.__new__(collector.Session)
    win = WindowInfo(hwnd=1, title="notebook", process="msedge.exe", pid=1, rect=(0, 0, 10, 10), minimized=False,
                     elevated=False)
    s.c = SimpleNamespace(is_blocked=lambda w: False)
    s.cap = collector.Capture(created=datetime(2026, 10, 8), mode="ask", screen_bgra=b"", screen_size=(10, 10),
                              screen_origin=(0, 0), foreground=win, focus={}, windows=[win],
                              default_selection=(0, 0, 10, 10), selection_source="manual", content_kind=question_kind)
    (tmp_path / "windows").mkdir()
    (tmp_path / "windows" / "00_msedge.txt").write_text("页面标题\nNameError: name 'tokenizer' is not defined\n正文",
                                                        encoding="utf-8")
    s.dir, s.url, s.selection_text = tmp_path, "https://modelscope.cn/x", "tokenizer"
    s.windows = [{"foreground": True, "text": "windows/00_msedge.txt"}]
    return s


def test_window_error_lines_only_when_asking_about_a_problem(tmp_path):
    s = _snapshot("text", tmp_path)
    assert "NameError" in s.situation("为什么这里报错").errors
    assert s.situation("帮我翻译一下").errors == ""


# ---- 做到一半想起、模型主动问 ----


def test_tool_output_text_skips_images():
    from super_aide.experience.recall import text_of as _text_of

    value = [{"type": "text", "text": "ModuleNotFoundError: No module named 'x'"},
             {"type": "image", "data": "A" * 100_000}, {"stdout": "ok", "stderr": "Traceback"}]
    text = _text_of(value)
    assert "ModuleNotFoundError" in text and "Traceback" in text and "AAAA" not in text


def test_claude_hook_adds_lessons_only_for_errors_from_running_things():
    from super_aide.engines.claude import SessionSlot, _recall_hooks

    slot, asked = SessionSlot(), []
    slot.remember = lambda lines: asked.append(lines) or "- 先核对拼写"
    after = _recall_hooks(slot)["PostToolUse"][0].hooks[0]

    def run(data):
        return asyncio.run(after(data, "t1", None))

    out = run({"hook_event_name": "PostToolUse", "tool_name": "Bash",
               "tool_response": {"stdout": "", "stderr": "ModuleNotFoundError: No module named 'modescope'"}})
    assert out["hookSpecificOutput"]["additionalContext"] == "- 先核对拼写" and "modescope" in asked[0]
    assert run({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_response": {"stdout": "done"}}) == {}
    # 读文件：内容里的 error 不是这次碰到的报错
    assert run({"hook_event_name": "PostToolUse", "tool_name": "Read",
                "tool_response": "except ModuleNotFoundError:\n    pass"}) == {}
    failed = run({"hook_event_name": "PostToolUseFailure", "tool_name": "PowerShell", "error": "pip: Access is denied"})
    assert failed["hookSpecificOutput"]["hookEventName"] == "PostToolUseFailure"
    assert len(asked) == 2


def test_codex_gets_the_memory_server(monkeypatch, tmp_path):
    from super_aide.engines import experience as glue

    monkeypatch.setenv("AIDE_LESSONS", str(tmp_path / "l.json"))
    joined = "\n".join(glue.codex_overrides())
    assert "mcp_servers.memory.command=" in joined and "super_aide.experience.server" in joined
    assert "AIDE_LESSONS" in joined


def test_memory_server_answers_over_mcp(lib, monkeypatch):
    import sys

    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def ask() -> tuple[list[str], str, str]:
        env = {"AIDE_LESSONS": str(lib.path), "PYTHONIOENCODING": "utf-8", "SYSTEMROOT": __import__("os").environ.get(
            "SYSTEMROOT", r"C:\\Windows")}
        params = StdioServerParameters(command=sys.executable, args=["-X", "utf8", "-m", "super_aide.experience.server"],
                                       env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = [t.name for t in (await session.list_tools()).tools]
                hit = await session.call_tool("recall", {"query": "pip install 一直超时，ProxyError"})
                miss = await session.call_tool("recall", {"query": "你好"})
                return tools, hit.content[0].text, miss.content[0].text

    tools, hit, miss = asyncio.run(ask())
    assert tools == ["recall"]
    assert "pip 装包超时先查代理" in hit
    assert miss == "没有相似的经验。"


def test_codex_hook_recalls_once_per_session(lib, monkeypatch, tmp_path):
    from super_aide.experience import codex_hook

    monkeypatch.setattr(codex_hook.tempfile, "gettempdir", lambda: str(tmp_path))
    payload = {"session_id": "s-1", "tool_name": "Bash",
               "tool_response": {"output": "pip install torch\nERROR: ProxyError: Cannot connect to proxy"}}
    first = codex_hook.respond(payload, lib)
    assert first.startswith(codex_hook.NOTE) and "pip 装包超时先查代理" in first
    assert codex_hook.respond(payload, lib) == ""  # 同一个会话里给过了
    assert "pip 装包超时先查代理" in codex_hook.respond(payload | {"session_id": "s-2"}, lib)  # 另一个会话照给
    assert codex_hook.respond({"session_id": "s-3", "tool_response": "all good"}, lib) == ""


def test_codex_sessions_turn_off_builtin_memories():
    from super_aide.engines import experience as glue

    assert "memories.use_memories=false" in glue.CODEX_MEMORIES_OFF
    assert "memories.generate_memories=false" in glue.CODEX_MEMORIES_OFF
