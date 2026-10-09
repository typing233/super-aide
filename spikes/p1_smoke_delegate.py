"""转交冒烟测试：Claude（操作模式）调用 operate_ui → Codex 去做 → 结果交回 Claude。

为了不动你的鼠标键盘，交给 Codex 的那一步是用命令行在临时目录建文件，验证的是转交通路本身。
不发送真实屏幕，测完删除临时目录。

用法：uv run python spikes/p1_smoke_delegate.py
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

WORK = Path(tempfile.mkdtemp(prefix="super_aide_delegate_"))
TARGET = WORK / "delegated.txt"
QUESTION = (f"这是在测试转交功能：请调用 operate_ui 工具，让它创建文件 {TARGET}，内容写 ok。"
            "这一步必须通过 operate_ui 完成，不要自己执行命令。拿到结果后简短汇报。")


def main() -> None:
    app = QCoreApplication(sys.argv)
    paths.ensure()
    cfg = config.load()
    cfg.pin_engine = "claude"
    hub = EngineHub(EngineRouter(cfg), prompts.shared_instructions(), False)
    collector = Collector(UiaWorker(), [], [])
    t0 = time.perf_counter()
    state = {"text": ""}

    def on_event(_key: str, ev: dict) -> None:
        kind = ev["type"]
        if kind == "route":
            print(f"路由：{ev['engine']} · {ev['model']} · 思考强度 {ev['effort']}", flush=True)
        elif kind == "status":
            print(f"  · {ev['text']}", flush=True)
        elif kind in ("new_message", "retract"):
            state["text"] = ""
        elif kind == "delta":
            state["text"] += ev["text"]
        elif kind == "error":
            print(f"  ✗ {ev['text']}", flush=True)
        elif kind == "done":
            print(f"汇报：{state['text'].strip()[:300]}", flush=True)
            print(f"[{'成功' if ev.get('ok') else '失败'}] 总计 {time.perf_counter() - t0:.1f}s；发生转交：{ev.get('delegated')}；"
                  f"文件已创建：{TARGET.exists()}", flush=True)
            hub.shutdown()
            shutil.rmtree(WORK, ignore_errors=True)
            app.quit()

    hub.event.connect(on_event)
    snap = collector.start(synthetic_capture())
    hub.ask(snap.id, "act", QUESTION, snap, Task("act", QUESTION, "text", "Code.exe"))
    QTimer.singleShot(420_000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
