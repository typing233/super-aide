"""自研 Computer Use 自检（不调用模型）：起一个靶子窗口，用工具函数逐项操作，读靶子写出的状态核对，记下每步耗时。
最后再通过真正的 MCP 协议（stdio）调一次，确认图片和文字都能传回去。

会在屏幕左上角弹出一个小窗口并操作它，大约 20 秒。

    uv run --no-sync python -X utf8 spikes/p4_cu_check.py
"""

from __future__ import annotations

import sys

sys.coinit_flags = 0

import asyncio  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from super_aide.cu import server  # noqa: E402  （导入时设好 DPI 感知）
from super_aide.cu.actions import Action  # noqa: E402

HERE = Path(__file__).parent
results: list[tuple[str, bool, str, float]] = []


def state(path: Path) -> dict:
    for _ in range(20):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            time.sleep(0.05)
    return {}


def settle(path: Path, key: str, want, timeout: float = 1.5):
    """等靶子把变化写进状态文件（程序处理粘贴、信号都要一点时间）。"""
    end = time.time() + timeout
    while time.time() < end:
        if state(path).get(key) == want:
            return want
        time.sleep(0.05)
    return state(path).get(key)


def check(name: str, ok: bool, detail: str = "", ms: float = 0.0) -> None:
    results.append((name, ok, detail, ms))


def element_id(text: str, role: str = "") -> int:
    obs = server.STATE["obs"]
    for e in obs.elements.values():
        if e.name == text and (not role or e.role == role):
            return e.id
    raise LookupError(f"没找到控件 {role} {text}")


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t) * 1000


def main() -> int:
    state_file = Path(tempfile.mkdtemp()) / "state.json"
    target = subprocess.Popen([sys.executable, str(HERE / "p4_cu_target.py"), str(state_file)])
    try:
        for _ in range(50):
            if state_file.exists():
                break
            time.sleep(0.1)
        time.sleep(0.8)

        out, ms = timed(lambda: server.observe_window("CU 靶子"))
        text = out[0]
        check("观察：列出控件", all(k in text for k in ("姓名", "城市", "我同意条款", "提交", "清空")), text[:300], ms)
        check("观察：带截图", len(out) == 2, f"{len(out)} 项")
        print(text)

        def act(actions, observe_after=False):
            return timed(lambda: server.act([Action(**a) for a in actions], observe_after=observe_after))

        out, ms = act([{"do": "type", "id": element_id("姓名", "Edit"), "text": "张三", "replace": True}])
        check("输入（UIA 填值）", state(state_file).get("name") == "张三", out[0], ms)

        out, ms = act([{"do": "select", "id": element_id("城市", "ComboBox"), "text": "深圳"}])
        check("下拉选择", state(state_file).get("city") == "深圳", out[0], ms)

        out, ms = act([{"do": "toggle", "id": element_id("我同意条款"), "on": True}])
        check("勾选", state(state_file).get("agree") is True, out[0], ms)

        server.observe_window("CU 靶子", screenshot=False)
        out, ms = act([{"do": "click", "id": element_id("橙子", "ListItem")}])
        check("列表选中", state(state_file).get("fruit") == "橙子", out[0], ms)

        server.observe_window("CU 靶子", screenshot=False)
        out, ms = act([{"do": "type", "id": element_id("备注", "Edit"), "text": "第一行 Hello\n第二行：中文😀"}])
        notes = settle(state_file, "notes", "第一行 Hello\n第二行：中文😀")
        check("多行中文粘贴（含表情）", notes == "第一行 Hello\n第二行：中文😀", out[0] + " → " + repr(notes), ms)

        out, ms = act([{"do": "click", "id": element_id("提交", "Button")},
                       {"do": "wait_for", "text": "已提交", "seconds": 5}])
        check("点击按钮（UIA）+ 等文字出现", state(state_file).get("submitted") == 1, out[0], ms)

        server.observe_window("CU 靶子", screenshot=False)
        out, ms = act([{"do": "click", "id": element_id("清空", "Button"), "method": "mouse"}])
        s = state(state_file)
        check("真实鼠标点击", s.get("cleared") == 1 and s.get("name") == "", out[0], ms)

        server.observe_window("CU 靶子", screenshot=False)
        out, ms = act([{"do": "type", "id": element_id("姓名", "Edit"), "text": "李四", "replace": True,
                        "method": "mouse", "enter": True}])
        check("真实键盘输入 + 回车", state(state_file).get("name") == "李四", out[0], ms)

        out, ms = act([{"do": "key", "keys": "ctrl+a, backspace"}])
        check("组合键", state(state_file).get("name") == "", out[0], ms)

        obs = server.STATE["obs"]
        cx, cy = obs.to_image(*obs.elements[element_id("提交", "Button")].center)
        out, ms = act([{"do": "click", "x": cx, "y": cy}])
        check("按截图坐标点击", state(state_file).get("submitted") == 2, out[0], ms)

        out, ms = timed(lambda: server.find("葡萄"))
        check("按名字找控件", "葡萄" in out, out, ms)

        out, ms = timed(lambda: server.zoom(0, 0, 200, 120))
        check("放大", len(out) == 2, out[0], ms)

        out, ms = timed(lambda: server.read())
        check("读窗口文字", "已提交" in out, out[:120], ms)

        out, ms = act([{"do": "click", "id": 9999}])
        check("错误编号给出明确提示", "失败" in out[0] and "observe" in out[0], out[0], ms)

        out, ms = act([{"do": "toggle", "id": element_id("我同意条款"), "on": False}], observe_after=True)
        check("执行后自动观察", len(out) == 3 and "CU 靶子窗口" in out[1], f"{len(out)} 项", ms)

        mcp_ok, detail = asyncio.run(via_mcp())
        check("MCP 协议：工具列表 + 观察返回文字和图片", mcp_ok, detail)
    finally:
        target.terminate()

    bad = [r for r in results if not r[1]]
    for name, ok, detail, ms in results:
        timing = f"{ms:6.0f}ms" if ms else "       "
        print(f"{'PASS' if ok else 'FAIL'} {timing}  {name}" + (f"  [{detail[:200]}]" if not ok else ""))
    print(f"\n{len(results) - len(bad)}/{len(results)} 通过")
    return 1 if bad else 0


async def via_mcp() -> tuple[bool, str]:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-X", "utf8", "-m", "super_aide.cu.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = sorted(t.name for t in (await session.list_tools()).tools)
            result = await session.call_tool("observe_window", {"window": "CU 靶子"})
            kinds = [c.type for c in result.content]
            ok = {"observe_window", "act", "zoom", "find", "read", "windows", "browser"} <= set(tools) \
                and kinds == ["text", "image"] and not result.is_error
            return ok, f"tools={tools} content={kinds}"


if __name__ == "__main__":
    sys.exit(main())
