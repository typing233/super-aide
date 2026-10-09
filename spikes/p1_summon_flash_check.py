"""召唤闪烁自检：真实的控制器 + 空的引擎中枢（不发送任何内容）。

1. 启动预热时网页很慢（开机自启时常见）：输入框不能自己出现在屏幕上。
2. 连续召唤（操作 → 问答 → 问答 → 操作，窗口被隐藏过，上一次是回答卡片），每次召唤时高速截取输入框所在
   的区域：第一眼不能是上一次留下的画面（旧模式的颜色、上一次的卡片），出现后不能先变淡再出现（闪一下），
   位置也不能再跳。截图有时会漏掉几帧，旧画面不一定每次都截到：改动召唤流程后多跑几遍。

为了截到输入框，这里不给它设"不出现在截图里"；背后铺一层灰色窗口，颜色好分辨。截图在另一个进程里做：
同一进程里的截图线程要和召唤抢 GIL，最要紧的那一百多毫秒恰好截不到。会在真实屏幕上出现约 20 秒。

    uv run --no-sync python -X utf8 spikes/p1_summon_flash_check.py [-v 逐帧数据]
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from super_aide import config, paths
from super_aide.app import _displays
from super_aide.shell import controller as controller_mod
from super_aide.shell.controller import Controller
from super_aide.shell.panel import MARGIN, Panel
from super_aide.snapshot.collector import Collector
from super_aide.snapshot.uia import UiaWorker

SLOW_WARMUP_MS = 900  # 预热时网页晚这么久才处理"显示输入框"（比预热等的 600ms 久）
BASELINE_MS = 150     # 召唤前先截这么久，作为背景
SAMPLE_MS = 700       # 召唤后截这么久
MODE_NAME = {"ask": "问答", "act": "操作"}
DEAD_HWND = 0x7FFFFFF0  # 不存在的窗口
OUT = Path(__file__).parent / "out" / "flash"
SAMPLER = r"""
import sys, time
import mss, numpy as np
left, top, width, height, ms = map(int, sys.argv[1:6])
region = {"left": left, "top": top, "width": width, "height": height}
sct = mss.MSS()
sct.grab(region)
print("ready", flush=True)
stamps, frames = [], []
end = time.perf_counter() + ms / 1000
while time.perf_counter() < end:
    shot = sct.grab(region)
    stamps.append(time.perf_counter())
    frames.append(np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)[..., 2::-1].copy())
    time.sleep(0.001)
