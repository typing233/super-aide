"""英文对照：引擎层（回答卡片上的进度行、出错提示，设置里的浏览器操作状态和模型列表报错）。"""

EN = {
    # 进度行：看界面、动界面（computer.status，三个引擎共用）
    "正在看「{window}」…": "Looking at “{window}”…",
    "正在看窗口…": "Looking at the window…",
    "正在按 {keys}": "Pressing {keys}",
    "正在选择「{target}」": "Selecting “{target}”",
    "正在等「{target}」出现": "Waiting for “{target}” to appear",
    "正在等「{target}」消失": "Waiting for “{target}” to go away",
    "正在点击": "Clicking",
    "正在双击": "Double-clicking",
    "正在右键点击": "Right-clicking",
    "正在移动鼠标": "Moving the mouse",
    "正在输入": "Typing",
    "正在滚动": "Scrolling",
    "正在拖动": "Dragging",
    "正在勾选": "Toggling",
    "正在切换窗口": "Switching windows",
    "正在等待": "Waiting",
    "正在操作界面": "Working on screen",
    "{action}（共 {count} 步）…": "{action} ({count} steps)…",
    "正在打开 {url}…": "Opening {url}…",
    "正在操作浏览器…": "Working in the browser…",
    "正在找「{target}」…": "Looking for “{target}”…",
    "正在放大看细节…": "Zooming in for a closer look…",
    "正在读窗口里的文字…": "Reading the text in the window…",
    "正在查看打开的窗口…": "Checking the open windows…",
    "正在屏幕上圈出位置…": "Highlighting the spot on screen…",
    "正在操作界面…": "Working on screen…",
    "正在思考…": "Thinking…",

    # 进度行：其它工具（Claude、Codex、DeepSeek Harness）
    "正在运行 {command}": "Running {command}…",
    "正在搜索 {query}": "Searching the web for {query}…",
    "正在读 {name}": "Reading {name}…",
    "正在修改 {name}": "Editing {name}…",
    "正在查找文件…": "Searching files…",
    "正在打开网页…": "Opening a web page…",
    "正在使用 {name}…": "Using {name}…",
    "交给 Codex 操作界面…": "Handing the on-screen steps to Codex…",
    "正在回想以前的经验…": "Recalling past lessons…",

    # 中枢
    "想起以前的经验：{title}": "Recalled a past lesson: {title}",
    "上一轮没办成，这次加强：{model} · {effort}": "Last try didn't work, stepping up to {model} · {effort}",
    "{error} 换一个引擎接着做…": "Switching to another engine… ({error})",
    "{engine} {reason}，换 {other} 接着做…": "{engine} {reason}; switching to {other}…",
    "{model} {reason}，换 {other} 接着做…": "{model} {reason}; switching to {other}…",
    "用不了": "isn't available",
    "被限流了": "is rate-limited",
    "认证失败": "couldn't sign in",
    "服务暂时不可用": "is temporarily unavailable",
    "响应超时": "timed out",
    "连不上": "can't be reached",
    "出错了": "ran into an error",
    "这个对话已经结束，请重新提问。": "This conversation has ended. Please ask again.",
    "引擎没给出结果就断开了": "The engine disconnected without a result",
    "没有可用的模型": "No model is available",
    "{engine}：{error}": "{engine}: {error}",  # 设置里刷新模型列表时的报错

    # 引擎出错
    "Codex 出错": "Codex ran into an error",
    "没找到 DeepSeek Harness": "DeepSeek Harness not found",
    "DeepSeek Harness 退出了": "DeepSeek Harness stopped running",
    "DeepSeek Harness 退出了：{detail}": "DeepSeek Harness stopped running: {detail}",
    "回答太长被截断了": "The answer was too long and got cut off",

    # 浏览器操作没接通（设置页、回答卡片上的修法）。设置页会去掉开头的 "Browser control isn't connected yet: "
    "在 Codex 应用的插件页里安装「Chrome」插件（用 ChatGPT 控制浏览器，Edge 也支持）":
        "Install the “Chrome” plugin from the Plugins page in the Codex app (it lets ChatGPT control your browser; "
        "Edge works too)",
    "浏览器操作还没接通：{fix}。": "Browser control isn't connected yet: {fix}.",
    "浏览器操作还没接通：{browser} 里没装 ChatGPT 扩展，按 Codex 应用里 Chrome 插件的提示装上。":
        "Browser control isn't connected yet: The ChatGPT extension isn't installed in {browser}. "
        "Install it by following the Chrome plugin's prompts in the Codex app.",
}
