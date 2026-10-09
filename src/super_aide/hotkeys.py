"""全局快捷键：解析"Alt+Q"这类写法，用 RegisterHotKey 注册，从 Qt 的原生事件里接收。"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer

from .i18n import tr

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

_MODIFIERS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
              "shift": MOD_SHIFT, "win": MOD_WIN}
_NAMED_KEYS = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "pause": 0x13, "`": 0xC0, "backquote": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD,
    ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC,
}
#: 不带修饰键也允许单独注册的键（不会和日常打字冲突）
_STANDALONE = {0x13} | set(range(0x7C, 0x88))  # Pause、F13~F24
PROBE_ID = 0xBFFF  # 试注册用的编号（应用可用的最大编号），不和正式注册的冲突

user32 = ctypes.windll.user32


def parse(spec: str) -> tuple[int, int]:
    """'Ctrl+Alt+Q' → (修饰键位掩码, 虚拟键码)。写法不合法时抛 ValueError。"""
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError(tr("快捷键不能为空"))
    *mods, key = parts
    mask = 0
    for m in mods:
        if m.lower() not in _MODIFIERS:
            raise ValueError(tr("不认识的修饰键：{key}", key=m))
        mask |= _MODIFIERS[m.lower()]
    k = key.lower()
    if len(k) == 1 and (k.isascii() and k.isalnum()):
        vk = ord(k.upper())
    elif k.startswith("f") and k[1:].isdigit() and 1 <= int(k[1:]) <= 24:
        vk = 0x70 + int(k[1:]) - 1
    elif k in _NAMED_KEYS:
        vk = _NAMED_KEYS[k]
    else:
        raise ValueError(tr("不认识的按键：{key}", key=key))
    if not mask and vk not in _STANDALONE:
        raise ValueError(tr("需要至少一个修饰键（Ctrl / Alt / Shift / Win）"))
    return mask, vk


class HotkeyManager(QAbstractNativeEventFilter):
    """注册全局快捷键；按下时在 Qt 主线程回调 callback(name, 按下时刻)。"""

    def __init__(self, callback: Callable[[str, float], None]) -> None:
        super().__init__()
        self.callback = callback
        self._ids: dict[int, str] = {}
        self._keys: dict[int, tuple[int, int]] = {}

    @property
    def active(self) -> bool:
        return bool(self._ids)

    def register(self, name: str, spec: str) -> bool:
        mask, vk = parse(spec)
        hid = len(self._ids) + 1
        ok = bool(user32.RegisterHotKey(None, hid, mask | MOD_NOREPEAT, vk))
        if ok:
            self._ids[hid] = name
            self._keys[hid] = (mask, vk)
        return ok

    def available(self, spec: str) -> bool:
        """这个组合键能不能用：没被其它程序占用（我们自己正在用的也算能用）。写法不合法时抛 ValueError。"""
        mask, vk = parse(spec)
        if (mask, vk) in self._keys.values():
            return True
        if not user32.RegisterHotKey(None, PROBE_ID, mask | MOD_NOREPEAT, vk):
            return False
        user32.UnregisterHotKey(None, PROBE_ID)
        return True

    def unregister_all(self) -> None:
        for hid in self._ids:
            user32.UnregisterHotKey(None, hid)
        self._ids.clear()
        self._keys.clear()

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt 的方法名
        name = event_type.data() if hasattr(event_type, "data") else bytes(event_type)
        if name == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam in self._ids:
                arrived = time.perf_counter()
                hotkey = self._ids[msg.wParam]
                QTimer.singleShot(0, lambda: self.callback(hotkey, arrived))
                return True, 0
        return False, 0
