"""Super Aide 和工具服务器之间的两个信号（Windows 命名事件，不同进程都能用）。

- 停止：你按物理 Esc 时置位，工具服务器每一步之前检查，立刻停下；新的操作开始时复位。
- 收起指引：你收起回答或者重新召唤时置位，屏幕上的指引框消失。
"""

from __future__ import annotations

import ctypes

STOP = "Local\\SuperAideStop"
GUIDE_CLEAR = "Local\\SuperAideGuideClear"
kernel32 = ctypes.windll.kernel32
kernel32.CreateEventW.restype = ctypes.c_void_p
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
kernel32.SetEvent.argtypes = [ctypes.c_void_p]
kernel32.ResetEvent.argtypes = [ctypes.c_void_p]


class Signals:
    """主进程这边：建好事件（工具服务器打开同名事件）。"""

    def __init__(self) -> None:
        self._stop = kernel32.CreateEventW(None, True, False, STOP)          # 手动复位：停下后一直保持
        self._guide = kernel32.CreateEventW(None, False, False, GUIDE_CLEAR)  # 自动复位：指引窗口读一次就清

    def stop(self) -> None:
        if self._stop:
            kernel32.SetEvent(self._stop)

    def resume(self) -> None:
        if self._stop:
            kernel32.ResetEvent(self._stop)

    def clear_guide(self) -> None:
        if self._guide:
            kernel32.SetEvent(self._guide)
