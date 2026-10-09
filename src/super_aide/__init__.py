"""Super Aide：Windows 桌面超级助手。"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("super-aide")
except PackageNotFoundError:  # 没装、直接从源码跑
    __version__ = "0.0.0"
