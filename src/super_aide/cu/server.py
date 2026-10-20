"""自研 Computer Use / Browser Use 的 MCP 工具服务器（stdio）。Claude 和 Codex 都接这一个。

    python -m super_aide.cu.server

环境变量：AIDE_APP_PID（Super Aide 主进程，它的窗口不能操作）、AIDE_BLOCKED_APPS（隐私名单，分号分隔）、
AIDE_MODE（ask：问答模式，只注册看和指引的工具，act、浏览器导航这些会改动东西的工具根本不存在）。
"""

from __future__ import annotations

import sys

sys.coinit_flags = 0  # COM 用多线程模式：MCP 在工作线程里调用工具，UIA 对象要能跨线程用

import ctypes  # noqa: E402

ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # 每显示器 DPI 感知：坐标都是物理像素

import logging  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402

import win32api  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402
from mcp.server.mcpserver.utilities.types import Image  # noqa: E402
from PIL import Image as PILImage  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from ..snapshot import uia as snapshot_uia  # noqa: E402
from ..snapshot import uiawalk, win32  # noqa: E402
from . import browser, elements, inputs, observe, ocr  # noqa: E402
from .actions import Action, Runner, Session, Stopped, find_window, win32gui_title  # noqa: E402
from .guard import GUARD  # noqa: E402

log = logging.getLogger("aide-computer")
OWN_PID = int(os.environ.get("AIDE_APP_PID", "0") or 0)
MODE = os.environ.get("AIDE_MODE", "act")
BLOCKED = {a for a in os.environ.get("AIDE_BLOCKED_APPS", "").split(";") if a}
LOCK = threading.Lock()  # 动作不能交错：同一时间只执行一个工具
#: obs：最近一次观察；fg_after：上一步做完时的前台窗口；given_back：上一步做完还给用户的窗口
STATE: dict = {"obs": None, "fg_after": None, "given_back": None}
GUARD_NOTE = "助手正在用键鼠，马上好 · Esc 停止"

INSTRUCTIONS = """用这些工具像人一样操作 Windows 上的任何应用和浏览器（你正在用的浏览器，已登录的网站都在）。
做法：observe 看窗口 → act 用控件编号操作（可以一次给几步）→ 看 act 返回的新画面确认结果。
- 优先用控件编号 id，比坐标准。界面没交出控件的地方（画布、远程桌面、游戏、自绘界面）也有编号：
  控件太少时会自动把截图上的字认出来编上号（类型 OCR），也可以 observe_window(ocr=true) 强制认一遍；没有字的图标再用截图坐标 x、y。
- 要看清文字（报错、代码、长页面、表格）用 read：逐字原文，包括滚动出去的部分，比看截图准，拼写以它为准。
- 能用快捷键就用快捷键；字太小看不清用 zoom；找不到某个按钮用 find 按名字找（包括还没滚动到的，也会认图找）。
- 浏览器：browser 工具读网址、打开网址、前进后退、切标签页；网页里的按钮、输入框就是普通控件。
- 动作默认直接操作控件（不动鼠标）；如果点了没反应，同一步改用 method="mouse" 再试。
- 用户可能同时在用电脑：需要真实键鼠的那一刻会短暂挡住用户的键鼠，做完把鼠标和用户正在用的窗口还给他，这些都是自动的。
- 命令行或接口能做的事别用界面做。"""

ASK_INSTRUCTIONS = """问答模式：只能看，不能操作。observe_window 看窗口里的控件和截图，find 找控件，zoom 看细节，
read 读文字（逐字原文，包括滚动出去的部分，比看截图准）。
回答"怎么操作"时，可以用 point 把要点的地方在用户屏幕上圈出来（可以一次圈几个，编号和你回答里的步骤对应）。"""

server = MCPServer("aide-computer", instructions=ASK_INSTRUCTIONS if MODE == "ask" else INSTRUCTIONS)
_highlighter = None


def _guide():
    """屏幕上的透明提示层（圈位置、护栏提示）。第一次用时才建。"""
    global _highlighter
    if _highlighter is None:
        from .guide import Highlighter

        _highlighter = Highlighter()
    return _highlighter


