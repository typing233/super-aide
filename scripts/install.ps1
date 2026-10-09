# Super Aide 一键安装 / 更新（Windows 10、11，64 位）。再运行一次就是更新到当前代码。
#
#   双击仓库根目录的 install.cmd，或者：
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#
# 都装在你自己的用户目录里，不需要管理员权限：
#   1. 准备 uv（Python 环境管理工具）：没有就装，官方地址连不上时从国内 PyPI 镜像取。
#   2. 用 uv 装好 Python 3.12 和 Super Aide 自己的环境，依赖版本按 uv.lock 锁定；
#      官方源连不上或装失败，自动换国内镜像（阿里云 / 清华 PyPI，Python 本体用 npmmirror）。
#   3. 建开始菜单快捷方式，然后启动。第一次启动会先打开"准备"窗口：检查 Claude Code、Codex
#      （可选 DeepSeek Harness）装没装、模型配没配，缺的帮你装、帮你配好。
# 开发目录里的改动不会影响已安装的版本，直到你重新运行这个脚本。开机自启在 Super Aide 的设置里打开。

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Windows PowerShell 的下载进度条会让下载慢很多
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$repo = Split-Path -Parent $PSScriptRoot

$PypiMirrors = @('https://mirrors.aliyun.com/pypi/simple', 'https://pypi.tuna.tsinghua.edu.cn/simple')
$PythonMirror = 'https://registry.npmmirror.com/-/binary/python-build-standalone'
$UvHome = Join-Path $env:USERPROFILE '.local\bin'

function Say([string]$text) { Write-Host "==> $text" -ForegroundColor Cyan }

