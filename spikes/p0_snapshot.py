"""P0-⑤ 快照验证：所有窗口的截图 + 文字，各要多久、能拿到多少。

只打印耗时、尺寸、字数这类元数据，不打印窗口标题和内容（避免隐私进入日志）；
实际截图和文字写到 spikes/out/<时间戳>/，该目录已加入 .gitignore。

用法：uv run python spikes/p0_snapshot.py
"""

from __future__ import annotations

import ctypes
import json
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

# 必须在任何窗口/截图调用之前声明 DPI 感知，否则坐标和截图尺寸会按 125% 缩放错位
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2

import mss  # noqa: E402
import uiautomation as auto  # noqa: E402
import win32con  # noqa: E402
import win32gui  # noqa: E402
import win32process  # noqa: E402
import win32ui  # noqa: E402
from PIL import Image  # noqa: E402

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi

PW_RENDERFULLCONTENT = 0x2
DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

PER_WINDOW_TEXT_BUDGET_S = 0.8
MAX_TEXT_CHARS = 200_000
OUT = Path(__file__).parent / "out" / datetime.now().strftime("%Y%m%d-%H%M%S")


def process_name(hwnd: int) -> str:
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return f"pid{pid}(拒绝访问)"
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name
        return f"pid{pid}"
    finally:
        kernel32.CloseHandle(h)


def is_cloaked(hwnd: int) -> bool:
    cloaked = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return cloaked.value != 0


def visible_rect(hwnd: int) -> tuple[int, int, int, int]:
    """DWM 可见边界（不含 Win11 窗口四周看不见的缩放边框）。"""
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                    ctypes.byref(r), ctypes.sizeof(r)) == 0:
        return r.left, r.top, r.right, r.bottom
    return win32gui.GetWindowRect(hwnd)


def top_level_windows() -> list[int]:
    """按 Z 序（从上到下）列出用户能看到的应用窗口。"""
    out: list[int] = []

    def cb(hwnd: int, _: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd) or is_cloaked(hwnd):
            return True
        if not win32gui.GetWindowText(hwnd):
            return True
        ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if ex & win32con.WS_EX_TOOLWINDOW:
            return True
        if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
            return True
        out.append(hwnd)
        return True

    win32gui.EnumWindows(cb, None)
    return out


def capture_window(hwnd: int) -> Image.Image | None:
    """PrintWindow + PW_RENDERFULLCONTENT：被其它窗口挡住也能截到；最小化的窗口没有画面。"""
    if win32gui.IsIconic(hwnd):
        return None
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        return None
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    mem_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    try:
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        mem_dc.SelectObject(bmp)
        if not user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), PW_RENDERFULLCONTENT):
            return None
        info = bmp.GetInfo()
        img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                               bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
        # 裁掉看不见的缩放边框，只留 DWM 可见区域
        vl, vt, vr, vb = visible_rect(hwnd)
        return img.crop((vl - l, vt - t, vl - l + (vr - vl), vt - t + (vb - vt)))
    finally:
        win32gui.DeleteObject(bmp.GetHandle())
        mem_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)


def is_blank(img: Image.Image) -> bool:
    lo, hi = img.convert("L").getextrema()
    return hi - lo < 8


def document_text(ctrl: auto.Control) -> str | None:
    """优先走 TextPattern：一次调用拿到整篇文字（网页、文档包括没滚动到的部分）。"""
    try:
        pattern = ctrl.GetPattern(auto.PatternId.TextPattern)
        if pattern:
            return pattern.DocumentRange.GetText(MAX_TEXT_CHARS)
    except Exception:  # noqa: BLE001 - 各应用的 UIA 实现参差不齐，任何异常都按"没有"处理
        pass
    return None


def window_text(hwnd: int) -> tuple[str, str]:
    """返回 (文字, 方法)。先找文档类控件用 TextPattern，否则遍历控件树收集名称和值。"""
    deadline = time.perf_counter() + PER_WINDOW_TEXT_BUDGET_S
    root = auto.ControlFromHandle(hwnd)
    parts: list[str] = []
    for ctrl, _depth in auto.WalkControl(root, includeTop=True, maxDepth=25):
        if time.perf_counter() > deadline:
            parts.append("…（超时截断）")
            break
        ctype = ctrl.ControlType
        if ctype == auto.ControlType.DocumentControl:
            text = document_text(ctrl)
            if text:
                return text, "TextPattern(Document)"
        name = ctrl.Name
        if name:
            parts.append(name)
        if ctype in (auto.ControlType.EditControl, auto.ControlType.ComboBoxControl):
            try:
                vp = ctrl.GetPattern(auto.PatternId.ValuePattern)
                if vp and vp.Value:
                    parts.append(vp.Value)
            except Exception:  # noqa: BLE001
                pass
        if sum(map(len, parts)) > MAX_TEXT_CHARS:
            break
    return "\n".join(parts), "WalkControl"


