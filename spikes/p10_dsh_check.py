"""P10：DeepSeek Harness（ACP 模式）能不能接上。

    uv run --no-sync python -X utf8 spikes/p10_dsh_check.py

1. 问答（只读）问一句很短的话：看事件流、首字耗时、会话报来的模型清单。
2. 问答模式下让它写文件：必须写不成（只读沙箱 + 不审批）。
3. 操作模式（完全访问）跑一条只读命令：看工具调用的状态行和最后的回答。
4. 中途停下：发一个要写很久的问题，几秒后中断，应该很快以"interrupted"结束。
先预热（起进程、提前建好会话），之后建会话应该几乎不用等。
会用你的 DeepSeek 账号（或 DEEPSEEK_API_KEY）问四句很短的话，花费可以忽略。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

from super_aide import paths
from super_aide.engines import prompts
from super_aide.engines.dsh import DshEngine


async def turn(engine: DshEngine, mode: str, text: str, effort: str = "low") -> dict:
    started = time.monotonic()
    session = await engine.open(mode, "deepseek-flash", effort)
    print(f"\n[{mode}] 会话 {session.session_id}，建好用了 {time.monotonic() - started:.1f}s；"
          f"模型 {list(session.values)}，当前 {session.applied}")
    answer, done, first = "", {}, None
    async for ev in session.send(text, []):
        if ev.type == "delta" and first is None:
            first = time.monotonic() - started
        if ev.type in ("new_message", "retract"):
            answer = ""
        elif ev.type == "delta":
            answer += ev.text
        elif ev.type == "done":
            done = ev.data
        print("   ", ev.as_dict())
    await session.close()
    print(f"    → 回答：{answer.strip()!r}；首字 {first or 0:.1f}s，总共 {time.monotonic() - started:.1f}s")
    return {"answer": answer, **done}


async def main() -> int:
    paths.ensure()
    engine = DshEngine(prompts.shared_instructions())
    ok = True
    try:
        started = time.monotonic()
        await asyncio.gather(engine.warm("ask"), engine.warm("act"))
        print(f"预热用了 {time.monotonic() - started:.1f}s")
        r = await turn(engine, "ask", "只回复两个字：好的")
        ok &= bool(r.get("ok")) and "好" in r["answer"]
        target = Path(tempfile.gettempdir()) / "super_aide_dsh_readonly_probe.txt"
        target.unlink(missing_ok=True)
        r = await turn(engine, "ask", f"在 {target} 新建一个文本文件，内容写 hello。做不到就直接说做不到，不要换别的办法。")
        wrote = target.exists()
        print(f"    → 只读检查：文件{'被写出来了（不对！）' if wrote else '没有写出来（对）'}")
        ok &= not wrote
        target.unlink(missing_ok=True)
        r = await turn(engine, "act", "用 pwsh 运行 `Get-Date -Format yyyy`，只回复它输出的那个年份。")
        ok &= bool(r.get("ok")) and str(time.localtime().tm_year) in r["answer"]
        session = await engine.open("ask", "deepseek-flash", "low")
        started, done = time.monotonic(), {}

        async def stop_later() -> None:
            await asyncio.sleep(4)
            await session.interrupt()

        stopper = asyncio.create_task(stop_later())
        async for ev in session.send("写一篇两千字的文章，介绍 Windows 的历史。", []):
            if ev.type == "done":
                done = ev.data
        await stopper
        await session.close()
        print(f"\n[中断] {done}，用了 {time.monotonic() - started:.1f}s")
        ok &= done.get("reason") == "interrupted"
        print("\n模型清单：", await engine.models())
    finally:
        await engine.close()
    print("\n结果：", "通过" if ok else "有问题")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
