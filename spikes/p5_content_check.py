"""界面内容读取自检（不调用模型）：在新的 Edge 窗口里打开仿 notebook 的靶子页（深色主题、拼错的 modescope、
两段报错、框架、只有像素的画布、滚动到很下面才看得到的文字），检查：

- 完整内容：滚动出去的部分、框架里的文字都读得到，拼写逐字不变；
- 框选区域里的原文：只要框里的行，逐字准确；框里只有像素时用 OCR 认出来；
- 采集流程端到端：首条消息里有框选区域的原文、前台窗口完整内容的文件；
- 自研 CU 的 read 工具：读整个窗口，能分段往后读。

会弹出一个 Edge 窗口，大约 20 秒，最后关掉它。

    uv run --no-sync python -X utf8 spikes/p5_content_check.py
"""

from __future__ import annotations

import sys

sys.coinit_flags = 0

import ctypes  # noqa: E402

ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import win32gui  # noqa: E402

from super_aide import paths  # noqa: E402
from super_aide.cu import inputs, server  # noqa: E402
from super_aide.snapshot import chromium, collector, uia, win32  # noqa: E402

PAGE = (Path(__file__).parent / "p5_notebook.html").resolve()
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
TITLE = "内容读取靶子"
CODE_LINE = "from modescope import AutoModelForCausalLM, AutoTokenizer"
results: list[tuple[str, bool, str, float]] = []


def check(name, ok, detail="", ms=0.0):
    results.append((name, ok, detail, ms))


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t) * 1000


def text_rect(worker: uia.UiaWorker, hwnd: int, needle: str, scroll: bool = False):
    """页面里一段文字在屏幕上的位置（物理像素）。scroll：先把它滚到可视区的底部（窗口小的时候它可能在下面）。"""
    for element in uia._documents(worker, hwnd):
        pattern = uia._text_pattern(element)
        if not pattern:
            continue
        found = pattern.pattern.DocumentRange.FindText(needle, 0, 0)
        if found and scroll:
            found.ScrollIntoView(False)
            time.sleep(0.5)
        boxes = uia._boxes(found) if found else []
        if boxes:
            return tuple(round(v) for v in boxes[0])
    return None


def open_page() -> int:
    for w in win32.visible_windows():  # 上次没关掉的靶子窗口
        if w.title.startswith(TITLE):
            win32gui.PostMessage(w.hwnd, 0x0010, 0, 0)
    time.sleep(0.5)
    before = {w.hwnd for w in win32.visible_windows()}
    subprocess.Popen([str(EDGE), "--new-window", f"{PAGE.as_uri()}?run={int(time.time())}"])
    for _ in range(60):
        hwnd = next((w.hwnd for w in win32.visible_windows() if w.title.startswith(TITLE) and w.hwnd not in before), 0)
        if hwnd:
            for _ in range(40):  # 等网页内容的子窗口建好（刚打开的窗口还没有）
                if chromium.children(hwnd):
                    break
                time.sleep(0.25)
            return hwnd
        time.sleep(0.25)
    return 0


