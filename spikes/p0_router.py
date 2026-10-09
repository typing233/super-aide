"""P0-④ 路由验证：用 llmrouter 的决策/学习内核给"引擎臂"做路由，不改它的代码。

验证三件事：
1. 用自定义能力字符串（gui_control / browser_control）表达工具约束，不可行的臂带着理由被筛掉；
2. 关掉级联、冷启动探测和探索后，决策确定、可解释；两边先验相同时，选更快更省的；
3. predictor.update 让后验朝观测移动；EXCLUDE_SIGNAL（限流、网络错误）不计入学习。

用法：uv run python spikes/p0_router.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.environ.get("LLMROUTER_PATH", ""))  # llmrouter 所在的文件夹（作者本机的路由项目）

from llmrouter.catalog import ModelCatalog, ModelSpec, ThinkingMode  # noqa: E402
from llmrouter.core.contracts import (  # noqa: E402
    Arm, Features, QualityTier, QualityVerdict, Requirements, TaskKind,
)
from llmrouter.core.grading import EXCLUDE_SIGNAL  # noqa: E402
from llmrouter.policy.cost import CostModel  # noqa: E402
from llmrouter.policy.predictor import QualityPredictor  # noqa: E402
from llmrouter.policy.router import Router, RouterConfig  # noqa: E402

# 两个引擎共有的能力；Codex 额外具备界面和浏览器操作
BASE_CAPS = frozenset({"text", "vision", "tools", "shell", "file_edit", "web"})


def engine_catalog() -> ModelCatalog:
    # 价格先用同一组占位值：两边都走自定义服务，真实单价由 cost_model 按实际用量校准
    common = dict(price_in=4.0, price_out=20.0, price_cache_read=0.4, price_cache_write=5.0,
                  context_tokens=1_000_000, max_output_tokens=128_000,
                  thinking_mode=ThinkingMode.ALWAYS_ON, can_disable_thinking=False,
                  capability_prior=0.85, speed_tokens_per_sec=60.0,
                  latency_overhead_ms=3000.0)
    return ModelCatalog([
        ModelSpec(provider="claude_code", model_id="claude-opus-5-5",
                  display_name="Claude Code · Opus 5.5", capabilities=BASE_CAPS,
                  efforts=("low", "medium", "high", "xhigh"), default_effort="xhigh",
                  **common),
        ModelSpec(provider="codex", model_id="gpt-6-astra",
                  display_name="Codex · gpt-6-astra",
                  capabilities=BASE_CAPS | {"gui_control", "browser_control"},
                  efforts=("low", "medium", "high", "xhigh", "max"), default_effort="max",
                  **common),
    ])


SCENARIOS = {
    "问答·解释报错": (
        Features(task_kind=TaskKind.QA_FACTUAL, domain="explain_error", difficulty=0.3,
                 has_images=True, lang="zh", input_tokens=3000, expected_output_tokens=400),
        Requirements(modalities=("text", "vision")),
    ),
    "操作·改设置（要动界面）": (
        Features(task_kind=TaskKind.AGENTIC, domain="gui_operation", difficulty=0.5,
                 has_images=True, has_tools=True, lang="zh", input_tokens=4000,
                 expected_output_tokens=1500),
        Requirements(modalities=("text", "vision", "tools", "gui_control")),
    ),
    "操作·卸载软件（命令行）": (
        Features(task_kind=TaskKind.AGENTIC, domain="system_admin", difficulty=0.6,
                 has_images=True, has_tools=True, lang="zh", input_tokens=4000,
                 expected_output_tokens=1500),
        Requirements(modalities=("text", "vision", "tools", "shell")),
    ),
}

PROVIDERS = ("claude_code", "codex")


def build(config: RouterConfig) -> tuple[Router, QualityPredictor, ModelCatalog]:
    catalog = engine_catalog()
    predictor = QualityPredictor(catalog, seed=7)
    return Router(catalog, predictor, CostModel(catalog), config, seed=7), predictor, catalog


def best_arm(router: Router, catalog: ModelCatalog, feats: Features, req: Requirements) -> Arm:
    """动态参照臂：可行臂里预测质量最高的那个（llmrouter 默认用先验最高的固定臂）。"""
    scored = []
    for arm, spec, reason in catalog.feasible_arms(req, PROVIDERS):
        if not reason:
            scored.append((router.predictor.predict(feats, arm, spec).mean, arm))
    return max(scored, key=lambda t: t[0])[1]


def show(router: Router, catalog: ModelCatalog, title: str, dynamic_ref: bool) -> None:
    feats, req = SCENARIOS[title]
    kwargs = {"reference_arm": best_arm(router, catalog, feats, req)} if dynamic_ref else {}
    plan = router.route(feats, req, available_providers=PROVIDERS, **kwargs)
    d = plan.decision
    print(f"\n▶ {title}\n  选中 {d.arm.id}  mode={d.mode}  参照={d.reference_arm.id}")
    print(f"  理由：{d.reason}")
    for c in d.candidates:
        flag = "✓" if c.feasible else "✗"
        print(f"    {flag} {c.arm_id:<36} q={c.predicted_quality:.3f} lb={c.quality_lower_bound:.3f}"
              f" ${c.predicted_cost_usd:.4f} {c.predicted_latency_ms / 1000:5.1f}s"
              f" n={c.n_observations} {c.reject_reason}")


def verdict(score: float, tier: QualityTier = QualityTier.DETERMINISTIC,
            confidence: float = 0.9, exclude: bool = False) -> QualityVerdict:
    signals = ((EXCLUDE_SIGNAL, 1.0),) if exclude else (("task_status", score),)
    return QualityVerdict(score=score, passed=score >= 0.5, tier=tier,
                          confidence=confidence, signals=signals)


def main() -> None:
    interactive = RouterConfig(quality_tolerance=0.03, use_lower_bound=False,
                               cascade_enabled=False, coldstart_probe=False,
                               exploration_rate=0.0, latency_weight_usd_per_sec=0.002)

    print("=" * 80, "\n配置 A：llmrouter 默认参照臂（先验最高的固定臂）+ 交互参数")
    router, predictor, catalog = build(interactive)
    for title in SCENARIOS:
        show(router, catalog, title, dynamic_ref=False)

    print("\n" + "=" * 80, "\n配置 B：动态参照臂（可行臂里预测质量最高的）+ 交互参数")
    for title in SCENARIOS:
        show(router, catalog, title, dynamic_ref=True)

    print("\n" + "=" * 80, "\n学习：卸载类任务上 Codex 连续成功、Claude 连续失败（各 8 次，默认思考档）")
    feats, req = SCENARIOS["操作·卸载软件（命令行）"]
    claude = Arm("claude_code", "claude-opus-5-5", effort="xhigh", thinking=True)
    codex = Arm("codex", "gpt-6-astra", effort="max", thinking=True)
    for _ in range(8):
        predictor.update(feats, claude, verdict(0.0))
        predictor.update(feats, codex, verdict(1.0))
    show(router, catalog, "操作·卸载软件（命令行）", dynamic_ref=True)
    print("\n  同一批观测是否影响别的任务类型（问答·解释报错）：")
    show(router, catalog, "问答·解释报错", dynamic_ref=True)

    before = predictor.predict(feats, claude).mean
    accepted = predictor.update(feats, claude, verdict(1.0, exclude=True))
    after = predictor.predict(feats, claude).mean
    print(f"\nEXCLUDE_SIGNAL（如限流）：update 返回 {accepted}，Claude 后验 {before:.3f} → {after:.3f}")


if __name__ == "__main__":
    main()
