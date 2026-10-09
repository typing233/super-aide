"""把经验接到两个引擎上。

- 提问时：中枢按这次的情况想起相似的经验，写进首条消息（hub.py）；
- 做到一半：Claude 的工具结果里出现报错时，钩子再想一次，附在工具结果后面（claude.py）；
- 模型主动问：两边都有一个只读的 recall 工具。Claude 用进程内的工具，Codex 挂一个很小的 stdio 工具服务器
  （super_aide.experience.server，只读经验库文件）。
"""

from __future__ import annotations

import json
import os

from ..experience import recall
from ..experience.store import Store
from ..i18n import tr
from . import computer

SERVER_NAME = "memory"
STATUS = "正在回想以前的经验…"  # 中文原文（tr 的键），显示用 status()
error_lines = recall.error_lines
text_of = recall.text_of
#: Codex 自带的记忆每次都把总结塞进上下文、还会从助手的会话里学：助手的会话里关掉，经验由我们按需想起
#: （键名取自 codex.exe 里的配置项：memories.generate_memories、memories.use_memories）
CODEX_MEMORIES_OFF = ("memories.generate_memories=false", "memories.use_memories=false")


def status() -> str:
    """模型在回想经验时界面上的那一行进度（三个引擎共用）。"""
    return tr(STATUS)


def lookup(query: str, store: Store | None = None) -> str:
    """模型主动问：和 query 相似的经验，写好给模型看的文字；对不上就是空字符串。"""
    return recall.render(recall.recall(store or Store(), recall.Situation(question=query)))


def codex_overrides() -> tuple[str, ...]:
    """给 Codex 的 -c 配置：挂上只读的经验工具服务器。"""
    prefix = f"mcp_servers.{SERVER_NAME}"
    env = {"PYTHONIOENCODING": "utf-8"} | ({"AIDE_LESSONS": os.environ["AIDE_LESSONS"]}
                                          if os.environ.get("AIDE_LESSONS") else {})
    env_toml = ",".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in env.items())
    return (f"{prefix}.command={json.dumps(computer._python())}",
            f'{prefix}.args=["-X", "utf8", "-m", "super_aide.experience.server"]',
            f"{prefix}.env={{{env_toml}}}",
            f"{prefix}.startup_timeout_sec=20",
            f"{prefix}.tool_timeout_sec=30")
