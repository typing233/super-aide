"""自研 Computer Use 的端到端试用：Claude 和 Codex 各自只拿到一句任务，用 computer 工具操作靶子窗口，按靶子状态核对。

会真实调用两个引擎各一次，并在屏幕上操作一个小窗口（会动鼠标）。

    uv run --no-sync python -X utf8 spikes/p4_cu_engines.py [claude|codex]
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from super_aide import app, paths
from super_aide.engines import prompts
from super_aide.engines.claude import ClaudeEngine
from super_aide.engines.codex import CodexEngine

HERE = Path(__file__).parent
TASK = ("当前是操作模式，直接动手。请在屏幕上的「CU 靶子窗口」里：姓名填「赵六」，城市选「上海」，勾选「我同意条款」，"
        "水果选「葡萄」，然后点「提交」。最后用一行汇报，以「已完成：」或「没完成：」开头。")
WANT = {"name": "赵六", "city": "上海", "agree": True, "fruit": "葡萄"}


async def run(engine_name: str) -> tuple[bool, str]:
    state_file = Path(tempfile.mkdtemp()) / "state.json"
    target = subprocess.Popen([sys.executable, str(HERE / "p4_cu_target.py"), str(state_file)])
    await asyncio.sleep(2.5)
    instructions = prompts.shared_instructions()
    if engine_name == "claude":
        engine, model = ClaudeEngine(instructions, False, "ours", lambda: []), "claude-opus-5-5"
    else:
        engine, model = CodexEngine(instructions, False, "ours", lambda: []), "gpt-6-astra"
    t0 = time.perf_counter()
    statuses, answer, done = [], "", {}
    try:
        session = await engine.open("act", model, "medium")
        async for ev in session.send(TASK, []):
            if ev.type == "status" and ev.text and (not statuses or statuses[-1] != ev.text):
                statuses.append(ev.text)
                print(f"  [{time.perf_counter() - t0:5.1f}s] {ev.text}", flush=True)
            elif ev.type in ("new_message", "retract"):
                answer = ""
            elif ev.type == "delta":
                answer += ev.text
            elif ev.type == "error":
                print("  错误：", ev.text)
            elif ev.type == "done":
                done = ev.data
    finally:
        await engine.close()
        await asyncio.sleep(0.5)
        state = json.loads(state_file.read_text(encoding="utf-8"))
        target.terminate()
    elapsed = time.perf_counter() - t0
    ok = all(state.get(k) == v for k, v in WANT.items()) and state.get("submitted", 0) >= 1
    detail = (f"{engine_name}：{'成功' if ok else '失败'}，{elapsed:.0f} 秒，{len(statuses)} 步；"
              f"状态 {json.dumps({k: state.get(k) for k in (*WANT, 'submitted')}, ensure_ascii=False)}；"
              f"回答「{answer.strip()[:80]}」；done={ {k: done.get(k) for k in ('ok', 'error') if k in done} }")
    return ok, detail


async def main() -> int:
    paths.ensure()
    app._sync_workspace()
    which = sys.argv[1:] or ["claude", "codex"]
    results = []
    for name in which:
        print(f"== {name}")
        results.append(await run(name))
    print()
    for ok, detail in results:
        print(("PASS " if ok else "FAIL ") + detail)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
