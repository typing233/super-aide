"""在连着的安卓手机上驱动调试版超级助手（adb）。

  python scripts/android/device_test.py setup            装最新调试版、开无障碍、设默认助手、写入电脑上的模型服务
  python scripts/android/device_test.py cmd dump         发调试命令（dump / shot / probe / overlay / session / ask / act / stop）
  python scripts/android/device_test.py ask "这是什么？"  问一句，等答完把结果打出来（act 同理）
  python scripts/android/device_test.py chat "查一下…"     在对话页里问（不读屏幕；--show 打开对话页）
  python scripts/android/device_test.py setup --keep-assistant   同上，但不改手机的默认助手
  python scripts/android/device_test.py log [N]          看最近 N 条日志

结果都来自 App 的诊断日志 files/debug/log.jsonl（经 run-as 读，只有调试版能读）。
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADB = r"D:\Android\sdk\platform-tools\adb.exe"
# 要测 staging（R8 压缩过的正式包）就设 AIDE_PKG=io.github.typing233.superaide.staging
PKG = os.environ.get("AIDE_PKG", "io.github.typing233.superaide.debug")
APK = ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
A11Y = f"{PKG}/io.github.typing233.superaide.a11y.AideAccessibilityService"
ACTION = "io.github.typing233.superaide.DEBUG"


def adb(*args: str, check: bool = True, input: bytes | None = None) -> str:
    p = subprocess.run([ADB, *args], capture_output=True, input=input)
    out = p.stdout.decode("utf-8", "replace")
    if check and p.returncode != 0:
        raise SystemExit(f"adb {' '.join(args)} 失败：{p.stderr.decode('utf-8', 'replace').strip() or out.strip()}")
    return out


def log_lines() -> list[dict]:
    raw = adb("exec-out", "run-as", PKG, "cat", "files/debug/log.jsonl", check=False)
    out = []
    for line in raw.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def show(entries: list[dict]) -> None:
    for e in entries:
        t = time.strftime("%H:%M:%S", time.localtime(e["t"] / 1000))
        print(f"{t} {e['event']} {e.get('detail', '')}")


def broadcast(cmd: str, arg: str = "", extra: dict[str, str] | None = None) -> None:
    # adb shell 会把参数拼成一行交给手机上的 sh：带空格、引号的要先转义
    parts = ["am", "broadcast", "-a", ACTION, "-p", PKG, "--es", "cmd", cmd]
    if arg:
        parts += ["--es", "arg", arg]
    for k, v in (extra or {}).items():
        parts += ["--es", k, v]
    adb("shell", " ".join(shlex.quote(p) for p in parts))


def wait_for(event_prefix: str, before: int, timeout: float, settle: float = 0) -> list[dict]:
    """等日志里出现以 event_prefix 开头的新事件（before = 发命令前的日志条数；不比时间，手机和电脑的钟可能差几秒）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        new = log_lines()[before:]
        if any(e["event"].startswith(event_prefix) for e in new):
            time.sleep(settle)
            return log_lines()[before:]
        time.sleep(1)
    return log_lines()[before:]


def setup() -> None:
    print("安装", APK.name)
    adb("install", "-r", "-t", str(APK))
    # 无障碍自愈（被系统清理后自己加回去）要这个权限，只能由 adb 授予
    adb("shell", "pm", "grant", PKG, "android.permission.WRITE_SECURE_SETTINGS", check=False)
    current = adb("shell", "settings", "get", "secure", "enabled_accessibility_services").strip()
    services = [s for s in current.split(":") if s and s != "null"]
    if A11Y not in services:
        services.append(A11Y)
        adb("shell", "settings", "put", "secure", "enabled_accessibility_services", ":".join(services))
        adb("shell", "settings", "put", "secure", "accessibility_enabled", "1")
    if "--keep-assistant" not in sys.argv:
        role = adb("shell", "cmd", "role", "add-role-holder", "android.app.role.ASSISTANT", PKG, check=False)
        print("默认助手：", (role.strip() or "已设置"))
    adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1", check=False)
    time.sleep(2)
    extra = ["--deepseek"] if "--deepseek" in sys.argv else []
    subprocess.run([sys.executable, str(ROOT / "scripts" / "android" / "provision.py"), "--package", PKG, *extra], check=True)
    time.sleep(1)
    show([e for e in log_lines()[-8:]])


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    what = sys.argv[1]
    if what == "setup":
        setup()
    elif what == "log":
        show(log_lines()[-int(sys.argv[2]) if len(sys.argv) > 2 else -30:])
    elif what in ("ask", "act", "chat"):
        before = len(log_lines())
        broadcast(what, sys.argv[2], {"show": "1"} if "--show" in sys.argv else None)
        show(wait_for(f"debug.{what}.result", before, 600 if what == "chat" else 300))
    elif what == "cmd":
        before = len(log_lines())
        broadcast(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
        show(wait_for(f"debug.{sys.argv[2]}.", before, 120, settle=3)[-20:])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
