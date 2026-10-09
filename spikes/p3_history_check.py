"""历史记录窗口自检：临时会话目录里放几段示例问答，打开窗口，模拟搜索、切换、Esc，截图。

不读你真实的会话记录。

    uv run --no-sync python -X utf8 spikes/p3_history_check.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from super_aide import history, paths

paths.SESSIONS = Path(tempfile.mkdtemp(prefix="aide-history-"))
from super_aide.shell.history_window import HistoryWindow  # noqa: E402

OUT = Path(__file__).parent / "out" / "history"
OUT.mkdir(parents=True, exist_ok=True)
NOW = datetime.now()
SAMPLES = [
    (NOW - timedelta(minutes=12), "ask", [
        ("这个报错是什么原因？", True, "当前内核用的 Python 环境里没有装 `pandas`。\n\n1. 在 notebook 里运行：\n\n"
                                  "   ```\n   %pip install pandas\n   ```\n\n2. 重启内核，再运行这个单元格。"),
        ("装了还是不行", True, "多半是装到了别的 Python。先运行 `import sys; print(sys.executable)` 看内核用的是哪个。")]),
    (NOW - timedelta(hours=2), "act", [
        ("帮我修好它", False, "没完成：浏览器操作还没接通。\n本次没有改动任何东西，不用撤销。")]),
    (NOW - timedelta(days=1, hours=3), "act", [
        ("帮我把这个软件卸载干净", True, "已完成：卸载了 Foo，清理了 3 处残留。\n以后要用需要重新安装。")]),
    (NOW - timedelta(days=5), "ask", [
        ("怎么把默认浏览器改成 Edge？", True, "1. 打开**设置** → **应用** → **默认应用**。\n2. 点 **Microsoft Edge**。\n3. 点**设为默认值**。")]),
]


def seed() -> None:
    for started, mode, turns in SAMPLES:
        folder = paths.SESSIONS / (started.strftime("%Y%m%d-%H%M%S-") + f"{abs(hash(started)) % 65536:04x}")
        folder.mkdir()
        history.save(folder, {"mode": mode, "started": started.isoformat(timespec="seconds"), "foreground": "",
                              "turns": [{"t": started.isoformat(timespec="seconds"), "question": q, "answer": a,
                                         "ok": ok, "error": "" if ok else "浏览器操作还没接通：在 ChatGPT 桌面应用的插件页里，把 Browser 插件重新安装一次。",
                                         "engine": "codex" if mode == "act" else "claude",
                                         "model": "gpt-6-astra" if mode == "act" else "claude-opus-5-5"}
                                        for q, ok, a in turns]})


def main() -> int:
    seed()
    app = QApplication(sys.argv)
    theme = {"value": "dark"}
    win = HistoryWindow(lambda: theme["value"])
    results: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    def probe(code, name, expect):
        win.view.page().runJavaScript(code, 0, lambda v: check(name, expect(v), repr(v)))

    def js(code):
        win.view.page().runJavaScript(code)

    def shot(name):
        size, dpr = win.size(), win.devicePixelRatioF()
        canvas = QPixmap(round(size.width() * dpr), round(size.height() * dpr))
        canvas.setDevicePixelRatio(dpr)
        g = QLinearGradient(0, 0, size.width(), size.height())
        g.setColorAt(0, QColor("#3b4a6b"))
        g.setColorAt(1, QColor("#6b4a5a"))
        p = QPainter(canvas)
        p.fillRect(canvas.rect(), g)
        p.drawPixmap(QPoint(0, 0), win.grab())
        p.end()
        canvas.save(str(OUT / f"{name}.png"))

    steps = [
        (900, lambda: (check("首次打开后显示", win.isVisible()), shot("1-dark"))),
        (0, lambda: probe("document.querySelectorAll('.item').length", "列出 4 段对话", lambda v: v == 4)),
        (0, lambda: probe("document.querySelector('.item.active .q').textContent", "默认选中最新的",
                          lambda v: v == "这个报错是什么原因？")),
        (0, lambda: probe("document.querySelectorAll('.turn').length", "追问也显示出来", lambda v: v == 2)),
        (0, lambda: js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true}))")),
        (400, lambda: probe("document.querySelector('.turn .error').textContent", "下移到失败的操作，显示原因",
                            lambda v: (v or "").startswith("浏览器操作还没接通"))),
        (0, lambda: shot("2-failed")),
        (0, lambda: js("const s = document.querySelector('#search'); s.value = '默认浏览器'; s.dispatchEvent(new Event('input'))")),
        (600, lambda: probe("document.querySelectorAll('.item').length", "搜索", lambda v: v == 1)),
        (0, lambda: (theme.update(value="light"), js("document.querySelector('#search').focus()"))),
        (100, lambda: js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")),
        (600, lambda: probe("document.querySelectorAll('.item').length", "Esc 先清空搜索", lambda v: v == 4)),
        (0, lambda: shot("3-light")),
        (0, lambda: js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")),
        (400, lambda: check("再按 Esc 关窗口", not win.isVisible())),
        (0, win.open),
        (600, lambda: check("再次打开", win.isVisible())),
    ]

    def run(i=0):
        if i >= len(steps):
            bad = [r for r in results if not r[1]]
            for name, ok, detail in results:
                print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if not ok else ""))
            print(f"\n{len(results) - len(bad)}/{len(results)} 通过，截图在 {OUT}")
            app.exit(1 if bad else 0)
            return
        delay, fn = steps[i]
        QTimer.singleShot(delay, lambda: (fn(), run(i + 1)))

    def wait_visible(tries=0):
        if win.isVisible() or tries > 100:
            run()
        else:
            QTimer.singleShot(100, lambda: wait_visible(tries + 1))

    win.open()
    wait_visible()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