def _scale_at(pos: tuple[int, int]) -> float:
    """pos 所在显示器的缩放比例（提示要按它画，高分屏上才不会太小）。"""
    try:
        monitor = win32api.MonitorFromPoint(pos, 2)  # MONITOR_DEFAULTTONEAREST
        dx, dy = ctypes.c_uint(), ctypes.c_uint()
        ctypes.windll.shcore.GetDpiForMonitor(ctypes.c_void_p(int(monitor)), 0, ctypes.byref(dx), ctypes.byref(dy))
        return (dx.value or 96) / 96
    except Exception:  # noqa: BLE001
        return 1.0


def _on_blocked(pos: tuple[int, int]) -> None:
    if _highlighter is not None:  # 钩子回调里不建窗口：护栏开之前已经建好了
        _highlighter.note(GUARD_NOTE, pos, 1.6, _scale_at(pos))


GUARD.on_blocked = _on_blocked
GUARD.enabled = MODE == "act"


def _user_window(target: int) -> int:
    """用户是不是正在用别的窗口：上一步做完之后，用户自己切到了别的窗口（或者还在用上次还给他的那个）。
    是的话返回那个窗口，这一步做完把前台还给他，免得他接着打的字落进助手正在操作的窗口里。"""
    fg = win32.foreground()
    if fg is None or STATE["fg_after"] is None or fg.hwnd == target or fg.pid == OWN_PID or not fg.title:
        return 0
    if fg.process.lower() in {b.lower() for b in BLOCKED}:
        return 0
    return fg.hwnd if fg.hwnd != STATE["fg_after"] or fg.hwnd == STATE["given_back"] else 0


def _give_back(hwnd: int) -> str:
    """把前台还给用户正在用的窗口，返回给模型的说明（前台本来就是它时不用说）。"""
    STATE["given_back"] = None
    if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
        return ""
    STATE["given_back"] = hwnd
    fg = win32.foreground()
    if fg is not None and fg.hwnd == hwnd:
        return ""  # 这一步没动前台（比如都是直接操作控件）
    inputs.focus_window(hwnd)
    GUARD.release(keep_cursor=True)
    info = win32.window_info(hwnd)
    return f"（用户正在用「{info.title[:40] if info else '别的窗口'}」：这一步做完已把前台还给用户，下一步要用键鼠时会自动切回来）"


def _remember_foreground() -> None:
    fg = win32.foreground()
    STATE["fg_after"] = fg.hwnd if fg is not None else None


def tool(**kwargs):
    """注册工具。modes 里没有当前模式的不注册（问答模式只要看和指引）。
    问答模式也能用的工具（只看、只指）标成只读：Codex 在只读沙箱里，没标只读的工具要审批，
    而我们不审批，会被直接拒掉（实测）。"""
    modes = kwargs.pop("modes", ("ask", "act"))

    def wrap(fn):
        if MODE in modes:
            annotations = ToolAnnotations(read_only_hint=True) if "ask" in modes else None
            server.tool(structured_output=False, annotations=annotations, **kwargs)(fn)
        return fn

    return wrap


def _image(img: PILImage.Image, fmt: str = "JPEG") -> Image:
    return Image(data=observe.encode(img, fmt), format="jpeg" if fmt == "JPEG" else fmt.lower())


def _observe(hwnd: int, screenshot: bool = True, use_ocr: bool | None = None) -> list:
    Session(None, BLOCKED, OWN_PID).check_window(hwnd)
    obs = observe.observe(hwnd, marks=screenshot, use_ocr=use_ocr)
    STATE["obs"] = obs
    content: list = [observe.describe(obs)]
    if screenshot and obs.image is not None:
        content.append(_image(obs.image))
    return content


@tool()
def observe_window(window: str = "", screenshot: bool = True, ocr: bool = False) -> list:
    """看一个窗口：返回能操作的控件列表（带编号）和画好编号的截图。
    window：标题或进程名的一部分，或窗口句柄；不填就是当前前台窗口。screenshot=false 只要文字列表（更快、更省）。
    ocr=true：把截图上的字也认出来编上号（界面没交出控件的地方，比如画布、远程桌面里的按钮）。控件太少时会自动认。"""
    with LOCK:
        hwnd = find_window(window, OWN_PID)
        if not hwnd:
            return [f"没找到窗口「{window}」。用 windows 工具看看都有哪些窗口。"]
        return _observe(hwnd, screenshot, use_ocr=True if ocr else None)


