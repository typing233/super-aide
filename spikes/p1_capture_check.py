"""P1 本地自检：真实的快照采集 + 整理（只在本机运行，不发给任何引擎）。

只打印结构和耗时，不打印窗口标题和内容。
"""

from __future__ import annotations

import ctypes
import time

ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

from super_aide import paths  # noqa: E402
from super_aide.snapshot.collector import Collector  # noqa: E402
from super_aide.snapshot.uia import UiaWorker  # noqa: E402

paths.ensure()
worker = UiaWorker()
worker.wait_ready()
collector = Collector(worker, ["KeePass.exe"], [{"name": "primary", "size": [1920, 1080], "scale": 1.25}])

t = time.perf_counter()
cap = collector.capture("ask", own=set())
quick = (time.perf_counter() - t) * 1000
print(f"按键瞬间采集：{quick:.0f}ms；窗口 {len(cap.windows)} 个；默认选区来源 {cap.selection_source}；"
      f"内容类型 {cap.content_kind}；选中文字 {len(cap.focus.get('selected_text', ''))} 字")

kinds: list[str] = []
t = time.perf_counter()
session = collector.start(cap, on_kind=kinds.append)
ctx = session.finalize(timeout=4)
print(f"后台采集 + 整理：{(time.perf_counter() - t) * 1000:.0f}ms；会话文件夹 {ctx.dir.name}")
print(f"附带图片：{[p.name for p in ctx.images]}；推荐问题的内容类型：{kinds}")
print(f"环境目录 {len(ctx.index.splitlines())} 行，{len(ctx.index)} 字")
files = sorted(p.relative_to(ctx.dir).as_posix() for p in ctx.dir.rglob("*") if p.is_file())
print(f"会话文件：{len(files)} 个 → {[f for f in files if not f.startswith('windows/')]} + windows/ 下 "
      f"{sum(1 for f in files if f.startswith('windows/'))} 个")
worker.stop()
