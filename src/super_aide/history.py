"""历史记录：每次对话的问答存在它的会话文件夹里（conversation.json），这里负责读取、搜索和清理。

截图和窗口文字只在最近几天有用（追问时引擎要看），过期后删掉，只留问答本身，省空间也少留隐私。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

FILE = "conversation.json"
SESSION_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
KEEP_DAYS = 7


def save(folder: Path, conversation: dict) -> None:
    tmp = folder / (FILE + ".tmp")
    tmp.write_text(json.dumps(conversation, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, folder / FILE)


def _read(folder: Path) -> dict | None:
    try:
        return json.loads((folder / FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def summaries(query: str = "", limit: int = 300) -> list[dict]:
    """最近的对话，新的在前。query 不为空时只留问题或回答里包含它的。"""
    query = query.strip().lower()
    out = []
    folders = sorted((d for d in paths.SESSIONS.iterdir() if SESSION_ID.match(d.name)), reverse=True) \
        if paths.SESSIONS.exists() else []
    for folder in folders:
        conv = _read(folder)
        if not conv or not conv.get("turns"):
            continue
        turns = conv["turns"]
        if query and not any(query in (t.get("question", "") + t.get("answer", "")).lower() for t in turns):
            continue
        first, last = turns[0], turns[-1]
        out.append({"id": folder.name, "started": conv.get("started", ""), "mode": conv.get("mode", "ask"),
                    "question": first.get("question", ""), "preview": _preview(last.get("answer", "")),
                    "ok": last.get("ok", True), "turns": len(turns)})
        if len(out) >= limit:
            break
    return out


def load(session_id: str) -> dict | None:
    if not SESSION_ID.match(session_id):  # 只接受会话文件夹名，防止读到别处的文件
        return None
    conv = _read(paths.SESSIONS / session_id)
    if conv is not None:
        conv["id"] = session_id
    return conv


def folder(session_id: str) -> Path | None:
    path = paths.SESSIONS / session_id
    return path if SESSION_ID.match(session_id) and path.is_dir() else None


def _preview(markdown: str) -> str:
    for line in markdown.splitlines():
        text = re.sub(r"^[#>*\-\d.)\s`]+", "", line).replace("**", "").replace("`", "").strip()
        if text:
            return text[:80]
    return ""


def prune(keep_days: int = KEEP_DAYS) -> int:
    """过期的会话文件夹：有问答的只留 conversation.json，没有的整个删掉。返回清理了几个。"""
    if not paths.SESSIONS.exists():
        return 0
    cutoff = time.time() - keep_days * 86400
    cleaned = 0
    for folder in paths.SESSIONS.iterdir():
        if not (folder.is_dir() and SESSION_ID.match(folder.name)):
            continue
        try:
            if folder.stat().st_mtime > cutoff:
                continue
            if not (folder / FILE).exists():
                shutil.rmtree(folder)
                cleaned += 1
                continue
            extra = [p for p in folder.iterdir() if p.name != FILE]
            for p in extra:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
            cleaned += bool(extra)
        except OSError as e:
            log.warning("清理会话 %s 失败：%s", folder.name, e)
    return cleaned