@tool(modes=("act",))
def act(actions: list[Action], observe_after: bool = True) -> list:
    """按顺序执行一组动作（失败就停在那一步），默认执行完再观察一次并返回新的截图。
    动作 do 可以是：click、double_click、right_click、hover、type、key、scroll、drag、select、toggle、focus、wait、wait_for、wait_gone。
    等事情做完用 wait_for（等某个文字出现）或 wait_gone（等某个文字消失，比如"正在下载"、运行中才有的"中断"按钮），比固定 wait 准。
    目标用 id（observe 里的编号）或截图坐标 x、y。编号只在最近一次观察里有效。"""
    with LOCK:
        session = Session(STATE["obs"], BLOCKED, OWN_PID)
        if not session.hwnd and not any(a.do in ("focus", "wait") for a in actions):
            return ["还没有观察任何窗口：先用 observe_window，或者第一步用 focus 指定窗口。"]
        if session.hwnd and not uiawalk.wait_responsive(session.hwnd):
            return [observe.unresponsive(win32gui_title(session.hwnd))]
        _guide()  # 护栏挡住用户时要在鼠标旁边提示，提示层先建好
        user = _user_window(session.hwnd)
        try:
            lines = Runner(session).run(actions)
        except (Stopped, inputs.Interrupted) as e:
            _give_back(user)
            _remember_foreground()
            return [f"已停止：{e}"]
        target, moved = _after_target(session.hwnd, user) if observe_after else (0, "")  # 先看前台，再还前台
        note = _give_back(user) or moved
        if note:
            lines.append(note)
        _remember_foreground()
        content: list = ["\n".join(lines)]
        if target:
            try:
                content += _observe(target)
            except Exception as e:  # noqa: BLE001
                content.append(f"（执行完再观察失败：{e}）")
        return content


def _after_target(hwnd: int, user: int = 0) -> tuple[int, str]:
    """执行完看哪个窗口，以及要不要告诉模型前台变了。
    目标程序弹出了新窗口（对话框、新窗口）就看新的；前台是别的程序（多半是用户在用）就还看原来的，只提一句。"""
    fg = win32.foreground()
    if (fg is None or fg.hwnd in (hwnd, user) or fg.pid == OWN_PID or not fg.title
            or fg.process.lower() in {b.lower() for b in BLOCKED}):
        return hwnd, ""
    target = win32.window_info(hwnd) if hwnd else None
    if target is None or fg.pid == target.pid:
        return fg.hwnd, ""
    return hwnd, f"（前台现在是「{fg.title[:40]}」（{fg.process}），要看它就用 observe_window）"


@tool()
def zoom(x0: int, y0: int, x1: int, y1: int) -> list:
    """放大最近一次截图里的一块区域（截图坐标），返回原始分辨率的图，看清小字和小图标。坐标仍按原来那张截图算。"""
    with LOCK:
        obs = STATE["obs"]
        if obs is None or obs.full is None:
            return ["还没有截图，先 observe_window。"]
        sx0, sy0 = obs.to_physical(min(x0, x1), min(y0, y1))
        sx1, sy1 = obs.to_physical(max(x0, x1), max(y0, y1))
        ox, oy = obs.origin
        crop = obs.full.crop((sx0 - ox, sy0 - oy, max(sx1 - ox, sx0 - ox + 1), max(sy1 - oy, sy0 - oy + 1)))
        scale = observe.fit(crop.width, crop.height)
        if scale < 1:
            crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), PILImage.LANCZOS)
        return [f"区域 ({x0},{y0})-({x1},{y1}) 的原始分辨率图：", _image(crop, "PNG")]