def main() -> int:
    hwnd = open_page()
    if not hwnd:
        print("Edge 窗口没出现")
        return 1
    time.sleep(1.5)
    inputs.focus_window(hwnd)
    time.sleep(0.3)
    worker = uia.UiaWorker()
    worker.wait_ready()
    try:
        # 1) 完整内容
        (text, how), ms = timed(lambda: worker.call(uia.window_content, hwnd, timeout=8, default=("", "超时")))
        check("完整内容：拼写逐字不变", CODE_LINE in text and "No module named 'modescope'" in text, how, ms)
        check("完整内容：滚动出去的部分", "END-OF-PAGE-MARKER-4409" in text, f"{len(text):,} 字")
        check("完整内容：框架里的文字", "IFRAME-MARKER-7731" in text)
        check("完整内容：界面控件的文字（标签页、地址栏等）", "【界面上的其它文字和控件" in text)

        # 2) 框选区域里的原文：从代码第一行框到报错最后一行
        top = worker.call(text_rect, hwnd, "# 导入模型和分词器", timeout=5)
        bottom = worker.call(text_rect, hwnd, "No module named 'modescope'", timeout=5)
        if not top or not bottom:
            check("找到靶子文字的位置", False, f"{top} {bottom}")
        else:
            rect = (top[0] - 20, top[1] - 8, top[0] + 1400, bottom[3] + 8)
            sel, ms = timed(lambda: worker.call(uia.text_in_rect, hwnd, rect, timeout=6, default=""))
            check("框选原文：代码逐字准确", CODE_LINE in sel, sel[:300], ms)
            check("框选原文：报错完整", "ModuleNotFoundError: No module named 'modescope'" in sel)
            check("框选原文：不含框外的内容", "tokenizer' is not defined" not in sel and "notebook.ipynb" not in sel,
                  sel[:120])

        # 3) 采集流程端到端（模拟用户按 Alt+Q 后框选报错区域、马上提问）。采集用自己的 UIA 线程：
        # 它会在后台把所有窗口读一遍，和上面的探测共用一个线程的话探测要排很久的队
        paths.SESSIONS = Path(tempfile.mkdtemp(prefix="aide-p5-"))
        col = collector.Collector(uia.UiaWorker(), [], [])
        col.warm()
        cap = col.capture("ask", own=set())
        check("前台是靶子窗口", cap.foreground is not None and cap.foreground.hwnd == hwnd,
              cap.foreground.title if cap.foreground else "无")
        if top and bottom:
            snap = col.start(cap)
            snap.set_selection((top[0] - 20, top[1] - 8, top[0] + 1400, bottom[3] + 8), "manual")
            ctx, ms = timed(snap.finalize)
            index = ctx.index
            check("首条消息：框选区域的原文", "<selection_text>" in index and CODE_LINE in index and "逐字原文" in index,
                  index[index.find("- 框选区域"):][:400], ms)
            check("首条消息：前台窗口的完整内容文件", "前台窗口的完整内容" in index)
            fg_file = next((w["text"] for w in snap.windows if w["foreground"]), None)
            full = (ctx.dir / fg_file).read_text(encoding="utf-8") if fg_file else ""
            check("内容文件：包括滚动出去的部分", "END-OF-PAGE-MARKER-4409" in full, fg_file or "没写文件")
            t = time.perf_counter()
            fg_before = win32.foreground()
            collector.wait(snap.futures, timeout=60)
            fg_after = win32.foreground()
            read = [w for w in snap.windows if w["text"]]
            print(f"后台读完所有窗口：再等了 {time.perf_counter() - t:.1f}s，{len(read)}/{len(snap.windows)} 个窗口有文字："
                  + "、".join(f"{w['process']} {w['chars']:,}" for w in read))
            check("后台读取不改变前台窗口", (fg_before and fg_before.hwnd) == (fg_after and fg_after.hwnd),
                  f"{fg_before and fg_before.process} → {fg_after and fg_after.process}")

        # 4) 框里只有像素（画布）：用 OCR 认。画布 64 像素高，紧挨着第 1 段填充文字的上面
        first = worker.call(text_rect, hwnd, "第 1 段填充文字", True, timeout=5)
        if first:
            s = ctypes.windll.user32.GetDpiForWindow(hwnd) / 96
            canvas = (first[0] - 6, first[1] - round(80 * s), first[0] + 1100, first[1] - 3)
            inputs.focus_window(hwnd)  # 测试期间用户可能切到了别的窗口
            time.sleep(0.4)
            cap = col.capture("ask", own=set())
            check("第二次召唤：前台是靶子窗口", cap.foreground is not None and cap.foreground.hwnd == hwnd,
                  cap.foreground.title if cap.foreground else "无")
            snap = col.start(cap)
            snap.set_selection(canvas, "manual")
            ctx, ms = timed(snap.finalize)
            part = ctx.index[ctx.index.find("- 框选区域里的文字"):][:300]
            check("画布：OCR 认出只有像素的文字", "8812" in ctx.index and "OCR" in part, part, ms)
        else:
            check("找到画布的位置", False, f"{first}")

        # 5) 自研 CU 的 read 工具
        server.observe_window(str(hwnd), screenshot=False)
        out, ms = timed(lambda: server.read(max_chars=3000))
        check("read：整个窗口、超长时提示接着读", CODE_LINE in out and "start=3000" in out, out[-120:], ms)
        rest = ""
        start = 0
        while True:
            piece = server.read(start=start, max_chars=3000)
            rest += piece
            if "start=" not in piece[-80:]:
                break
            start += 3000
        check("read：分段读到最底部", "END-OF-PAGE-MARKER-4409" in rest, f"读了 {start // 3000 + 1} 段")
    finally:
        win32gui.PostMessage(hwnd, 0x0010, 0, 0)
        worker.stop()

    width = max(len(r[0]) for r in results)
    for name, ok, detail, ms in results:
        timing = f"{ms:7.0f}ms" if ms else " " * 9
        print(f"{'✓' if ok else '✗'} {name.ljust(width)} {timing}  {detail[:160]!r}" if detail else
              f"{'✓' if ok else '✗'} {name.ljust(width)} {timing}")
    passed = sum(r[1] for r in results)
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
