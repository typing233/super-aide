"""按键名 → 虚拟键码。写法和快捷键一样："ctrl+s"、"alt+f4"、"enter"、"shift+tab"。"""

from __future__ import annotations

import ctypes

MODIFIERS = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "meta": 0x5B, "cmd": 0x5B}
NAMED = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "capslock": 0x14, "printscreen": 0x2C, "pause": 0x13, "apps": 0x5D, "menu": 0x5D,
    "plus": 0xBB, "minus": 0xBD, "comma": 0xBC, "period": 0xBE,
}
#: 这些键要带"扩展键"标记，否则一些程序会当成小键盘上的同名键
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5D}


def vk_of(name: str) -> int:
    """单个键名 → 虚拟键码。不认识时抛 ValueError。"""
    k = name.strip().lower()
    if not k:
        raise ValueError("空的按键名")
    if k in MODIFIERS:
        return MODIFIERS[k]
    if k in NAMED:
        return NAMED[k]
    if k.startswith("f") and k[1:].isdigit() and 1 <= int(k[1:]) <= 24:
        return 0x70 + int(k[1:]) - 1
    if len(k) == 1:
        if k.isascii() and k.isalnum():
            return ord(k.upper())
        scan = ctypes.windll.user32.VkKeyScanW(ord(k))
        if scan != -1 and scan & 0xFF != 0xFF:
            return scan & 0xFF
    raise ValueError(f"不认识的按键：{name}")


def parse_combo(combo: str) -> list[int]:
    """"ctrl+shift+s" → [VK_CONTROL, VK_SHIFT, 'S']。"+" 本身用 "plus" 表示。"""
    parts = [p for p in combo.replace(" ", "").split("+") if p]
    if not parts:
        raise ValueError("空的组合键")
    return [vk_of(p) for p in parts]
