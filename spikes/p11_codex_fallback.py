"""自检：没有 Claude Code / Opus 5.5 时的兜底——Codex（auto_review + workspace-write 沙箱）能不能在工作台里改文件、
跑命令，会不会弹 UAC 卡住。只在临时目录里做，思考强度 low，花费很小。

    uv run python spikes/p11_codex_fallback.py [模型，默认 gpt-6-astra]
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for name in list(os.environ):
    if name.startswith(("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_AGENT_SDK")):
        del os.environ[name]

from super_aide.evolve import agent, prompts  # noqa: E402
from super_aide.evolve.agent import Choice, ClaudeRun  # noqa: E402
from super_aide.evolve.testenv import TestEnv  # noqa: E402


async def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "gpt-6-astra"
    work = Path(tempfile.mkdtemp(prefix="aide-codex-check-"))
    (work / "src").mkdir()
    (work / "app.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    bench = TestEnv(work, work.parent / f"{work.name}-venv")  # 和流水线一样：python 是测试环境的
    bench.ensure()
    steps = []
    system = prompts.IMPLEMENTER + prompts.CODEX_NOTE
    run = ClaudeRun(Choice("codex", model, "medium"), work, system, bench.env(), [], prompts.RESULT_SCHEMA)
    prompt = ("这是一次连通性自检，不用分析任何问题：把当前目录 app.py 里的 return 0 改成 return 1，"
              "再运行 python -m pytest --version 确认能跑测试工具，然后按要求的 JSON 结构给出结论"
              "（action=changed；tests 里写 pytest 输出的版本号）。")
    t0 = time.time()
    try:
        outcome = await asyncio.wait_for(agent.run_codex(run, prompt, "", lambda label, tool: steps.append(label)), 600)
    except asyncio.TimeoutError:
        print("10 分钟没完成：可能卡在 UAC 或审批上")
        return 1
    changed = "return 1" in (work / "app.py").read_text(encoding="utf-8")
    print(f"用时 {time.time() - t0:.0f} 秒；结果：{outcome.ok} {outcome.kind} {outcome.error[:200]}")
    print(f"步骤：{steps}")
    print(f"结论：{outcome.data}")
    print(f"改了文件：{changed}")
    shutil.rmtree(work, ignore_errors=True)
    return 0 if outcome.ok and changed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
