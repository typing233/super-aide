"""界面内容读取：框选区域的原文、OCR 兜底、首条消息里的写法。COM 和 OCR 都用假的，不碰真实界面。"""

from __future__ import annotations

from concurrent.futures import Future
from datetime import datetime
from pathlib import Path

from PIL import Image

from super_aide.cu import ocr
from super_aide.snapshot import collector, uia
from super_aide.snapshot.win32 import WindowInfo

# ---- 框住的那几行 ----


class FakeDoc:
    """一个文档：每行 (文字, 文字的框, 行尾嵌入对象的框或 None)。位置用行号表示。"""

    def __init__(self, lines):
        self.lines = lines


class FakeRange:
    """IUIAutomationTextRange 的最小实现：[start, end) 是行号；trim 表示行尾的换行和嵌入对象被去掉了。"""

    def __init__(self, doc, start, end, trim=False):
        self.doc, self.start, self.end, self.trim = doc, start, end, trim

    def Clone(self):
        return FakeRange(self.doc, self.start, self.end, self.trim)

    def MoveEndpointByRange(self, src, other, target):
        pos = other.start if target == uia.ENDPOINT_START else other.end
        if src == uia.ENDPOINT_END:
            self.end = pos
        else:
            self.start = pos

    def ExpandToEnclosingUnit(self, unit):
        assert unit == uia.TEXT_UNIT_LINE
        self.end = self.start + 1

    def CompareEndpoints(self, src, other, target):
        a = self.start if src == uia.ENDPOINT_START else self.end
        b = other.start if target == uia.ENDPOINT_START else other.end
        return (a > b) - (a < b)

    def GetText(self, _max):
        parts = []
        for i in range(self.start, max(self.end, self.start + 1)):
            text, _box, obj = self.doc.lines[i]
            parts.append(text + ("\n\ufffc" if obj and not self.trim else "\n"))
        return "".join(parts)

    def GetBoundingRectangles(self):
        out = []
        for i in range(self.start, max(self.end, self.start + 1)):
            _text, box, obj = self.doc.lines[i]
            boxes = [box] + ([obj] if obj and not self.trim else [])
            if not self.trim:
                boxes.append((box[0], box[3], box[0], box[3] + 20))  # 换行符在下一行开头报的零宽框
            for left, top, right, bottom in boxes:
                out += [left, top, right - left, bottom - top]
        return tuple(out)

    def MoveEndpointByUnit(self, endpoint, unit, count):
        assert unit == uia.TEXT_UNIT_CHARACTER
        self.trim = True

    def Move(self, unit, count):
        target = self.start + count
        if not 0 <= target < len(self.doc.lines):
            return 0
        self.start = self.end = target
        return count


class FakePattern:
    """RangeFromPoint：点所在的那一行；点在两行之间时给离它最近的一行（Chromium 就是这样）。"""

    def __init__(self, doc):
        self.doc = doc

    def RangeFromPoint(self, point):
        y = point.y
        best = min(range(len(self.doc.lines)),
                   key=lambda i: 0 if self.doc.lines[i][1][1] <= y <= self.doc.lines[i][1][3]
                   else min(abs(y - self.doc.lines[i][1][1]), abs(y - self.doc.lines[i][1][3])))
        return FakeRange(self.doc, best, best)


NOTEBOOK = FakeDoc([
    ("notebook.ipynb", (10, 40, 200, 60), None),
    ("框架里的文字：IFRAME", (10, 100, 300, 120), (10, 130, 600, 210)),  # 后面紧跟着画布
    ("from modescope import AutoTokenizer", (10, 230, 400, 250), None),
    ("ModuleNotFoundError: No module named 'modescope'", (10, 260, 500, 280), None),
    ("页面下面的文字", (10, 400, 200, 420), None),
])


def test_overlaps_needs_half_the_line_inside():
    rect = (0, 100, 500, 200)
    assert uia._overlaps((10, 110, 200, 130), rect)
    assert uia._overlaps((10, 185, 200, 205), rect)        # 一大半在框里
    assert not uia._overlaps((10, 195, 200, 215), rect)    # 只擦到边
    assert not uia._overlaps((600, 110, 700, 130), rect)   # 横向不相交


def test_corner_text_takes_exactly_the_lines_in_the_box():
    error = (0, 222, 700, 288)
    assert uia._corner_text(FakePattern(NOTEBOOK), error) == (
        "from modescope import AutoTokenizer\nModuleNotFoundError: No module named 'modescope'")


def test_corner_text_drops_the_nearest_line_outside_the_box():
    """框的上边落在空白处：离它最近的是框上面那行标题，不能算进来。"""
    loose = (0, 70, 700, 255)
    assert uia._corner_text(FakePattern(NOTEBOOK), loose).splitlines()[0] == "框架里的文字：IFRAME"


def test_corner_text_reaches_past_blank_lines_when_the_probe_lands_high():
    """框的下边落在留白里，Chromium 给到了隔着空行的上面那行（实测）：要扩回来，最后一行报错不能丢。"""
    doc = FakeDoc([
        ("ModuleNotFoundError    Traceback", (10, 100, 400, 120), None),
        ("----> 2 from modescope import x", (10, 130, 400, 150), None),
        ("", (10, 160, 10, 180), None),
        ("ModuleNotFoundError: No module named 'modescope'", (10, 190, 500, 210), None),
        ("tokenizer", (10, 300, 100, 320), None),
    ])

    class HighProbe(FakePattern):
        def RangeFromPoint(self, point):
            return FakeRange(self.doc, 1, 1) if point.y > 200 else super().RangeFromPoint(point)

    text = uia._corner_text(HighProbe(doc), (0, 95, 700, 218))
    assert text.endswith("No module named 'modescope'") and "tokenizer" not in text


