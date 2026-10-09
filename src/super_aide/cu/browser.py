"""浏览器：在你正在用的浏览器里直接操作（已经登录的网站、打开的标签页都在），不需要装扩展。

网址从地址栏读（Chromium 系的 OmniboxViewViews、Firefox 的 urlbar-input）；打开网址、前进后退、
标签页都用浏览器自己的快捷键。网页里的按钮、输入框和普通控件一样，在 observe 的控件列表里。
"""

from __future__ import annotations

import time

from uiautomation.uiautomation import _AutomationClient

from . import inputs

BROWSERS = {"chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe", "opera.exe", "arc.exe", "firefox.exe"}
P_CLASS, P_AID, P_TYPE, P_NAME, P_VALUE, P_SELECTED = 30012, 30011, 30003, 30005, 30045, 30079
ADDRESS_BARS = ((P_CLASS, "OmniboxViewViews"), (P_AID, "urlbar-input"))
TAB_ITEM = 50019


def _uia():
    return _AutomationClient.instance().IUIAutomation


def _url_like(value: str) -> str:
    return value if value and ("." in value or value.startswith(("http", "localhost", "file:", "edge:", "chrome:"))) else ""


def current_url(hwnd: int) -> str:
    uia = _uia()
    root = uia.ElementFromHandle(hwnd)
    for prop, value in ADDRESS_BARS:
        try:
            bar = root.FindFirst(4, uia.CreatePropertyCondition(prop, value))
            if bar:
                url = _url_like(str(bar.GetCurrentPropertyValue(P_VALUE) or ""))
                if url:
                    return url
        except Exception:  # noqa: BLE001
            continue
    return ""


def tabs(hwnd: int) -> list[tuple[str, bool]]:
    """标签页：(标题, 是否当前)。"""
    uia = _uia()
    root = uia.ElementFromHandle(hwnd)
    found = root.FindAll(4, uia.CreatePropertyCondition(P_TYPE, TAB_ITEM))
    out = []
    for i in range(found.Length if found else 0):
        e = found.GetElement(i)
        try:
            out.append((str(e.CurrentName or ""), bool(e.GetCurrentPropertyValue(P_SELECTED))))
        except Exception:  # noqa: BLE001
            continue
    return out


def run(hwnd: int, command: str, value: str = "") -> str:
    """执行浏览器命令，返回一句说明。调用前窗口要在前台（inputs.focus_window）。"""
    command = command.strip().lower()
    if command == "url":
        return current_url(hwnd) or "读不到网址"
    if command == "tabs":
        listed = tabs(hwnd)
        return "\n".join(f"{'* ' if on else '  '}{i + 1}. {title}" for i, (title, on) in enumerate(listed)) or "读不到标签页"
    if command in ("go", "new_tab"):
        if not value:
            return "需要网址"
        inputs.press("ctrl+t" if command == "new_tab" else "ctrl+l")
        time.sleep(0.25)
        if command == "go":
            inputs.press("ctrl+a")
        inputs.paste_text(value)
        inputs.press("enter")
        time.sleep(1.2)
        return f"已打开 {value}"
    keys = {"back": "alt+left", "forward": "alt+right", "reload": "f5", "close_tab": "ctrl+w",
            "next_tab": "ctrl+tab", "prev_tab": "ctrl+shift+tab"}
    if command in keys:
        inputs.press(keys[command])
        time.sleep(0.6)
        return f"已执行 {command}"
    if command == "tab" and value.isdigit():
        n = int(value)
        if 1 <= n <= 8:
            inputs.press(f"ctrl+{n}")
            time.sleep(0.4)
            return f"已切到第 {n} 个标签页"
        return "只能直接切到前 8 个标签页，其余用 next_tab"
    return f"不认识的浏览器命令：{command}（可用 url、go、new_tab、back、forward、reload、tabs、tab、next_tab、prev_tab、close_tab）"
