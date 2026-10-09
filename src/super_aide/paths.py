"""运行时目录。所有数据都放在 ~/.super_aide/ 下。"""

from __future__ import annotations

from pathlib import Path

HOME = Path.home() / ".super_aide"
CONFIG = HOME / "config.toml"
SESSIONS = HOME / "sessions"
WORKSPACE = HOME / "workspace"
#: 技能包：Claude 当本地插件加载，Codex 把其中的 skills 加为技能目录，两边读同一份（技能名都是 aide:xxx）
PLUGIN = WORKSPACE / "plugin"
ROUTER = HOME / "router"
LOGS = HOME / "logs"
#: 自我改进：任务、工作台（正在运行的版本的源码）、测试环境、打好的包
EVOLVE = HOME / "evolve"
SYSTEM_PROFILE = HOME / "system_profile.json"

PACKAGE = Path(__file__).resolve().parent
UI_INDEX = PACKAGE / "ui" / "web" / "index.html"
#: 扩展包模板（共享指令、技能）随包一起发布，启动时同步到 WORKSPACE
WORKSPACE_TEMPLATE = PACKAGE / "workspace"
ICON = PACKAGE / "ui" / "super_aide.ico"


def ensure() -> None:
    for d in (HOME, SESSIONS, WORKSPACE, ROUTER, LOGS):
        d.mkdir(parents=True, exist_ok=True)
