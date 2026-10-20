"""分小步遍历 UI Automation 树。

一次 FindAll（子孙）在应用那边是一整个调用：Chromium 系（Edge、Chrome、VS Code……）在界面线程上处理它，
页面很大时要很久，这期间整个浏览器都卡住。实测：网页版 VS Code 的 ModelScope 编辑器上，一次观察让 Edge
卡了 4 分半，被系统判定"停止响应"后关掉。

所以改成一层一层地取：每次只取一个元素的子元素（一个很小的调用，调用之间浏览器照常处理自己的事），并且
- 有总时间和总个数的上限，到了就停（返回已经取到的）；
- 可以按位置剪枝：整块落在可视范围外的子树不进去（看窗口时只要看得见的）；
- 可以不进文档区（网页内容用文本接口一次读完，不用一个个元素地取）。
另外给 UIA 客户端设上超时，万一应用卡住，一次调用也不会把我们拖上几分钟。
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Callable
from typing import Any

TREE_CHILDREN = 2
P_RECT, P_TYPE, P_CLASS, P_IS_CONTROL, P_OFFSCREEN, P_HAS_TEXT = 30001, 30003, 30012, 30016, 30022, 30040
DOCUMENT = 50030
WINDOW = 50032
#: Chromium 系放网页的那个子窗口在 UIA 里的类名。它下面就是网页（文档区）
WEB_HOST = "Chrome_RenderWidgetHostHWND"
CONNECTION_TIMEOUT_MS, TRANSACTION_TIMEOUT_MS = 2000, 5000

_limited: set[int] = set()


def limit_timeouts(uia: Any) -> None:
    """给 UIA 客户端设上超时（每个客户端对象设一次）：应用没响应时，调用最多等这么久就报错返回。"""
    if id(uia) in _limited:
        return
    _limited.add(id(uia))
    try:
        from comtypes.gen.UIAutomationClient import IUIAutomation2

        v2 = uia.QueryInterface(IUIAutomation2)
        v2.ConnectionTimeout = CONNECTION_TIMEOUT_MS
        v2.TransactionTimeout = TRANSACTION_TIMEOUT_MS
    except Exception:  # noqa: BLE001 - 老系统没有这个接口：只是没有超时保护
        pass


def hung(hwnd: int) -> bool:
    """窗口所在的程序是不是没响应（系统几秒收不到它处理消息就算）。没响应时别再往它那里发请求。"""
    return bool(hwnd) and bool(ctypes.windll.user32.IsHungAppWindow(hwnd))


def wait_responsive(hwnd: int, seconds: float = 3.0) -> bool:
    """程序没响应时等它一会儿（它可能只是忙一下），等到了返回 True。"""
    deadline = time.perf_counter() + seconds
    while hung(hwnd):
        if time.perf_counter() > deadline:
            return False
        time.sleep(0.2)
    return True


def rect_of(e: Any) -> tuple[int, int, int, int]:
    try:
        r = e.CachedBoundingRectangle
        return int(r.left), int(r.top), int(r.right), int(r.bottom)
    except Exception:  # noqa: BLE001
        return 0, 0, 0, 0


def cached(e: Any, pid: int) -> Any:
    try:
        return e.GetCachedPropertyValue(pid)
    except Exception:  # noqa: BLE001
        return None


def walk(uia: Any, root: Any, request: Any, *, seconds: float, max_nodes: int,
         within: tuple[int, int, int, int] | None = None, on_screen: bool = False,
         enter: Callable[[Any], bool] | None = None) -> list:
    """深度优先地取 root 下面的元素（带缓存，按树的顺序，不含 root），到时间或个数上限就停。
    request 要包含 BoundingRectangle 和 ControlType（剪枝要用）。
    within：只要和这个范围相交的；完全在范围外的元素连同它的子树都不要（滚动出去的、别的标签页的）。
    on_screen：只要应用说"在屏幕上"的子元素。由应用那边筛，几千行的表格只把看得见的几十行传过来
    （实测：不筛的话，一个四千行表格的子元素列表就要取好几秒）。
    enter(e) 返回 False 时不进 e 的子树（e 本身照样返回），比如不进网页的文档区。"""
    limit_timeouts(uia)
    deadline = time.perf_counter() + seconds
    condition = on_screen_condition(uia) if on_screen else uia.CreateTrueCondition()
    out: list = []
    stack = [root]
    while stack and len(out) < max_nodes and time.perf_counter() < deadline:
        parent = stack.pop()
        try:
            children = parent.FindAllBuildCache(TREE_CHILDREN, condition, request)
        except Exception:  # noqa: BLE001 - 元素没了、应用超时：跳过这一支
            continue
        kept = []
        for i in range(children.Length if children else 0):
            e = children.GetElement(i)
            if within is not None and not _touches(rect_of(e), within):
                continue
            kept.append(e)
        out.extend(kept)
        stack.extend(e for e in reversed(kept) if enter is None or enter(e))
    return out[:max_nodes]


def on_screen_condition(uia: Any) -> Any:
    """"在屏幕上"的子元素，再加上所有窗口类的子元素（不管它说自己在不在屏幕上）。
    Win11 的 XAML 应用（新版记事本、终端、设置……）把浮出的面板放在一个 Popup 窗口里，这个窗口报"不在屏幕上"、
    大小是 0，里面的控件却都在屏幕上：只按"在屏幕上"筛，整块面板都看不到（实测记事本按 Ctrl+H 以后，
    替换框、"全部替换"一个都没有）。同一层的窗口很少，不会像几千行的表格那样拖慢。"""
    return uia.CreateOrCondition(uia.CreatePropertyCondition(P_OFFSCREEN, False),
                                 uia.CreatePropertyCondition(P_TYPE, WINDOW))


def walk_siblings(uia: Any, root: Any, request: Any, *, seconds: float, max_nodes: int,
                  enter: Callable[[Any], bool] | None = None) -> list:
    """和 walk 一样深度优先，但一次只取一个元素（第一个子元素、下一个兄弟）。
    比 walk 慢，但一个元素有几千个子元素时（长表格、长列表）也不会有一次很大的调用把浏览器卡住
    （实测：四千行的表格，一次取它的子元素卡了浏览器 4.7 秒）。按名字找"还没滚动到的"时用。"""
    limit_timeouts(uia)
    deadline = time.perf_counter() + seconds
    walker = uia.RawViewWalker
    out: list = []

    def first_child(e):
        try:
            return walker.GetFirstChildElementBuildCache(e, request)
        except Exception:  # noqa: BLE001
            return None

    stack = [first_child(root)]
    while stack and len(out) < max_nodes and time.perf_counter() < deadline:
        e = stack.pop()
        if e is None:
            continue
        out.append(e)
        try:
            sibling = walker.GetNextSiblingElementBuildCache(e, request)
        except Exception:  # noqa: BLE001
            sibling = None
        stack.append(sibling)  # 先把兄弟压栈，再压子元素：子元素先处理（按树的顺序）
        if enter is None or enter(e):
            stack.append(first_child(e))
    return out


def web_documents(uia: Any, hwnd: int, hosts: list[int]) -> list:
    """Chromium 系窗口里每个网页的文档节点：网页子窗口的元素下面第一个子元素就是它。
    要用树遍历器取：在这个元素上用 FindAll 找子元素会直接跳过文档节点、返回文档里面的东西（实测）。"""
    limit_timeouts(uia)
    docs = []
    for host in hosts:
        try:
            doc = uia.ControlViewWalker.GetFirstChildElement(uia.ElementFromHandle(host))
            if doc is not None and doc.CurrentControlType == DOCUMENT:
                docs.append(doc)
        except Exception:  # noqa: BLE001 - 网页还没交出来、子窗口刚关掉
            continue
    return docs


def not_into_pages(e: Any) -> bool:
    """walk 的 enter：不进网页和文档区（那里的内容用文本接口一次读完，不用一个个元素地取）。"""
    return cached(e, P_TYPE) != DOCUMENT and cached(e, P_CLASS) != WEB_HOST


def _touches(r: tuple[int, int, int, int], area: tuple[int, int, int, int]) -> bool:
    if r[2] <= r[0] or r[3] <= r[1]:
        return True  # 没有位置的容器（不少应用的分组就是这样）：不能据此剪掉，进去看看
    return min(r[2], area[2]) > max(r[0], area[0]) and min(r[3], area[3]) > max(r[1], area[1])


def light_request(uia: Any) -> Any:
    """剪枝和判断用的最少属性。"""
    request = uia.CreateCacheRequest()
    for pid in (P_RECT, P_TYPE, P_CLASS, P_IS_CONTROL):
        request.AddProperty(pid)
    return request
