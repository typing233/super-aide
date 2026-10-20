"""判断模型（可选）：比关键词准、比大模型快得多的判断。见 client.py、checks.py 和设计 7.9 节。"""

from .client import Answer, Decider

__all__ = ["Answer", "Decider"]
