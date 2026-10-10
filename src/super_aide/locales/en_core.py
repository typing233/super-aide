"""英文对照：应用外壳（托盘、提示、设置窗口、准备窗口、安装和配置、更新、快捷键、推荐问题）。"""

EN = {
    # 托盘和提示
    "{app}已更新到 {version}": "{app} updated to {version}",
    "按 {ask} 问答，{act} 操作。右键托盘图标可以打开设置。":
        "Press {ask} to ask, {act} to act. Right-click the tray icon for settings.",
    "快捷键 {keys} 注册失败（可能被其它程序占用），可以在设置里换一个。":
        "Couldn't register hotkey {keys} (another app may be using it). You can pick another in Settings.",
    "{app}已经在运行": "{app} is already running",
    "{app}已在后台运行": "{app} is running in the background",
    "已被其它程序占用": "Already used by another app",
    "快捷键 {keys} 注册不上（可能被其它程序占用），还用原来的":
        "Couldn't register hotkey {keys} (another app may be using it); keeping the old one",
    "{spec}（{reason}）": "{spec} ({reason})",
    "、": ", ",
    "{app} · {ask} 问答 / {act} 操作": "{app} · {ask} ask / {act} act",
    "历史记录": "History",
    "设置": "Settings",
    "退出": "Quit",
    "问答": "Ask",
    "操作": "Act",
    "{app}历史记录": "{app} history",
    "{app}设置": "{app} settings",
    "没能设置开机自启：{error}": "Couldn't change autostart: {error}",
    "设置有误：{error}": "Invalid settings: {error}",
    "已按 Esc 停止": "Stopped with Esc",

    # 快捷键
    "快捷键不能为空": "The hotkey can't be empty",
    "需要至少一个修饰键（Ctrl / Alt / Shift / Win）": "Needs at least one modifier (Ctrl / Alt / Shift / Win)",
    "不认识的修饰键：{key}": "Unknown modifier: {key}",
    "不认识的按键：{key}": "Unknown key: {key}",

    # 准备窗口
    "准备{app}": "Set up {app}",
    "准备安装…": "Preparing to install…",
    "没能打开登录窗口：{error}": "Couldn't open the sign-in window: {error}",
    "没装上：{error}": "Didn't install: {error}",

    # 检测
    "还没配置模型": "No model set up yet",
    "自定义服务地址 {host}": "Custom endpoint {host}",
    "还没登录 DeepSeek 账号": "Not signed in to DeepSeek",
    "第三方云平台（Bedrock / Vertex / Foundry）": "Cloud provider (Bedrock / Vertex / Foundry)",
    "Claude 账号（长期令牌）": "Claude account (long-lived token)",
    "Claude 账号登录": "Signed in with a Claude account",
    "Anthropic Console 账号": "Anthropic Console account",
    "本地模型": "Local model",
    "配置里选的服务商 {provider} 没有定义": "The provider {provider} chosen in the config isn't defined",
    "{host} 的密钥（环境变量 {name}）没有设置": "The key for {host} (environment variable {name}) isn't set",
    "{host} 需要先登录": "{host} needs you to sign in first",
    "DeepSeek 账号登录": "Signed in with a DeepSeek account",
    "ChatGPT 账号登录": "Signed in with a ChatGPT account",

    # 安装 Claude Code / Codex
    "官方源": "the official registry",
    "国内镜像 npmmirror": "the npmmirror mirror (China)",
    "Node.js 官网": "nodejs.org",
    "正在挑一个连得上的下载源…": "Finding a download source that works…",
    "排队中，等前一个装完…": "Waiting for the previous one to finish…",
    "正在从{source}安装…": "Installing from {source}…",
    "{reason}，换{source}再装…": "{reason}; trying {source}…",
    "已安装 {version}": "Installed {version}",
    "装完了却找不到命令": "Installed, but the command can't be found",
    "没装上：{reason}": "Didn't install: {reason}",
    "没装上": "Didn't install",
    "安装超时": "The install timed out",
    "npm 运行不了（{error}）": "npm can't run ({error})",
    "原因不明": "Unknown reason",
    "它": "it",
    "连接超时": "Connection timed out",
    "连接被重置": "Connection was reset",
    "连接被拒绝": "Connection was refused",
    "找不到服务器": "Server not found",
    "域名解析失败": "DNS lookup failed",
    "证书有问题": "Certificate problem",
    "没有写入权限": "No write permission",
    "文件被占用（先关掉正在运行的 {}）": "A file is in use (close the running {} first)",
    "找到了 Node.js，但没有 npm": "Found Node.js, but npm is missing",
    "正在从{source}下载 Node.js（安装 Claude Code 和 Codex 需要）…":
        "Downloading Node.js from {source} (needed to install Claude Code and Codex)…",
    "正在下载 Node.js {version}…{percent}%": "Downloading Node.js {version}… {percent}%",
    "下载的文件校验不通过": "The download failed its checksum",
    "正在解压 Node.js…": "Unpacking Node.js…",
    "{source}没下载成功，换下一个…": "Download from {source} failed; trying the next one…",
    "没装上 Node.js（{reasons}）": "Couldn't install Node.js ({reasons})",
    "下载源都连不上": "no download source was reachable",
    "下载源里没有合适的 Node.js 版本": "No suitable Node.js version on the download source",
    "{path} 里已经有别的东西，没有覆盖": "{path} already contains something else; left it alone",

    # 配置模型
    "登录 {name}": "Sign in to {name}",
    "没找到 DeepSeek Harness": "DeepSeek Harness not found",
    "密钥不对（服务地址返回 {code}）": "Wrong key (the endpoint returned {code})",
    "连上了，但这个服务不支持列出模型，没法提前确认密钥":
        "Connected, but this service can't list models, so the key couldn't be checked in advance",
    "服务地址返回 {code}，请检查地址": "The endpoint returned {code}. Please check the address",
    "连不上这个地址（{reason}）": "Can't reach this address ({reason})",
    "连上了，但返回的不是模型列表，没法提前确认密钥":
        "Connected, but it didn't return a model list, so the key couldn't be checked in advance",
    "连接成功，找到 {n} 个模型": "Connected, found {n} models",
    "连接成功": "Connected",
    "请填写密钥": "Please enter the key",
    "连接成功，{model} 能用": "Connected, {model} works",
    "用 {model} 试了一下，服务报错：{reason}": "Tried {model}; the service returned an error: {reason}",
    "这个地址上没有对应的接口（返回 {code}），请检查地址":
        "No matching API at this address (it returned {code}). Please check the address",
    "用 {model} 试了 {seconds} 秒没有回应：这个服务可能没有这个模型，或者地址不对":
        "No response from {model} after {seconds} s: this service may not offer that model, or the address is wrong",
    "这个服务好像没有模型 {model}（返回 {code}：{detail}）":
        "This service doesn't seem to offer {model} (it returned {code}: {detail})",
    "服务地址返回 {code}：{detail}": "The endpoint returned {code}: {detail}",
    "{problem}。这个服务提供的有：{models}": "{problem}. This service offers: {models}",
    "这个服务没法列出模型：请在“模型”里填一个它提供的模型（看服务商的说明或请求示例），再点测试并保存":
        "This service can't list its models. Enter a model it offers under Model (see the provider's docs or request example), then click Test and save",
    "已保存 · {detail}": "Saved · {detail}",
    "；默认模型换成了 {model}（这个服务没有原来的 {old}）": "; the default model is now {model} (this service doesn't offer {old})",
    "；用的时候出错，再回来检查密钥": "; if it fails when used, come back and check the key",
    "没法自动修改 {path}（{error}），请手动配置": "Couldn't edit {path} automatically ({error}). Please set it up by hand",
    "Codex 没能保存 API Key（{error}）": "Codex couldn't save the API key ({error})",
    "{path} 不是有效的 JSON，没有改动它（{error}）": "{path} isn't valid JSON, so it wasn't changed ({error})",
    "{path} 的内容不是对象，没有改动它": "{path} doesn't contain an object, so it wasn't changed",

    # 更新
    "阿里云镜像": "Aliyun mirror",
    "连不上更新服务器（{reasons}）": "Can't reach the update servers ({reasons})",
    "GitHub 上最新发布的版本号看不懂：{tag}": "Can't read the version of the latest GitHub release: {tag}",
    "镜像里还没有超级助手": "Super Aide isn't on the mirror yet",
    "没找到安装器：请到发布页下载最新的 SuperAideSetup.exe 运行":
        "Installer not found: download the latest SuperAideSetup.exe from the releases page and run it",

    # 引擎出错（显示在回答卡片里）
    "引擎出错：{error}": "Engine error: {error}",
    "引擎认证失败，请检查 Claude Code / Codex 的登录或服务地址配置。":
        "Engine sign-in failed. Check the Claude Code / Codex login or endpoint settings.",
    "引擎被限流了，稍后再试。": "The engine is rate-limited. Try again later.",
    "引擎响应超时。": "The engine timed out.",
    "模型服务暂时不可用，稍后再试。": "The model service is temporarily unavailable. Try again later.",
    "已停止": "Stopped",
    "连不上模型服务，请检查网络或代理。": "Can't reach the model service. Check your network or proxy.",

    # 推荐问题（输入框里的提示）
    "这个报错是什么原因？": "What's causing this error?",
    "帮我修好它": "Fix it for me",
    "解释这段代码": "Explain this code",
    "帮我改好": "Fix it up for me",
    "翻译并解释": "Translate and explain",
    "翻译并替换成中文": "Translate and replace with English",
    "这是什么意思，该怎么选？": "What does this mean, and what should I pick?",
    "帮我按推荐设置好": "Set it up the recommended way",
    "这是什么？": "What is this?",
    "帮我处理": "Handle this for me",
    # 数据位置
    "选择数据位置": "Choose a data folder",
    "数据已经在这里了": "The data is already here",
    "新位置和现在的数据文件夹不能一个套着一个": "The new folder can't be inside the current data folder, or contain it",
    "这个文件夹写不进去：{error}": "Can't write to this folder: {error}",
    "{drive} 空间不够：要 {need}，只剩 {free}": "Not enough space on {drive}: needs {need}, only {free} free",
    "没能搬过去：{error}": "Couldn't move the data: {error}",
    "数据已经移到新位置": "Data moved to the new folder",
}
