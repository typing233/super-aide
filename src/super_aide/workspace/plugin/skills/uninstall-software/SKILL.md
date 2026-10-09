---
name: uninstall-software
description: 在 Windows 上彻底、正确地卸载软件并清理残留。用户要卸载、删除、移除某个软件，问怎么卸载干净，或者卸载失败、控制面板里删不掉时使用。
---

# 卸载软件

目标：只卸掉用户说的那个软件，卸干净，并说清楚删了什么。

## 1. 找准对象

先列出候选，核对名称、发布者、版本。同名的有好几个时：问答模式里问清楚；操作模式里选最匹配的，并在汇报里说明选了哪个。

```powershell
# winget 能管理的（大多数 Win32 软件和商店应用）
winget list --name "关键词"

# 注册表里的卸载信息（64 位、32 位、当前用户三处）
$keys = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
Get-ItemProperty $keys -ErrorAction SilentlyContinue |
  Where-Object DisplayName -like '*关键词*' |
  Select-Object DisplayName, DisplayVersion, Publisher, InstallLocation, UninstallString, QuietUninstallString, PSChildName

# 商店（UWP）应用
Get-AppxPackage *关键词* | Select-Object Name, PackageFullName, Publisher
```

## 2. 卸载（按顺序选第一个可行的）

先结束这个软件正在运行的进程（`Get-Process <名字> -ErrorAction SilentlyContinue | Stop-Process`），否则卸载程序可能失败或要求重启。

1. winget：`winget uninstall --id <Id> --exact --silent --accept-source-agreements`。用 `winget list` 里的 Id，不用名字，避免误伤同名软件。
2. MSI 安装的（PSChildName 是 `{GUID}` 形式）：`Start-Process msiexec -ArgumentList '/x {GUID} /qn /norestart' -Wait -PassThru`，看返回码：0 成功，3010 成功但需要重启，1605 本来就没装，1603 多半是权限不够。
3. 有 QuietUninstallString 的：照它执行。
4. 只有 UninstallString 的：常见的静默参数是 NSIS `/S`、Inno Setup `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`、InstallShield `-s`。不确定时运行不带参数的卸载程序，再用 Computer Use 在界面上点完。
5. 商店应用：`Get-AppxPackage <Name> | Remove-AppxPackage`。

需要管理员权限时（拒绝访问、1603），用 `Start-Process <程序> -ArgumentList '<参数>' -Verb RunAs -Wait`。系统会弹出确认框，告诉用户点"是"。

## 3. 验证和清理残留

- 再查一遍第 1 步的几处，确认条目已经没了。
- 只清理明确属于这个软件的残留：
  - 安装目录（InstallLocation）；
  - `%AppData%`、`%LocalAppData%`、`%ProgramData%` 下以软件或厂商命名的文件夹；
  - 开始菜单和桌面的快捷方式；
  - 同名的服务（`Get-Service`）和计划任务（`Get-ScheduledTask`）。
- 用户数据（文档、存档、配置）删之前要说明是什么。厂商目录下还有别的软件时，只删这个软件的子目录。
- 注册表只删 `HKCU\Software\<厂商>\<软件>` 这类明确的键，不做批量的注册表清理。

## 4. 汇报

一行结果，加上清理了哪些残留、需不需要重启。卸载一般没法撤销，提醒一句"以后要用需要重新安装"。

问答模式：只做第 1 步的只读查询，然后给出适合这个软件的卸载步骤。
