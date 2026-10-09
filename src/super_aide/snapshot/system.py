"""系统画像（启动时采集，每天刷新）和此刻的系统状态。"""

from __future__ import annotations

import ctypes
import json
import shutil
import subprocess
import time
import winreg
from datetime import datetime
from pathlib import Path

import psutil

from .. import paths

CREATE_NO_WINDOW = 0x08000000
DEV_TOOLS = {
    "python": ["--version"], "py": ["--version"], "conda": ["--version"], "uv": ["--version"],
    "node": ["--version"], "npm": ["--version"], "git": ["--version"], "jupyter": ["--version"],
    "java": ["-version"], "dotnet": ["--version"], "winget": ["--version"], "pwsh": ["--version"],
}


def _reg(root: int, path: str, name: str) -> str:
    try:
        with winreg.OpenKey(root, path) as key:
            return str(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return ""


def proxy() -> str:
    settings = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    if _reg(winreg.HKEY_CURRENT_USER, settings, "ProxyEnable") == "1":
        return _reg(winreg.HKEY_CURRENT_USER, settings, "ProxyServer")
    return ""


def _tool_version(exe: str, args: list[str]) -> dict | None:
    path = shutil.which(exe)
    if not path:
        return None
    try:
        out = subprocess.run([path, *args], capture_output=True, text=True, timeout=5,
                             creationflags=CREATE_NO_WINDOW, encoding="utf-8", errors="replace")
        lines = (out.stdout or out.stderr).strip().splitlines()
        return {"path": path, "version": lines[0][:100] if lines else ""}
    except (OSError, subprocess.SubprocessError):
        return {"path": path, "version": ""}


def _locale() -> str:
    buf = ctypes.create_unicode_buffer(85)
    ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, len(buf))
    return buf.value


def build_profile(displays: list[dict]) -> dict:
    nt = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    hklm = winreg.HKEY_LOCAL_MACHINE
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "os": {
            "name": _reg(hklm, nt, "ProductName"),
            "display_version": _reg(hklm, nt, "DisplayVersion"),
            "build": f"{_reg(hklm, nt, 'CurrentBuild')}.{_reg(hklm, nt, 'UBR')}",
        },
        "cpu": _reg(hklm, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString").strip(),
        "cpu_cores": psutil.cpu_count(logical=True),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "displays": displays,
        "locale": _locale(),
        "default_browser": _reg(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice", "ProgId"),
        "dev_tools": {name: v for name, args in DEV_TOOLS.items() if (v := _tool_version(name, args))},
    }


def load_profile(displays: list[dict], max_age_h: float = 24, path: Path = paths.SYSTEM_PROFILE) -> dict:
    """读缓存的系统画像；过期或不存在时重新采集（较慢，调用方应放在后台线程）。
    显示器总是用这次传进来的：可能刚插拔过，取起来也不费事。"""
    profile = None
    if path.exists() and time.time() - path.stat().st_mtime < max_age_h * 3600:
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    if profile is None:
        profile = build_profile(displays)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    if displays:
        profile["displays"] = displays
    return profile


def _online() -> bool:
    flags = ctypes.c_ulong()
    return bool(ctypes.windll.wininet.InternetGetConnectedState(ctypes.byref(flags), 0))


def dynamic_state() -> dict:
    """此刻的系统状态（约 50ms）。

    不列进程：遍历所有进程的内存占用要约 4 秒（P1 实测），而且"哪个进程占资源"
    引擎随时可以自己用只读命令（Get-Process）查到。
    """
    vm = psutil.virtual_memory()
    disks = {}
    for part in psutil.disk_partitions(all=False):
        if "fixed" in part.opts or part.fstype:
            try:
                disks[part.device.rstrip("\\")] = round(psutil.disk_usage(part.mountpoint).free / 2**30, 1)
            except OSError:
                continue
    battery = psutil.sensors_battery()
    return {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": vm.percent,
        "disk_free_gb": disks,
        "battery": None if battery is None else {"percent": battery.percent, "plugged": battery.power_plugged},
        "online": _online(),
        "proxy": proxy(),
    }


def summary(profile: dict, state: dict) -> str:
    """一行系统摘要，写进首条消息。"""
    os_ = profile.get("os", {})
    parts = [f"{os_.get('name', 'Windows')} {os_.get('display_version', '')}（build {os_.get('build', '?')}）".strip()]
    parts.append(f"CPU {state.get('cpu_percent', '?')}%")
    parts.append(f"内存 {state.get('memory_percent', '?')}%（共 {profile.get('ram_gb', '?')}GB）")
    disks = state.get("disk_free_gb", {})
    if disks:
        parts.append("剩余空间 " + "、".join(f"{d} {gb}GB" for d, gb in disks.items()))
    parts.append("网络正常" if state.get("online") else "网络不通")
    if state.get("proxy"):
        parts.append(f"系统代理 {state['proxy']}")
    return " · ".join(parts)
