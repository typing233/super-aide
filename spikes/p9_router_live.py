"""路由 v2 在真实引擎上的自检（会真的调用模型，几次很短的对话）：
1. 后台对比用的会话（duel）：两个引擎都能答，而且没有看实时界面、在屏幕上圈位置的工具；
2. 同一个对话里换配置：Claude 换思考强度（带着会话 id 重连）、换模型（就地换），Codex 下一轮换模型和强度，
   对话历史都还在（记住的暗号还答得出来）；
3. 评审：明显答错的那份判 0，两份都对判 1。

    uv run --no-sync python -X utf8 spikes/p9_router_live.py
"""

from __future__ import annotations

import asyncio
import random
import sys
import time

from super_aide.engines.claude import ClaudeEngine, complete
from super_aide.engines.codex import CodexEngine
from super_aide.router import judge

CODE = "蓝鲸-4721"
SCREEN_PROBE = "用 computer 工具服务器的 windows 工具列出现在打开的窗口，只回答窗口数量；没有这个工具就只回答「没有这个工具」。"
results: list[tuple[str, bool, str, float]] = []


def check(name: str, ok: bool, detail: str, seconds: float) -> None:
    results.append((name, ok, detail, seconds))


async def answer_of(session, text: str) -> tuple[str, list[str], dict]:
    answer, statuses, done = "", [], {}
    async for ev in session.send(text, []):
        if ev.type in ("new_message", "retract"):
            answer = ""
        elif ev.type == "delta":
            answer += ev.text
        elif ev.type == "status":
            statuses.append(ev.text)
        elif ev.type == "done":
            done = ev.data
    return answer.strip(), statuses, done


async def main() -> int:
    claude = ClaudeEngine("", False, "ours")
    try:
        t = time.perf_counter()
        session = await claude.open("duel", "claude-sonnet-5-5", "low", rewarm=False)
        text, statuses, done = await answer_of(session, "用一句话说明 HTTP 404 是什么意思。")
        check("Claude 后台对比会话能答", bool(done.get("ok")) and "404" in text, text[:80], time.perf_counter() - t)
        t = time.perf_counter()
        text, statuses, _ = await answer_of(session, SCREEN_PROBE)
        check("Claude 后台对比会话没有看界面的工具", not any("正在查看打开的窗口" in s for s in statuses) and "没有" in text, f"{statuses} {text[:60]}",
              time.perf_counter() - t)
        await session.close()

        t = time.perf_counter()
        session = await claude.open("ask", "claude-opus-5-5", "low", rewarm=False)
        await answer_of(session, f"记住这个暗号：{CODE}。只回答「好的」。")
        session = await claude.switch(session, "ask", "claude-opus-5-5", "medium")
        text, _, done = await answer_of(session, "刚才的暗号是什么？只回答暗号。")
        check("Claude 换思考强度（重连续上）后还记得", CODE in text and session.effort == "medium", text[:60],
              time.perf_counter() - t)
        t = time.perf_counter()
        session = await claude.switch(session, "ask", "claude-sonnet-5-5", "medium")
        text, _, done = await answer_of(session, "再说一遍刚才的暗号，只回答暗号。")
        check("Claude 就地换模型后还记得", CODE in text and session.model == "claude-sonnet-5-5", text[:60],
              time.perf_counter() - t)
        await session.close()
    finally:
        await claude.close()

    codex = CodexEngine("", False, "ours")
    try:
        t = time.perf_counter()
        session = await codex.open("duel", "gpt-6-luna", "low")
        text, statuses, done = await answer_of(session, "用一句话说明 HTTP 404 是什么意思。")
        check("Codex 后台对比会话能答", bool(done.get("ok")) and "404" in text, text[:80], time.perf_counter() - t)
        t = time.perf_counter()
        text, statuses, _ = await answer_of(session, SCREEN_PROBE)
        check("Codex 后台对比会话没有看界面的工具", not any("正在查看打开的窗口" in s for s in statuses) and "没有" in text, f"{statuses} {text[:60]}",
              time.perf_counter() - t)

        t = time.perf_counter()
        session = await codex.open("ask", "gpt-6-astra", "low")
        await answer_of(session, f"记住这个暗号：{CODE}。只回答「好的」。")
        session = await codex.switch(session, "ask", "gpt-6.1-sol", "medium")
        text, _, done = await answer_of(session, "刚才的暗号是什么？只回答暗号。")
        check("Codex 下一轮换模型和强度后还记得", CODE in text and bool(done.get("ok")), text[:60], time.perf_counter() - t)
    finally:
        await codex.close()

    for name, question, served, candidate, want in (
            ("评审：候选答错判 0", "1 + 1 等于几？", "1 + 1 = 2。", "1 + 1 = 3。", 0.0),
            ("评审：两份都对判 1", "Python 里 len() 是做什么的？", "len() 返回对象的长度（元素个数）。",
             "len() 用来取得序列或集合里有多少个元素，比如 len([1, 2, 3]) 是 3。", 1.0)):
        t = time.perf_counter()
        flip = random.random() < 0.5
        raw = await asyncio.get_running_loop().run_in_executor(
            None, complete, judge.prompt(question, "", served, candidate, flip), "claude-opus-5-5")
        verdict = judge.parse(raw, flip)
        check(name, verdict is not None and verdict.candidate == want, f"{verdict}", time.perf_counter() - t)

    for name, ok, detail, seconds in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {seconds:.0f}s  {detail!r}")
    passed = sum(r[1] for r in results)
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
