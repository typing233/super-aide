"""引擎桥：Claude Code / Codex。

这个包的 __init__ 必须保持为空：Codex 的执行前钩子以 `python -m super_aide.engines.codex_hook`
运行，每次工具调用都会启动一次，这里一旦导入 SDK 就会拖慢每一条命令。
"""
