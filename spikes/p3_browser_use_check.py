"""浏览器操作接通后的自检：从我们自己的进程启动 Codex，让它用 Browser Use 只读地列出浏览器标签页。

先确认连接组件已装好（重装 ChatGPT 桌面应用里的 Browser 插件），再运行。会真实调用一次 Codex（很短）。

    uv run --no-sync python -X utf8 spikes/p3_browser_use_check.py
"""

from __future__ import annotations

import asyncio
import sys

from super_aide import paths
from super_aide.engines import browser_use, prompts
from super_aide.engines.codex import CodexEngine

TASK = ("只读检查，不要点击、输入或打开任何网页：用 Browser Use 连接用户的浏览器，"
        "列出当前打开的标签页标题（最多 5 个）。连不上就照实说明原因。"
        "回复第一行以「已完成：」或「没完成：」开头。")


async def main() -> int:
    status = browser_use.status("msedge.exe")
    print("本机检查：", "已接通" if status.ready else status.problem)
    if not status.ready:
        return 1
    paths.ensure()
    engine = CodexEngine(prompts.shared_instructions(), blocklist=False)
    try:
        session = await engine.open("act", "gpt-6-astra", "low")
        answer = ""
        async for ev in session.send(TASK, []):
            if ev.type == "status":
                print("  …", ev.text)
            elif ev.type in ("new_message", "retract"):
                answer = ""
            elif ev.type == "delta":
                answer += ev.text
            elif ev.type == "done":
                print("回合结束：", ev.data)
        print("\nCodex 的回答：\n" + answer.strip())
        return 0 if answer.strip().startswith("已完成") else 1
    finally:
        await engine.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
