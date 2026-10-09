"""中英文界面（设置 → 外观 → 语言：跟随系统 / 中文 / English）。应用名：中文"超级助手"，英文"Super Aide"。

源语言是中文：给人看的界面文字直接写中文、用 tr() 包起来；英文在 locales/en_*.py 里按中文原文查（查不到就显示中文）。
- 带变量的写成 tr("正在读 {name}", name=...)：中英文各自决定变量放在哪。
- 要在用的时候调用 tr()（函数里），不要在模块导入时算好存成常量：语言可以随时切换。
- 只翻译人看的文字；写给模型看的指令、工具说明、环境资料照旧是中文（模型都看得懂）。
网页那边是同样的做法（ui/web/i18n.js 和 i18n-en.js）。
"""

from __future__ import annotations

import ctypes
import importlib
import os
import pkgutil

from . import locales

LANGUAGES = ("system", "zh", "en")
_lang = "zh"
_catalog: dict[str, str] | None = None


def system_language() -> str:
    """Windows 的显示语言是中文就用中文，其它都用英文。环境变量 SUPER_AIDE_LANG=zh / en 可以指定（测试用）。"""
    forced = os.environ.get("SUPER_AIDE_LANG", "").strip().lower()
    if forced in ("zh", "en"):
        return forced
    try:
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return "zh"
    return "zh" if langid & 0x3FF == 0x04 else "en"  # 主语言 0x04 = 中文（简体、繁体）


def resolve(setting: str) -> str:
    """设置里的值（system / zh / en）→ 实际用的语言。"""
    return setting if setting in ("zh", "en") else system_language()


def set_language(code: str) -> None:
    global _lang
    _lang = "en" if code == "en" else "zh"


def lang() -> str:
    return _lang


def english() -> dict[str, str]:
    """所有 locales/en_*.py 合在一起的英文对照表（第一次用时读）。"""
    global _catalog
    if _catalog is None:
        merged: dict[str, str] = {}
        for info in pkgutil.iter_modules(locales.__path__):
            if info.name.startswith("en_"):
                merged.update(importlib.import_module(f"{locales.__name__}.{info.name}").EN)
        _catalog = merged
    return _catalog


def tr(text: str, /, **values) -> str:  # text 只能按位置传：变量也可以叫 {text}
    out = english().get(text, text) if _lang == "en" else text
    return out.format(**values) if values else out


def app_name() -> str:
    return "Super Aide" if _lang == "en" else "超级助手"