@tool()
def find(text: str, role: str = "") -> str:
    """在最近观察的窗口里按名字（或值）找控件，包括还没滚动到可视区的。找到的会加上新编号，可以直接用来 act（会自动滚过去）。
    role 可选：Button、Edit、Link、CheckBox、ListItem、MenuItem、TabItem 等。"""
    with LOCK:
        obs = STATE["obs"]
        if obs is None:
            return "先用 observe_window 看一个窗口。"
        if not uiawalk.wait_responsive(obs.hwnd):
            return observe.unresponsive(obs.title)
        found = elements.search(obs.hwnd, text, role)
        how = ""
        if not found and not role:
            found, how = _find_on_screen(obs, text), "（界面没交出这个控件，是从截图上认出来的字，会用鼠标点）"
        if not found:
            return (f"没找到名字里包含「{text}」的控件，截图上也没认出这几个字。"
                    "很大的页面一次找不全（为了不卡住程序，最多找 3 秒）：可以先滚动到大概的位置再找。")
        start = max(obs.elements, default=0) + 1
        lines = []
        for i, el in enumerate(found, start):
            el.id = i
            obs.elements[i] = el
            cx, cy = obs.to_image(*el.center)
            states = f" ({', '.join(el.states)})" if el.states else ""
            value = f" value=\"{el.value}\"" if el.value else ""
            lines.append(f"[{i}] {el.role} \"{el.name}\"{value}{states} @{cx},{cy}")
        return f"找到{how}：\n" + "\n".join(lines)


def _find_on_screen(obs, text: str) -> list:
    """在最近一次截图上认字，找包含 text 的文字块（不分大小写、不管空格）。"""
    if obs.full is None:
        return []
    want = text.replace(" ", "").lower()
    hits = [p for p in ocr.phrases(obs.full) if want in p.text.replace(" ", "").lower()]
    return observe.ocr_elements(obs.full, obs.origin, [], 0, phrases=hits)


@tool()
def read(id: int | None = None, start: int = 0, max_chars: int = 8000) -> str:
    """读文字（逐字原文，比看截图准）：给编号就读那个控件（文档、编辑框、列表等）的全部文字；
    不给就读整个窗口的完整内容，包括滚动出去、没显示出来的部分（网页全文、文档、代码、各控件的文字）。
    内容很长时用 start 接着往后读。界面没交出文字的地方（图片、画布、远程桌面）用 OCR 认图。"""
    with LOCK:
        obs = STATE["obs"]
        if obs is None:
            return "先用 observe_window 看一个窗口。"
        if not uiawalk.wait_responsive(obs.hwnd):
            return observe.unresponsive(obs.title)
        if id is not None:
            el = obs.elements.get(id)
            if el is None:
                return f"没有编号 {id} 的控件。"
            text = _element_text(el)
        else:
            text, _ = snapshot_uia.window_content(_Direct(), obs.hwnd, budget_s=2.5)
        text = text.strip()
        if not text and obs.full is not None:
            text = ocr.text_of(obs.full)
            if text:
                text = "（界面没交出文字，下面是 OCR 认图的结果，个别字可能认错）\n" + text
        if not text:
            return "这里读不到文字（可能是图片或自绘界面），请看截图，必要时 zoom。"
        piece = text[start:start + max_chars]
        rest = len(text) - start - len(piece)
        return piece + (f"\n……（共 {len(text)} 字，后面还有 {rest} 字：用 start={start + len(piece)} 接着读）"
                        if rest > 0 else "")


class _Direct:
    """让 snapshot.uia 里的函数在当前线程直接执行（它们原本跑在 UiaWorker 里）。"""

    @property
    def _uia(self):
        return elements._client().IUIAutomation


def _element_text(el) -> str:
    import uiautomation as auto

    c = auto.Control.CreateControlFromElement(el.raw)
    try:
        pattern = c.GetTextPattern()
        if pattern:
            return snapshot_uia.newlines(pattern.DocumentRange.GetText(200_000))
    except Exception:  # noqa: BLE001
        pass
    try:
        pattern = c.GetValuePattern()
        if pattern:
            return snapshot_uia.newlines(pattern.Value or "")
    except Exception:  # noqa: BLE001
        pass
    names = [c.Name] + [child.Name for child, _ in auto.WalkControl(c, maxDepth=6) if child.Name]
    return "\n".join(dict.fromkeys(n for n in names if n))


@tool()
def windows() -> str:
    """列出所有打开的窗口（从上到下），可以把标题或进程名传给 observe_window 或 focus。"""
    with LOCK:
        rows = []
        for w in win32.visible_windows():
            if w.pid == OWN_PID or not w.title:
                continue
            flag = "（最小化）" if w.minimized else ""
            blocked = "（隐私名单，不能操作）" if w.process.lower() in {b.lower() for b in BLOCKED} else ""
            rows.append(f"- {w.title}（{w.process}）{flag}{blocked}")
        return "\n".join(rows) or "没有可见的窗口"


