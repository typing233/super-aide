"""UI Automation。COM 要求在同一个线程里初始化和使用，所以所有调用都投递到一个后台线程里做。

P0 实测：初始化约 250ms（只在启动时做一次），之后读焦点和选中文字约 10ms；
读窗口文字先用 UIA 原生 FindFirst 直接找文档节点（网页 134ms 拿到全文），找不到再遍历控件树。
"""

from __future__ import annotations

import queue
from ctypes import wintypes
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

import uiautomation as auto
from uiautomation.uiautomation import _AutomationClient

from . import chromium, uiawalk

TREE_SCOPE_DESCENDANTS = 4  # uiautomation 库没有导出这个枚举
MAX_SELECTED_CHARS = 20_000
MAX_WINDOW_CHARS = 200_000
#: 新装好第一次运行时，comtypes 要为 UIA 生成包装代码。几个线程同时初始化会互相读到写了一半的文件
#:（打包后实测："unmatched ')'"），所以初始化一个一个来
_INIT_LOCK = threading.Lock()


class UiaWorker:
    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._uia: Any = None
        self._thread = threading.Thread(target=self._run, name="uia", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        with auto.UIAutomationInitializerInThread():
            with _INIT_LOCK:
                self._uia = _AutomationClient.instance().IUIAutomation
                uiawalk.limit_timeouts(self._uia)  # 应用卡住时，一次调用最多等几秒就返回
                auto.GetRootControl()  # 预热，把一次性的初始化开销放在启动时
            self._ready.set()
            while True:
                fn, args, fut = self._q.get()
                if fn is None:
                    return
                if not fut.set_running_or_notify_cancel():
                    continue
                try:
                    fut.set_result(fn(self, *args))
                except BaseException as e:  # noqa: BLE001 - 各应用的 UIA 实现参差不齐
                    fut.set_exception(e)

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future:
        fut: Future = Future()
        self._q.put((fn, args, fut))
        return fut

    def call(self, fn: Callable[..., Any], *args: Any, timeout: float, default: Any = None) -> Any:
        try:
            return self.submit(fn, *args).result(timeout=timeout)
        except Exception:  # noqa: BLE001 - 超时或应用异常都按"拿不到"处理
            return default

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        self._q.put((None, (), None))

    # ---- 以下函数都在 UIA 线程里执行（第一个参数是 worker）----

    def find_first(self, root: auto.Control, control_type: int) -> auto.Control | None:
        return self.find_first_by(root, auto.PropertyId.ControlTypeProperty, control_type)

    def find_first_by(self, root: auto.Control, property_id: int, value: Any) -> auto.Control | None:
        cond = self._uia.CreatePropertyCondition(property_id, value)
        elem = root.Element.FindFirst(TREE_SCOPE_DESCENDANTS, cond)
        return auto.Control.CreateControlFromElement(elem) if elem else None


def focus_and_selection(worker: UiaWorker) -> dict:
    """焦点控件，以及选中的文字和它在屏幕上的位置（物理像素）。"""
    out: dict = {"focused": None, "selected_text": "", "selection_rects": []}
    ctrl = auto.GetFocusedControl()
    if ctrl is None:
        return out
    out["focused"] = {"type": ctrl.ControlTypeName, "name": (ctrl.Name or "")[:200]}
    # 有的应用把文字能力放在焦点的上层（比如浏览器的文档节点），往上找几层
    for _ in range(4):
        pattern = ctrl.GetPattern(auto.PatternId.TextPattern)
        if pattern:
            texts, rects = [], []
            for r in pattern.GetSelection() or []:
                text = r.GetText(MAX_SELECTED_CHARS)
                if text and text.strip():
                    texts.append(text)
                    rects += [(b.left, b.top, b.right, b.bottom) for b in r.GetBoundingRectangles()]
            out["selected_text"] = "\n".join(texts)[:MAX_SELECTED_CHARS]
            out["selection_rects"] = rects
            return out
        ctrl = ctrl.GetParentControl()
        if ctrl is None:
            break
    return out


TEXT_UNIT_CHARACTER, TEXT_UNIT_LINE = 0, 4  # TextUnit_Character / TextUnit_Line
EDGE_CHARS = "\r\n￼"  # 行首行尾不算字的：换行、嵌入对象（图片、画布、框架）
ENDPOINT_START, ENDPOINT_END = 0, 1
P_TYPE, P_NAME, P_VALUE, P_PASSWORD, P_OFFSCREEN, P_RECT, P_CLASS = 30003, 30005, 30045, 30019, 30022, 30001, 30012
DOCUMENT = 50030
OUTLINE_SECONDS, OUTLINE_NODES = 1.5, 4000
ROLE_NAMES = {50000: "按钮", 50002: "勾选框", 50003: "下拉框", 50004: "输入框", 50005: "链接", 50007: "列表项",
              50011: "菜单项", 50013: "单选", 50019: "标签页", 50020: "文字", 50024: "树节点", 50029: "数据项",
              50034: "表头", 50035: "表头项", 50037: "标题栏"}
MAX_OUTLINE_LINES = 4000
GROW_LINES = 60  # 框边上的行最多往外扩、往里收这么多行


def _documents(worker: UiaWorker, hwnd: int) -> list:
    """窗口里的文档区。Chromium 系直接从网页子窗口拿（一个很小的调用）；
    别的程序分小步找，不进文档里面（以前一次 FindAll 整棵树，大网页上会把浏览器卡死）。"""
    uia = worker._uia
    hosts = chromium.children(hwnd)
    if hosts:
        return uiawalk.web_documents(uia, hwnd, hosts)
    found = uiawalk.walk(uia, uia.ElementFromHandle(hwnd), uiawalk.light_request(uia), seconds=1.0, max_nodes=3000,
                         enter=uiawalk.not_into_pages)
    return [e for e in found if uiawalk.cached(e, P_TYPE) == DOCUMENT]


def _text_pattern(element):
    try:
        return auto.Control.CreateControlFromElement(element).GetPattern(auto.PatternId.TextPattern)
    except Exception:  # noqa: BLE001
        return None


def _document_texts(worker: UiaWorker, hwnd: int, deadline: float) -> list[str]:
    """每个文档区（网页的每个框架、编辑器、Word……）的完整文字。DocumentRange 是整个文档，不只是显示出来的部分。"""
    texts: list[str] = []
    for element in _documents(worker, hwnd):
        if time.perf_counter() > deadline:
            break
        pattern = _text_pattern(element)
        if not pattern:
            continue
        try:
            text = pattern.DocumentRange.GetText(MAX_WINDOW_CHARS).replace("\ufffc", "").strip()
        except Exception:  # noqa: BLE001
            continue
        if not text or any(text in t for t in texts):
            continue
        texts = [t for t in texts if t not in text] + [text]  # 外层文档已经包含了框架里的文字时只留一份
    return texts


def _wait_for_documents(worker: UiaWorker, hwnd: int, deadline: float) -> None:
    """唤醒后网页内容要过一会儿才出现在无障碍树里：等到某个文档区有字，或者超时。"""
    while time.perf_counter() < deadline:
        for element in _documents(worker, hwnd):
            pattern = _text_pattern(element)
            try:
                if pattern and pattern.DocumentRange.GetText(20).strip():
                    return
            except Exception:  # noqa: BLE001
                continue
        time.sleep(0.2)


def _outline(worker: UiaWorker, hwnd: int, known: str, deadline: float) -> str:
    """所有控件的名字和值（包括不在可视区的），文档里已经有的文字不再重复。
    分小步取、有时间上限，不进网页和文档区：那里的内容已经用文本接口整篇读出来了。"""
    uia = worker._uia
    request = uia.CreateCacheRequest()
    for pid in (P_TYPE, P_NAME, P_VALUE, P_PASSWORD, P_OFFSCREEN, P_RECT, P_CLASS):
        request.AddProperty(pid)
    seconds = max(0.2, min(OUTLINE_SECONDS, deadline - time.perf_counter()))
    found = uiawalk.walk(uia, uia.ElementFromHandle(hwnd), request, seconds=seconds, max_nodes=OUTLINE_NODES,
                         enter=uiawalk.not_into_pages)
    lines: list[str] = []
    seen: set[str] = set()
    known = " ".join(known.split())  # 控件名字里的换行、空格都压成了一个空格，比较前文档也一样处理
    for e in found:
        if len(lines) >= MAX_OUTLINE_LINES:
            lines.append("…（控件太多，后面的省略）")
            break
        try:
            role = ROLE_NAMES.get(e.GetCachedPropertyValue(P_TYPE), "")
            name = " ".join(str(e.GetCachedPropertyValue(P_NAME) or "").split())
            value = "" if e.GetCachedPropertyValue(P_PASSWORD) else " ".join(str(e.GetCachedPropertyValue(P_VALUE) or "").split())
        except Exception:  # noqa: BLE001
            continue
        text = name if not value or value == name else f"{name} = {value}" if name else value
        if not text or text in seen or (len(text) > 3 and text in known):
            continue
        seen.add(text)
        lines.append(f"{role}：{text}" if role else text)
    return "\n".join(lines)


def window_content(worker: UiaWorker, hwnd: int, budget_s: float = 3.0, wake: bool = True) -> tuple[str, str]:
    """窗口的完整内容，包括滚动出去、没显示出来的部分。返回 (文字, 读取方式)。
    文档区的完整文字 + 所有控件的名字和值。wake：Chromium / Electron 系窗口先唤醒无障碍树
    （唤醒会让那个应用一直维护无障碍树、多占些资源，所以后台窗口不唤醒，有就读、没有就算了）。"""
    deadline = time.perf_counter() + budget_s
    if uiawalk.hung(hwnd):
        return "", "hung"  # 程序没响应：别再往它那里发请求，越发越卡
    if wake and chromium.wake(hwnd):
        _wait_for_documents(worker, hwnd, min(deadline, time.perf_counter() + 1.5))
    docs = _document_texts(worker, hwnd, deadline)
    outline = _outline(worker, hwnd, "\n".join(docs), deadline + 1.0) if time.perf_counter() < deadline + 1.0 else ""
    parts = []
    if docs:
        parts.append("【文档内容（完整，包括没显示出来的部分）】\n" + "\n\n".join(docs))
    if outline:
        parts.append("【界面上的其它文字和控件（包括滚动出去的）】\n" + outline)
    text = "\n\n".join(parts)
    return text[:MAX_WINDOW_CHARS], "document" if docs else ("controls" if outline else "none")


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """行和框选区域有没有实质重叠：横向有交集，纵向至少一半在框里。"""
    if min(a[2], b[2]) <= max(a[0], b[0]):
        return False
    inter = min(a[3], b[3]) - max(a[1], b[1])
    return inter > 0 and inter >= (a[3] - a[1]) * 0.5


def _boxes(text_range) -> list[tuple[float, float, float, float]]:
    """IUIAutomationTextRange::GetBoundingRectangles 返回 (left, top, width, height) 一组组排开。
    不要没有宽度的框：一行末尾的换行符会在下一行开头报一个，按它算会把上一行也算进框里（实测）。"""
    f = text_range.GetBoundingRectangles() or ()
    return [(f[k], f[k + 1], f[k] + f[k + 2], f[k + 1] + f[k + 3]) for k in range(0, len(f) - 3, 4) if f[k + 2] >= 2]


def _trimmed(line):
    """量位置前去掉行首行尾的换行和嵌入对象：Chromium 的"一行"会连上后面的图片、画布，
    按它们的框算会把这一行也算进框里（实测）。只有换行和嵌入对象的行返回 None。"""
    raw_text = line.GetText(4000)
    if not raw_text.strip(EDGE_CHARS + " \t"):
        return None
    trail = len(raw_text) - len(raw_text.rstrip(EDGE_CHARS))
    lead = len(raw_text) - len(raw_text.lstrip(EDGE_CHARS))
    if not (trail or lead):
        return line
    probe = line.Clone()
    if trail:
        probe.MoveEndpointByUnit(ENDPOINT_END, TEXT_UNIT_CHARACTER, -trail)
    if lead:
        probe.MoveEndpointByUnit(ENDPOINT_START, TEXT_UNIT_CHARACTER, lead)
    return probe


def _line_inside(line, rect: tuple[int, int, int, int]) -> bool | None:
    """这一行在不在框里；空行（只有换行、嵌入对象）返回 None。"""
    probe = _trimmed(line)
    if probe is None:
        return None
    return any(_overlaps(box, rect) for box in _boxes(probe))


def _step(line, direction: int):
    """相邻的一行（direction 1 往下、-1 往上），到头了返回 None。"""
    nxt = line.Clone()
    if nxt.Move(TEXT_UNIT_LINE, direction) == 0:
        return None
    nxt.ExpandToEnclosingUnit(TEXT_UNIT_LINE)
    return nxt


def _grow(line, direction: int, rect: tuple[int, int, int, int]):
    """从这一行往外扩，下一行（隔着空行也算）还在框里就扩进来，最多 GROW_LINES 行。"""
    for _ in range(GROW_LINES):
        nxt = _step(line, direction)
        if nxt is None:
            break
        inside = _line_inside(nxt, rect)
        if inside is None:  # 空行：看它后面那行在不在框里
            after = _step(nxt, direction)
            if after is None or not _line_inside(after, rect):
                break
            nxt = after
        elif not inside:
            break
        line = nxt
    return line


def _shrink(line, direction: int, rect: tuple[int, int, int, int], limit):
    """这一行不在框里就往里收（direction 1 往下收、-1 往上收），收到 limit 那一行为止。"""
    for _ in range(GROW_LINES):
        if _line_inside(line, rect):
            return line
        if line.CompareEndpoints(ENDPOINT_START, limit, ENDPOINT_START) == 0:
            return None
        nxt = _step(line, direction)
        if nxt is None:
            return None
        line = nxt
    return None


def _corner_text(raw, rect: tuple[int, int, int, int]) -> str:
    """框住的那几行：框的上边和下边各取一个文字位置当起点，扩到整行，再修正——
    框里还有的行扩进来（隔着空行也算），落在框外的行收回去——最后取两行之间的文字。
    不管文档多长，都只是边上几行的几十个调用。以前是把可见区一行行量位置，大网页上一次要两分多钟、
    把浏览器卡住半分钟（实测）。直接用 COM 接口：uiautomation 库包的移动类方法每调一次都要 sleep 0.5 秒。
    起点不一定准：Chromium 给的是"离这点最近的字"，点落在留白里时可能给到上面隔着空行的那一行（实测）。"""
    left, top, right, bottom = rect
    x = left + 6  # 靠左取：各行开头是对齐的，远近主要看上下
    a = raw.RangeFromPoint(wintypes.POINT(x, top + 3))
    b = raw.RangeFromPoint(wintypes.POINT(x, bottom - 3))
    if a is None or b is None:
        return ""
    if a.CompareEndpoints(ENDPOINT_START, b, ENDPOINT_START) > 0:
        a, b = b, a
    a.ExpandToEnclosingUnit(TEXT_UNIT_LINE)
    b.ExpandToEnclosingUnit(TEXT_UNIT_LINE)
    a = _shrink(a, 1, rect, b)
    b = _shrink(b, -1, rect, a) if a is not None else None
    if a is None or b is None:
        return ""  # 框里没有文字（比如画布、图片）：交给 OCR
    a, b = _grow(a, -1, rect), _grow(b, 1, rect)
    a.MoveEndpointByRange(ENDPOINT_END, b, ENDPOINT_END)
    return a.GetText(MAX_SELECTED_CHARS).replace("\ufffc", "").strip("\r\n")


def text_in_rect(worker: UiaWorker, hwnd: int, rect: tuple[int, int, int, int], budget_s: float = 2.0) -> str:
    """框选区域里的原文（不是认图）：文档区取框住的那几行；没有文档区就取框里控件的名字和值。"""
    deadline = time.perf_counter() + budget_s
    if uiawalk.hung(hwnd):
        return ""
    chromium.wake(hwnd)
    texts: list[str] = []
    for element in _documents(worker, hwnd):
        try:
            r = element.CurrentBoundingRectangle
            if min(r.right, rect[2]) <= max(r.left, rect[0]) or min(r.bottom, rect[3]) <= max(r.top, rect[1]):
                continue  # 这个文档区不在框里（比如浏览器的侧边栏）
        except Exception:  # noqa: BLE001
            continue
        pattern = _text_pattern(element)
        if not pattern:
            continue
        try:
            text = _corner_text(pattern.pattern, rect)
        except Exception:  # noqa: BLE001
            continue
        if text.strip() and text not in texts:
            texts.append(text)
    if texts:
        return "\n".join(texts)
    # 不是文档：取框里控件的名字和值（按树的顺序；分小步，只进框住的范围）
    uia = worker._uia
    request = uia.CreateCacheRequest()
    for pid in (P_NAME, P_VALUE, P_PASSWORD, P_RECT, P_TYPE, P_CLASS):
        request.AddProperty(pid)
    found = uiawalk.walk(uia, uia.ElementFromHandle(hwnd), request, seconds=max(0.3, deadline - time.perf_counter()),
                         max_nodes=3000, within=rect, on_screen=True)
    out: list[str] = []
    for e in found:
        try:
            r = e.CachedBoundingRectangle
            if not _overlaps((r.left, r.top, r.right, r.bottom), rect):
                continue
            name = str(e.GetCachedPropertyValue(P_NAME) or "").strip()
            value = "" if e.GetCachedPropertyValue(P_PASSWORD) else str(e.GetCachedPropertyValue(P_VALUE) or "").strip()
        except Exception:  # noqa: BLE001
            continue
        for text in (name, value):
            if text and text not in out:
                out.append(text)
    return "\n".join(out)


def window_text(worker: UiaWorker, hwnd: int, budget_s: float = 0.6) -> tuple[str, str]:
    """窗口里所有可读的文字。返回 (文字, 读取方式)。（旧的读法，现在用 window_content。）"""
    root = auto.ControlFromHandle(hwnd)
    if root is None:
        return "", "none"
    doc = worker.find_first(root, auto.ControlType.DocumentControl)
    if doc is not None:
        pattern = doc.GetPattern(auto.PatternId.TextPattern)
        if pattern:
            text = pattern.DocumentRange.GetText(MAX_WINDOW_CHARS)
            if text and text.strip():
                return text, "document"
    deadline = time.perf_counter() + budget_s
    parts: list[str] = []
    seen: set[str] = set()
    for ctrl, _depth in auto.WalkControl(root, includeTop=True, maxDepth=25):
        if time.perf_counter() > deadline:
            parts.append("…（读取超时，后面的内容省略）")
            break
        for text in (ctrl.Name, _value(ctrl)):
            if text and text not in seen:
                seen.add(text)
                parts.append(text)
        if sum(map(len, parts)) > MAX_WINDOW_CHARS:
            break
    return "\n".join(parts), "walk"


def _value(ctrl: auto.Control) -> str:
    if ctrl.ControlType not in (auto.ControlType.EditControl, auto.ControlType.ComboBoxControl):
        return ""
    try:
        vp = ctrl.GetPattern(auto.PatternId.ValuePattern)
        return vp.Value if vp else ""
    except Exception:  # noqa: BLE001
        return ""


#: 地址栏：Chromium 系（Chrome、Edge、Brave…）的类名，Firefox 的控件 ID。都不依赖界面语言
ADDRESS_BARS = ((auto.PropertyId.ClassNameProperty, "OmniboxViewViews"),
                (auto.PropertyId.AutomationIdProperty, "urlbar-input"))


def _url_like(value: str) -> str:
    return value if value and ("." in value or value.startswith(("http", "localhost", "file:"))) else ""


def browser_url(worker: UiaWorker, hwnd: int) -> str:
    """浏览器地址栏里的网址。按地址栏的类名直接找（P1：网页里嵌了 iframe、侧边栏时，
    按"第一个编辑框"找不到或太慢）；都没找到再退回第一个编辑框。"""
    if uiawalk.hung(hwnd):
        return ""
    uia = worker._uia
    request = uia.CreateCacheRequest()
    for pid in (P_TYPE, P_CLASS, P_RECT, 30011, P_VALUE):  # 30011：AutomationId
        request.AddProperty(pid)
    found = uiawalk.walk(uia, uia.ElementFromHandle(hwnd), request, seconds=1.0, max_nodes=1500,
                         enter=uiawalk.not_into_pages)
    wanted = {value for _prop, value in ADDRESS_BARS}
    edits = []
    for e in found:
        if uiawalk.cached(e, P_CLASS) in wanted or uiawalk.cached(e, 30011) in wanted:
            url = _url_like(str(uiawalk.cached(e, P_VALUE) or ""))
            if url:
                return url
        if uiawalk.cached(e, P_TYPE) == 50004:
            edits.append(e)
    return next((u for u in (_url_like(str(uiawalk.cached(e, P_VALUE) or "")) for e in edits) if u), "")


def ui_tree(worker: UiaWorker, hwnd: int, max_nodes: int = 400, max_depth: int = 7,
            budget_s: float = 0.5) -> str:
    """精简控件树：每行一个控件，缩进表示层级。"""
    if uiawalk.hung(hwnd):
        return ""
    root = auto.ControlFromHandle(hwnd)
    if root is None:
        return ""
    deadline = time.perf_counter() + budget_s
    lines: list[str] = []
    for ctrl, depth in auto.WalkControl(root, includeTop=True, maxDepth=max_depth):
        if len(lines) >= max_nodes or time.perf_counter() > deadline:
            lines.append("…")
            break
        kind = ctrl.ControlTypeName.removesuffix("Control")
        name = (ctrl.Name or "").replace("\n", " ")[:80]
        lines.append(f"{'  ' * depth}[{kind}] {name}".rstrip())
    return "\n".join(lines)


def text_at(worker: UiaWorker, x: int, y: int) -> str:
    """屏幕某一点上控件的文字，用来给重新框选的区域判断内容类型。"""
    ctrl = auto.ControlFromPoint(x, y)
    if ctrl is None:
        return ""
    return "\n".join(t for t in (ctrl.Name, _value(ctrl)) if t)[:4000]
