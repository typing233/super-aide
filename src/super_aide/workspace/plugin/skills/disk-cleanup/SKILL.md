---
name: disk-cleanup
description: 清理 Windows 磁盘空间：C 盘满了、空间不够、找出是什么占地方、安全地清理缓存和临时文件。
---

# 磁盘清理

原则：先找出是什么占地方，再只清理删了不影响任何东西的缓存。用户自己的文件只列出来，由用户决定。

## 1. 看清现状

```powershell
Get-PSDrive -PSProvider FileSystem |
  Select-Object Name, @{n='已用GB'; e={[math]::Round($_.Used / 1GB, 1)}}, @{n='可用GB'; e={[math]::Round($_.Free / 1GB, 1)}}
```

找大目录（只读，可能要几十秒）。先看用户目录：

```powershell
function Get-SizeGB($path) {
  [math]::Round(((Get-ChildItem $path -Recurse -Force -File -ErrorAction SilentlyContinue |
    Measure-Object Length -Sum).Sum) / 1GB, 2)
}
Get-ChildItem $env:USERPROFILE -Directory -Force -ErrorAction SilentlyContinue |
  ForEach-Object { [pscustomobject]@{ 目录 = $_.FullName; GB = Get-SizeGB $_.FullName } } |
  Sort-Object GB -Descending | Select-Object -First 15
```

常见的大户：

- `Downloads`；
- `AppData\Local`（浏览器和各种缓存）、`AppData\Local\Temp`；
- `C:\Windows\SoftwareDistribution\Download`（Windows 更新）；
- 虚拟机和 Docker 的磁盘文件（.vhdx）；
- `C:\hiberfil.sys`（休眠）和 `C:\pagefile.sys`（虚拟内存）；
- 微信、QQ 的聊天文件；
- 模型和数据集缓存：`.cache\huggingface`、`.cache\modelscope`。

## 2. 可以直接清的

操作模式下照做；每清一类，记下释放了多少。

- 用户临时文件：`Remove-Item "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue`（正在用的文件会跳过）
- 回收站：`Clear-RecycleBin -Force`（清之前告诉用户回收站里有多少）
- 包管理器的缓存：`python -m pip cache purge`、`uv cache clean`、`conda clean --all -y`、`npm cache clean --force`
- Windows 更新留下的旧组件（需要管理员）：`Dism.exe /Online /Cleanup-Image /StartComponentCleanup`
- Docker：`docker system prune`（会删掉停止的容器和没用的镜像，先说明）

## 3. 只列出来，让用户决定

- Downloads 里的大文件、旧安装包、视频、压缩包
- 模型缓存、数据集、虚拟机磁盘
- 微信、QQ 等聊天软件的文件（应该在软件自己的设置里清理）
- 不再使用的软件（卸载见 uninstall-software 技能）
- 关闭休眠能省下和内存差不多大的空间：`powercfg /hibernate off`（需要管理员，同时会关掉快速启动）

绝不删除：

- `C:\Windows`、`System32` 里的东西；`WinSxS` 只能用 DISM 清理；
- `Program Files` 里的东西（卸载软件除外）；
- 用户的文档和桌面上的文件。

## 4. 汇报

- 清理前后的可用空间对比；
- 删了哪些类别；
- 还可以考虑处理的大文件清单（路径和大小）。

问答模式：只做第 1 步，给出建议清理的清单。
