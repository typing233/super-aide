"""两项联调：① 按 Esc（停止信号）能让正在执行的动作立刻停下；② 问答模式里 Claude 用 observe_window + point 圈出要点的地方。

② 会真实调用一次 Claude（问答模式，只读）。

    uv run --no-sync python -X utf8 spikes/p4_cu_stop_and_guide.py
"""

from __future__ import annotations

import sys

sys.coinit_flags = 0

import asyncio  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from super_aide import app, paths  # noqa: E402
from super_aide.cu import server  # noqa: E402
from super_aide.cu.actions import Action  # noqa: E402
from super_aide.cu.signals import Signals  # noqa: E402
from super_aide.engines import prompts  # noqa: E402
from super_aide.engines.claude import ClaudeEngine  # noqa: E402

HERE = Path(__file__).parent


def stop_check() -> tuple[bool, str]:
    signals = Signals()
    signals.resume()
    server.observe_window("CU 靶子", screenshot=False)
    box = {}
    t0 = time.perf_counter()
    worker = threading.Thread(target=lambda: box.update(out=server.act([Action(do="wait", seconds=20)],
                                                                         observe_after=False)))
    worker.start()
    time.sleep(0.5)
    signals.stop()
    worker.join(5)
    elapsed = time.perf_counter() - t0
    signals.resume()
    out = (box.get("out") or ["（没返回）"])[0]
    return "已停止" in out and elapsed < 1.5, f"{elapsed:.2f}s：{out}"


async def guide_check() -> tuple[bool, str]:
    engine = ClaudeEngine(prompts.shared_instructions(), False, "ours", lambda: [])
    tools, answer = [], ""
    try:
        session = await engine.open("ask", "claude-opus-5-5", "low")
        question = prompts.MODE_RULES["ask"] + "\n\n【我的问题】\n屏幕上那个「CU 靶子窗口」，我要怎么把表单提交出去？请在屏幕上圈给我看。"
        async for ev in session.send(question, []):
            if ev.type == "status" and ev.text:
                tools.append(ev.text)
            elif ev.type in ("new_message", "retract"):
                answer = ""
            elif ev.type == "delta":
                answer += ev.text
    finally:
        await engine.close()
    pointed = server_was_pointed(tools)
    return pointed, f"步骤：{tools}；回答：{answer.strip()[:120]}"


def server_was_pointed(statuses: list[str]) -> bool:
    return any("正在看" in s for s in statuses) and any("point" in s or "正在操作界面" in s or "圈" in s for s in statuses)


def main() -> int:
    paths.ensure()
    app._sync_workspace()
    state = Path(tempfile.mkdtemp()) / "s.json"
    target = subprocess.Popen([sys.executable, str(HERE / "p4_cu_target.py"), str(state)])
    try:
        time.sleep(2.5)
        ok1, d1 = stop_check()
        print(("PASS " if ok1 else "FAIL ") + "Esc 停止正在执行的动作  " + d1)
        ok2, d2 = asyncio.run(guide_check())
        print(("PASS " if ok2 else "FAIL ") + "问答模式圈出要点的地方  " + d2)
    finally:
        target.terminate()
    return 0 if ok1 and ok2 else 1


if __name__ == "__main__":
    sys.exit(main())
