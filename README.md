# 超级助手（Super Aide）

[English](README.en.md)

Windows 桌面助手：按一个快捷键、说一句话，它看着你当前的屏幕回答问题，或者直接动手做完。

背后调度 **Claude Code** 和 **Codex**（也可以用 **DeepSeek Harness** 替代），每次自动挑最合适的引擎、模型和思考强度。你不用描述背景，也不用选模型。

- **问答**（默认 `Alt+Q`）：只读，不动你的电脑。可以读文件、跑只读的诊断命令，需要你点哪里时会在屏幕上圈出来。
- **操作**（默认 `Alt+W`）：直接动手做完，命令行、文件、桌面软件、网页都行，做完汇报结果和怎么撤销。随时按 `Esc` 停下。
- **看得全**：提问那一刻所有窗口的文字（逐字，包括滚动出去的部分）、截图和你框选的区域都会交给它。
- **越用越懂你**：先保证办成，再在证明一样好的前提下换更快、更省的配置；踩过的坑在相似情况下会想起来。
- **中文 / English**：界面跟随系统语言，也可以在设置里切换；你用什么语言问，它就用什么语言答。

## 安装

需要 Windows 10（1809 以上）或 Windows 11，64 位。

1. 到 [Releases](../../releases/latest) 下载 **`SuperAideSetup.exe`**（约 100 KB）。
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
| Codex | `~/.codex/config.toml` 加服务商 `model_providers.super_aide`，密钥放在用户环境变量 `SUPER_AIDE_CODEX_API_KEY` |
| DeepSeek Harness | API Key 放在用户环境变量 `DEEPSEEK_API_KEY`（账号在 DeepSeek Harness 自己的界面里登录） |

服务地址的写法：Claude Code 填 Anthropic 格式接口的地址（如 `https://api.example.com`）；Codex 填 OpenAI 格式接口的地址（如 `https://api.example.com/v1`，需要支持 Responses API）。

### 关于 DeepSeek Harness

[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（DSH）是可选的替代引擎，不是必需的。超级助手认得它的桌面版，也认得 npm 装的 `@deepseek-ai/dsh`。

- 没装 Claude Code / Codex、你在准备窗口里选了先用它时，超级助手就靠它回答和动手；以后装上了 Claude Code / Codex，在设置的"可路由的模型"里可以让它继续参与，也可以关掉。
- 问答模式下它跑在只读沙箱里；操作模式完全放行。
- 超级助手的会话里有你屏幕上的内容，所以**关掉了 DSH 默认的"上传会话日志"**。这只影响超级助手发起的会话，不改你自己的 DSH 设置。

## 使用

- **打开**：开始菜单里的"超级助手"（英文系统叫 Super Aide）。它没有主窗口，只在托盘里，打开后右下角会提示一下；再点一次也只是提示它已经在运行。安装时勾了"开机自动启动"的话，开机就在后台待命（开机时不提示）。
- `Alt+Q` 问答、`Alt+W` 操作（设置里可以改）。输入框只在按快捷键时出现。召唤出来后框选重点区域，或者直接输入问题；追问框里按 `Tab` 在问答和操作之间切换。
- 托盘图标：问答、操作、历史记录、设置、退出。
- **设置**：快捷键、主题、**语言**（跟随系统 / 中文 / English）、哪些应用不看（默认不看密码管理器）、每个引擎可以用哪些模型、思考强度的上限、开机自启。
- **更新**：设置 → 通用 → 版本。打开设置时会顺手查一下有没有新版本；点"更新"后超级助手先退出，安装器装好新版本再自动打开，设置和记录都保留。

## 数据和隐私

- 超级助手自己的数据都在 `~/.super_aide/`：设置、会话快照、路由的学习记录、经验库、日志。会话文件夹 7 天后只留问答记录。
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
