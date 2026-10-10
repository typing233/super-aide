<div align="center">

<a href="https://typing233.github.io/super-aide/"><img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/logo.png" width="88" height="88" alt="超级助手"></a>

# 超级助手（Super Aide）

**按一个键，说一句话，就办好。**

看得见屏幕的 Windows 助手：屏幕上的东西直接问，或者让它直接动手。<br>
背后调度 **Claude Code** 和 **Codex**，从每次任务里学习，越用越好——对你如此，对所有人也是。

[English](README.md) · **简体中文**

[![最新版本](https://img.shields.io/github/v/release/typing233/super-aide?label=release&color=5B8CFF)](https://github.com/typing233/super-aide/releases/latest)
[![MIT 许可证](https://img.shields.io/badge/license-MIT-9B6BFF)](https://github.com/typing233/super-aide/blob/main/LICENSE)
[![Windows 10 | 11](https://img.shields.io/badge/Windows-10%20%7C%2011-555)](#安装)

**[官网](https://typing233.github.io/super-aide/?lang=zh)** · **[下载 Windows 版](https://github.com/typing233/super-aide/releases/latest/download/SuperAideSetup.exe)**（约 100 KB）

</div>

https://github.com/user-attachments/assets/3c84873e-12d7-41b2-b592-83ed046d6131

## 能做什么

### 看得见你的屏幕

提问的那一刻，所有窗口的文字它都逐字读到（包括滚动出去的部分），再加上截图和你框选的区域。你不用描述背景，也不用复制粘贴。

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/see-zh.webp" width="100%" alt="超级助手逐字读到每个窗口的文字，包括笔记里滚动出去的部分">

### 问答 · `Alt+Q`：一句话，它把前后都串起来

回答会把各个窗口里的东西串起来——终端里的报错、聊天里的截止时间、笔记里的步骤——结论先说。问答模式只读：可以读文件、跑只读的诊断命令，不会动你的电脑。

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/ask-zh.webp" width="100%" alt="一句回答串起三个窗口：终端里的报错、笔记里的一行、聊天里的截止时间">

### 操作 · `Alt+W`：它直接动手

命令行、文件、桌面软件、网页都行。点一下操作胶囊能看到每一步；做完汇报改了什么、怎么撤销。随时按 `Esc` 停下；它干活的时候，你照常用电脑。

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/act-zh.webp" width="100%" alt="展开的操作胶囊里能看到助手正在做的每一步">

### 告诉你点哪里

想自己来？它在屏幕上把要点的地方按顺序圈出来、标上编号。分步骤的回答会贴到屏幕边上，方便边看边做。

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/guide-zh.webp" width="100%" alt="打印对话框上的编号标记：先选“另存为 PDF”，再点保存">

### 中文 / English

界面跟随系统语言，也可以在设置里切换；你用什么语言问，它就用什么语言答。

## 而且越用越好——对你如此，对所有人也是

### 会学习的路由：先挑最好的，再学着省钱

每次自动挑引擎（Claude Code、Codex，也可以用 DeepSeek Harness）、模型和思考强度，你不用选。每一次结果都在教它：你的 👍 👎、追问、失败。你空下来的时候，它还会用更省的配置把一些问题在后台再答一遍，由强模型来评；要有 90% 把握成功率不降才会换。某一轮没办成，下一轮自动换更强的配置。

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/learn-zh.webp" width="100%" alt="学习信号流进路由，后台对比在比较现在用的配置和更省的配置">
<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/gate-zh.webp" width="80%" alt="成功率一直不降，每证明一次更省的配置，每次的花费就降一档">

### 同一个坑，不踩第二次

走了弯路的任务，它会总结出真正管用的做法。相似的经验合并成一条，总是不管用的会被淘汰，不会越堆越多。只有情况对得上时才想起来（看报错、关键词，也用本地小模型看意思），一次最多两条；说一句"你好"，一条也不带。

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/lesson-zh.webp" width="100%" alt="一段走了弯路的对话，总结成一条经验">
<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/recall-zh.webp" width="100%" alt="几天后换个说法问，只想起那一条经验">

### 会自己改进，由你来塑造

任务没办成、你按 `Esc` 停下并说是它的问题、点了 👎，或者你在设置里提了建议，它会用 Claude Code（Opus 5.5 · max）分析原因、改进自己的代码，测试和复核都通过后请你确认生效，随时可以撤销。你用的这一份，会按你的习惯改变——软件开始按用它的人改变自己。

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/improve-zh.webp" width="70%" alt="自我改进面板：找到原因、改好代码、测试和复核都通过、已生效">
<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/personal-zh.webp" width="100%" alt="按“回答再短一点”的建议改进前后的对比">

### 一人修好，人人受益

愿意的话（设置 → 高级 → 参与社区共建），稳定运行一天的改进会以你的 GitHub 账号提交 PR——只有代码，提交前做隐私检查，不带你屏幕上的任何内容。维护者审核合并后，下次更新就到了每个人手里。这已经在发生：0.3.0 里就有超级助手按一位用户的建议改进自己的代码。用的人越多，它越好用。

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/community-zh.webp" width="80%" alt="合进主版本的改进，推送到每一位用户">

## 安装

需要 Windows 10（1809 以上）或 Windows 11，64 位。

1. 到[官网](https://typing233.github.io/super-aide/?lang=zh)或 [Releases](https://github.com/typing233/super-aide/releases/latest) 下载 **`SuperAideSetup.exe`**（约 100 KB）。
2. 双击运行，点"安装"。它会下载、检查、装好运行环境（第一次约 600 MB，要几分钟；官方源连不上时自动换国内镜像），装好后自动打开超级助手。不需要管理员权限。

> 安装器还没有代码签名，Windows 可能提示"Windows 已保护你的电脑"：点 **更多信息 → 仍要运行**。

装好以后它就是一个普通应用：从开始菜单打开，在"设置 → 应用"里卸载。

**从源码安装**（开发者）：`git clone` 后双击仓库根目录的 `install.cmd`（或运行 `powershell -ExecutionPolicy Bypass -File scripts\install.ps1`）。用的是同一套运行环境，同样会自动换镜像。

## 第一次打开：准备窗口

超级助手直接用 Claude Code、Codex 自己的模型配置，所以开始之前会先检查它们装好、配好了没有：

| 情况 | 准备窗口怎么做 |
|---|---|
| Claude Code、Codex 有没装的，电脑里有 DeepSeek Harness | 问你要不要装（装了效果更好）。不装也能用，先靠 DeepSeek Harness |
| 有没装的，也没有 DeepSeek Harness | 直接自动装：官方 npm 包，官方源不通就换国内镜像（npmmirror）；没有 Node.js 22 以上时，先装一个便携版 Node.js |
| 装好了但没配模型 | 二选一：**用账号登录**（弹出登录窗口，在浏览器里登录，登好自动显示）；**自定义服务地址**（填地址、密钥，可以填模型，先测一下连得上再保存） |
| 都装好、配好了 | 不打扰，直接启动 |

至少有一个引擎能用了才能点"开始使用"；没配的以后再配也行。之后在 **设置 → 通用 → 环境检查** 里随时能再打开。

自定义服务地址会写进各工具自己的配置（改之前各留一份 `*.super-aide.bak`，别的设置和注释原样保留）：

| 工具 | 写到哪 |
|---|---|
| Claude Code | `~/.claude/settings.json` 的 `env`：`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`（官方 API 用 `ANTHROPIC_API_KEY`） |
| Codex | `~/.codex/config.toml` 加服务商 `model_providers.super_aide`，密钥也写在里面（`experimental_bearer_token`），已经开着的 Codex 桌面版、VS Code 插件也读得到；原来的默认模型新服务没有的，换成它提供的 |
| DeepSeek Harness | API Key 放在用户环境变量 `DEEPSEEK_API_KEY`（账号在 DeepSeek Harness 自己的界面里登录） |

服务地址的写法：Claude Code 填 Anthropic 格式接口的地址（如 `https://api.example.com`）；Codex 填 OpenAI 格式接口的地址（如 `https://api.example.com/v1`，需要支持 Responses API）。服务列不出模型时，Codex 要在"模型"里填一个它提供的模型（看服务商的说明或请求示例），保存前会用它真发一个很小的请求试一下。

### 关于 DeepSeek Harness

[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（DSH）是可选的替代引擎，不是必需的。超级助手认得它的桌面版，也认得 npm 装的 `@deepseek-ai/dsh`。

- 没装 Claude Code / Codex、你在准备窗口里选了先用它时，超级助手就靠它回答和动手；以后装上了 Claude Code / Codex，在设置的"可路由的模型"里可以让它继续参与，也可以关掉。
- 问答模式下它跑在只读沙箱里；操作模式完全放行。
- 超级助手的会话里有你屏幕上的内容，所以**关掉了 DSH 默认的"上传会话日志"**。这只影响超级助手发起的会话，不改你自己的 DSH 设置。

## 使用

- **打开**：开始菜单里的"超级助手"（英文系统叫 Super Aide）。它没有主窗口，只在托盘里，打开后右下角会提示一下；再点一次也只是提示它已经在运行。安装时勾了"开机自动启动"的话，开机就在后台待命（开机时不提示）。
- `Alt+Q` 问答、`Alt+W` 操作（设置里可以改）。输入框只在按快捷键时出现。召唤出来后框选重点区域，或者直接输入问题；追问框里按 `Tab` 在问答和操作之间切换。
- 托盘图标：问答、操作、历史记录、设置、退出。
- **历史记录**：所有问答，可以搜索。悬停在一条上点垃圾桶删除；按住 `Ctrl` / `Shift` 点选（或 `Ctrl+A`）可以一次删多条，按 `Delete` 也行。删了几秒内能撤销。
- **设置**：快捷键、主题、**语言**（跟随系统 / 中文 / English）、哪些应用不看（默认不看密码管理器）、每个引擎可以用哪些模型、思考强度的上限、开机自启。
- **更新**：设置 → 通用 → 版本。打开设置时会顺手查一下有没有新版本；点"更新"后超级助手先退出，安装器装好新版本再自动打开，设置和记录都保留。

## 自我改进

- **什么时候**：一次任务没办成（网络、登录之类的故障不算）；操作时你按 `Esc` 停下，并在提示里说了是助手哪里没做好（不答就当不是它的问题）；你点了 👎；你在 **设置 → 高级** 里写了建议。
- **怎么做**：先判断是不是它自己能改好的缺陷；是的话在一份工作副本上改代码、补测试，自己跑全部测试，再另开一个会话独立复核。默认用 Claude Code + Opus 5.5（最高思考强度），用不了时换你电脑上最好的工具和模型。
- **生效要你点**：改好后会通知你，点开能看到改了什么，点"生效"才换上新版本（超级助手重启几秒）。新版本起不来会自动装回原来的；也可以随时"撤销"最近一次改进。版本号会变成 `0.2.0+aide.1` 这样，官方更新照常提示，更新后本地改进会自动搬到新版本上（同样要你确认）。
- **过程中**：开始时会提醒你别关机、尽量保持联网；可以照常使用。托盘菜单最上面一行和设置里能看到进度，设置里点两下"不要了"马上停下，改到一半的还原。断网、关机后会接着做。一次只做一个，后来的排队，轮到时先看是不是已经被前面的改进解决了。
- **社区共建**（可选）：设置 → 高级 → 参与社区共建，用 GitHub 账号登录一次。生效后稳定运行一天的改进会以你的账号向主仓库提交 PR，只有代码改动，不带屏幕内容和日志；疑似含个人信息的不会自动提交。维护者审过才合并，见 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 自我改进的数据在 `~/.super_aide/evolve/`：任务记录、工作副本、打好的包。分析用的对话和日志只发给你配置的模型服务，任务结束就删掉，只留结论和补丁。

## 数据和隐私

- 超级助手自己的数据都在 `~/.super_aide/`：设置、会话快照、路由的学习记录、经验库、日志。会话文件夹 7 天后只留问答记录；召唤了没提问就关掉的，12 小时后整个删掉。
- 提问时的屏幕内容只发给你配置的模型服务。"不看这些应用"里的应用，它们的窗口在截图里涂黑，也不读里面的文字。

## 卸载

在 Windows 的 **设置 → 应用** 里找到"超级助手"，点卸载。可以选同时删除你的数据（设置、历史记录、经验）。Claude Code、Codex 是独立的工具，不会被删；需要的话另外卸载（`npm uninstall -g @anthropic-ai/claude-code @openai/codex`）。

从源码装的：运行 `uv tool uninstall super-aide`，再删掉开始菜单里的快捷方式。

## 常见问题

- **安装很慢或失败**：多半是网络。安装器和准备窗口都会自动换国内镜像；开着代理的话，系统代理也会用上。安装器的"查看详情"里有完整记录（也在 `%TEMP%\SuperAideSetup.log`），点"重试"会接着试。
- **登录好了还显示"未配置模型"**：点"重新检查"。命令行窗口里登录失败时会停住，能看到原因。
- **自定义服务地址测试不通过**：看提示是"密钥不对"还是"连不上这个地址"；有的服务不支持列出模型，这时会提示没法提前确认密钥，但照样会保存。

## 开发

```powershell
uv sync
uv run python -m super_aide          # 从源码运行（同一时间只能运行一个）
uv run python -m pytest -q           # 单元测试
powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1   # 编译安装器（用 Windows 自带的编译器）
```

设计文档在 [docs/design.md](docs/design.md)，`spikes/` 里是各阶段的验证和自检脚本（有的会调用真实模型）。

官网在 `website/`，由 `.github/workflows/pages.yml` 发布到 GitHub Pages（顺便把最新版安装器放到网站上）。宣传片和截图用 Remotion 从 `video/` 渲染，见 [video/README.md](video/README.md)。

界面文字以中文为准：Python 里用 `tr("中文")`，英文写在 `src/super_aide/locales/en_*.py`；网页里用 `data-i18n` 和 `I18N.t("中文")`，英文写在 `src/super_aide/ui/web/i18n-en.js`。`tests/test_i18n.py` 会检查每一句都有英文。

### 发版

推送 `v` 开头的标签就会自动发版（`.github/workflows/release.yml`）：跑测试 → 打包 → 编译安装器 → 建 GitHub Release → 发布到 PyPI。

```powershell
# 1. 改 pyproject.toml 里的 version（比如 0.2.0），提交
# 2. 打标签并推送
git tag v0.2.0
git push origin v0.2.0
```

第一次之前要做一次设置：

1. 在 [PyPI](https://pypi.org) 注册账号，到 **Account settings → Publishing** 添加一个 "pending publisher"：项目名 `super-aide`，填你的 GitHub 用户名和仓库名，工作流 `release.yml`，环境 `pypi`。这样发布时不用保存任何密码或令牌。
2. 在 GitHub 仓库的 **Settings → Environments** 里新建一个叫 `pypi` 的环境（可以设成需要你确认才发布）。
3. 可选：代码签名。[SignPath Foundation](https://signpath.org) 给开源项目免费签名（需要开源许可证、已经发布过、有一定使用量）。申请通过后按 `release.yml` 里的注释加上签名步骤。

## 许可证

[MIT](LICENSE)