@tool(name="browser", modes=("act",))
def browser_tool(command: str, value: str = "", window: str = "") -> list:
    """在你正在用的浏览器里操作（Edge、Chrome、Firefox……已登录的网站都在）。
    command：url（读网址）、go（在当前标签打开 value 网址）、new_tab（新标签打开 value）、back、forward、reload、
    tabs（列出标签页）、tab（切到第 value 个）、next_tab、prev_tab、close_tab。window：哪个浏览器窗口，不填就用最近观察的或最上面的。"""
    with LOCK:
        hwnd = _browser_window(window)
        if not hwnd:
            return ["没找到浏览器窗口。可以先用命令行打开浏览器，或者 windows 看看。"]
        session = Session(None, BLOCKED, OWN_PID)
        session.check_window(hwnd)
        _guide()
        user = _user_window(hwnd)
        try:
            if command not in ("url", "tabs"):
                inputs.focus_window(hwnd)
            result = browser.run(hwnd, command, value)
        except (Stopped, inputs.Interrupted) as e:
            return [f"已停止：{e}"]
        finally:
            GUARD.release(target=hwnd)
        note = _give_back(user)
        _remember_foreground()
        content: list = [result + (f"\n{note}" if note else "")]
        if command in ("go", "new_tab", "back", "forward", "reload", "tab", "next_tab", "prev_tab", "close_tab"):
            content += _observe(hwnd)
        return content


class Target(BaseModel):
    id: int | None = Field(None, description="observe 列表里的控件编号")
    x0: int | None = Field(None, description="没有编号时：截图上区域的左上角横坐标")
    y0: int | None = None
    x1: int | None = Field(None, description="区域右下角横坐标")
    y1: int | None = None
    label: str = Field("", description="标签上的一句说明，比如「点这里打开设置」")


@tool()
def point(targets: list[Target], seconds: float = 30) -> str:
    """在用户的屏幕上把要点的地方圈出来（不进截图、不挡鼠标），每个框带编号和说明，编号和你回答里的步骤对应。
    targets：控件编号 id，或者截图上的区域 x0,y0,x1,y1。seconds：显示多久（最多 300 秒），用户收起回答时也会消失。"""
    with LOCK:
        obs = STATE["obs"]
        if obs is None:
            return "先用 observe_window 看一下窗口，才能圈出位置。"
        boxes = []
        for t in targets:
            if t.id is not None:
                el = obs.elements.get(t.id)
                if el is None:
                    return f"没有编号 {t.id} 的控件，请重新 observe_window。"
                boxes.append((el.rect, t.label))
            elif None not in (t.x0, t.y0, t.x1, t.y1):
                ax, ay = obs.to_physical(min(t.x0, t.x1), min(t.y0, t.y1))
                bx, by = obs.to_physical(max(t.x0, t.x1), max(t.y0, t.y1))
                boxes.append(((ax, ay, bx, by), t.label))
        if not boxes:
            return "没有可以圈的目标：给控件编号 id，或者区域 x0,y0,x1,y1。"
        dpi = ctypes.windll.user32.GetDpiForWindow(obs.hwnd) or 96
        _guide().show(boxes, seconds, scale=dpi / 96)
        return f"已在屏幕上圈出 {len(boxes)} 处，显示 {min(max(seconds, 3), 300):g} 秒。"


def _browser_window(spec: str) -> int:
    if spec:
        return find_window(spec, OWN_PID)
    obs = STATE["obs"]
    if obs is not None and obs.process.lower() in browser.BROWSERS and win32.window_info(obs.hwnd):
        return obs.hwnd
    for w in win32.visible_windows():
        if w.process.lower() in browser.BROWSERS and w.pid != OWN_PID and not w.minimized:
            return w.hwnd
    return 0


def main() -> None:
    # DeepSeek Harness 桌面版把自己当 Node 跑（ELECTRON_RUN_AS_NODE=1），这个变量会传给我们：
    # 不清掉的话，从这里打开的 VS Code 这类 Electron 程序会以 Node 的方式启动、打不开
    os.environ.pop("ELECTRON_RUN_AS_NODE", None)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    server.run("stdio")


if __name__ == "__main__":
    main()
