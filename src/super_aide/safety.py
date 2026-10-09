"""命令安全判断，两个引擎共用（设计第 8、11 节）。

- is_read_only()：问答模式下哪些命令可以跑（只读诊断）。白名单做法，宁可误拒。
- blocked_reason()：操作模式全放行时，静默拦截的灾难性操作。命中就拦下，不弹窗。
"""

from __future__ import annotations

import re

# ---------------- 问答模式：只读命令 ----------------

_SPLIT = re.compile(r"\|\||&&|[|;\n&]")
_REDIRECT = re.compile(r"(?<![0-9])>{1,2}(?!\s*\$null)|\bOut-File\b|\bTee-Object\b|\bSet-Content\b|\bAdd-Content\b",
                       re.IGNORECASE)
_READ_VERBS = ("get-", "test-", "select-", "where-", "measure-", "format-", "sort-", "group-",
               "compare-", "convertto-", "convertfrom-", "resolve-", "split-path", "join-path",
               "out-string", "out-host", "write-output", "write-host", "foreach-object")
_READ_COMMANDS = {
    "dir", "ls", "gci", "gc", "cat", "type", "echo", "where", "where.exe", "whoami", "hostname",
    "ipconfig", "systeminfo", "tasklist", "netstat", "ping", "tracert", "nslookup", "getmac",
    "driverquery", "findstr", "tree", "more", "sort", "fc", "ver", "%", "?", "select", "sls",
    "pwd", "cd", "set-location",
}
# 这些命令只有特定子命令是只读的
_READ_SUBCOMMANDS = {
    "git": {"status", "log", "diff", "show", "branch", "remote", "rev-parse", "describe", "config"},
    "winget": {"list", "show", "search", "--version", "--info"},
    "pip": {"list", "show", "freeze", "--version", "check"},
    "pip3": {"list", "show", "freeze", "--version", "check"},
    "conda": {"list", "info", "--version", "env"},
    "npm": {"ls", "list", "--version", "-v", "view", "config"},
    "node": {"--version", "-v"},
    "python": {"--version", "-v", "-V"},
    "py": {"--version", "-0", "-0p", "-V"},
    "dotnet": {"--info", "--list-sdks", "--list-runtimes", "--version"},
    "java": {"-version", "--version"},
    "uv": {"--version", "pip"},
    "reg": {"query"},
    "sc": {"query", "qc", "queryex"},
    "schtasks": {"/query"},
    "netsh": {"interface", "wlan", "winhttp"},  # 下面还要求出现 show
    "wmic": set(),  # 必须带 get
    "jupyter": {"--version", "kernelspec", "server", "notebook"},
}
_NETSH_SHOW = re.compile(r"\bshow\b", re.IGNORECASE)


def _first_word(segment: str) -> tuple[str, list[str]]:
    words = segment.strip().split()
    if not words:
        return "", []
    head = words[0].strip("&'\"").lower()
    if head.endswith(".exe"):
        head = head[:-4] if head[:-4] in _READ_SUBCOMMANDS else head
    return head, [w.lower() for w in words[1:]]


def _segment_read_only(segment: str) -> bool:
    head, rest = _first_word(segment)
    if not head:
        return True
    if head.startswith(_READ_VERBS) or head in _READ_COMMANDS:
        return True
    if head in _READ_SUBCOMMANDS:
        if head == "wmic":
            return "get" in rest and not {"call", "delete", "set", "create"} & set(rest)
        allowed = _READ_SUBCOMMANDS[head]
        if not rest or rest[0] not in allowed:
            return False
        if head == "netsh":
            return bool(_NETSH_SHOW.search(segment))
        if head == "conda" and rest[0] == "env":
            return len(rest) > 1 and rest[1] == "list"
        if head == "uv" and rest[0] == "pip":
            return len(rest) > 1 and rest[1] in {"list", "show", "freeze"}
        if head == "git" and rest[0] in {"branch", "remote", "config"}:
            return not {"-d", "-D", "-m", "--delete", "add", "remove", "set-url", "--unset", "--global"} & set(rest[1:])
        return True
    return False


def is_read_only(command: str) -> bool:
    if not command or _REDIRECT.search(command):
        return False
    if re.search(r"\$\(|`|\binvoke-expression\b|\biex\b|-encodedcommand", command, re.IGNORECASE):
        return False
    return all(_segment_read_only(s) for s in _SPLIT.split(command))


# ---------------- 操作模式：静默拦截的灾难性操作 ----------------

_BLOCKLIST: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bformat(\.com)?\s+[a-z]:", re.I), "格式化磁盘"),
    (re.compile(r"\b(Format-Volume|Clear-Disk|Initialize-Disk|Remove-Partition)\b", re.I), "格式化或清除磁盘/分区"),
    (re.compile(r"\bdiskpart\b", re.I), "磁盘分区工具"),
    (re.compile(r"\bbcdedit\b|\bbcdboot\b", re.I), "修改启动配置"),
    (re.compile(r"\bcipher\s+/w\b", re.I), "擦除磁盘空闲空间"),
    (re.compile(r"\b(vssadmin|wbadmin)\s+delete\b", re.I), "删除系统备份/还原点"),
    (re.compile(r"Set-MpPreference\b.*-Disable\w*\s+(\$true|1)", re.I), "关闭 Windows Defender"),
    (re.compile(r"\b(sc|sc\.exe)\s+(stop|config|delete)\s+(WinDefend|MpsSvc|wscsvc)\b", re.I), "停用安全服务"),
    (re.compile(r"\bnetsh\s+advfirewall\s+set\s+\w+\s+state\s+off\b", re.I), "关闭防火墙"),
    (re.compile(r"Set-NetFirewallProfile\b.*-Enabled\s+(False|\$false|0)", re.I), "关闭防火墙"),
    (re.compile(r"(Remove-Item|\brm\b|\bdel\b|\berase\b|\brd\b|\brmdir\b)[^\n]*"
                r"(\s|['\"])([a-z]:\\?(['\"]|\s|$)|[a-z]:\\(windows|users|program files[^\\]*)\\?(['\"]|\s|$)"
                r"|\$env:(systemroot|windir|userprofile|programfiles)\\?(['\"]|\s|$)|~\\?(['\"]|\s|$))", re.I),
     "删除磁盘根目录、系统目录或整个用户目录"),
    (re.compile(r"\breg(\.exe)?\s+delete\s+\"?(HKLM|HKEY_LOCAL_MACHINE)\\(SYSTEM|SOFTWARE)\\?\"?(\s|$)", re.I),
     "删除注册表根键"),
    (re.compile(r"Login Data|Web Data|logins\.json|key4\.db|\bvaultcmd\b.*\/list", re.I), "读取或导出浏览器保存的密码"),
    (re.compile(r"\bmimikatz\b|sekurlsa", re.I), "凭据窃取工具"),
    (re.compile(r"\bwevtutil\s+(cl|clear-log)\b|Clear-EventLog\b", re.I), "清除系统日志"),
    (re.compile(r"SUPER_AIDE_CANARY_BLOCK"), "拦截清单自检暗号"),
]


def blocked_reason(command: str) -> str | None:
    """命中拦截清单时返回原因（中文），否则返回 None。"""
    for pattern, reason in _BLOCKLIST:
        if pattern.search(command or ""):
            return reason
    return None
