"""英文对照：自我改进（托盘、系统通知、设置里的状态）和社区共建。"""

EN = {
    # 系统通知
    "超级助手开始自我改进": "Super Aide is improving itself",
    "期间请不要关机，尽量保持联网；可以照常使用。进度在托盘菜单里。":
        "Please keep your PC on and online meanwhile. You can keep using it as usual; progress is in the tray menu.",
    "自我改进好了：{title}": "Self-improvement ready: {title}",
    "测试和复核都通过了。点这里看看改了什么，确认后点「生效」（会重启超级助手，几秒钟）。":
        "Tests and review passed. Click here to see what changed, then click Apply (Super Aide restarts in a few seconds).",
    "已完成自我改进": "Self-improvement applied",
    "{title}（已更新到 {version}）": "{title} (now on {version})",
    "这次改进没能启动": "The improved version didn't start",
    "已经装回原来的版本：{title}": "Restored the previous version: {title}",
    "已撤销改进": "Improvement undone",

    # 托盘
    "正在自我改进 · 先看看是不是助手的问题": "Improving itself · checking whether it's the assistant's fault",
    "正在自我改进 · 正在准备": "Improving itself · preparing",
    "正在自我改进 · 正在分析和修改": "Improving itself · analyzing and changing code",
    "正在把本地改进移到新版本": "Carrying local improvements over to the new version",
    "正在自我改进 · 正在跑测试": "Improving itself · running tests",
    "正在自我改进 · 正在复核": "Improving itself · reviewing",
    "正在自我改进 · 正在打包": "Improving itself · packaging",
    "自我改进 · 等网络恢复": "Self-improvement · waiting for the network",
    "自我改进 · 需要登录或配置": "Self-improvement · needs sign-in or setup",
    "自我改进好了 · 点这里确认生效": "Self-improvement ready · click to apply",
    "自我改进 · 正在生效": "Self-improvement · applying",

    # 进度和原因
    "正在准备测试环境": "Preparing the test environment",
    "正在跑一遍现有的测试": "Running the existing tests",
    "正在跑测试": "Running tests",
    "正在检查每个模块能不能导入": "Checking that every module imports",
    "正在复核改动": "Reviewing the change",
    "正在打包": "Packaging",
    "卡住了，稍后续上": "Stuck; will resume shortly",
    "网络断了": "The network dropped",
    "需要登录": "Sign-in needed",
    "没有给出结论": "No conclusion was given",
    "没能修好": "Couldn't fix it",
    "检查没通过：{problems}": "Checks failed: {problems}",
    "复核没通过：{problems}": "Review failed: {problems}",
    "装测试工具失败：{error}": "Couldn't install the test tools: {error}",
    "现有的测试没跑起来：{error}": "The existing tests didn't run: {error}",
    "自我改进需要 Claude Code 或 Codex": "Self-improvement needs Claude Code or Codex",
    "新版本已经包含了全部本地改进": "The new version already includes all local improvements",
    "把本地改进移到 {version}": "Carry local improvements to {version}",
    "把 {n} 项本地改进移到 {version}": "Carry {n} local improvements to {version}",
    "从源码运行，没有自动生效：改动在 {path}": "Running from source, so not applied: the change is in {path}",

    # 设置里的操作
    "没有待生效的改进": "No improvement is waiting to be applied",
    "只能撤销最近一次改进": "Only the latest improvement can be undone",
    "从源码运行时不能自动换包：用 install.cmd 重新安装": "Can't swap packages when running from source: reinstall with install.cmd",
    "找不到要装的包": "The package to install is missing",
    "没能开始：{error}": "Couldn't start: {error}",
    "先写下你的建议": "Write your suggestion first",
    "没有登录 GitHub": "Not signed in to GitHub",
}
