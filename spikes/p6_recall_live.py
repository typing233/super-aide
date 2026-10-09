"""经验在真实引擎里的自检（会真的调用模型，用临时经验库）。

临时库里放一条编出来的经验："出现 AIDE-7731 时运行 aide-fix --reset-7731"。这个命令模型不可能自己知道，
回答里出现它，就说明经验确实送到了模型手里：
1. Claude 做到一半：运行一条会打出 AIDE-7731 报错的命令，钩子把经验附在工具结果后面；
2. Claude 主动问：用 recall 工具查；
3. Codex 主动问：用 memory 工具服务器的 recall 查。

    uv run --no-sync python -X utf8 spikes/p6_recall_live.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

LESSONS = Path(tempfile.mkdtemp(prefix="aide-recall-")) / "lessons.json"
os.environ["AIDE_LESSONS"] = str(LESSONS)  # 本进程和 Codex 的工具服务器都用临时库

from super_aide import config  # noqa: E402
from super_aide.engines import experience as glue  # noqa: E402
from super_aide.engines.claude import ClaudeEngine  # noqa: E402
from super_aide.engines.codex import CodexEngine  # noqa: E402
from super_aide.experience import recall, store  # noqa: E402

FIX = "aide-fix --reset-7731"
results: list[tuple[str, bool, str, float]] = []


def check(name: str, ok: bool, detail: str, seconds: float) -> None:
    results.append((name, ok, detail, seconds))


async def answer_of(session, text: str) -> tuple[str, list[str]]:
    answer, statuses = "", []
    async for ev in session.send(text, []):
        if ev.type in ("new_message", "retract"):
            answer = ""
        elif ev.type == "delta":
            answer += ev.text
        elif ev.type == "status":
            statuses.append(ev.text)
    return answer, statuses


async def main() -> int:
    lib = store.Store(LESSONS)
    lib.add("AIDE-7731 报错要先运行修复命令", "命令输出里出现 AIDE-7731 错误（缓存损坏）",
            f"出现 AIDE-7731 时，正确的处理是运行 {FIX}，不要重装软件。",
            triggers=["AIDE-7731", "缓存损坏", "cache corrupted"], errors=["AIDE-7731"])
    cfg = config.load()
    claude_model = cfg.engine("claude").enabled_models()[0].id
    codex_model = cfg.engine("codex").enabled_models()[0].id
    hooked: list[str] = []

    def remember(text: str) -> str:
        found = recall.recall(lib, recall.Situation(text=text))
        hooked.extend(x.title for x in found)
        return ("【以前踩过的坑】刚才的结果里有报错。以前遇到相似情况时总结的经验，只在和这次情况相符时参考：\n"
                + recall.render(found)) if found else ""

    claude = ClaudeEngine("", False, "ours")
    try:
        t = time.perf_counter()
        session = await claude.open("act", claude_model, "low")
        session.slot.remember = remember
        session.slot.lookup = lambda q: glue.lookup(q, lib)
        text, _ = await answer_of(session, "运行这条 PowerShell 命令：Write-Output 'ERROR AIDE-7731: cache corrupted'。"
                                           "然后告诉我下一步该怎么处理这个报错；如果你知道专门的修复命令就写出来。不要做别的。")
        await session.close()
        check("Claude 做到一半想起经验（钩子）", FIX in text and bool(hooked), text.strip()[-160:], time.perf_counter() - t)

        t = time.perf_counter()
        session = await claude.open("ask", claude_model, "low")
        session.slot.lookup = lambda q: glue.lookup(q, lib)
        text, statuses = await answer_of(session, "用 recall 工具查一下以前关于 AIDE-7731 报错的经验，把修复命令告诉我。")
        await session.close()
        check("Claude 主动问（recall 工具）", FIX in text and glue.STATUS in statuses, text.strip()[-160:],
              time.perf_counter() - t)
    finally:
        await claude.close()

    codex = CodexEngine("", False, "ours")
    try:
        t = time.perf_counter()
        session = await codex.open("act", codex_model, "low")
        text, statuses = await answer_of(session, "运行这条 PowerShell 命令：Write-Output 'ERROR AIDE-7731: cache corrupted'。"
                                                  "然后告诉我下一步该怎么处理这个报错；如果你知道专门的修复命令就写出来。"
                                                  "不要用任何工具查资料，也不要做别的。")
        check("Codex 做到一半想起经验（执行后钩子）", FIX in text and glue.STATUS not in statuses, text.strip()[-160:],
              time.perf_counter() - t)

        t = time.perf_counter()
        session = await codex.open("ask", codex_model, "low")
        text, statuses = await answer_of(session, "用 memory 工具服务器的 recall 工具查一下以前关于 AIDE-7731 报错的经验，"
                                                  "把修复命令告诉我。")
        check("Codex 主动问（memory 工具服务器）", FIX in text and glue.STATUS in statuses, text.strip()[-160:],
              time.perf_counter() - t)
        t = time.perf_counter()
        session = await codex.open("ask", codex_model, "low")
        text, statuses = await answer_of(session, "用 computer 工具服务器的 windows 工具列出现在打开的窗口，"
                                                  "只回答窗口的数量。")
        check("Codex 问答模式能用只看的界面工具", any("窗口" in s for s in statuses) and "审批" not in text,
              f"{statuses[-2:]} {text.strip()[-80:]}", time.perf_counter() - t)
    finally:
        await codex.close()

    for name, ok, detail, seconds in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {seconds:.0f}s  {detail!r}")
    passed = sum(r[1] for r in results)
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
