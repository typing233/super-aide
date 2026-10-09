"""一个窗口里能操作的控件。

用 UIA 缓存请求把需要的属性一起取回，但不再一次取整棵树：Chromium 系浏览器在界面线程上处理这种请求，
大网页上一次就能让浏览器卡住好几秒到几分钟（实测 Edge 被卡到"停止响应"）。改为分小步一层层取
（snapshot/uiawalk.py），只取在屏幕上、在窗口范围里的，并且有时间上限。
只留下能操作的（按钮、输入框、链接、勾选框、列表项……以及网页里能点的元素），按树的顺序编号。
编号只在这一次观察里有效：界面变了要重新观察。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from uiautomation.uiautomation import _AutomationClient

from ..snapshot import uiawalk
from ..snapshot.win32 import Rect

# UIA 属性编号（UIAutomationClient.h）
P_RECT, P_TYPE, P_NAME = 30001, 30003, 30005
P_FOCUSED, P_FOCUSABLE, P_ENABLED = 30008, 30009, 30010
P_AID, P_CLASS, P_PASSWORD, P_OFFSCREEN = 30011, 30012, 30019, 30022
P_HAS_EXPAND, P_HAS_INVOKE, P_HAS_SCROLL, P_HAS_SCROLLITEM, P_HAS_SELITEM = 30028, 30031, 30034, 30035, 30036
P_HAS_TEXT, P_HAS_TOGGLE, P_HAS_VALUE = 30040, 30041, 30043
P_VALUE, P_READONLY = 30045, 30046
P_EXPAND_STATE, P_SELECTED, P_TOGGLE_STATE = 30070, 30079, 30086
P_DEFAULT_ACTION = 30100
QUERY_SECONDS, QUERY_NODES = 3.0, 6000  # 看一个窗口最多花这么久、取这么多个元素
SEARCH_SECONDS, SEARCH_NODES = 3.0, 12000  # 按名字找（包括滚动出去的）
PROPS = (P_RECT, P_TYPE, P_NAME, P_FOCUSED, P_FOCUSABLE, P_ENABLED, P_AID, P_CLASS, P_PASSWORD, P_OFFSCREEN,
         P_HAS_EXPAND, P_HAS_INVOKE, P_HAS_SCROLL, P_HAS_SCROLLITEM, P_HAS_SELITEM, P_HAS_TEXT, P_HAS_TOGGLE,
         P_HAS_VALUE, P_VALUE, P_READONLY, P_EXPAND_STATE, P_SELECTED, P_TOGGLE_STATE, P_DEFAULT_ACTION)
TREE_DESCENDANTS = 4

ROLES = {
    50000: "Button", 50002: "CheckBox", 50003: "ComboBox", 50004: "Edit", 50005: "Link", 50006: "Image",
    50007: "ListItem", 50008: "List", 50009: "Menu", 50010: "MenuBar", 50011: "MenuItem", 50012: "ProgressBar",
    50013: "Radio", 50014: "ScrollBar", 50015: "Slider", 50016: "Spinner", 50017: "StatusBar", 50018: "Tab",
    50019: "TabItem", 50020: "Text", 50021: "ToolBar", 50023: "Tree", 50024: "TreeItem", 50025: "Custom",
    50026: "Group", 50028: "DataGrid", 50029: "DataItem", 50030: "Document", 50031: "SplitButton",
    50032: "Window", 50033: "Pane", 50034: "Header", 50035: "HeaderItem", 50036: "Table", 50037: "TitleBar",
}
#: 本身就是用来操作的控件类型
INTERACTIVE = {"Button", "CheckBox", "ComboBox", "Edit", "Link", "ListItem", "MenuItem", "Radio", "Slider",
               "Spinner", "SplitButton", "TabItem", "TreeItem", "DataItem", "HeaderItem", "Document"}
#: Chromium 给链接里的文字之类也挂了"点击祖先"的默认动作，那不是独立的可点元素
ANCESTOR_ACTIONS = ("ancestor", "祖先")
#: 普通文字只有默认动作真的是"点击/跳转"时才算能操作（Qt 给标签也挂了 Invoke 和"按"，那只是聚焦旁边的输入框）
CLICK_ACTIONS = ("click", "单击", "jump", "跳转", "open", "打开")
MAX_NAME, MAX_VALUE = 80, 80


@dataclass
class Element:
    id: int
    role: str
    name: str
    rect: Rect                     # 物理像素
    value: str = ""
    states: tuple[str, ...] = ()
    patterns: frozenset[str] = frozenset()
    automation_id: str = ""
    class_name: str = ""
    raw: Any = field(default=None, repr=False)  # IUIAutomationElement（带缓存）

    @property
    def center(self) -> tuple[int, int]:
        return (self.rect[0] + self.rect[2]) // 2, (self.rect[1] + self.rect[3]) // 2


def _client():
    client = _AutomationClient.instance()
    uiawalk.limit_timeouts(client.IUIAutomation)
    return client


def _cache_request():
    uia = _client().IUIAutomation
    request = uia.CreateCacheRequest()
    for pid in PROPS:
        request.AddProperty(pid)
    return request


def _get(e: Any, pid: int) -> Any:
    try:
        return e.GetCachedPropertyValue(pid)
    except Exception:  # noqa: BLE001 - 个别应用的个别属性会抛
        return None


def _rect(e: Any) -> Rect:
    try:
        r = e.CachedBoundingRectangle
        return int(r.left), int(r.top), int(r.right), int(r.bottom)
    except Exception:  # noqa: BLE001
        return 0, 0, 0, 0


def _short(text: Any, limit: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _patterns(e: Any) -> frozenset[str]:
    flags = {"invoke": P_HAS_INVOKE, "value": P_HAS_VALUE, "toggle": P_HAS_TOGGLE, "select": P_HAS_SELITEM,
             "expand": P_HAS_EXPAND, "scroll": P_HAS_SCROLL, "scrollitem": P_HAS_SCROLLITEM, "text": P_HAS_TEXT}
    return frozenset(k for k, pid in flags.items() if _get(e, pid))


def _states(e: Any, role: str) -> tuple[str, ...]:
    out = []
    if _get(e, P_FOCUSED):
        out.append("focused")
    if _get(e, P_ENABLED) is False:
        out.append("disabled")
    toggle = _get(e, P_TOGGLE_STATE)
    if role in ("CheckBox", "Button", "MenuItem") and toggle in (0, 1):
        out.append("checked" if toggle == 1 else "unchecked")
    if _get(e, P_SELECTED):
        out.append("selected")
    expand = _get(e, P_EXPAND_STATE)
    if expand in (0, 1) and role in ("ComboBox", "MenuItem", "TreeItem", "SplitButton", "Button"):
        out.append("expanded" if expand == 1 else "collapsed")
    if _get(e, P_HAS_VALUE) and _get(e, P_READONLY) and role in ("Edit", "ComboBox"):
        out.append("readonly")
    return tuple(out)


def _is_interactive(e: Any, role: str, patterns: frozenset[str]) -> bool:
    if role in INTERACTIVE:
        return role != "Document" or "value" in patterns  # 只把可编辑的文档区（编辑器）算进来
    action = str(_get(e, P_DEFAULT_ACTION) or "").lower()
    if any(a in action for a in ANCESTOR_ACTIONS):
        return False
    if role == "Text":
        return any(a in action for a in CLICK_ACTIONS)
    return bool(patterns & {"invoke", "toggle", "select", "expand"}) or bool(action)


def _intersects(r: Rect, bounds: Rect) -> bool:
    return min(r[2], bounds[2]) - max(r[0], bounds[0]) > 2 and min(r[3], bounds[3]) - max(r[1], bounds[1]) > 2


def query(hwnd: int, bounds: Rect, visible_only: bool = True, limit: int = 400) -> list[Element]:
    """窗口里能操作的控件（按树的顺序，编号从 1 开始）。bounds 外的不要。"""
    uia = _client().IUIAutomation
    root = uia.ElementFromHandle(hwnd)
    found = uiawalk.walk(uia, root, _cache_request(), seconds=QUERY_SECONDS, max_nodes=QUERY_NODES,
                         within=bounds if visible_only else None, on_screen=visible_only)
    out: list[Element] = []
    seen: set[tuple] = set()
    for e in found:
        role = ROLES.get(_get(e, P_TYPE), "Custom")
        rect = _rect(e)
        if rect[2] - rect[0] < 3 or rect[3] - rect[1] < 3 or not _intersects(rect, bounds):
            continue
        patterns = _patterns(e)
        if not _is_interactive(e, role, patterns):
            continue
        name = _short(_get(e, P_NAME), MAX_NAME)
        if not name and role not in INTERACTIVE:
            continue  # 没名字的容器（网页里大量的 Group）只是噪音；没名字的按钮、输入框留着（图标按钮）
        key = (name, rect)
        if key in seen:  # 外层和里层一模一样（比如列表项和它里面的文字），留外层
            continue
        seen.add(key)
        value = ""
        if "value" in patterns:
            value = "••••" if _get(e, P_PASSWORD) else _short(_get(e, P_VALUE), MAX_VALUE)
        out.append(Element(id=len(out) + 1, role=role, name=name, rect=rect, value=value if value != name else "",
                           states=_states(e, role), patterns=patterns,
                           automation_id=str(_get(e, P_AID) or ""), class_name=str(_get(e, P_CLASS) or ""), raw=e))
        if len(out) >= limit:
            break
    return out


def _search_request():
    """按名字找时一路上只取这几个属性；找到的再补齐（几千个元素各取二十几个属性太慢）。"""
    uia = _client().IUIAutomation
    request = uia.CreateCacheRequest()
    for pid in (P_RECT, P_TYPE, P_NAME, P_VALUE, P_PASSWORD, P_OFFSCREEN):
        request.AddProperty(pid)
    return request


def _matches(e: Any, needle: str) -> bool:
    name = str(_get(e, P_NAME) or "").lower()
    value = "" if _get(e, P_PASSWORD) else str(_get(e, P_VALUE) or "").lower()
    return needle in name or needle in value


def search(hwnd: int, text: str, role: str = "", limit: int = 30) -> list[Element]:
    """按名字（或值）里包含 text 找控件，包括还没滚动到的。用于"找到某个按钮再去点"。
    分小步找，最多 SEARCH_SECONDS 秒：特别大的页面可能找不全，那时先滚动到大概的位置再找。"""
    uia = _client().IUIAutomation
    root = uia.ElementFromHandle(hwnd)
    needle = text.strip().lower()
    # 先找屏幕上的（快）；没有再在整棵树里一个一个地找（不会卡住浏览器，但大页面可能找不全）
    found = [x for x in uiawalk.walk(uia, root, _search_request(), seconds=QUERY_SECONDS, max_nodes=QUERY_NODES,
                                     on_screen=True) if _matches(x, needle)]
    if not found:
        found = [x for x in uiawalk.walk_siblings(uia, root, _search_request(), seconds=SEARCH_SECONDS,
                                                  max_nodes=SEARCH_NODES) if _matches(x, needle)]
    out: list[Element] = []
    full = _cache_request()
    for e in found:
        r = ROLES.get(_get(e, P_TYPE), "Custom")
        if role and r.lower() != role.lower():
            continue
        name = str(_get(e, P_NAME) or "")
        value = "" if _get(e, P_PASSWORD) else str(_get(e, P_VALUE) or "")
        if needle not in name.lower() and needle not in value.lower():
            continue
        try:
            e = e.BuildUpdatedCache(full)  # 找到了：补齐操作要用的属性
        except Exception:  # noqa: BLE001 - 刚好没了
            continue
        rect = _rect(e)
        states = _states(e, r) + (("offscreen",) if _get(e, P_OFFSCREEN) else ())
        out.append(Element(id=0, role=r, name=_short(name, MAX_NAME), rect=rect, value=_short(value, MAX_VALUE),
                           states=states, patterns=_patterns(e), raw=e))
        if len(out) >= limit:
            break
    return out
