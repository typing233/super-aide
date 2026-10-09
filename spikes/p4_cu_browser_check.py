"""自研 Browser Use 自检（不调用模型）：在新的 Edge 窗口里打开本地靶子网页，用工具操作，读页面文字核对，最后关掉这个窗口。

会弹出一个 Edge 窗口并操作它，大约 20 秒。

    uv run --no-sync python -X utf8 spikes/p4_cu_browser_check.py
"""

from __future__ import annotations

import sys

sys.coinit_flags = 0

import subprocess  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from super_aide.cu import server  # noqa: E402
from super_aide.cu.actions import Action  # noqa: E402
import win32gui  # noqa: E402

from super_aide.snapshot import win32  # noqa: E402

PAGE = (Path(__file__).parent / "p4_cu_web.html").resolve()
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
results: list[tuple[str, bool, str, float]] = []


def check(name, ok, detail="", ms=0.0):
    results.append((name, ok, detail, ms))


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t) * 1000


def eid(text: str, role: str = "") -> int:
    for e in server.STATE["obs"].elements.values():
        if text in e.name and (not role or e.role == role):
            return e.id
    raise LookupError(f"没找到 {role} {text}")


def page_text() -> str:
    return server.read()


def main() -> int:
    for w in win32.visible_windows():  # 上次没关掉的靶子窗口会被误认成这次的
        if w.title.startswith("CU 网页靶子"):
            win32gui.PostMessage(w.hwnd, 0x0010, 0, 0)
    time.sleep(0.5)
    before = {w.hwnd for w in win32.visible_windows()}
    subprocess.Popen([str(EDGE), "--new-window", f"{PAGE.as_uri()}?run={int(time.time())}"])
    hwnd = 0
    for _ in range(60):
        hwnd = next((w.hwnd for w in win32.visible_windows()
                     if w.title.startswith("CU 网页靶子") and w.hwnd not in before), 0)
        if hwnd:
            break
        time.sleep(0.25)
    if not hwnd:
        print("Edge 窗口没出现")
        return 1
    time.sleep(1.0)
    try:
        out, ms = timed(lambda: server.observe_window(str(hwnd)))
        text = out[0]
        check("观察网页：表单控件都在", all(k in text for k in ("姓名", "城市", "我同意条款", "提交")), text[:400], ms)
        check("读到网址", "p4_cu_web.html" in text, text.splitlines()[1] if len(text.splitlines()) > 1 else text)
        print(text[:1500])

        def act(actions, observe_after=False):
            return timed(lambda: server.act([Action(**a) for a in actions], observe_after=observe_after))

        out, ms = act([{"do": "type", "id": eid("姓名", "Edit"), "text": "王五", "replace": True}])
        check("网页输入中文", "失败" not in out[0], out[0], ms)
        out, ms = act([{"do": "select", "id": eid("城市", "ComboBox"), "text": "广州"}])
        check("网页下拉选择", "失败" not in out[0], out[0], ms)
        server.observe_window(str(hwnd), screenshot=False)
        out, ms = act([{"do": "click", "id": eid("我同意条款", "CheckBox")}])
        check("网页勾选", "失败" not in out[0], out[0], ms)
        server.observe_window(str(hwnd), screenshot=False)
        out, ms = act([{"do": "type", "id": eid("备注", "Edit"), "text": "两行\n备注"}])
        check("网页多行输入", "失败" not in out[0], out[0], ms)
        server.observe_window(str(hwnd), screenshot=False)
        out, ms = act([{"do": "click", "id": eid("提交", "Button")}, {"do": "wait_for", "text": "已提交", "seconds": 5}])
        body = page_text()
        check("网页点击提交并核对结果", "已提交 1 次：王五｜广州｜同意｜两行\n备注" in body or "已提交 1 次：王五｜广州｜同意｜两行 备注" in body,
              out[0] + " ‖ " + body[body.find("已提交"):body.find("已提交") + 60], ms)

        server.observe_window(str(hwnd), screenshot=False)
        out, ms = act([{"do": "click", "id": eid("卡片按钮")}])
        body = page_text()
        check("只听 pointerdown 的按钮（UIA 点不动时）", "卡片按下了" in body, out[0], ms)
        if "卡片按下了" not in body:
            server.observe_window(str(hwnd), screenshot=False)
            out, ms = act([{"do": "click", "id": eid("卡片按钮"), "method": "mouse"}])
            body = page_text()
            check("  改用真实鼠标", "卡片按下了" in body, out[0], ms)

        out, ms = timed(lambda: server.find("远处的按钮"))
        check("找到可视区外的按钮", "远处的按钮" in out, out, ms)
        far = int(out.split("[")[1].split("]")[0])
        out, ms = act([{"do": "click", "id": far}])
        body = page_text()
        check("点击可视区外的按钮（自动滚过去）", "远处的按钮被点了" in body, out[0], ms)

        out, ms = timed(lambda: server.browser_tool("url", window=str(hwnd)))
        check("browser url", "p4_cu_web.html" in out[0], out[0], ms)
        out, ms = timed(lambda: server.browser_tool("tabs", window=str(hwnd)))
        check("browser tabs", "CU 网页靶子" in out[0], out[0], ms)
    finally:
        try:
            server.act([Action(do="focus", window=str(hwnd)), Action(do="key", keys="ctrl+w")], observe_after=False)
        except Exception:  # noqa: BLE001
            pass

    bad = [r for r in results if not r[1]]
    for name, ok, detail, ms in results:
        timing = f"{ms:6.0f}ms" if ms else "       "
        print(f"{'PASS' if ok else 'FAIL'} {timing}  {name}" + (f"  [{detail[:220]}]" if not ok else ""))
    print(f"\n{len(results) - len(bad)}/{len(results)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
