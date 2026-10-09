"""运行时目录。设置和"数据在哪"的记录在 ~/.super_aide/；数据默认也在这里，可以在设置 → 通用 → 数据位置换到别处。"""

from __future__ import annotations

import json
import os
from pathlib import Path

HOME = Path.home() / ".super_aide"
CONFIG = HOME / "config.toml"
#: 数据放在哪（relocate.py 写）：{"data": 文件夹, "previous": 换位置前的文件夹（新的进程起来后删掉那份）}
LOCATION = HOME / "location.json"


def _data_root() -> Path:
    try:
        chosen = str(json.loads(LOCATION.read_text(encoding="utf-8")).get("data") or "")
    except (OSError, ValueError, AttributeError):
        chosen = ""
    if chosen and os.path.exists(Path(chosen).anchor or chosen):
        return Path(chosen)
    return HOME  # 没换过，或者选的那个盘现在不在（比如移动硬盘拔了）


DATA = _data_root()
SESSIONS = DATA / "sessions"
WORKSPACE = DATA / "workspace"
#: 技能包：Claude 当本地插件加载，Codex 把其中的 skills 加为技能目录，两边读同一份（技能名都是 aide:xxx）
PLUGIN = WORKSPACE / "plugin"
ROUTER = DATA / "router"
LOGS = DATA / "logs"
#: 自我改进：任务、工作台（正在运行的版本的源码）、测试环境、打好的包
EVOLVE = DATA / "evolve"
MODELS = DATA / "models"
EXPERIENCE = DATA / "experience"
DSH = DATA / "dsh"
SYSTEM_PROFILE = DATA / "system_profile.json"

PACKAGE = Path(__file__).resolve().parent
UI_INDEX = PACKAGE / "ui" / "web" / "index.html"
#: 扩展包模板（共享指令、技能）随包一起发布，启动时同步到 WORKSPACE
WORKSPACE_TEMPLATE = PACKAGE / "workspace"
ICON = PACKAGE / "ui" / "super_aide.ico"


def ensure() -> None:
    for d in (HOME, DATA, SESSIONS, WORKSPACE, ROUTER, LOGS):
        d.mkdir(parents=True, exist_ok=True)
