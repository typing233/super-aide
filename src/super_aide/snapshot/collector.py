"""快照采集（设计第 6 节）。

两段：
- capture()：按键瞬间在主线程完成（P0 实测约 60~100ms）——前台窗口、全屏原始像素、
  焦点和选中的文字、窗口列表、默认选区。定格画面就用这里的像素，所以必须先于浮层出现。
- Session：后台把每个窗口的截图和文字、浏览器网址、控件树、系统状态写进会话文件夹；
  提问时 finalize() 生成"环境资料目录"写进首条消息，其余资料由引擎按需自己去读。

文字一律优先从界面本身读（UI Automation，逐字准确，包括滚动出去、没显示出来的部分），
界面没交出文字的地方才用 OCR 认图。模型看图会把拼错的字自动"纠正"（实测把 modescope 看成 modelscope），
所以框选区域里的原文要逐字放进首条消息。

隐私：黑名单里的应用在所有截图里涂黑，文字一律不采集；文本发出前统一打码。
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import mss
from PIL import Image, ImageDraw

from .. import paths
from ..cu import ocr
from ..experience.recall import Situation, error_lines
from . import content, redact, system, uia, win32

SMALL_LONG_EDGE = 1600      # 发给模型的全屏缩略图长边
SELECTED_TEXT_LIMIT = 2000  # 首条消息里最多放多少选中的文字
SELECTION_TEXT_LIMIT = 4000  # 首条消息里最多放多少框选区域里的文字（全文另存 selection.txt）
FG_TEXT_WAIT = 4.0  # 提问时最多等前台窗口的完整内容多久（通常早就读完了：用户框选、打字要好几秒）
FG_TEXT_BUDGET, OTHER_TEXT_BUDGET = 3.0, 1.5  # 读一个窗口完整内容的时间上限
CLIPBOARD_LIMIT = 500
BROWSERS = {"chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe", "opera.exe", "arc.exe", "firefox.exe"}
WEEKDAYS = "一二三四五六日"
#: 问题像是在说"出问题了"：这时前台窗口里的报错行也拿去想经验（平时不用，免得页面上不相干的报错带出不相干的经验）
PROBLEM = re.compile(r"报错|错误|为什么|失败|不行|不了|没反应|出错|异常|怎么回事|卡住|打不开|error|fail|why|not work",
                     re.IGNORECASE)


@dataclass
class Capture:
    """按键那一刻的环境。坐标都是物理像素。"""

    created: datetime
    mode: str
    screen_bgra: bytes
    screen_size: tuple[int, int]
    screen_origin: tuple[int, int]
    foreground: win32.WindowInfo | None
    focus: dict
    windows: list[win32.WindowInfo]
    default_selection: win32.Rect
    selection_source: str  # text | window | screen
    content_kind: str
    clipboard: str = ""
    timings: dict[str, float] = field(default_factory=dict)  # 各步耗时（毫秒），用来查召唤慢在哪

    def screen_image(self) -> Image.Image:
        return Image.frombytes("RGB", self.screen_size, self.screen_bgra, "raw", "BGRX")


@dataclass
class Context:
    """交给引擎的首条消息素材。"""

    dir: Path
    index: str
    images: list[Path] = field(default_factory=list)


def _union(rects: list[win32.Rect], pad: int = 8) -> win32.Rect:
    return (min(r[0] for r in rects) - pad, min(r[1] for r in rects) - pad,
            max(r[2] for r in rects) + pad, max(r[3] for r in rects) + pad)


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class Collector:
    def __init__(self, worker: uia.UiaWorker, blocked_apps: list[str], displays: list[dict]) -> None:
        """displays 由主线程算好传进来：Qt 的屏幕对象不能在后台线程访问。"""
        self.uia = worker  # 后台读窗口文字、控件树（每个窗口要几十到几百毫秒）
        # 召唤时的快速读取（焦点、选中文字、某点的文字）单独一个线程，不排在后台任务后面
        self.uia_fast = uia.UiaWorker()
        self.blocked = {a.lower() for a in blocked_apps}
        self.displays = displays
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="snapshot")
        self.profile: dict = {}
        self.pool.submit(self._load_profile)
        self.pool.submit(ocr.available)  # OCR 引擎的首次初始化放在启动时
        self._sct: mss.MSS | None = None  # 截图对象建一次反复用（每次新建约 40ms）；只在主线程用
        self._last: Session | None = None

    def _load_profile(self) -> None:
        self.profile = system.load_profile(self.displays)

    def warm(self) -> None:
        """主线程调用：截一次屏，把截图组件的首次初始化（约 200ms）放在启动时。"""
        if self._sct is None:
            self._sct = mss.MSS()
        self._sct.grab(self._sct.monitors[0])

    def close(self) -> None:
        self.uia.stop()
        self.uia_fast.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def is_blocked(self, w: win32.WindowInfo | None) -> bool:
        return w is not None and w.process.lower() in self.blocked

    def capture(self, mode: str, own: set[int], prefer_hwnd: int = 0, clipboard: str = "") -> Capture:
        """主线程调用。prefer_hwnd：前台是我们自己的窗口时，改用上一次的前台窗口。"""
        timings: dict[str, float] = {}
        t = time.perf_counter()

        def lap(label: str) -> None:
            nonlocal t
            now = time.perf_counter()
            timings[label] = round((now - t) * 1000)
            t = now

        fg = win32.foreground()
        ours = fg is not None and fg.hwnd in own
        if fg is None or ours:
            fg = win32.window_info(prefer_hwnd) if prefer_hwnd else None
        lap("前台")
        # 读焦点和截屏同时进行：焦点在 UIA 线程里读，这边先截屏。
        # 前台是我们自己的窗口时不读：读自己进程的窗口要主线程应答，而主线程正在这里等，只会等到超时。
        skip_focus = ours or self.is_blocked(fg)
        focus_future = None if skip_focus else self.uia_fast.submit(uia.focus_and_selection)
        if self._sct is None:
            self._sct = mss.MSS()
        mon = self._sct.monitors[0]  # 所有显示器拼成的虚拟屏
        shot = self._sct.grab(mon)
        lap("截屏")
        focus: dict = {}
        if focus_future is not None:
            try:
                focus = focus_future.result(timeout=0.06) or {}
            except Exception:  # noqa: BLE001 - 超时或应用异常都按"没有选中文字"处理
                focus_future.cancel()
        lap("焦点")
        windows = win32.visible_windows(exclude=own)
        lap("窗口")

        rects = focus.get("selection_rects") or []
        if focus.get("selected_text", "").strip() and rects:
            sel, source = _union(rects), "text"
            kind = content.classify(focus["selected_text"], source="selection")
        elif fg is not None and not fg.minimized:
            sel, source = fg.rect, "window"
            kind = "dialog" if fg.class_name in content.DIALOG_CLASSES else "text"
        else:
            sel, source = (mon["left"], mon["top"], mon["left"] + mon["width"], mon["top"] + mon["height"]), "screen"
            kind = "text"
        screen = bytes(shot.bgra)
        lap("复制像素")
        return Capture(created=datetime.now(), mode=mode, screen_bgra=screen,
                       screen_size=(shot.width, shot.height), screen_origin=(mon["left"], mon["top"]),
                       foreground=fg, focus=focus, windows=windows, default_selection=sel,
                       selection_source=source, content_kind=kind, clipboard=clipboard, timings=timings)

    def start(self, cap: Capture, on_kind: Callable[[str], None] | None = None) -> Session:
        # 上一次的会话要么已经提过问、要么被放弃了：它还没开始读的窗口不用读了，别让新会话排在后面等
        if self._last is not None:
            for fut in self._last.futures:
                fut.cancel()
        self._last = Session(self, cap, on_kind)
        return self._last


class Session:
    """一次提问的会话文件夹：~/.super_aide/sessions/<时间>-<随机>/。"""

    def __init__(self, collector: Collector, cap: Capture, on_kind: Callable[[str], None] | None) -> None:
        self.c = collector
        self.cap = cap
        self.selection = cap.default_selection
        self.selection_source = cap.selection_source
        self.id = cap.created.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.dir = paths.SESSIONS / self.id
        (self.dir / "windows").mkdir(parents=True, exist_ok=True)
        self.windows: list[dict] = []
        self.url = ""
        self.state: dict = {}
        self.futures: list[Future] = []
        self.fg_text: Future | None = None
        self.selection_text = ""
        self.selection_text_source = ""  # ui：从界面读的原文；ocr：认图
        self._start(on_kind)

    # ---- 后台采集 ----

    def _start(self, on_kind: Callable[[str], None] | None) -> None:
        c, cap = self.c, self.cap
        fg = cap.foreground
        self.futures.append(c.pool.submit(self._save_screen))
        self.futures.append(c.pool.submit(self._save_state))
        # 网址最先读：它对回答最有用、读起来也快，排在各窗口的文字后面会等不到（P1：十来个窗口时就超时了）
        if fg is not None and not c.is_blocked(fg) and fg.process.lower() in BROWSERS:
            self.futures.append(c.uia.submit(self._save_url, fg.hwnd))
        ordered = sorted(cap.windows, key=lambda w: 0 if fg and w.hwnd == fg.hwnd else 1)
        texts = []
        for i, w in enumerate(ordered):
            stem = f"{i:02d}_{Path(w.process).stem}"
            entry = {"process": w.process, "title": w.title, "minimized": w.minimized,
                     "elevated": w.elevated, "blocked": c.is_blocked(w), "image": None, "text": None,
                     "chars": 0, "foreground": bool(fg and w.hwnd == fg.hwnd)}
            self.windows.append(entry)
            if entry["blocked"]:
                continue
            self.futures.append(c.pool.submit(self._save_window_image, w.hwnd, stem, entry))
            is_fg = entry["foreground"]
            texts.append((w.hwnd, stem, entry, w.class_name if is_fg else "", on_kind if is_fg else None))
        # 读文字的顺序：前台窗口的完整内容 → 前台控件树 → 其它窗口
        if texts and texts[0][2]["foreground"]:
            self.fg_text = c.uia.submit(self._save_window_text, *texts.pop(0))
            self.futures.append(self.fg_text)
        if fg is not None and not c.is_blocked(fg):
            self.futures.append(c.uia.submit(self._save_ui_tree, fg.hwnd))
        for args in texts:
            self.futures.append(c.uia.submit(self._save_window_text, *args))

    def _blocked_rects(self) -> list[win32.Rect]:
        return [w.rect for w in self.cap.windows if self.c.is_blocked(w) and not w.minimized]

    def _black_out(self, img: Image.Image) -> Image.Image:
        ox, oy = self.cap.screen_origin
        draw = ImageDraw.Draw(img)
        for left, top, right, bottom in self._blocked_rects():
            draw.rectangle((left - ox, top - oy, right - ox, bottom - oy), fill=(0, 0, 0))
        return img

    def _save_screen(self) -> None:
        img = self._black_out(self.cap.screen_image())
        img.save(self.dir / "screen.jpg", "JPEG", quality=88)
        small = img.copy()
        small.thumbnail((SMALL_LONG_EDGE, SMALL_LONG_EDGE))
        small.save(self.dir / "screen_small.jpg", "JPEG", quality=85)

    def _save_state(self) -> None:
        self.state = system.dynamic_state()
        payload = {"profile": self.c.profile, "now": self.state}
        _write_atomic(self.dir / "system.json", json.dumps(payload, ensure_ascii=False, indent=2).encode())

    def _save_window_image(self, hwnd: int, stem: str, entry: dict) -> None:
        img = win32.capture_window(hwnd)
        if img is not None:
            img.save(self.dir / "windows" / f"{stem}.jpg", "JPEG", quality=85)
            entry["image"] = f"windows/{stem}.jpg"

    def _save_window_text(self, worker: uia.UiaWorker, hwnd: int, stem: str, entry: dict,
                          window_class: str, on_kind: Callable[[str], None] | None) -> None:
        """窗口的完整内容（包括滚动出去、没显示出来的部分），不是截图里看得到的那一屏。"""
        front = entry["foreground"]
        text, _method = uia.window_content(worker, hwnd, budget_s=FG_TEXT_BUDGET if front else OTHER_TEXT_BUDGET,
                                           wake=front)
        text = redact.redact(text)
        if text.strip():
            _write_atomic(self.dir / "windows" / f"{stem}.txt", text.encode("utf-8"))
            entry["text"] = f"windows/{stem}.txt"
            entry["chars"] = len(text)
        # 默认选区是整个前台窗口时，用窗口文字给推荐问题判断内容类型
        if on_kind is not None and self.cap.selection_source == "window":
            on_kind(content.classify(text, source="window", window_class=window_class))

    def _save_ui_tree(self, worker: uia.UiaWorker, hwnd: int) -> None:
        tree = uia.ui_tree(worker, hwnd)
        if tree:
            _write_atomic(self.dir / "ui_tree.txt", redact.redact(tree).encode("utf-8"))

    def _save_url(self, worker: uia.UiaWorker, hwnd: int) -> None:
        self.url = uia.browser_url(worker, hwnd)

    # ---- 提问时 ----

    def set_selection(self, rect: win32.Rect, source: str = "manual") -> None:
        self.selection, self.selection_source = rect, source

    def finalize(self, timeout: float = 1.5) -> Context:
        crop = self._selection_image()
        # 框选区域里的原文和下面的等待同时进行
        sel_text = self.c.pool.submit(self._read_selection_text, crop)
        t0 = time.perf_counter()
        if self.fg_text is not None:
            wait([self.fg_text], timeout=FG_TEXT_WAIT)
        # 其它窗口的资料：总共最多等 timeout（读完的才列进目录，没读完的不耽误提问）
        wait(self.futures, timeout=max(0.2, timeout - (time.perf_counter() - t0)))
        images = []
        sel = self._save_selection(crop)
        if sel is not None:
            images.append(sel)
        try:
            self.selection_text, self.selection_text_source = sel_text.result(timeout=3.0)
        except Exception:  # noqa: BLE001 - 读不到就只有图
            sel_text.cancel()
        if self.selection_text:
            _write_atomic(self.dir / "selection.txt", self.selection_text.encode("utf-8"))
        small = self.dir / "screen_small.jpg"
        if small.exists():
            images.append(small)
        index = self._index()
        context = {"captured_at": self.cap.created.isoformat(timespec="seconds"), "mode": self.cap.mode,
                   "selection": {"rect": self.selection, "source": self.selection_source,
                                 "text_source": self.selection_text_source},
                   "foreground": self._fg_dict(), "url": self.url, "windows": self.windows,
                   "focus": self.cap.focus.get("focused"), "system": self.state}
        _write_atomic(self.dir / "context.json", json.dumps(context, ensure_ascii=False, indent=2).encode())
        return Context(dir=self.dir, index=index, images=images)

    def _selection_image(self) -> Image.Image | None:
        ox, oy = self.cap.screen_origin
        left, top, right, bottom = self.selection
        box = (max(0, left - ox), max(0, top - oy),
               min(self.cap.screen_size[0], right - ox), min(self.cap.screen_size[1], bottom - oy))
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            return None
        return self._black_out(self.cap.screen_image()).crop(box)

    def _save_selection(self, img: Image.Image | None) -> Path | None:
        if img is None:
            return None
        path = self.dir / "selection.png"
        img.save(path, "PNG", compress_level=1)
        return path

    def _window_at_selection(self) -> win32.WindowInfo | None:
        """框选区域中心所在的窗口（按 Z 序从上往下找第一个盖住中心的）。"""
        left, top, right, bottom = self.selection
        cx, cy = (left + right) // 2, (top + bottom) // 2
        for w in self.cap.windows:
            r = w.rect
            if not w.minimized and r[0] <= cx < r[2] and r[1] <= cy < r[3]:
                return w
        return None

    def _read_selection_text(self, crop: Image.Image | None) -> tuple[str, str]:
        """框选区域里的原文：先从界面本身读（逐字准确），界面没交出文字（图片、画布、远程桌面……）再用 OCR 认图。
        已经选中了文字、或者框的是整个屏幕时不用读。"""
        if crop is None or self.selection_source in ("text", "screen"):
            return "", ""
        target = self._window_at_selection()
        if target is None or self.c.is_blocked(target):
            return "", ""
        ui = self.c.uia_fast.submit(uia.text_in_rect, target.hwnd, self.selection)
        seen = ocr.text_of(crop) if ocr.available() else ""  # 认图和读界面同时进行
        try:
            text = ui.result(timeout=2.5) or ""
        except Exception:  # noqa: BLE001
            ui.cancel()
            text = ""
        text, seen = redact.redact(text).strip("\n"), redact.redact(seen).strip()
        if text.strip():
            # 框里有界面没交出来的字（比如网页里的截图）：认图认出来的明显更多时一起给
            if len(seen) > 2 * len(text) + 40:
                text += "\n\n（框里还有界面没交出来的文字，下面是 OCR 认图的结果，个别字可能认错）\n" + seen
            return text, "ui"
        return (seen, "ocr") if seen else ("", "")

    def situation(self, question: str) -> Situation:
        """想起经验用的"这次的情况"：问题、框选区域的原文和选中的文字、前台窗口里的报错行、程序、网址、标题。"""
        fg = self.cap.foreground
        if fg is None or self.c.is_blocked(fg):
            return Situation(question=question)
        errors = ""
        front = next((w for w in self.windows if w["foreground"] and w["text"]), None)
        if front is not None and (PROBLEM.search(question) or self.cap.content_kind == "error"):
            try:
                errors = error_lines((self.dir / front["text"]).read_text(encoding="utf-8"))
            except OSError:
                pass
        selected = redact.redact(self.cap.focus.get("selected_text", "")).strip()
        text = "\n".join(x for x in (self.selection_text, selected) if x)
        return Situation(question=question, text=text[:8000], errors=errors, app=fg.process, url=self.url,
                         title=fg.title)

    def _fg_dict(self) -> dict | None:
        fg = self.cap.foreground
        if fg is None:
            return None
        return {"process": fg.process, "title": fg.title, "elevated": fg.elevated, "rect": fg.rect}

    def _index(self) -> str:
        cap = self.cap
        t = cap.created
        lines = [f"- 时间：{t:%Y-%m-%d %H:%M:%S}（周{WEEKDAYS[t.weekday()]}）"]
        fg = cap.foreground
        if fg is not None:
            admin = "，以管理员权限运行" if fg.elevated else ""
            hidden = "（在隐私黑名单中，未采集内容）" if self.c.is_blocked(fg) else ""
            lines.append(f"- 前台窗口：{fg.process}「{fg.title}」{admin}{hidden}")
        source = {"text": "你选中的文字", "window": "前台窗口", "screen": "整个屏幕", "manual": "手动框选的区域"}
        left, top, right, bottom = self.selection
        lines.append(f"- 框选：{source.get(self.selection_source, '区域')}"
                     f"（{right - left}×{bottom - top} 物理像素，图片 selection.png）")
        selected = redact.redact(cap.focus.get("selected_text", "")).strip()
        if selected:
            clipped = selected[:SELECTED_TEXT_LIMIT] + ("…（已截断）" if len(selected) > SELECTED_TEXT_LIMIT else "")
            lines.append(f"- 选中的文字：\n<selected_text>\n{clipped}\n</selected_text>")
        if self.selection_text:
            how = ("逐字原文，从界面本身读出，拼写以这里为准" if self.selection_text_source == "ui"
                   else "界面没交出文字，这是 OCR 认图的结果，个别字可能认错，拿不准时对照图片")
            text = self.selection_text
            clipped = text[:SELECTION_TEXT_LIMIT] + (
                f"…（已截断，全文在 selection.txt，共 {len(text):,} 字）" if len(text) > SELECTION_TEXT_LIMIT else "")
            lines.append(f"- 框选区域里的文字（{how}）：\n<selection_text>\n{clipped}\n</selection_text>")
        front = next((w for w in self.windows if w["foreground"] and w["text"]), None)
        if front is not None:
            lines.append(f"- 前台窗口的完整内容（包括滚动出去、没显示出来的部分）：{front['text']}"
                         f"（{front['chars']:,} 字）。问题和这个窗口有关时先读它，不要只看截图")
        if self.url:
            lines.append(f"- 浏览器网址：{self.url}")
        if cap.clipboard:
            lines.append(f"- 剪贴板（最近复制）：\n<clipboard>\n{redact.redact(cap.clipboard)[:CLIPBOARD_LIMIT]}\n</clipboard>")
        if self.windows:
            lines.append("- 打开的窗口（从上到下）：")
            for i, w in enumerate(self.windows, 1):
                files = []
                if w["text"]:
                    files.append(f"{w['text']}（{w['chars']:,} 字）")
                if w["image"]:
                    files.append(w["image"])
                state = "，最小化" if w["minimized"] else ""
                note = "（隐私黑名单，未采集）" if w["blocked"] else ("→ " + "、".join(files) if files else "")
                lines.append(f"  {i}. {w['process']}「{w['title'][:80]}」{state} {note}".rstrip())
        if self.state:
            lines.append(f"- 系统：{system.summary(self.c.profile, self.state)}")
        lines.append("- 其它资料：screen.jpg（全屏原图）、ui_tree.txt（前台窗口控件树）、"
                     "system.json（系统画像，含开发环境）、context.json（以上汇总）")
        return "\n".join(lines)
