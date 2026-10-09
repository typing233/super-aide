"""用当前代码实际跑一遍：典型任务路由给谁、典型命令拦不拦。"""

from super_aide import paths  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
paths.ROUTER = Path(tempfile.mkdtemp(prefix="aide-router-"))  # 测试不写你真实的路由学习记录（2026-10-08 曾经写进去过）
from super_aide.config import Config
from super_aide.router import EngineRouter, Task
from super_aide.safety import blocked_reason, is_read_only

router = EngineRouter(Config())
print("=== 路由 ===")
cases = [
    ("ask", "这个报错是什么原因？", "error", "chrome.exe"),
    ("ask", "帮我写一段回复", "text", "Feishu.exe"),
    ("act", "帮我修好它", "error", "Code.exe"),
    ("act", "帮我修好它", "error", "chrome.exe"),
    ("act", "帮我把这个单元格改好再运行", "error", "chrome.exe"),
    ("act", "帮我卸载这个软件", "text", "explorer.exe"),
    ("act", "帮我按推荐设置好", "dialog", "SystemSettings.exe"),
    ("act", "帮我把深色模式打开", "text", "SystemSettings.exe"),
    ("act", "帮我清理一下 C 盘", "text", "explorer.exe"),
]
for mode, q, kind, fg in cases:
    d = router.decide(Task(mode, q, kind, fg))
    caps = [c for c in d.capabilities if c in ("gui_control", "browser_control")]
    print(f"{mode:<4} {fg:<20} {q:<16} → {d.engine:<6} {d.model:<16} 思考 {d.effort:<6} 需要 {caps or '-'}")

print("\n=== 拦截（操作模式）===")
for cmd in [
    "winget uninstall --id Foo.Bar", "msiexec /x {GUID} /qn", "Stop-Process -Name foo -Force",
    "Remove-Item -Recurse C:\\work\\build", "reg delete HKCU\\Software\\Foo /f",
    "reg delete HKLM\\SOFTWARE\\Vendor\\App /f", "pip install pandas", "Get-Volume",
    "bcdedit /enum", "bcdedit /set {current} safeboot minimal", "diskpart",
    "Format-Volume -DriveLetter D", "Remove-Item -Recurse -Force C:\\", "del temp.txt; Get-ChildItem C:\\",
    "Set-MpPreference -DisableRealtimeMonitoring $true", "netsh advfirewall set allprofiles state off",
    "wevtutil cl System", "Remove-Item \"$env:LOCALAPPDATA\\Google\\Chrome\\User Data\\Default\\Web Data\"",
]:
    print(f"{'⛔ ' + blocked_reason(cmd) if blocked_reason(cmd) else '✓ 放行':<28} {cmd}")

print("\n=== 问答模式的只读判断 ===")
for cmd in ["Get-Process", "winget list", "Get-WinEvent -LogName System -MaxEvents 20",
            "python -c \"import pandas\"", "pip show pandas", "curl https://example.com",
            "Test-NetConnection pypi.org -Port 443", "where.exe python", "conda env list"]:
    print(f"{'✓ 可以运行' if is_read_only(cmd) else '✗ 会被拒绝':<10} {cmd}")