def test_corner_text_gives_nothing_for_pixels_only():
    """框住的是画布：附近的字都在框外（行尾连着画布的那行也不算），交给 OCR。"""
    canvas = (0, 128, 700, 212)
    assert uia._corner_text(FakePattern(NOTEBOOK), canvas) == ""


# ---- 框选区域的原文：界面优先，OCR 兜底 ----


class FakeCollector:
    def __init__(self, ui_text):
        self.blocked = set()
        self.profile = {}
        self.ui_text = ui_text
        self.uia_fast = self

    def submit(self, fn, *args):
        fut: Future = Future()
        fut.set_result(self.ui_text)
        return fut

    def is_blocked(self, w):
        return False


def _session(ui_text="", source="manual", windows=None):
    s = object.__new__(collector.Session)
    win = WindowInfo(hwnd=1, title="内容读取靶子", process="msedge.exe", pid=10, rect=(0, 0, 1000, 800),
                     minimized=False, elevated=False)
    s.c = FakeCollector(ui_text)
    s.cap = collector.Capture(created=datetime(2026, 10, 8, 16, 0), mode="ask", screen_bgra=b"",
                              screen_size=(1000, 800), screen_origin=(0, 0), foreground=win, focus={},
                              windows=windows if windows is not None else [win],
                              default_selection=(0, 0, 1000, 800), selection_source=source, content_kind="text")
    s.selection, s.selection_source = (100, 100, 600, 300), source
    s.url, s.state, s.windows = "", {}, []
    s.selection_text, s.selection_text_source = "", ""
    s.dir = Path(".")
    return s


def test_selection_text_prefers_the_interface(monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "text_of", lambda img: "from modelscope import AutoTokenizer")  # 认图会"纠正"拼写
    s = _session("from modescope import AutoTokenizer")
    assert s._read_selection_text(Image.new("RGB", (50, 20))) == ("from modescope import AutoTokenizer", "ui")


def test_selection_text_falls_back_to_ocr(monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "text_of", lambda img: "CANVAS 8812")
    s = _session("")
    assert s._read_selection_text(Image.new("RGB", (50, 20))) == ("CANVAS 8812", "ocr")


def test_selection_text_adds_ocr_when_interface_misses_most(monkeypatch):
    """框里有张报错截图：界面只交出了标题，认图认出来的多得多，两样都给。"""
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "text_of", lambda img: "Traceback (most recent call last): " * 4)
    text, how = _session("图 1")._read_selection_text(Image.new("RGB", (50, 20)))
    assert how == "ui" and text.startswith("图 1") and "OCR" in text and "Traceback" in text


def test_selection_text_skipped_for_selected_text_and_screen(monkeypatch):
    monkeypatch.setattr(ocr, "text_of", lambda img: "x")
    img = Image.new("RGB", (50, 20))
    assert _session("abc", source="text")._read_selection_text(img) == ("", "")
    assert _session("abc", source="screen")._read_selection_text(img) == ("", "")
    assert _session("abc", windows=[])._read_selection_text(img) == ("", "")  # 框的地方没有窗口


def test_index_shows_selection_text_and_full_content():
    s = _session()
    s.selection_text, s.selection_text_source = "from modescope import AutoTokenizer", "ui"
    s.windows = [{"process": "msedge.exe", "title": "notebook", "minimized": False, "blocked": False,
                  "image": "windows/00_msedge.jpg", "text": "windows/00_msedge.txt", "chars": 5734,
                  "foreground": True}]
    index = s._index()
    assert "<selection_text>\nfrom modescope import AutoTokenizer\n</selection_text>" in index
    assert "逐字原文" in index
    assert "前台窗口的完整内容（包括滚动出去、没显示出来的部分）：windows/00_msedge.txt（5,734 字）" in index

    s.selection_text, s.selection_text_source = "x" * (collector.SELECTION_TEXT_LIMIT + 10), "ocr"
    index = s._index()
    assert "OCR" in index and "selection.txt" in index


# ---- OCR 的预处理 ----


def test_ocr_scale_limits():
    _, small = ocr._prepare(Image.new("RGB", (300, 40)), invert=False)
    assert small == 3.0  # 小图放大 3 倍
    _, window = ocr._prepare(Image.new("RGB", (2560, 1440)), invert=False)
    assert 1.0 < window < 3.0 and 2560 * 1440 * window ** 2 <= ocr.MAX_WORK_PIXELS * 1.01
    _, huge = ocr._prepare(Image.new("RGB", (12000, 500)), invert=False)
    assert huge < 1.0 and 12000 * huge <= ocr.MAX_SIDE + 1  # 超过 OCR 的尺寸上限才缩小


def test_ocr_with_comtypes_exits_cleanly():
    """UI Automation（comtypes）和 OCR 引擎同时用过的进程，退出时不能崩溃（实测曾经 0xC0000005）。"""
    import subprocess
    import sys

    if not ocr.available():
        return
    code = "import comtypes; from super_aide.cu import ocr; from PIL import Image; ocr.text_of(Image.new('RGB', (80, 30)))"
    assert subprocess.run([sys.executable, "-c", code], timeout=60).returncode == 0


def test_ocr_rows_join_pieces_on_the_same_line():
    pieces = [ocr.Line("import", (200, 10, 260, 30)), ocr.Line("from modescope", (10, 12, 180, 31)),
              ocr.Line("ModuleNotFoundError", (10, 50, 300, 70))]
    rows = ocr._rows(pieces)
    assert [r.text for r in rows] == ["from modescope import", "ModuleNotFoundError"]
