"""自检：自我改进的完整流程，真实的 Claude Code（claude-opus-5-5 · max · auto 权限）。

在临时目录里造一个"正在运行的版本"（一个带 bug 的小包加上它的测试），不碰真实的代码和数据：
1. 失败：数词有个 bug（连续空格多数了词）。应该：初筛判"值得改" → 修好 + 加测试 → 流程自己跑测试 → 独立复核 → 打包 → 待生效；
2. 失败：服务连不上（网络故障）。初筛应该判"无需改进"；
3. 和 1 一样的问题，排在 1 后面：1 "生效"之后轮到它，应该判"已覆盖"，不再改。
会花一点模型费用（几个美元以内）。

    uv run python spikes/p11_evolve_check.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for name in list(os.environ):  # 在 Claude Code 里跑这个脚本时：别让嵌套的会话以为自己在别的会话里
    if name.startswith(("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_AGENT_SDK")):
        del os.environ[name]

from PySide6.QtCore import QCoreApplication  # noqa: E402

from super_aide import paths  # noqa: E402
from super_aide.config import Config  # noqa: E402
from super_aide.evolve import manager  # noqa: E402
from super_aide.evolve.manager import EvolveManager  # noqa: E402
from super_aide.evolve.workshop import Installed  # noqa: E402

BUGGY = '''"""文字小工具（超级助手回答"有几个词"之类的问题时用）。"""


def word_count(text: str) -> int:
    """数一段英文里有几个词。"""
    return len(text.split(" "))
'''
TEST = '''from super_aide.textutil import word_count


def test_simple():
    assert word_count("hello world") == 2
'''
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(("  通过 " if ok else "  失败 ") + name + (f"：{detail}" if detail else ""), flush=True)


def fake_installed(root: Path, version: str = "0.2.0") -> Installed:
    site = root / "site"
    pkg = site / "super_aide"
    (pkg / "_source" / "tests").mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "textutil.py").write_text(BUGGY, encoding="utf-8")
    (pkg / "_source" / "pyproject.toml").write_text('[project]\nname = "super-aide"\nversion = "0.2.0"\n',
                                                    encoding="utf-8")
    (pkg / "_source" / "tests" / "test_textutil.py").write_text(TEST, encoding="utf-8")
    info = site / f"super_aide-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.4\nName: super-aide\nVersion: {version}\n", encoding="utf-8")
    return Installed(version, pkg, info, site, False, f"fp-{version}-{time.time()}")


def failure(conv: str, question: str, answer: str, error: str) -> dict:
    return {"conv": conv, "mode": "ask", "started": time.time() - 60, "captured": time.time(), "home": "",
            "foreground": "notepad.exe", "kind": "text", "url": "", "question": question,
            "decision": {"engine": "claude", "model": "claude-opus-5-5", "effort": "medium", "reason": ""},
            "record": [{"t": "2026-10-09T18:00:00", "question": question, "answer": answer, "ok": False,
                        "error": error, "reason": "reported", "engine": "claude", "model": "claude-opus-5-5",
                        "effort": "medium", "seconds": 8, "tools": 1, "trace": ["正在数词"],
                        "situation": {"text": "the  quick brown   fox"}}],
            "trouble": [{"kind": "thumbs_down", "choice": "wrong", "text": "明明是 4 个词"}]}


def drive(mgr: EvolveManager, job, done: tuple[str, ...], limit_s: float = 1800) -> None:
    started = time.time()
    last = ""
    while time.time() - started < limit_s:
        asyncio.run(mgr._step())
        line = f"{job.status} {job.phase} {job.step}"
        if line != last:
            print(f"    [{time.time() - started:5.0f}s] {line}", flush=True)
            last = line
        if job.status in done:
            return
        if job.status in ("waiting", "login"):
            print(f"    暂停：{job.error}", flush=True)
            if job.status == "login":
                return
            time.sleep(min(30, max(0, job.retry_at - time.time())))
            job.retry_at = 0


def main() -> int:
    QCoreApplication.instance() or QCoreApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="aide-evolve-check-"))
    print(f"临时目录：{tmp}", flush=True)
    state = SimpleNamespace(installed=fake_installed(tmp / "inst"))
    manager.Installed = SimpleNamespace(current=lambda: state.installed)
    paths.LOGS = tmp / "logs"
    paths.LOGS.mkdir()
    router = SimpleNamespace(ready={"claude"}, meta={})
    hub = SimpleNamespace(conversations={}, loop=None, _submit=lambda coro: coro.close())
    mgr = EvolveManager(Config(), hub, router, quit_app=lambda: None, root=tmp / "evolve")
    mgr.notify.connect(lambda title, body: print(f"    通知：{title}", flush=True))

    job1 = mgr.submit(failure("c1", "这段话有几个词？", "一共 7 个词。", "用户说答错了"))
    job2 = mgr.submit({"conv": "c2", "mode": "ask", "started": time.time(), "captured": time.time(), "home": "",
                       "foreground": "chrome.exe", "kind": "text", "url": "", "question": "帮我总结这篇文章",
                       "decision": {}, "record": [], "trouble": [
                           {"kind": "failure", "error": "引擎出错：Connection error: getaddrinfo failed（服务连不上）"}]})
    job3 = mgr.submit(failure("c3", "how many words: 'a  b  c'", "There are 5 words.", "用户说答错了"))

    t0 = time.time()
    print("1. 数词的 bug", flush=True)
    drive(mgr, job1, ("ready", "none", "covered", "failed", "held"))
    check("改好了，等你确认生效", job1.status == "ready", f"{job1.status} {job1.error}")
    patch_file = mgr.jobs.folder(job1) / "change.patch"
    patch = patch_file.read_text(encoding="utf-8") if patch_file.exists() else ""
    print(patch[:3000], flush=True)
    check("修了 textutil.py", "textutil.py" in patch)
    check("加了测试", "tests/" in patch)
    check("复核通过", bool(job1.review.get("approve")), str(job1.review)[:300])
    roles = [s["role"] for s in job1.sessions]
    check("用的是 Claude Code + Opus 5.5 max", (job1.engine, job1.model, job1.effort) == ("claude", "claude-opus-5-5", "max"),
          f"{job1.engine} {job1.model} {job1.effort}；会话：{roles}")
    print(f"    结论：{job1.result.get('title_zh')} —— {job1.result.get('summary_zh')}", flush=True)
    print(f"    花费 {job1.cost} 美元，用时 {time.time() - t0:.0f} 秒；权限：{mgr.state.get('permission')}", flush=True)

    if job1.status == "ready":  # 模拟你点了"生效"：把改好的代码换进"正在运行的版本"
        shutil.rmtree(state.installed.pkg / "textutil.py", ignore_errors=True)
        shutil.copy2(mgr.workshop.src / "textutil.py", state.installed.pkg / "textutil.py")
        for test in (mgr.workshop.root / "tests").glob("*.py"):
            shutil.copy2(test, state.installed.pkg / "_source" / "tests" / test.name)
        state.installed = Installed("0.2.0+aide.1", state.installed.pkg, state.installed.dist_info,
                                    state.installed.site, False, f"fp-applied-{time.time()}")
        mgr.jobs.update(job1, status="done", applied=time.time())

    print("2. 服务连不上", flush=True)
    drive(mgr, job2, ("ready", "none", "covered", "failed", "held"))
    check("初筛判无需改进", job2.status == "none", f"{job2.status} {job2.error[:120]}")

    print("3. 同样的问题，排在 1 后面", flush=True)
    drive(mgr, job3, ("ready", "none", "covered", "failed", "held"))
    check("判为已被前面的改进解决", job3.status in ("covered", "none"), f"{job3.status} {job3.error[:160]}")
    total = sum(j.cost for j in (job1, job2, job3))
    print(f"\n总花费 {total:.2f} 美元，总用时 {time.time() - t0:.0f} 秒", flush=True)
    passed = sum(ok for _, ok in results)
    print(f"{passed}/{len(results)} 通过", flush=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
