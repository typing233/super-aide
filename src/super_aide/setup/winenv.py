"""用户级环境变量（HKCU\\Environment）：加 PATH、设变量。不用管理员权限。

改完广播一下，之后新开的命令行窗口就能看到；当前进程的 os.environ 同时改掉，不用重启 Super Aide。
"""

from __future__ import annotations

import ctypes
import os
import winreg
from pathlib import Path

HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002


def _broadcast() -> None:
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                                             SMTO_ABORTIFHUNG, 2000, ctypes.byref(result))


def _same(a: str, b: str) -> bool:
    def norm(x: str) -> str:
        return os.path.normcase(os.path.normpath(os.path.expandvars(x.strip().strip('"')))).rstrip("\\/")
    return norm(a) == norm(b)


def add_user_path(directory: Path) -> bool:
    """把目录加到用户 PATH 末尾（已经有了就不动）。返回是否改了。"""
    directory = str(directory)
    changed = False
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            value, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            value, kind = "", winreg.REG_EXPAND_SZ
        parts = [p for p in str(value).split(";") if p.strip()]
        if not any(_same(p, directory) for p in parts):
            kind = kind if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) else winreg.REG_EXPAND_SZ
            winreg.SetValueEx(key, "Path", 0, kind, ";".join(parts + [directory]))
            changed = True
    if changed:
        _broadcast()
    if not any(_same(p, directory) for p in os.environ.get("PATH", "").split(os.pathsep) if p):
        os.environ["PATH"] = os.environ.get("PATH", "").rstrip(os.pathsep) + os.pathsep + directory
    return changed


def set_user_env(name: str, value: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    os.environ[name] = value
    _broadcast()
