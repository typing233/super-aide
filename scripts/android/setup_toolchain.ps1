# 安卓构建工具链：JDK 21 + Android SDK + Gradle，装到一个目录里（默认 D:\Android），下载走本机代理。
# 不改系统环境变量；用的时候在命令前设 JAVA_HOME / ANDROID_HOME，或用 scripts\android\gradle.ps1。
param(
    [string]$Root = "D:\Android",
    [string]$Proxy = "http://127.0.0.1:7897",
    [string]$Platform = "android-37.0",
    [string]$BuildTools = "37.0.0",
    [string]$GradleVersion = "9.8.1"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
# curl.exe（schannel）经代理查不了证书吊销列表，所以下面都带 --ssl-no-revoke

$proxyUri = [Uri]$Proxy
$downloads = Join-Path $Root "downloads"
New-Item -ItemType Directory -Force $downloads | Out-Null

function Get-File($url, $name, $sha256 = "") {
    $path = Join-Path $downloads $name
    if (-not (Test-Path $path)) {
        Write-Host "下载 $name"
        & curl.exe --ssl-no-revoke -fL --retry 3 -x $Proxy -o "$path.part" $url
        if ($LASTEXITCODE -ne 0) { throw "下载失败：$url" }
        Move-Item -Force "$path.part" $path
    }
    if ($sha256) {
        $got = (Get-FileHash -Algorithm SHA256 $path).Hash.ToLower()
        if ($got -ne $sha256.ToLower()) { Remove-Item $path; throw "校验失败：$name" }
    }
    return $path
}

# 每个压缩包先解到自己的空目录，再挪到最终位置
function Expand-Fresh($zip, $target) {
    $tmp = Join-Path $Root ("_unpack_" + [IO.Path]::GetFileNameWithoutExtension($zip))
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand-Archive -Path $zip -DestinationPath $tmp
    $inner = Get-ChildItem $tmp
    $source = if ($inner.Count -eq 1 -and $inner[0].PSIsContainer) { $inner[0].FullName } else { $tmp }
    if (Test-Path $target) { Remove-Item -Recurse -Force $target }
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    Move-Item $source $target
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
}

# 1. JDK 21（Temurin），按 Adoptium 给的校验和核对
$jdk = Join-Path $Root "jdk"
if (-not (Test-Path (Join-Path $jdk "bin\java.exe"))) {
    $api = "https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=x64&image_type=jdk&os=windows&vendor=eclipse"
    $meta = (& curl.exe --ssl-no-revoke -fsSL -x $Proxy $api | ConvertFrom-Json)[0].binary.package
    $zip = Get-File $meta.link $meta.name $meta.checksum
    Expand-Fresh $zip $jdk
}
$env:JAVA_HOME = $jdk

# 2. Android 命令行工具 → sdk\cmdline-tools\latest
$sdk = Join-Path $Root "sdk"
$sdkmanager = Join-Path $sdk "cmdline-tools\latest\bin\sdkmanager.bat"
if (-not (Test-Path $sdkmanager)) {
    $xml = & curl.exe --ssl-no-revoke -fsSL -x $Proxy "https://dl.google.com/android/repository/repository2-3.xml"
    $name = ([regex]::Matches(($xml -join "`n"), 'commandlinetools-win-(\d+)_latest\.zip') |
        Sort-Object { [int]$_.Groups[1].Value } | Select-Object -Last 1).Value
    $zip = Get-File "https://dl.google.com/android/repository/$name" $name
    Expand-Fresh $zip (Join-Path $sdk "cmdline-tools\latest")
}

# 3. SDK 组件。新版命令行工具里 sdkmanager 已换成 android.exe（包名用 / 分隔，走系统代理）
$cli = Join-Path $sdk "cmdline-tools\latest\bin\android.exe"
if (Test-Path $cli) {
    & $cli --no-metrics "--sdk=$sdk" sdk install "platform-tools" "platforms/$Platform" "build-tools/$BuildTools"
} else {
    $proxyArgs = @("--proxy=http", "--proxy_host=$($proxyUri.Host)", "--proxy_port=$($proxyUri.Port)")
    ("y`n" * 20) | & $sdkmanager --sdk_root=$sdk @proxyArgs --licenses | Out-Null
    & $sdkmanager --sdk_root=$sdk @proxyArgs "platform-tools" "platforms;$Platform" "build-tools;$BuildTools"
}
if ($LASTEXITCODE -ne 0) { throw "SDK 组件安装失败" }
foreach ($need in @("platforms\$Platform", "build-tools\$BuildTools")) {
    if (-not (Test-Path (Join-Path $sdk $need))) { throw "没装上：$need" }
}

# 4. Gradle（只用来生成 wrapper；平时用仓库里的 gradlew）
$gradle = Join-Path $Root "gradle-$GradleVersion"
if (-not (Test-Path (Join-Path $gradle "bin\gradle.bat"))) {
    $zip = Get-File "https://services.gradle.org/distributions/gradle-$GradleVersion-bin.zip" "gradle-$GradleVersion-bin.zip"
    $sum = (& curl.exe --ssl-no-revoke -fsSL -x $Proxy "https://services.gradle.org/distributions/gradle-$GradleVersion-bin.zip.sha256").Trim()
    if ((Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower() -ne $sum.ToLower()) { Remove-Item $zip; throw "Gradle 校验失败" }
    Expand-Fresh $zip $gradle
}

# 5. Gradle 走代理（用户级配置；已有就不动）
$gradleProps = Join-Path $HOME ".gradle\gradle.properties"
if (-not (Test-Path $gradleProps)) {
    New-Item -ItemType Directory -Force (Split-Path $gradleProps) | Out-Null
    @(
        "systemProp.http.proxyHost=$($proxyUri.Host)",
        "systemProp.http.proxyPort=$($proxyUri.Port)",
        "systemProp.https.proxyHost=$($proxyUri.Host)",
        "systemProp.https.proxyPort=$($proxyUri.Port)",
        "systemProp.http.nonProxyHosts=localhost|127.*|[::1]"
    ) | Set-Content -Encoding ascii $gradleProps
}

Write-Host ""
Write-Host "装好了：JAVA_HOME=$jdk  ANDROID_HOME=$sdk  Gradle=$gradle"
& (Join-Path $sdk "platform-tools\adb.exe") version
