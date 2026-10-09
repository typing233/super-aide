# P0 验证报告

> 日期：2026-10-07　|　对应设计：docs/design.md v0.3.1 第 14 节
> 验证脚本都在 `spikes/` 下，可以重复运行。

## 结论

**架构可行，没有推翻设计的发现。**两个最大的风险都排除了：

- 从我们自己的进程驱动 Codex，并在全放行配置下运行时，Computer Use 能正常工作，全程没有授权请求卡住流程。
- Claude 全放行时，静默拦截钩子仍然有效。

需要调整的地方见文末"对设计的修正"，都属于细节。

## 逐项结果

| # | 验证项 | 结果 | 依据 |
|---|---|---|---|
| ① | 界面原型 | ✅ 可交互试用（模拟回答） | `spikes/p0_shell.py`；12 张状态截图在 `spikes/out/ui/` |
| ② | Claude 全放行 + 静默拦截 | ✅ `bypassPermissions` 下普通命令、写文件照常执行；命中拦截清单的命令被 PreToolUse 钩子拦下，模型也没有绕过去重试 | `p0_claude.py` |
| ② | Claude 问答只读 | ✅ `dontAsk` 在技术上拒绝了 Write 和 PowerShell，文件没有被创建（不靠提示词） | `p0_claude.py` 1b |
| ② | Codex 全放行 | ✅ `full_access` 加不审批（`ApprovalMode.deny_all`，即 approval=never）时没有收到任何服务端请求 | `p0_codex.py` |
| ② | Codex 原生 PreToolUse 钩子（全放行） | ✅ 钩子通过启动参数注入，只按哈希信任这一个钩子，不改全局配置；命中暗号的命令被拦下（状态 blocked），模型如实汇报 | `p0_codex_guard.py` A |
| ② | Codex `forbidden` 规则（全放行） | ✅ 按命令词匹配的规则能拦下（Codex 会把 PowerShell 命令拆成词再匹配）；按完整命令行写的规则不生效。测试文件已删除 | `p0_codex_guard.py` B |
| ③ | 从我们的进程驱动 Codex + Computer Use | ✅ SDK 自带的 CLI（0.160.1）读你的 `config.toml`，Computer Use 正确列出了打开的应用 | `p0_codex.py` |
| ③ | Codex 中断 | ✅ 状态变为 interrupted | `p0_codex.py` |
| ④ | 可用模型 | ✅ Codex 8 个（gpt-6.1-sol、gpt-6-astra、gpt-6-sol、gpt-6-luna、gpt-5.6-sol、gpt-5.6-terra、gpt-5.6-luna、gpt-5.5）；✅ Claude：SDK 只报别名（default/opus/fable/sonnet/haiku），你的服务地址 `/v1/models` 返回 32 个完整模型名（含 Opus 5.5、Sonnet 5.5、Fable 5.1、Haiku 4.5） | `p0_codex.py`、`p0_leftovers.py` |
| ④ | llmrouter 做引擎路由 | ✅ 不改它的代码：自定义能力字符串（`gui_control` 等）做硬约束；学习、限流排除都正常 | `p0_router.py` |
| ⑤ | 召唤延迟 | ✅ 中位数约 60ms（目标 150ms）；第一次召唤 662ms，已经用启动预热解决 | `p0_shell.py --selftest` |
| ⑤ | 所有窗口快照 | ✅ 被挡住的窗口能截到（每个约 60ms）；最小化窗口没有画面，但能读到文字；预热后全屏截图约 50ms | `p0_snapshot*.py` |
| ⑤ | 透明窗口 + 视觉 | ✅ CSS 半透明表面在 QtWebEngine 中效果良好；DWM 亚克力还没试 | 截图 |
| ⑤ | 125% 缩放坐标 | ⏳ 逻辑已写好，需要在真实桌面上试用确认 | — |

## 关键数据

| 项 | 数值 |
|---|---|
| Claude 冷启动连接 / 带图提问首字 / 预热后首字 | 2.8s / 2.6s / 1.5s |
| Claude 新会话首问费用（SDK 估算） | 缓存冷约 $0.30，缓存热约 $0.07；同会话追问 $0.01～0.05 |
| Codex 启动握手 / 带图提问首字 | 0.3s / 7.9s（effort=low） |
| Codex 用 Computer Use 列出应用 | 84s，16.7 万输入 token（13.7 万命中缓存）；大部分时间花在读说明文档、初始化运行环境 |
| UIA 初始化（只在启动时一次）/ 之后读焦点和选中文字 | 253ms / 8～14ms |
| 网页正文：原生 FindFirst 直接定位 / 逐个遍历控件 | 134ms 拿到 2312 字 / 0.8s 超时只拿到 298 字 |
| 全屏截图编码：PNG 默认 / PNG 快速 / JPEG | 548ms / 89ms / 13ms |

