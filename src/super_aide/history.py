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
from .engines.base import friendly_text
from .i18n import tr

log = logging.getLogger(__name__)

FILE = "conversation.json"
SESSION_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
KEEP_DAYS = 7
#: 召唤了没提问（没有问答记录）的会话文件夹留这么久就删：截图和窗口文字一点用都没有了（每个约 1～2MB）。
#: 不能太短：首问的问答记录要等这一轮答完才写，长的操作要跑好一阵
UNUSED_HOURS = 12
#: 在历史记录里删掉的会话先挪到这里（撤销时挪回去），过一会儿再真删
TRASH = ".trash"
UNDO_S = 60


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
                    "question": first.get("question", ""), "preview": _preview(last.get("answer", "")) or _preview(_shown_error(last)),
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
        for turn in conv.get("turns", []):
            if turn.get("error") or turn.get("reason") == "interrupted":
                turn["error"] = _shown_error(turn)
    return conv


def _shown_error(turn: dict) -> str:
    """给人看的出错原因：引擎原始的接口报错（429 之类的英文）换成一句人话，和回答卡片上一样。记录里留原文。"""
    if turn.get("reason") == "interrupted":  # 你按 Esc 停下的：引擎报上来的只是一串内部诊断（[ede_diagnostic] …）
        return tr("已停止")
    error = str(turn.get("error") or "")
    return error if turn.get("reason") == "reported" else friendly_text(error)


def delete(session_ids: list[str]) -> list[str]:
    """删掉这些会话（历史记录里点的删除）。先挪到回收处，撤销时能挪回来；过 UNDO_S 秒再真删。返回删掉了哪些。"""
    trash = paths.SESSIONS / TRASH
    done = []
    for sid in session_ids:
        src = folder(str(sid))
        if src is None:
            continue
        dst = trash / src.name
        try:
            trash.mkdir(exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            os.replace(src, dst)
            os.utime(dst)  # 记下删的时间：过一会儿真删
        except OSError as e:
            log.warning("删除会话 %s 失败：%s", sid, e)
            continue
        done.append(src.name)
    empty_trash()
    return done


def restore(session_ids: list[str]) -> list[str]:
    """撤销刚才的删除：从回收处挪回来。返回挪回了哪些。"""
    back = []
    for sid in session_ids:
        sid = str(sid)
        src, dst = paths.SESSIONS / TRASH / sid, paths.SESSIONS / sid
        if not SESSION_ID.match(sid) or not src.is_dir() or dst.exists():
            continue
        try:
            os.replace(src, dst)
        except OSError as e:
            log.warning("恢复会话 %s 失败：%s", sid, e)
            continue
        back.append(sid)
    return back


def empty_trash(older_than_s: float = UNDO_S) -> int:
    """真删回收处里删了超过 older_than_s 秒的。返回删了几个。"""
    trash = paths.SESSIONS / TRASH
    if not trash.is_dir():
        return 0
    cutoff, gone = time.time() - older_than_s, 0
    for path in trash.iterdir():
        try:
            if path.stat().st_mtime <= cutoff:
                shutil.rmtree(path) if path.is_dir() else path.unlink()
                gone += 1
        except OSError as e:
            log.warning("清理回收处 %s 失败：%s", path.name, e)
    return gone


def folder(session_id: str) -> Path | None:
    path = paths.SESSIONS / session_id
    return path if SESSION_ID.match(session_id) and path.is_dir() else None


def _preview(markdown: str) -> str:
    for line in markdown.splitlines():
        # 开头只去掉列表、引用、标题的记号；"3 个文件已删除"开头的数字是正文，不是编号
        text = re.sub(r"^(?:[#>*\-\s`]|\d+[.)](?=\s|$))+", "", line).replace("**", "").replace("`", "").strip()
        if text:
            return text[:80]
    return ""


def prune(keep_days: int = KEEP_DAYS, unused_hours: float = UNUSED_HOURS) -> int:
    """过期的会话文件夹：有问答的 keep_days 天后只留 conversation.json；没有问答的（召唤了没提问）
    unused_hours 小时后整个删掉。返回清理了几个。"""
    if not paths.SESSIONS.exists():
        return 0
    empty_trash()  # 历史记录里删掉、过了撤销时间的
    now = time.time()
    cutoff, unused_cutoff = now - keep_days * 86400, now - unused_hours * 3600
    cleaned = 0
    for folder in paths.SESSIONS.iterdir():
        if not (folder.is_dir() and SESSION_ID.match(folder.name)):
            continue
        try:
            mtime = folder.stat().st_mtime
            if not (folder / FILE).exists():
                if mtime <= unused_cutoff:
                    shutil.rmtree(folder)
                    cleaned += 1
                continue
            if mtime > cutoff:
                continue
            extra = [p for p in folder.iterdir() if p.name != FILE]
            for p in extra:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
            cleaned += bool(extra)
        except OSError as e:
            log.warning("清理会话 %s 失败：%s", folder.name, e)
    return cleaned
