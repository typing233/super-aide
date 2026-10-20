"""用户配置：~/.super_aide/config.toml。

除了快捷键、外观、隐私这些常规项，还包括每个引擎"可被路由的模型"清单
（设计 7.7 节）：每个模型一个开关，只有打开的才会被路由选中。
DeepSeek Harness（dsh）是可选的替代引擎，默认不参与：没装 Claude Code / Codex、你选了先用它时才打开。
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import tomli_w

from . import paths

EFFORTS = ("low", "medium", "high", "xhigh", "max")
ENGINES = ("claude", "codex", "dsh")
#: DeepSeek Harness 默认可路由的模型（DeepSeek 账号登录后能用的）
DSH_MODELS = ("deepseek-flash",)


@dataclass
class ModelEntry:
    id: str
    enabled: bool = False
    #: 思考强度上限（路由按任务定思考强度，但不会超过这里）。不支持 max 的模型在这里调低。
    max_effort: str = "max"


@dataclass
class EngineSettings:
    enabled: bool = True
    models: list[ModelEntry] = field(default_factory=list)

    def enabled_models(self) -> list[ModelEntry]:
        return [m for m in self.models if m.enabled] if self.enabled else []

    def merge_discovered(self, ids: list[str]) -> int:
        """把新发现的模型加进清单（默认关闭，由用户决定是否启用）。返回新增数量。"""
        known = {m.id for m in self.models}
        added = [ModelEntry(i) for i in ids if i not in known]
        self.models.extend(added)
        return len(added)


DEFAULT_BLOCKED_APPS = [
    "KeePass.exe", "KeePassXC.exe", "1Password.exe", "Bitwarden.exe", "LastPass.exe",
]


@dataclass
class Config:
    hotkey_ask: str = "Alt+Q"
    hotkey_act: str = "Alt+W"
    theme: str = "system"  # system | light | dark
    language: str = "system"  # system（跟随 Windows）| zh | en
    blocked_apps: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_APPS))
    clipboard_max_age_s: int = 300
    #: 静默拦截清单。默认关闭：操作模式完全交给 Claude Code / Codex 的全放行（用户决定）。
    blocklist_enabled: bool = False
    #: llmrouter 所在的文件夹（只借它估计任务难度；没有就用简单估计）
    llmrouter_path: str = ""
    pin_engine: str = ""  # 调试用：固定交给某个引擎，空 = 自动路由
    #: 后台对比：问答答完后，用更便宜/更快的配置在后台把同一个问题再答一遍，由强模型对比；
    #: 证明一样好之后路由才会用它（你看到的永远是当前最可靠的那份）。会多花一点费用。
    shadow_eval: bool = True
    shadow_daily: int = 20  # 每天最多对比几次
    claude: EngineSettings = field(default_factory=lambda: EngineSettings(
        models=[ModelEntry("claude-opus-5-5", True, "max")]))
    codex: EngineSettings = field(default_factory=lambda: EngineSettings(
        models=[ModelEntry("gpt-6-astra", True, "max")]))
    dsh: EngineSettings = field(default_factory=lambda: EngineSettings(
        enabled=False, models=[ModelEntry(m, True, "max") for m in DSH_MODELS]))
    #: 准备窗口（前置检查）走完过一次。之后只有一个能用的引擎都没有时才会自动打开
    setup_done: bool = False
    #: 新手指引看完（或跳过）了。第一次用时自动打开一次，之后从托盘菜单、设置里再打开
    tour_done: bool = False
    #: 自我改进：任务失败、你停下并说明原因、点 👎 或提建议时，分析并改进自己的代码，检查通过后自动更新
    evolve_enabled: bool = True
    #: 社区共建：稳定的改进以你的 GitHub 账号自动提交 PR 到主版本。auto = 能推送主仓库（维护者）时打开，否则关闭
    evolve_contribute: str = "auto"  # auto | on | off
    #: 判断模型（可选，Jev 类，设计 7.9 节）：路由看任务、学习看追问和停下的原因、经验复核时用。没填地址就照原来的做法
    decision_url: str = ""
    decision_key: str = ""
    decision_model: str = ""

    def engine(self, name: str) -> EngineSettings:
        return {"claude": self.claude, "codex": self.codex, "dsh": self.dsh}[name]

    def update_from(self, other: Config) -> None:
        """原地换成另一份设置：各部分拿着的是同一个配置对象，这样改了立刻生效。"""
        for f in fields(self):
            setattr(self, f.name, getattr(other, f.name))


def _engine_from(data: dict, default: EngineSettings) -> EngineSettings:
    if not data:
        return default
    models = [ModelEntry(id=str(m["id"]), enabled=bool(m.get("enabled", False)),
                         max_effort=str(m.get("max_effort", "max")))
              for m in data.get("models", []) if m.get("id")]
    return EngineSettings(enabled=bool(data.get("enabled", default.enabled)), models=models or default.models)


def _choice(value, allowed: tuple[str, ...], default: str) -> str:
    return value if value in allowed else default


def from_dict(data: dict) -> Config:
    d = Config()
    hot = data.get("hotkeys", {})
    privacy = data.get("privacy", {})
    router = data.get("router", {})
    engines = data.get("engines", {})
    return Config(
        hotkey_ask=hot.get("ask", d.hotkey_ask),
        hotkey_act=hot.get("act", d.hotkey_act),
        theme=data.get("appearance", {}).get("theme", d.theme),
        language=str(data.get("appearance", {}).get("language", d.language)),
        blocked_apps=list(privacy.get("blocked_apps", d.blocked_apps)),
        clipboard_max_age_s=int(privacy.get("clipboard_max_age_s", d.clipboard_max_age_s)),
        blocklist_enabled=bool(data.get("safety", {}).get("blocklist", d.blocklist_enabled)),
        llmrouter_path=router.get("llmrouter_path", d.llmrouter_path),
        pin_engine=router.get("pin_engine", d.pin_engine),
        shadow_eval=bool(router.get("shadow_eval", d.shadow_eval)),
        shadow_daily=int(router.get("shadow_daily", d.shadow_daily)),
        claude=_engine_from(engines.get("claude", {}), d.claude),
        codex=_engine_from(engines.get("codex", {}), d.codex),
        dsh=_engine_from(engines.get("dsh", {}), d.dsh),
        setup_done=bool(data.get("setup", {}).get("done", d.setup_done)),
        # 有新手指引之前就准备过的（老用户）不再自动打开：没有这一项时跟着"准备过没有"走
        tour_done=bool(data.get("tour", {}).get("done", data.get("setup", {}).get("done", d.tour_done))),
        evolve_enabled=bool(data.get("evolve", {}).get("enabled", d.evolve_enabled)),
        evolve_contribute=_choice(data.get("evolve", {}).get("contribute"), ("auto", "on", "off"), d.evolve_contribute),
        decision_url=str(data.get("decision", {}).get("url", d.decision_url)),
        decision_key=str(data.get("decision", {}).get("key", d.decision_key)),
        decision_model=str(data.get("decision", {}).get("model", d.decision_model)),
    )


def to_dict(cfg: Config) -> dict:
    return {
        "hotkeys": {"ask": cfg.hotkey_ask, "act": cfg.hotkey_act},
        "appearance": {"theme": cfg.theme, "language": cfg.language},
        "privacy": {"blocked_apps": cfg.blocked_apps, "clipboard_max_age_s": cfg.clipboard_max_age_s},
        "safety": {"blocklist": cfg.blocklist_enabled},
        "router": {"llmrouter_path": cfg.llmrouter_path, "pin_engine": cfg.pin_engine,
                   "shadow_eval": cfg.shadow_eval, "shadow_daily": cfg.shadow_daily},
        "engines": {
            name: {"enabled": eng.enabled, "models": [asdict(m) for m in eng.models]}
            for name, eng in (("claude", cfg.claude), ("codex", cfg.codex), ("dsh", cfg.dsh))
        },
        "setup": {"done": cfg.setup_done},
        "tour": {"done": cfg.tour_done},
        "evolve": {"enabled": cfg.evolve_enabled, "contribute": cfg.evolve_contribute},
        "decision": {"url": cfg.decision_url, "key": cfg.decision_key, "model": cfg.decision_model},
    }


def load(path: Path = paths.CONFIG) -> Config:
    if not path.exists():
        cfg = Config()
        save(cfg, path)
        return cfg
    return from_dict(tomllib.loads(path.read_text(encoding="utf-8")))


def save(cfg: Config, path: Path = paths.CONFIG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(tomli_w.dumps(to_dict(cfg)), encoding="utf-8")
    tmp.replace(path)
