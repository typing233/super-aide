"""P0-③ Codex（openai-codex 官方 Python SDK）验证，走你 ~/.codex/config.toml 里的服务商。

1. 可用模型：列出服务商实际返回的模型。
2. 问答：只读沙箱 + 不审批，进程级关闭 Computer Use / Browser Use；带图提问。
3. 操作 + Computer Use：完全访问 + 不审批（全放行），让它只读地列出打开的应用。
   重点看 Computer Use 能否从我们的进程用起来，以及中途有哪些服务端请求（应用授权等）。
4. 中断：长任务开始输出后立即中断，看状态。

用法：uv run python spikes/p0_codex.py
"""

from __future__ import annotations

import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

from p0_common import synthetic_error_png

from openai_codex import ApprovalMode, Codex, CodexConfig, LocalImageInput, Sandbox, TextInput
from openai_codex._run import _final_assistant_response_from_items
from openai_codex.generated.v2_all import (
    ItemCompletedNotification,
    ThreadTokenUsageUpdatedNotification,
    TurnCompletedNotification,
)

SERVER_REQUESTS: list[str] = []


def approval_handler(method: str, params: dict | None) -> dict:
    """记录 Codex 发来的每一个服务端请求；全放行模式下一律同意。"""
    SERVER_REQUESTS.append(method)
    print(f"    ↪ 服务端请求：{method}  参数键：{sorted((params or {}).keys())}")
    if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
        return {"decision": "acceptForSession"}
    return {}


def item_summary(root) -> str:
    data = root.model_dump(exclude_none=True, by_alias=True)
    keys = ("server", "tool", "command", "status", "exitCode", "aggregatedOutput")
    return ", ".join(f"{k}={str(data[k])[:80]}" for k in keys if k in data)


def run_turn(thread, input, label: str, timeout_s: float = 240, interrupt_on_first_delta=False, **kw):
    t0 = time.perf_counter()
    first = None
    items, usage, status = [], None, None
    methods: Counter[str] = Counter()
    turn = thread.turn(input, **kw)
    watchdog = threading.Timer(timeout_s, turn.interrupt)
    watchdog.start()
    try:
        for ev in turn.stream():
            methods[ev.method] += 1
            if first is None and ev.method == "item/agentMessage/delta":
                first = time.perf_counter() - t0
                if interrupt_on_first_delta:
                    turn.interrupt()
            p = ev.payload
            if isinstance(p, ItemCompletedNotification):
                items.append(p.item)
                root = getattr(p.item, "root", p.item)
                name = type(root).__name__
                if name not in ("AgentMessageThreadItem", "ReasoningThreadItem", "UserMessageThreadItem"):
                    print(f"    · {name}: {item_summary(root)}")
            elif isinstance(p, ThreadTokenUsageUpdatedNotification):
                usage = p.token_usage
            elif ev.method == "hook/completed" and getattr(p, "run", None) is not None:
                entries = [(e.kind.value, e.text[:80]) for e in p.run.entries]
                print(f"    ⚙ 钩子 {p.run.event_name.value} → {p.run.status.value} {entries}")
            elif isinstance(p, TurnCompletedNotification):
                status = p.turn.status
    finally:
        watchdog.cancel()
    total = time.perf_counter() - t0
    answer = _final_assistant_response_from_items(items)
    if answer:
        print(f"    回答：{answer.strip()[:400]}")
    tokens = usage.model_dump(exclude_none=True) if usage else {}
    ft = f"{first:.1f}s" if first is not None else "-"
    print(f"  [{label}] 状态 {getattr(status, 'value', status)}，首字 {ft}，总计 {total:.1f}s，"
          f"用量 {tokens.get('total', tokens)}")
    print(f"    事件类型：{dict(methods.most_common(8))}")
    return status


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="super_aide_p0_codex_"))
    png = tmp / "error.png"
    png.write_bytes(synthetic_error_png())

    print("=== 1/2. 问答进程（关闭 Computer Use / Browser Use）===")
    t = time.perf_counter()
    ask_cfg = CodexConfig(cwd=str(tmp), config_overrides=(
        "features.computer_use=false", "features.browser_use=false"))
    with Codex(ask_cfg) as codex:
        codex._client._approval_handler = approval_handler
        print(f"  启动 + 握手 {time.perf_counter() - t:.1f}s；服务端 {codex.metadata.model_dump(exclude_none=True).get('userAgent', '')}")
        try:
            models = codex.models()
            print(f"  可用模型：{[m.id for m in models.data][:15]}")
        except Exception as e:  # noqa: BLE001
            print(f"  列模型失败：{e}")
        thread = codex.thread_start(sandbox=Sandbox.read_only, approval_mode=ApprovalMode.deny_all,
                                    ephemeral=True, cwd=str(tmp))
        run_turn(thread, [LocalImageInput(str(png)),
                          TextInput("这张截图里的报错是什么原因？用中文一句话回答。")],
                 "问答·带图", effort="low")

    print("\n=== 3. 操作进程（全放行）+ Computer Use 只读观察 ===")
    t = time.perf_counter()
    with Codex(CodexConfig(cwd=str(tmp))) as codex:
        codex._client._approval_handler = approval_handler
        print(f"  启动 + 握手 {time.perf_counter() - t:.1f}s")
        thread = codex.thread_start(sandbox=Sandbox.full_access, approval_mode=ApprovalMode.deny_all,
                                    ephemeral=True, cwd=str(tmp))
        run_turn(thread, (
            "请使用 Computer Use 插件列出当前打开的应用（只列应用名，不要窗口标题）。"
            "只观察：不要点击、输入、启动或关闭任何东西。用中文简短回答。"
        ), "Computer Use 只读", effort="medium", timeout_s=300)

        print("\n=== 4. 中断 ===")
        thread2 = codex.thread_start(sandbox=Sandbox.read_only, approval_mode=ApprovalMode.deny_all,
                                     ephemeral=True, cwd=str(tmp))
        run_turn(thread2, "从 1 数到 300，每个数字单独一行。", "中断", effort="low",
                 interrupt_on_first_delta=True)

    print(f"\n收到的服务端请求：{Counter(SERVER_REQUESTS) or '无'}")


if __name__ == "__main__":
    main()
