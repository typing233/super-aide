---
name: network-proxy
description: 排查 Windows 上的网络和代理问题：网页打得开但命令行、pip、git、npm、conda、winget 连不上或超时，SSL 证书错误，代理软件（Clash 等）开着却不生效，某些网站打不开，国内网站反而变慢。
---

# 网络和代理

浏览器走系统代理，但很多命令行工具不读系统代理，只认环境变量或者自己的配置。这是"网页能开、命令行超时"最常见的原因。

## 1. 看现状

```powershell
# 系统代理（浏览器用的）
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' |
  Select-Object ProxyEnable, ProxyServer, ProxyOverride, AutoConfigURL
# WinHTTP 代理（winget 和部分系统服务用）
netsh winhttp show proxy
# 当前终端里的代理环境变量
Get-ChildItem env: | Where-Object Name -match 'proxy'
# 常见的代理端口有没有在监听
Get-NetTCPConnection -State Listen -LocalPort 7890, 7897, 10808, 10809, 1080 -ErrorAction SilentlyContinue
```

环境里的"系统"一行也写了系统代理的地址。

## 2. 测试

```powershell
curl.exe -I -m 10 https://www.google.com                                   # 直连
curl.exe -I -m 10 -x http://127.0.0.1:<端口> https://www.google.com        # 走代理
curl.exe -I -m 10 https://pypi.org/simple/
```

- 走代理能通、直连不通：工具没有走代理，按第 3 步配置。
- 两种都不通：是代理软件本身的问题，比如节点不可用、订阅过期、端口不对。

## 3. 让工具走代理

端口用第 1 步查到的。

- 只对当前终端生效：`$env:HTTP_PROXY='http://127.0.0.1:<端口>'; $env:HTTPS_PROXY=$env:HTTP_PROXY`
- 长期生效（用户级环境变量，之后新开的终端才生效）：
  - `[Environment]::SetEnvironmentVariable('HTTPS_PROXY', 'http://127.0.0.1:<端口>', 'User')`，HTTP_PROXY 同理；
  - 同时设 `NO_PROXY=localhost,127.0.0.1`。
- git：`git config --global http.proxy http://127.0.0.1:<端口>`（取消用 `git config --global --unset http.proxy`）
- pip：`python -m pip config set global.proxy http://127.0.0.1:<端口>`；或者换国内镜像 `python -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple`
- npm：`npm config set proxy http://127.0.0.1:<端口>` 和 `npm config set https-proxy http://127.0.0.1:<端口>`
- conda：`conda config --set proxy_servers.http http://127.0.0.1:<端口>`，https 同理
- winget 和系统服务：`netsh winhttp import proxy source=ie`。需要管理员权限；恢复用 `netsh winhttp reset proxy`。

## 4. 常见情况

- SSL 证书错误（CERTIFICATE_VERIFY_FAILED、self-signed certificate）：多半是代理软件开了抓包 / MITM，或者是公司网络。先关掉代理再试，确认是不是代理导致的。不要用关闭证书校验的办法来"解决"。
- 只有某个网站打不开：用 `nslookup <域名>` 看 DNS 解析；代理在规则模式下可能没有走代理，换成全局模式试一下。
- 国内服务反而变慢：代理规则让国内流量也走了代理。检查 NO_PROXY，或者代理软件的规则。

## 5. 汇报

说清楚改了哪些配置，以及每一项怎么撤销。

问答模式：只做第 1、2 步，给出要执行的配置命令。
