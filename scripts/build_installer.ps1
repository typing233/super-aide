# 编译安装器 SuperAideSetup.exe：用 Windows 自带的 .NET Framework 4.8 编译器，不用另装任何工具。
#
#   powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1 [-Repo 用户名/仓库名] [-Version 0.2.0] [-Out 输出路径]
#
# GitHub Actions 发版时也用它（-Repo 传当前仓库）。不传 -Repo 时从 git 的 origin 地址猜；猜不到就不带 GitHub，
# 安装器只从 PyPI（和国内镜像）下载 Super Aide。版本号默认取 pyproject.toml 里的。

param([string]$Repo = '', [string]$Version = '', [string]$Out = '')

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root 'installer'
if (-not $Out) { $Out = Join-Path $src 'out\SuperAideSetup.exe' }
if (-not $Version) {
    $Version = (Select-String -Path (Join-Path $root 'pyproject.toml') -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
}
if (-not $Repo -and (Get-Command git -ErrorAction SilentlyContinue)) {
    $ErrorActionPreference = 'Continue'  # 不是 git 仓库时 git 会往 stderr 写一句，Windows PowerShell 会把它当成错误
    $url = (git -C $root remote get-url origin 2>&1) | Out-String
    $ErrorActionPreference = 'Stop'
    if ($url -match 'github\.com[:/]([^/\s]+/[^/\s]+?)(\.git)?\s*$') { $Repo = $Matches[1] }
}

$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { throw "没找到 .NET Framework 4 的编译器：$csc" }
$framework = Split-Path -Parent $csc

$outDir = Split-Path -Parent $Out
New-Item -ItemType Directory -Force $outDir | Out-Null
$buildInfo = Join-Path $outDir 'BuildInfo.cs'
"namespace SuperAideSetup { static class BuildInfo { public const string Repo = `"$Repo`"; public const string Version = `"$Version`"; } }" |
    Set-Content -Path $buildInfo -Encoding UTF8

$references = 'System.dll', 'System.Core.dll', 'System.Drawing.dll', 'System.Windows.Forms.dll', 'System.Net.Http.dll',
    'System.IO.Compression.dll', 'System.IO.Compression.FileSystem.dll', 'System.Management.dll',
    'System.Web.Extensions.dll', 'Microsoft.CSharp.dll' | ForEach-Object { "/reference:$(Join-Path $framework $_)" }
$sources = @(Get-ChildItem (Join-Path $src '*.cs') | ForEach-Object { $_.FullName }) + $buildInfo

& $csc /nologo /noconfig /target:winexe /platform:anycpu /optimize+ /codepage:65001 /utf8output `
    "/out:$Out" "/win32icon:$(Join-Path $root 'src\super_aide\ui\super_aide.ico')" "/win32manifest:$(Join-Path $src 'app.manifest')" `
    @references @sources
if ($LASTEXITCODE -ne 0) { throw "编译失败（$LASTEXITCODE）" }

$size = [math]::Round((Get-Item $Out).Length / 1KB)
Write-Host "已生成：$Out（$size KB，版本 $Version，仓库 $(if ($Repo) { $Repo } else { '未设置：只从 PyPI 下载' })）"
