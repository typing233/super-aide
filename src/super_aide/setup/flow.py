"""准备流程怎么走（纯逻辑，准备窗口照着显示）：

1. Claude Code、Codex 有没装的：
   - 电脑里有 DeepSeek Harness（DSH）：问一句要不要装（装了效果更好）；不装也能用，先靠 DSH。
   - 没有 DSH：直接自动装（官方源 → 国内镜像），不用问。
2. 装好了但没配模型的：选"用账号登录"或"自定义服务地址"。
3. 至少有一个引擎能用了才能开始。
"""

from __future__ import annotations

from ..config import EngineSettings, ModelEntry
from ..router import catalog
from .detect import Report

CORE = ("claude", "codex")


def needs_setup(report: Report, use_dsh: bool, done: bool) -> bool:
    """启动时要不要先打开准备窗口。"""
    if not report.usable(use_dsh):
        return True  # 一个能用的引擎都没有
    if done:
        return False  # 已经准备过：没装的、没配的你都知道了，设置里随时能再打开
    return bool(report.missing() or [t for t in report.unconfigured() if t in CORE])


def auto_install(report: Report) -> list[str]:
    """没有 DSH 时，缺的直接装。"""
    return [] if report.dsh.installed else report.missing()


def should_ask(report: Report, decided: bool) -> bool:
    """有 DSH、Claude Code / Codex 又有没装的：问一句要不要装。"""
    return report.dsh.installed and bool(report.missing()) and not decided


def dsh_ready(report: Report) -> bool:
    return report.dsh.installed and report.dsh.configured


def use_dsh(report: Report, chose_dsh: bool, enabled: bool) -> bool:
    """DSH 要不要参与：你选了只用它、设置里本来就开着，或者别的引擎都用不了而它能用。"""
    if not dsh_ready(report):
        return False
    return chose_dsh or enabled or not report.usable(False)


def can_start(report: Report, chose_dsh: bool, enabled: bool) -> bool:
    return bool(report.usable(use_dsh(report, chose_dsh, enabled)))


# ---------- 刚配好的服务：用它确实提供的模型 ----------

def only_model(engine: EngineSettings, model: str) -> None:
    """你在自定义服务地址里填了模型：就用它（加进清单并打开），其它的先关掉，设置里还能再打开。"""
    if not model:
        return
    for m in engine.models:
        m.enabled = m.id == model
    if not any(m.id == model for m in engine.models):
        engine.models.insert(0, ModelEntry(model, True, "max"))


def strongest(engine: str, ids: list[str]) -> str:
    """一组模型里最强的：先看档次，同一档里 Claude 选版本新的，其它按列出的先后。"""
    def key(item: tuple[int, str]) -> tuple:
        order, model = item
        version = catalog.claude_version(model) if engine == "claude" else None
        return catalog.tier_of(model), -(version[1] if version else 0.0), order

    return min(enumerate(ids), key=key)[1]


def fit_models(engine: EngineSettings, name: str, found: list[str], typed: str = "") -> bool:
    """刚配好的服务列出了它提供的模型：打开的模型里它不提供的关掉，一个都不剩就打开它提供的最强的那个。
    你填了模型的以你填的为准（only_model 已经处理）。返回是否改了。"""
    if not found or typed:
        return False
    available = set(found)
    changed = False
    for m in engine.models:
        if m.enabled and m.id not in available:
            m.enabled = False
            changed = True
    if not any(m.enabled for m in engine.models):
        pick = strongest(name, found)
        for m in engine.models:
            m.enabled = m.id == pick
        changed = True
    return changed
