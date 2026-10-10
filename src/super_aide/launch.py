"""启动入口（开始菜单、桌面快捷方式、`python -m super_aide`）。

已经有一个在运行时（又从开始菜单点了一次），不加载别的模块，直接叫醒它（它会提示"已经在运行"）然后退出。
原来要先把 PySide6、两个引擎的 SDK 全部导入完才检查单实例，提示要等七八秒才出来，看着像没反应，容易一点再点。
这里只用标准库；没在运行、正在换包（自我改进生效）、自己重启自己时，照常走 app.main。
"""

from __future__ import annotations

import ctypes
import sys

SINGLETON = "Local\\SuperAideSingleton"   # 单实例互斥体（app._single_instance 创建）
WAKE_EVENT = "Local\\SuperAideWake"       # 再打开一次时，叫醒正在运行的那个（app.Wakeup 在等）
APPLYING = "Local\\SuperAideApplying"     # 自我改进正在换包（evolve/apply.py 持有，manager.wait_for_apply 等它）
#: 带这些参数启动时要走完整流程：等旧进程退出、换包后的健康检查（见 app.RESTART_FLAG、app.EVOLVE_FLAGS）
SLOW_FLAGS = ("--restart-after", "--evolved", "--evolve-failed", "--evolve-undone")

SYNCHRONIZE, EVENT_MODIFY_STATE = 0x00100000, 0x0002


def _exists(name: str) -> bool:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenMutexW(SYNCHRONIZE, False, name)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def wake_running() -> bool:
    """叫醒正在运行的那个。返回叫到了没有。"""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenEventW.restype = ctypes.c_void_p
    kernel32.OpenEventW.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.SetEvent.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, WAKE_EVENT)
    if not handle:
        return False
    kernel32.SetEvent(handle)
    kernel32.CloseHandle(handle)
    return True


def already_running(argv: list[str]) -> bool:
    """已经有一个在运行（而且不是正在换包、不是自己重启自己）。"""
    if any(flag in argv for flag in SLOW_FLAGS) or _exists(APPLYING):
        return False
    return _exists(SINGLETON)


def main() -> int:
    if already_running(sys.argv) and wake_running():
        return 0
    from .app import main as run  # 第一次启动：这时才加载界面和引擎

    return run()