np.savez(sys.argv[6], stamps=np.array(stamps), frames=np.stack(frames))
"""


class NoEngines(QObject):
    event = Signal(str, dict)

    def ask(self, *_args) -> None:
        pass  # 卡片停在"正在看你的屏幕…"

    def is_busy(self, _key: str) -> bool:
        return False

    def interrupt(self, _key: str) -> None:
        pass

    def feedback(self, *_args) -> None:
        pass


class Sampler:
    """在另一个进程里尽快地连续截取一块屏幕区域（物理像素）。perf_counter 在各进程间是同一个时钟。"""

    def __init__(self, region: dict, ms: int, name: str) -> None:
        OUT.mkdir(parents=True, exist_ok=True)
        self.out = OUT / f"{name}.npz"
        args = [str(region[k]) for k in ("left", "top", "width", "height")] + [str(ms), str(self.out)]
        self.proc = subprocess.Popen([sys.executable, "-c", SAMPLER, *args], stdout=subprocess.PIPE, text=True)
        self.proc.stdout.readline()  # 等它准备好再召唤

    def frames(self) -> list[tuple[float, np.ndarray]]:
        self.proc.wait()
        data = np.load(self.out)
        return [(float(t), f.astype(np.int16)) for t, f in zip(data["stamps"], data["frames"])]


def measure(rgb: np.ndarray, base: np.ndarray) -> tuple[float, int, int]:
    """(和背景差多少, 问答色的像素数, 操作色的像素数)。模式色来自输入框左边的光点和光标。"""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    blue = int(((b > 235) & (b - r > 90) & (g < 165)).sum())
    orange = int(((r > 235) & (r - b > 120) & (g < 200)).sum())
    return float(np.abs(rgb - base).mean()), blue, orange


def timeline(states: list[tuple[float, float, str | None]]) -> str:
    """把逐帧的状态压成几段：空 / 问答 / 操作 / 看不出模式（可见度范围）。"""
    segments: list[list] = []
    for ms, vis, mode in states:
        label = "空" if vis < 0.15 else MODE_NAME.get(mode, "看不出模式")
        if segments and segments[-1][0] == label:
            seg = segments[-1]
            seg[2], seg[3], seg[4] = ms, min(seg[3], vis), max(seg[4], vis)
        else:
            segments.append([label, ms, ms, vis, vis])
    parts = []
    for label, start, end, lo, hi in segments:
        span = f"+{start:.0f}–{end:.0f}ms {label}"
        parts.append(span if label == "空" else f"{span} {lo:.0%}–{hi:.0%}")
    return " · ".join(parts)


def backdrop() -> list[QWidget]:
    walls = []
    for screen in QGuiApplication.screens():
        w = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        w.setAttribute(Qt.WA_ShowWithoutActivating)
        w.setAutoFillBackground(True)
        pal = w.palette()
        pal.setColor(QPalette.Window, QColor(128, 128, 128))
        w.setPalette(pal)
        w.setGeometry(screen.geometry())
        w.show()
        walls.append(w)
    return walls


def main() -> int:
    app = QApplication(sys.argv)
    paths.ensure()
    cfg = config.load()
    worker = UiaWorker()
    worker.wait_ready()

    # 输入框要能被截到（定格浮层照旧不出现在截图里，截到的就是它下面的灰色背景）
    exclude = controller_mod.exclude_from_capture
    controller_mod.exclude_from_capture = lambda w: None if isinstance(w, Panel) else exclude(w)
    # 模拟开机时网页很慢：预热时那次"显示输入框"晚 SLOW_WARMUP_MS 才执行
    real_call, delayed = Panel.call, []

    def slow_call(self, fn, arg=None):
        if fn == "showInput" and not delayed:
            delayed.append(fn)
            QTimer.singleShot(SLOW_WARMUP_MS, lambda: real_call(self, fn, arg))
            return
        real_call(self, fn, arg)

    Panel.call = slow_call
    ctrl = Controller(cfg, Collector(worker, cfg.blocked_apps, _displays(app)), NoEngines())

    results: list[tuple[str, bool, str]] = []
    walls: list[QWidget] = []
    marks: dict = {}
    box: dict = {}

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    place = ctrl._place

    def traced_place() -> None:
        if "t0" in marks and "place" not in marks:
            marks["place"] = time.perf_counter()
        place()

    ctrl._place = traced_place
    ctrl.bridge.shown_on_screen.connect(lambda: marks.setdefault("shown", time.perf_counter()) if "t0" in marks else None)

    def run(steps: list, then) -> None:
        """依次执行 (等多久, 做什么)。"""
        if not steps:
            then()
            return
        delay, fn = steps[0]

        def go() -> None:
            fn()
            run(steps[1:], then)

        QTimer.singleShot(delay, go)

    def startup_checks() -> None:
        geo = ctrl.panel.geometry()
        on_screen = any(s.geometry().intersects(geo) for s in QGuiApplication.screens())
        check("预热时网页很慢：输入框没有自己出现在屏幕上", not on_screen, f"面板在 {geo.getRect()}")
        check("预热时网页很慢：没有进入输入状态", ctrl.view is None, f"view={ctrl.view!r}")

    def record_box() -> None:
        g = ctrl.panel.geometry()
        inner = QRect(g.x() + MARGIN, g.y() + MARGIN, g.width() - 2 * MARGIN, g.height() - 2 * MARGIN)
        left, top, right, bottom = ctrl.screen.to_physical(inner)
        box.update(geo=g, region={"left": left, "top": top, "width": right - left, "height": bottom - top})

    def js(code: str) -> None:
        ctrl.panel.view.page().runJavaScript(code)

    def run_round(i: int, mode: str, name: str, setup: list, hide_after: bool, then) -> None:
        def sample() -> None:
            sampler = Sampler(box["region"], BASELINE_MS + SAMPLE_MS + 100, f"round{i}")
            marks.clear()

            def go() -> None:
                marks["t0"] = time.perf_counter()
                ctrl.summon(mode)
                marks["geo0"] = ctrl.panel.geometry()

            def stop() -> None:
                marks["end"] = time.perf_counter()
                geo = ctrl.panel.geometry()
                active = ctrl.panel.isActiveWindow()
                if hide_after:
                    ctrl.prev_fg = DEAD_HWND  # 原来的窗口已经关掉：收起后退回隐藏
                ctrl.dismiss()

                def later() -> None:  # 收起后不卡住主线程：网页的空白帧要靠主线程画到窗口上
                    if hide_after:
                        print(f"\n（{name}：面板{'是' if active else '不是'}活动窗口，"
                              f"{'走的是真实的退回隐藏' if active else '隐藏是这里补上的'}）")
                        if not active:  # 面板没抢到焦点（比如被系统拦了）就走不到隐藏那一步：照它的做法补上
                            ctrl.panel.hide()
                        check(f"{name}：原来的窗口关掉了，收起后面板隐藏", not ctrl.panel.isVisible(),
                              f"面板是活动窗口：{active}")
                    analyze(mode, name, sampler.frames(), geo)
                    QTimer.singleShot(600, then)

                QTimer.singleShot(400, later)

            QTimer.singleShot(BASELINE_MS, go)
            QTimer.singleShot(BASELINE_MS + SAMPLE_MS, stop)

        run(setup, sample)

    def analyze(mode: str, name: str, frames, geo) -> None:
        t0 = marks["t0"]
        base = np.mean([f for t, f in frames if t < t0], axis=0)
        after = [((t - t0) * 1000, measure(f, base)) for t, f in frames if t0 <= t < marks["end"]]
        full = float(np.median([d for _, (d, _, _) in after[-5:]])) or 1.0
        states = []
        for ms, (diff, blue, orange) in after:
            shown = "act" if orange > 20 and orange > blue else "ask" if blue > 20 else None
            states.append((ms, diff / full, shown))
        other = "act" if mode == "ask" else "ask"
        # 旧画面：另一个模式的颜色，或者已经完全可见、却不是这次的输入框（比如上一次的回答卡片）
        stale = [ms for ms, vis, shown in states if (shown == other and vis > 0.3) or (vis >= 0.95 and shown != mode)]
        dips, peak = [], None
        for ms, vis, _ in states:
            if peak is None and vis < 0.15:
                continue
            peak = max(peak or 0.0, vis)
            if peak - vis > 0.15:  # 出现以后又变淡：先露出了旧画面，再从透明重新淡入
                dips.append(ms)
        place_ms = (marks.get("place", t0) - t0) * 1000
        shown_ms = (marks.get("shown", t0) - t0) * 1000
        print(f"\n[{name}] 召唤{MODE_NAME[mode]}：{len(states)} 帧；面板挪回屏幕 +{place_ms:.0f}ms，网页画好 +{shown_ms:.0f}ms")
        print("  " + timeline(states))
        if "-v" in sys.argv:
            for (ms, (_, blue, orange)), (_, vis, _) in zip(after, states):
                print(f"    +{ms:6.1f}ms  可见 {vis:4.0%}  问答色 {blue:4d}  操作色 {orange:4d}")
        check(f"{name}：截的区域就是输入框的位置", geo == box["geo"], f"{geo.getRect()} ≠ {box['geo'].getRect()}")
        check(f"{name}：召唤后位置没有再跳", geo == marks["geo0"], f"{marks['geo0'].getRect()} → {geo.getRect()}")
        check(f"{name}：没有先露出上一次的画面", not stale,
              f"+{stale[0]:.0f}ms 起共 {len(stale)} 帧" if stale else "")
        check(f"{name}：出现后没有先变淡再出现（闪一下）", not dips, f"+{dips[0]:.0f}ms 起共 {len(dips)} 帧" if dips else "")
        check(f"{name}：最后显示的是{MODE_NAME[mode]}输入框", bool(states) and states[-1][2] == mode,
              str(states[-1] if states else None))

    def finish() -> None:
        for w in walls:
            w.close()
        bad = [r for r in results if not r[1]]
        print()
        for name, ok, detail in results:
            print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
        print(f"\n{len(results) - len(bad)}/{len(results)} 通过")
        app.exit(1 if bad else 0)

    card = [(0, lambda: ctrl.summon("ask")), (500, lambda: js("app.submit('这是什么？')")),
            (700, ctrl.dismiss), (500, lambda: None)]
    rounds = [  # (召唤哪个模式, 名字, 先做什么, 收起后隐藏窗口)
        ("ask", "操作 → 问答", [], False),
        ("ask", "问答 → 问答", [], False),
        ("act", "问答 → 操作", [], True),
        ("ask", "隐藏过再召唤", [], False),
        ("ask", "回答卡片 → 问答", card, False),
    ]

    def next_round(i: int = 0) -> None:
        if i >= len(rounds):
            finish()
            return
        mode, name, setup, hide_after = rounds[i]
        run_round(i, mode, name, setup, hide_after, lambda: next_round(i + 1))

    def start_when_ready() -> None:
        if not ctrl.ready:
            QTimer.singleShot(100, start_when_ready)
            return
        # 预热里那次被推迟的"显示输入框"执行完以后再看；然后先召唤一次操作，记下输入框的位置
        run([(SLOW_WARMUP_MS + 400, startup_checks), (100, lambda: walls.extend(backdrop())),
             (300, lambda: ctrl.summon("act")), (700, record_box), (0, ctrl.dismiss), (500, lambda: None)],
            next_round)

    QTimer.singleShot(200, start_when_ready)
    QTimer.singleShot(60_000, app.quit)
    code = app.exec()
    worker.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
