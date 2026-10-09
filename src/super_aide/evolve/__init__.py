"""自我改进：超级助手发现自己没办好（任务失败、你按 Esc 停下并说明是它的问题、点了 👎），或者你提了建议，
就用 Claude Code（Opus 5.5 · max）分析原因、改进自己的代码，检查和复核都过了，等你空闲时重启生效（起不来自动装回）。
稳定之后还可以把改进以 PR 的形式贡献给主版本（社区共建）。设计见 docs/design.md 第 17 节。

- manager：调度（排队、续上、生效、撤销、提交 PR、审社区 PR）
- jobs：任务和状态；triggers：什么算、什么不算；evidence：证据
- workshop / patching / wheelfile：工作台（正在运行的版本的源码）、补丁、打包
- testenv：测试环境；agent / prompts：工具、模型和指令；apply：生效的小程序（独立运行）
- github / community：社区共建
"""
