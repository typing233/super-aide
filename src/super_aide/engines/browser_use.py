"""Codex 的浏览器操作有没有接通。

操作你自己的浏览器（已登录的网站、打开的标签页），Codex 用它的「Chrome」插件：
插件通过浏览器里的 ChatGPT 扩展加本机的连接组件（native messaging host）直接操作网页，Edge 也支持。
连接组件由 Codex 应用在安装 Chrome 插件时装好（应用里的 chrome-plugin-native-host-lifecycle，
注册表位置和我们检查的一致）。没接通时，Computer Use 往往也不肯操作浏览器窗口：
它要能确定当前网址才放行，网页里嵌了 iframe、开着侧边栏时就确定不了（P3 实测）。
这里只检查、不替你安装：插件说明里有浏览数据可能用于训练的提示，要不要开由你决定。
"""

from __future__ import annotations

import json
import os
import tomllib
import winreg
from dataclasses import dataclass
from pathlib import Path

from ..i18n import tr

HOST_NAME = "com.openai.codexextension"
EXTENSION_IDS = ("hehggadaopoacecdllhhajmbjkdcmajg", "odlomjlbamekndcpllcnffbgeohgkmjh")
#: Edge 和其它 Chromium 系浏览器也会读 Chrome 的这个位置
HOST_KEYS = (r"Software\Google\Chrome\NativeMessagingHosts", r"Software\Microsoft\Edge\NativeMessagingHosts")
BROWSER_DATA = {
    "msedge.exe": ("Microsoft Edge", r"Microsoft\Edge\User Data"),
    "chrome.exe": ("Google Chrome", r"Google\Chrome\User Data"),
    "brave.exe": ("Brave", r"BraveSoftware\Brave-Browser\User Data"),
}
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
CHROME_PLUGIN = "chrome@openai-bundled"
#: 没接通时的原因和修法。中文原文是 tr() 的键：给你看的显示时才翻译，写给引擎的说明照旧用中文
FIX = "在 Codex 应用的插件页里安装「Chrome」插件（用 ChatGPT 控制浏览器，Edge 也支持）"
NOT_CONNECTED = "浏览器操作还没接通：{fix}。"
NO_EXTENSION = "浏览器操作还没接通：{browser} 里没装 ChatGPT 扩展，按 Codex 应用里 Chrome 插件的提示装上。"


@dataclass
class Status:
    ready: bool
    problem: str = ""  # 给你看的原因和修法（按界面语言）
    note: str = ""     # 同一句话写给引擎看的（中文，见 hub._notes）


def plugin_enabled() -> bool:
    """你的 Codex 配置里开了 Chrome 插件吗？我们启动的 Codex 读同一份配置。"""
    try:
        data = tomllib.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return bool(data.get("plugins", {}).get(CHROME_PLUGIN, {}).get("enabled"))


def host_installed() -> bool:
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for base in HOST_KEYS:
            try:
                with winreg.OpenKey(root, rf"{base}\{HOST_NAME}") as key:
                    manifest = Path(winreg.QueryValue(key, None))
            except OSError:
                continue
            try:
                json.loads(manifest.read_text(encoding="utf-8"))
                return True
            except (OSError, ValueError):
                continue
    return False


def extension_installed(process: str) -> bool | None:
    """这个浏览器的任一用户配置里装了 ChatGPT 扩展吗？不认识的浏览器返回 None。"""
    entry = BROWSER_DATA.get(process.lower())
    if entry is None:
        return None
    data = Path(os.environ.get("LOCALAPPDATA", "")) / entry[1]
    if not data.exists():
        return None
    profiles = [d for d in data.iterdir() if d.is_dir() and (d.name == "Default" or d.name.startswith("Profile "))]
    return any((d / "Extensions" / ext).exists() for d in profiles for ext in EXTENSION_IDS)


def status(process: str = "") -> Status:
    if not plugin_enabled() or not host_installed():  # 装 Chrome 插件时，应用会一起装好连接组件
        return Status(False, tr(NOT_CONNECTED, fix=tr(FIX)), NOT_CONNECTED.format(fix=FIX))
    if process and extension_installed(process) is False:
        name = BROWSER_DATA[process.lower()][0]
        return Status(False, tr(NO_EXTENSION, browser=name), NO_EXTENSION.format(browser=name))
    return Status(True)
