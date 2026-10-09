"""开机自启：写 HKCU 的 Run 键，用虚拟环境里的 pythonw 启动（不弹控制台窗口）。

自启的命令带 --autostart：开机时安静地在后台起来；你自己打开时才提示一下它在哪、怎么用。
"""

from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "SuperAide"
FLAG = "--autostart"


def command() -> str:
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    return f'"{windowless if windowless.exists() else exe}" -m super_aide {FLAG}'


def _stored() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return str(winreg.QueryValueEx(key, NAME)[0])
    except OSError:
        return ""


def is_enabled() -> bool:
    return bool(_stored())


def upgrade() -> None:
    """以前写的自启命令没带 --autostart：是这个 Python 写的就补上（别的副本写的不动，免得被开发版抢走自启）。"""
    if _stored() == command().removesuffix(f" {FLAG}"):
        set_enabled(True)


def set_enabled(on: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass
