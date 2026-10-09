"""P1 冒烟测试：不经过界面，用合成的快照走一遍"快照 → 路由 → 引擎 → 流式回答 → 追问"。

不发送真实屏幕：截图是合成的报错图，窗口列表为空。两个引擎各跑一遍（固定引擎），Claude 再追问一轮。

用法：uv run python spikes/p1_smoke.py
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from datetime import datetime
from io import BytesIO

from PIL import Image
from PySide6.QtCore import QCoreApplication, QTimer

from p0_common import strip_nested_session_env, synthetic_error_png

strip_nested_session_env()

from super_aide import config, paths  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
paths.ROUTER = Path(tempfile.mkdtemp(prefix="aide-router-"))  # 测试不写你真实的路由学习记录（2026-10-08 曾经写进去过）
from super_aide.engines import prompts  # noqa: E402
from super_aide.engines.hub import EngineHub  # noqa: E402
from super_aide.router import EngineRouter, Task  # noqa: E402
from super_aide.snapshot.collector import Capture, Collector  # noqa: E402
from super_aide.snapshot.uia import UiaWorker  # noqa: E402

QUESTION = "这个报错是什么原因？"
FOLLOWUP = "那我应该装到哪个 Python 里？一句话。"


def synthetic_capture() -> Capture:
    img = Image.open(BytesIO(synthetic_error_png())).convert("RGB")
    return Capture(created=datetime.now(), mode="ask", screen_bgra=img.tobytes("raw", "BGRX"),
                   screen_size=img.size, screen_origin=(0, 0), foreground=None, focus={}, windows=[],
                   default_selection=(0, 0, *img.size), selection_source="screen", content_kind="error")


class Smoke:
    def __init__(self, app: QCoreApplication) -> None:
        self.app = app
        paths.ensure()
        self.collector = Collector(UiaWorker(), [], [])
        self.plan = [("claude", True), ("codex", False)]
        self.hub: EngineHub | None = None

    def next(self) -> None:
        if not self.plan:
            self.app.quit()
            return
        engine, self.with_followup = self.plan.pop(0)
        cfg = config.load()
        cfg.pin_engine = engine
        self.hub = EngineHub(EngineRouter(cfg), prompts.shared_instructions(), cfg.blocklist_enabled)
        self.hub.event.connect(self.on_event)
        self.start_turn(engine, QUESTION, first=True)

    def start_turn(self, engine: str, question: str, first: bool) -> None:
        print(f"\n=== {engine} · {'首问' if first else '追问'}：{question}", flush=True)
        self.t0, self.first_delta, self.text, self.events = time.perf_counter(), None, "", Counter()
        snap = self.collector.start(synthetic_capture())
        if first:
            self.key = snap.id
            self.hub.ask(self.key, "ask", question, snap, Task("ask", question, "error"))
        else:
            self.hub.followup(self.key, question, snap)

    def on_event(self, key: str, ev: dict) -> None:
        kind = ev["type"]
        self.events[kind] += 1
        if kind == "route":
            print(f"  路由：{ev['engine']} · {ev['model']} · 思考强度 {ev['effort']}（{ev['via']}）", flush=True)
        elif kind == "status":
            print(f"  · {ev['text']}", flush=True)
        elif kind in ("new_message", "retract"):
            self.text = ""
        elif kind == "delta":
            self.first_delta = self.first_delta or time.perf_counter() - self.t0
            self.text += ev["text"]
        elif kind == "error":
            print(f"  ✗ {ev['text']}", flush=True)
        elif kind == "done":
            took = time.perf_counter() - self.t0
            first = f"{self.first_delta:.1f}s" if self.first_delta else "-"
            print(f"  回答：{self.text.strip()[:300]}", flush=True)
            print(f"  [{'成功' if ev.get('ok') else '失败'}] 首字 {first}，总计 {took:.1f}s，"
                  f"会话 {ev.get('session', '')[:12]}，事件 {dict(self.events)}", flush=True)
            if self.with_followup:
                self.with_followup = False
                QTimer.singleShot(0, lambda: self.start_turn(ev.get("engine", ""), FOLLOWUP, first=False))
            else:
                hub = self.hub
                QTimer.singleShot(0, lambda: (hub.shutdown(), self.next()))


def main() -> None:
    app = QCoreApplication(sys.argv)
    smoke = Smoke(app)
    QTimer.singleShot(0, smoke.next)
    QTimer.singleShot(420_000, app.quit)  # 兜底：7 分钟没跑完就退出
    app.exec()


if __name__ == "__main__":
    main()
