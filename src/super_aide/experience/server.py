"""经验的 MCP 工具服务器（stdio），给 Codex 用。Claude 用进程内的同名工具，不走这里。

    python -m super_aide.experience.server

只有一个只读的工具 recall，读 ~/.super_aide/experience/lessons.json（文件变了会重新读）。
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .embed import Embedder
from .recall import Situation, recall, render
from .semantic import Semantic
from .store import Store

server = MCPServer("aide-memory", instructions="recall：查以前在相似问题上踩过的坑。碰到报错、卡住、准备绕路时用。")
_store = Store()
_semantic = Semantic(Embedder(), _store.path.with_name("vectors.json"))  # 模型还没下载时只按字面


# 标成只读：Codex 在只读沙箱（问答模式）里，没标只读的工具要审批，而我们不审批，会被直接拒掉（实测）
@server.tool(name="recall", structured_output=False, annotations=ToolAnnotations(read_only_hint=True))
def recall_tool(query: str) -> str:
    """查以前在相似问题上踩过的坑和总结的经验。碰到报错、卡住、准备绕路或者做没把握的操作之前用。
    query 写现在的情况：报错原文、在做什么、用的什么软件或网站。"""
    return render(recall(_store, Situation(question=query), semantic=_semantic)) or "没有相似的经验。"


def main() -> None:
    # DeepSeek Harness 桌面版把自己当 Node 跑（ELECTRON_RUN_AS_NODE=1），这个变量会传给我们：
    # 不清掉的话，从这里打开的 VS Code 这类 Electron 程序会以 Node 的方式启动、打不开
    os.environ.pop("ELECTRON_RUN_AS_NODE", None)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    server.run("stdio")


if __name__ == "__main__":
    main()