## 对设计的修正

1. **路由只在"引擎 × 模型"之间选，思考强度按规则定。**思考强度也作为臂的维度时，"Claude xhigh 失败"不会让"Claude high"学到任何东西，个人使用的数据量撑不起这么细的拆分。（已写进设计 7.7 节）
2. **路由用"动态参照臂"**：以当前可行臂里预测质量最高的那个为基准，而不是 llmrouter 默认的固定参照臂；并且关闭级联、冷启动探测和探索。两边先验相同时，选更快的。
3. **Codex 预热 + 分叉**：后台先建一个会话，读完 Computer Use 的说明、初始化好运行环境；每次提问从它 `thread_fork` 出来，省掉每次约一分钟的准备时间。
4. **Codex 问答速度**：首字 7.9s，明显慢于 Claude 的 2.6s，延迟先验要按实测设置。问答模式下路由会自然偏向 Claude，除非数据显示 Codex 答得更好。
5. **Claude 每次召唤的成本**：新会话首问冷启动约 $0.30，主要是系统提示和工具定义第一次写入缓存。P1 要做三件事：保持缓存热（预热的会话）、问答模式精简工具集、评估 `excludeDynamicSections` 提高跨会话的缓存命中率。
6. **问答模式的"只读诊断"**：`dontAsk` 加纯工具允许清单，会把 PowerShell 整个禁掉。改用 SDK 的 `can_use_tool` 回调：由我们判断命令是否只读，自动放行或拒绝，全程不弹窗。
7. **不可信内容走原生通道**：Codex SDK 有 `ExternalMessage`，专门用于传"来自其它应用的不可信内容"，权限低于用户指令。屏幕上的文字用它传，原生防提示注入。
8. **快照实现细节**：
   - 窗口文字先用 UIA 原生 FindFirst 找文档节点，找不到再遍历控件树；
   - 截图图片在后台编码，用快速 PNG 或 JPEG；
   - UIA 在启动时初始化一次。

## 顺带发现

- **llmrouter 的显示问题**（你的项目，我没改）：`use_lower_bound=False` 时，决策理由仍然写"质量下界 X ≥ 门槛 Y"，但实际比较的是均值，所以会出现"0.399 ≥ 0.940"这种自相矛盾的文字。
- **llmrouter 的跨任务类型泄漏**：卸载类任务上 8 次失败，把 Claude 在"解释报错"上的预测从 0.97 拉到了 0.51。这是粗粒度分层共享观测的结果；数据多了以后细粒度层会占主导，先记录。
- **uv 安装时偶发"拒绝访问"**：杀毒软件扫描刚解压的 codex.exe 时锁住了文件，重试即可。

## 静默拦截：两边统一用"执行前钩子"

- **Claude**：SDK 的 PreToolUse 钩子（进程内 Python 函数）。
- **Codex**：原生 PreToolUse 钩子（运行一条命令）。
  - 注入方式：通过启动参数 `-c hooks.PreToolUse=[...]`。
  - 信任方式：用 `hooks/list` 拿到这个钩子的 key 和哈希，再用 `-c hooks.state={...}` 只信任它。不用 `bypass_hook_trust`，否则项目目录里别人留下的钩子也会被一起信任。
- **两边发给钩子的数据格式一致**：`tool_name=Bash`、`tool_input.command`，可以共用一份拦截逻辑。
- **Windows 上的两个坑**：
  1. 钩子输出必须是 UTF-8，否则中文理由解析失败，钩子算"失败"，命令会被放行。
  2. Codex 经 PowerShell 运行钩子，退出码 2 会被吞成 1（同样算失败、放行）。拒绝只能写成"正常退出 + 标准输出里的 JSON：`permissionDecision: deny`"。
- `~/.codex/rules` 的 forbidden 规则也能用，但全局生效，会影响你平时直接用 Codex，所以只作为备选。

## 还没做的

- DWM 亚克力背景（目前的半透明纯色表面已获认可，优先级低）