def focus_and_selection() -> dict:
    t = time.perf_counter()
    out: dict = {}
    try:
        focused = auto.GetFocusedControl()
        out["focused_type"] = focused.ControlTypeName if focused else None
        pattern = focused.GetPattern(auto.PatternId.TextPattern) if focused else None
        if pattern:
            sel = pattern.GetSelection()
            out["selected_chars"] = sum(len(r.GetText(-1)) for r in sel) if sel else 0
    except Exception as e:  # noqa: BLE001
        out["error"] = type(e).__name__
    out["ms"] = round((time.perf_counter() - t) * 1000)
    return out


def browser_url(hwnd: int) -> dict:
    """Chromium 系浏览器地址栏：第一个值像网址的编辑框（不依赖语言和具体浏览器）。"""
    t = time.perf_counter()
    found = None
    root = auto.ControlFromHandle(hwnd)
    for ctrl, _ in auto.WalkControl(root, maxDepth=12):
        if time.perf_counter() - t > 0.5:
            break
        if ctrl.ControlType == auto.ControlType.EditControl:
            try:
                vp = ctrl.GetPattern(auto.PatternId.ValuePattern)
                v = vp.Value if vp else ""
            except Exception:  # noqa: BLE001
                v = ""
            if v and ("." in v or v.startswith(("http", "localhost"))):
                found = v
                break
    return {"found": found is not None, "url_len": len(found or ""),
            "ms": round((time.perf_counter() - t) * 1000)}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "windows").mkdir()
    t_all = time.perf_counter()

    t = time.perf_counter()
    fg = win32gui.GetForegroundWindow()
    fg_proc = process_name(fg)
    fg_ms = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[0])  # monitors[0] = 所有显示器拼成的虚拟屏
        Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX").save(OUT / "screen.png")
    screen_ms = (time.perf_counter() - t) * 1000

    sel = focus_and_selection()
    url = browser_url(fg) if fg_proc.lower() in ("chrome.exe", "msedge.exe", "brave.exe") else None

    print(f"前台：{fg_proc}  取前台信息 {fg_ms:.1f}ms")
    print(f"全屏截图：{shot.size[0]}×{shot.size[1]}  {screen_ms:.0f}ms")
    print(f"焦点与选中文字：{sel}")
    if url is not None:
        print(f"浏览器网址：{url}")

    t = time.perf_counter()
    hwnds = top_level_windows()
    print(f"\n可见窗口 {len(hwnds)} 个（枚举 {(time.perf_counter() - t) * 1000:.0f}ms）")
    print(f"{'#':>2} {'进程':<26} {'状态':<6} {'截图':<16} {'截图ms':>6} {'文字字数':>8} {'文字ms':>6} 方法")

    rows = []
    for i, hwnd in enumerate(hwnds):
        proc = process_name(hwnd)
        state = "最小化" if win32gui.IsIconic(hwnd) else "正常"
        t = time.perf_counter()
        img, cap = None, ""
        try:
            img = capture_window(hwnd)
        except Exception as e:  # noqa: BLE001
            cap = f"失败:{type(e).__name__}"
        cap_ms = (time.perf_counter() - t) * 1000
        if img is not None:
            cap = f"{img.width}×{img.height}" + ("·空白" if is_blank(img) else "")
            img.save(OUT / "windows" / f"{i:02d}_{Path(proc).stem}.png")
        elif not cap:
            cap = "无画面" if state == "最小化" else "无"

        t = time.perf_counter()
        try:
            text, method = window_text(hwnd)
        except Exception as e:  # noqa: BLE001
            text, method = "", f"失败:{type(e).__name__}"
        text_ms = (time.perf_counter() - t) * 1000
        (OUT / "windows" / f"{i:02d}_{Path(proc).stem}.txt").write_text(text, encoding="utf-8")

        print(f"{i:>2} {proc:<26} {state:<6} {cap:<16} {cap_ms:>6.0f} {len(text):>8} {text_ms:>6.0f} {method}")
        rows.append({"i": i, "process": proc, "state": state, "capture": cap,
                     "capture_ms": round(cap_ms), "text_chars": len(text),
                     "text_ms": round(text_ms), "method": method})

    total = (time.perf_counter() - t_all) * 1000
    (OUT / "timings.json").write_text(json.dumps({"windows": rows, "total_ms": round(total)},
                                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n总耗时 {total:.0f}ms（串行，未并行化）  输出：{OUT}")


if __name__ == "__main__":
    main()
