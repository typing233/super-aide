"""P1 冒烟测试（操作模式）：全放行 + 正式拦截钩子，两个引擎各跑一遍。

任务：在一个临时文件夹里创建 smoke_act.txt（验证全放行能直接动手），再执行暗号命令
（验证我们正式的拦截钩子：Claude 用 SDK 钩子，Codex 用 `python -m super_aide.engines.codex_hook`）。
不发送真实屏幕，测完删除临时文件夹。

用法：uv run python spikes/p1_smoke_act.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer

from p0_common import strip_nested_session_env
from p1_smoke import synthetic_capture

strip_nested_session_env()

from super_aide import config, paths  # noqa: E402
paths.ROUTER = Path(tempfile.mkdtemp(prefix="aide-router-"))  # 测试不写你真实的路由学习记录（2026-10-08 曾经写进去过）
from super_aide.engines import prompts  # noqa: E402
from super_aide.engines.hub import EngineHub  # noqa: E402
from super_aide.router import EngineRouter, Task  # noqa: E402
from super_aide.snapshot.collector import Collector  # noqa: E402
from super_aide.snapshot.uia import UiaWorker  # noqa: E402

WORK = Path(tempfile.mkdtemp(prefix="super_aide_act_"))


def task_text(engine: str) -> str:
    target = WORK / f"{engine}.txt"
    return (f"按顺序做两件事，每件都单独用命令行执行：\n"
            f"1. 创建文件 {target}，内容写 ok\n"
            f"2. 执行 echo SUPER_AIDE_CANARY_BLOCK\n最后简短汇报两件事各自的结果。")


class ActSmoke:
    def __init__(self, app: QCoreApplication) -> None:
        self.app = app
        paths.ensure()
        self.collector = Collector(UiaWorker(), [], [])
        self.plan = ["claude", "codex"]

    def next(self) -> None:
        if not self.plan:
            shutil.rmtree(WORK, ignore_errors=True)
            self.app.quit()
            return
        self.engine = self.plan.pop(0)
        cfg = config.load()
        cfg.pin_engine = self.engine
        self.hub = EngineHub(EngineRouter(cfg), prompts.shared_instructions(), True)
        self.hub.event.connect(self.on_event)
        print(f"\n=== {self.engine} · 操作模式", flush=True)
        self.t0, self.text, self.statuses = time.perf_counter(), "", []
        snap = self.collector.start(synthetic_capture())
        question = task_text(self.engine)
        self.hub.ask(snap.id, "act", question, snap, Task("act", question, "text", "Code.exe"))

    def on_event(self, key: str, ev: dict) -> None:
        kind = ev["type"]
        if kind == "route":
            print(f"  路由：{ev['engine']} · {ev['model']} · 思考强度 {ev['effort']}", flush=True)
        elif kind == "status":
            self.statuses.append(ev["text"])
            print(f"  · {ev['text']}", flush=True)
        elif kind in ("new_message", "retract"):
            self.text = ""
        elif kind == "delta":
            self.text += ev["text"]
        elif kind == "error":
            print(f"  ✗ {ev['text']}", flush=True)
        elif kind == "done":
            target = WORK / f"{self.engine}.txt"
            created = target.exists() and target.read_text(encoding="utf-8", errors="replace").strip()
            print(f"  汇报：{self.text.strip()[:300]}", flush=True)
            print(f"  [{'成功' if ev.get('ok') else '失败'}] 总计 {time.perf_counter() - self.t0:.1f}s；"
                  f"文件已创建：{bool(created)}（内容 {created!r}）", flush=True)
            hub = self.hub
            QTimer.singleShot(0, lambda: (hub.shutdown(), self.next()))


def main() -> None:
    app = QCoreApplication(sys.argv)
    smoke = ActSmoke(app)
    QTimer.singleShot(0, smoke.next)
    QTimer.singleShot(420_000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
