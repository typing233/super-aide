"""P0 收尾：Codex 全放行下的两种静默拦截方式。

A. 原生 PreToolUse 钩子 + 精确信任：先用 hooks/list 拿到我们这个钩子的 key 和哈希，
   再用 -c hooks.state={...} 只信任它（不用 bypass_hook_trust，不改全局配置）。
B. ~/.codex/rules 里的 forbidden 规则（用户已同意）：临时加一个单独的测试文件，测完删除。
   两条暗号分别对应"按命令词匹配"和"按完整 PowerShell 命令行匹配"，看哪种能生效。

用法：uv run python spikes/p0_codex_guard.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox
from openai_codex.generated.v2_all import HooksListResponse

from p0_codex import approval_handler, run_turn

HERE = Path(__file__).resolve().parent
HOOK_LOG = HERE / "out" / "codex_hook_log.jsonl"
HOOK_CMD = f"{sys.executable} {HERE / 'codex_hook_blocklist.py'}"
HOOK_OVERRIDE = "hooks.PreToolUse=[{hooks=[{type=\"command\", command='" + HOOK_CMD + "'}]}]"
RULES_FILE = Path.home() / ".codex" / "rules" / "super_aide_p0_test.rules"
POWERSHELL = r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"


def list_hooks(codex: Codex, cwd: Path) -> list[dict]:
    resp = codex._client.request("hooks/list", {"cwds": [str(cwd)]}, response_model=HooksListResponse)
    data = resp.model_dump(by_alias=True, exclude_none=True, mode="json")
    return [h for entry in data.get("data", []) for h in entry.get("hooks", [])]


def part_a(tmp: Path) -> None:
    print("=== A. 原生钩子 + 只信任我们自己的钩子 ===")
    with Codex(CodexConfig(cwd=str(tmp), config_overrides=(HOOK_OVERRIDE,))) as codex:
        ours = [h for h in list_hooks(codex, tmp) if h.get("source") == "sessionFlags"]
    if not ours:
        print("  没找到注入的钩子")
        return
    key, digest = ours[0]["key"], ours[0]["currentHash"]
    print(f"  钩子 key={key}  hash={digest[:16]}…  初始信任={ours[0]['trustStatus']}")

    trust = "hooks.state={" + json.dumps(key) + "={trusted_hash=" + json.dumps(digest) + "}}"
    HOOK_LOG.unlink(missing_ok=True)
    with Codex(CodexConfig(cwd=str(tmp), config_overrides=(HOOK_OVERRIDE, trust))) as codex:
        codex._client._approval_handler = approval_handler
        status = [h["trustStatus"] for h in list_hooks(codex, tmp) if h.get("source") == "sessionFlags"]
        print(f"  加上精确信任后：{status}")
        thread = codex.thread_start(sandbox=Sandbox.full_access, approval_mode=ApprovalMode.deny_all,
                                    ephemeral=True, cwd=str(tmp))
        run_turn(thread, ("按顺序用命令行执行，每条单独执行，不要合并：\n1. echo hello\n"
                          "2. echo SUPER_AIDE_CANARY_BLOCK\n最后用中文简短汇报每条的结果。"),
                 "钩子拦截", effort="low", timeout_s=180)
    lines = HOOK_LOG.read_text(encoding="utf-8").splitlines() if HOOK_LOG.exists() else []
    print(f"  钩子被调用 {len(lines)} 次")
    for line in lines[:3]:
        payload = json.loads(line)
        print(f"    字段 {sorted(payload)}；tool_name={payload.get('tool_name')}；"
              f"tool_input={str(payload.get('tool_input'))[:110]}")


def part_b(tmp: Path) -> None:
    print("\n=== B. ~/.codex/rules 的 forbidden 规则（临时测试文件）===")
    RULES_FILE.write_text(
        'prefix_rule(pattern=["echo", "SUPER_AIDE_CANARY_A"], decision="forbidden")\n'
        f"prefix_rule(pattern={json.dumps([POWERSHELL, '-Command', 'echo SUPER_AIDE_CANARY_B'])}, "
        'decision="forbidden")\n',
        encoding="utf-8")
    try:
        with Codex(CodexConfig(cwd=str(tmp))) as codex:
            codex._client._approval_handler = approval_handler
            thread = codex.thread_start(sandbox=Sandbox.full_access, approval_mode=ApprovalMode.deny_all,
                                        ephemeral=True, cwd=str(tmp))
            run_turn(thread, ("按顺序用命令行执行，每条单独执行，不要合并：\n"
                              "1. echo SUPER_AIDE_CANARY_A\n2. echo SUPER_AIDE_CANARY_B\n"
                              "最后用中文简短汇报每条的结果。"),
                     "规则拦截", effort="low", timeout_s=180)
    finally:
        RULES_FILE.unlink(missing_ok=True)
        print(f"  测试规则文件已删除：{not RULES_FILE.exists()}")


if __name__ == "__main__":
    tmp = Path(tempfile.mkdtemp(prefix="super_aide_p0_guard_"))
    part_a(tmp)
    part_b(tmp)