function Test-Url([string]$url) {
    try {
        Invoke-WebRequest -Uri $url -Method Head -TimeoutSec 6 -UseBasicParsing | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Add-UserPath([string]$dir) {
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    $parts = @($current -split ';' | Where-Object { $_ })
    if (-not ($parts | Where-Object { $_.TrimEnd('\') -ieq $dir.TrimEnd('\') })) {
        [Environment]::SetEnvironmentVariable('Path', (($parts + $dir) -join ';'), 'User')
    }
    if (-not (($env:Path -split ';') | Where-Object { $_.TrimEnd('\') -ieq $dir.TrimEnd('\') })) {
        $env:Path = "$env:Path;$dir"
    }
}

function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($candidate in @((Join-Path $UvHome 'uv.exe'), (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe'))) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

# 官方安装脚本要从 GitHub 下载，国内常常连不上：从 PyPI 镜像下载 uv 的 wheel（就是个 zip），取出 uv.exe
function Install-UvFromMirror {
    $platform = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'win_arm64' } else { 'win_amd64' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($index in $PypiMirrors) {
        try {
            $page = Invoke-WebRequest -Uri "$index/uv/" -UseBasicParsing -TimeoutSec 30
            $wheels = foreach ($link in $page.Links) {
                if ($link.href -match "uv-(\d+(?:\.\d+)+)-py3-none-$platform\.whl#sha256=([0-9a-f]{64})") {
                    [pscustomobject]@{ Version = [version]$Matches[1]; Href = $link.href.Split('#')[0]; Sha = $Matches[2] }
                }
            }
            $pick = $wheels | Sort-Object Version -Descending | Select-Object -First 1
            if (-not $pick) { continue }
            $url = ([Uri]::new([Uri]"$index/uv/", $pick.Href)).AbsoluteUri
            $wheel = Join-Path $env:TEMP "uv-$($pick.Version).whl"
            Invoke-WebRequest -Uri $url -OutFile $wheel -UseBasicParsing -TimeoutSec 300
            if ((Get-FileHash $wheel -Algorithm SHA256).Hash -ne $pick.Sha.ToUpper()) { throw '下载的文件校验不通过' }
            New-Item -ItemType Directory -Force $UvHome | Out-Null
            $zip = [IO.Compression.ZipFile]::OpenRead($wheel)
            try {
                $entry = $zip.Entries | Where-Object { $_.FullName -like '*/scripts/uv.exe' } | Select-Object -First 1
                if (-not $entry) { throw '包里没有 uv.exe' }
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $UvHome 'uv.exe'), $true)
            } finally {
                $zip.Dispose()
                Remove-Item $wheel -ErrorAction SilentlyContinue
            }
            Add-UserPath $UvHome
            return (Join-Path $UvHome 'uv.exe')
        } catch {
            Write-Host "    $index 没下载成功：$($_.Exception.Message)"
        }
    }
    return $null
}

if (-not [Environment]::Is64BitOperatingSystem) { throw 'Super Aide 需要 64 位的 Windows 10 或 11。' }

# 已经在运行的 Super Aide 会占着单实例锁，先让它退出
# 只认 Super Aide 自己的启动方式（python -m super_aide、super-aide.exe），不碰同一个虚拟环境里的其它 Python（比如编辑器插件）
$running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe' OR Name = 'super-aide.exe'" |
    Where-Object { $_.Name -eq 'super-aide.exe' -or $_.CommandLine -match '-m super_aide(\s|$)|super-aide\.exe' }
if ($running) {
    Say "先关掉正在运行的 Super Aide（$(@($running).Count) 个进程）"
    $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

# ---------- 1. uv ----------

$uv = Find-Uv
if (-not $uv) {
    Say '安装 uv（Python 环境管理工具）'
    if (Test-Url 'https://astral.sh/uv/install.ps1') {
        # 放在子进程里跑：官方脚本出错时会直接 exit，不能让它带走这个脚本
        powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
        $env:Path = "$env:Path;$UvHome"
        $uv = Find-Uv
    }
    if (-not $uv) {
        Say '官方地址没装上，改从国内 PyPI 镜像下载 uv'
        $uv = Install-UvFromMirror
    }
    if (-not $uv) { throw '没装上 uv。检查网络（或代理）后再运行一次，也可以先手动安装：https://docs.astral.sh/uv/' }
}
Write-Host "    uv：$uv"

# ---------- 2. Python 3.12 + Super Aide ----------

# 依赖版本按 uv.lock 锁定：别人装到的和这里测过的是同一套
$constraints = Join-Path $env:TEMP 'super-aide-constraints.txt'
& $uv export --project $repo --frozen --no-dev --no-hashes --no-emit-project --output-file $constraints --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host '    没能读取 uv.lock，按 pyproject.toml 里的版本范围安装'
    $constraints = $null
}

Say '检查下载源'
$pypiOk = Test-Url 'https://pypi.org/simple/'
$githubOk = Test-Url 'https://github.com/'
$attempts = @()
if ($pypiOk) { $attempts += , @('官方源', $null) }
foreach ($mirror in $PypiMirrors) { $attempts += , @("国内镜像 $(([Uri]$mirror).Host)", $mirror) }
if (-not $pypiOk) { $attempts += , @('官方源', $null) }  # 探不通也最后试一次（也许只是探测被拦了）
$env:UV_HTTP_TIMEOUT = '120'

$installed = $false
foreach ($attempt in $attempts) {
    $name, $index = $attempt
    # Python 本体默认从 GitHub 下载：连不上、或者已经在用国内镜像时，一起换成 npmmirror
    if ($githubOk -and -not $index) {
        [Environment]::SetEnvironmentVariable('UV_PYTHON_INSTALL_MIRROR', $null, 'Process')
    } else {
        $env:UV_PYTHON_INSTALL_MIRROR = $PythonMirror
    }
    Say "安装 Python 3.12 和 Super Aide（$name）"
    $uvArgs = @('tool', 'install', '--force', '--reinstall', '--python', '3.12')
    if ($constraints) { $uvArgs += @('--constraints', $constraints) }
    if ($index) { $uvArgs += @('--default-index', $index) }
    $uvArgs += $repo
    & $uv @uvArgs
    if ($LASTEXITCODE -eq 0) { $installed = $true; break }
    Write-Host "    $name 没装上，换下一个"
}
if ($constraints) { Remove-Item $constraints -ErrorAction SilentlyContinue }
if (-not $installed) { throw '安装失败：几个下载源都没装上。检查网络（或代理）后再运行一次。' }

# ---------- 3. 快捷方式，然后启动 ----------

$bin = (& $uv tool dir --bin).Trim()
$exe = Join-Path $bin 'super-aide.exe'
if (-not (Test-Path $exe)) { throw "没找到启动器：$exe" }
Add-UserPath $bin
$icon = Get-ChildItem (& $uv tool dir).Trim() -Recurse -Filter 'super_aide.ico' -ErrorAction SilentlyContinue |
    Select-Object -First 1

# 快捷方式按系统语言起名（和安装器一样）：中文系统叫"超级助手"，其它叫 "Super Aide"；另一个名字的旧快捷方式删掉
$programs = [Environment]::GetFolderPath('Programs')
$name = if ((Get-UICulture).TwoLetterISOLanguageName -eq 'zh') { '超级助手' } else { 'Super Aide' }
foreach ($old in @('超级助手.lnk', 'Super Aide.lnk')) {
    if ($old -ne "$name.lnk") { Remove-Item -LiteralPath (Join-Path $programs $old) -ErrorAction SilentlyContinue }
}
$link = Join-Path $programs "$name.lnk"
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = $env:USERPROFILE
$shortcut.Description = '超级助手（Super Aide）桌面助手'
if ($icon) { $shortcut.IconLocation = $icon.FullName }
$shortcut.Save()

Say '安装完成'
Write-Host "    启动器：$exe"
Write-Host "    开始菜单：$link"
Write-Host '    开机自启：在 Super Aide 的设置里打开。'

# 经资源管理器打开快捷方式：用的是一份干净的环境（刚加进 PATH 的目录也在），不带这个窗口里的临时变量
Start-Process explorer.exe -ArgumentList "`"$link`""
Write-Host '    已经启动。第一次启动会先打开"准备"窗口：检查并帮你装好、配好 Claude Code 和 Codex。'
