"""执行动作。语义和真实点击完全一样的才用 UIA 直接操作（按钮 Invoke、勾选 Toggle、展开下拉框、
原生输入框 SetValue）：快、不会点偏、窗口被挡住也行。列表项、标签页这类"选中"动作，不同框架里
UIA 的 Select 和真点一下效果不一样（Qt 的列表 Select 后"当前项"不变，自检实测），看得见时用真实鼠标，
看不见（被挡住、在可视区外）才退回 UIA。网页内容（浏览器、Electron 应用）里的点击也一样：UIA 的点击不产生
pointerdown，只听它的前端按钮不会响应（自检实测），所以看得见就真点。指定 method="mouse" 一律用真实键鼠。

你按物理 Esc 时，Super Aide 置位一个命名事件，这里每一步之前都会检查，立刻停下。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
import time
from collections.abc import Callable
from typing import Literal

import uiautomation as auto
from pydantic import BaseModel, Field

from ..snapshot import win32
from ..snapshot.uia import newlines
from . import browser, elements, inputs
from .elements import Element
from .guard import GUARD
from .observe import Observation
from .signals import STOP as STOP_EVENT

PATTERN_TIMEOUT = 3.0  # 有的老控件 Invoke 会一直等到它弹出的对话框关掉才返回
WAIT_MAX_S = 30       # wait 一次最多等这么久（等久了按 Esc 停不下来的感觉很差；要多等就多调几次）
WAIT_FOR_MAX_S = 60   # wait_for 一次最多等这么久
HIDDEN_INPUT_PX = 4   # 宽或高小于这么多像素的输入框是藏起来收键盘输入的（读回来的值核对不了）
SYNCHRONIZE, WAIT_OBJECT_0 = 0x00100000, 0
CLICK_INVOKE = {"Button", "SplitButton", "MenuItem", "Link", "Image", "HeaderItem"}
CLICK_SELECT = {"Radio", "ListItem", "TabItem", "TreeItem", "DataItem"}
TEXT_ROLES = {"Edit", "Document", "ComboBox"}
MOUSE_ACTIONS = {"click", "double_click", "right_click", "scroll", "drag", "select", "type"}  # 可能挪动鼠标的
GA_ROOT = 2
ctypes.windll.user32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
ctypes.windll.user32.WindowFromPoint.restype = ctypes.wintypes.HWND
ctypes.windll.user32.GetAncestor.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint]
ctypes.windll.user32.GetAncestor.restype = ctypes.wintypes.HWND


class Stopped(Exception):
    pass


class Action(BaseModel):
    """一个动作。目标用控件编号 id（优先），或截图上的坐标 x、y。"""

    do: Literal["click", "double_click", "right_click", "hover", "type", "key", "scroll", "drag",
                "select", "toggle", "focus", "wait", "wait_for", "wait_gone"]
    id: int | None = Field(None, description="observe 列表里的控件编号")
    x: int | None = Field(None, description="截图上的横坐标（没有编号时用）")
    y: int | None = Field(None, description="截图上的纵坐标")
    to_id: int | None = Field(None, description="drag 的终点控件")
    to_x: int | None = Field(None, description="drag 的终点横坐标")
    to_y: int | None = Field(None, description="drag 的终点纵坐标")
    text: str | None = Field(None, description="type 要输入的文字；select 的选项名；wait_for 要等出现的文字；"
                                               "wait_gone 要等消失的文字")
    keys: str | None = Field(None, description="key 的组合键，如 ctrl+s；多个用逗号隔开，依次按")
    replace: bool = Field(False, description="type 之前先清空原有内容")
    enter: bool = Field(False, description="type 之后按回车")
    amount: int = Field(3, description="scroll 的格数：正数向下、负数向上")
    on: bool | None = Field(None, description="toggle 的目标状态，不填就是切换")
    seconds: float = Field(1.0, description="wait 等多久（一次最多 30 秒）；wait_for、wait_gone 最多等多久（一次最多 60 秒）")
    window: str | None = Field(None, description="focus 的窗口：标题或进程名的一部分")
    method: Literal["auto", "uia", "mouse"] = Field("auto", description="auto：能直接操作控件就直接操作；mouse：用真实鼠标键盘")


class Session:
    """一次工具调用里的上下文：最近的观察、当前目标窗口、不能碰的窗口。"""

    def __init__(self, obs: Observation | None, blocked: set[str], own_pid: int) -> None:
        self.obs = obs
        self.hwnd = obs.hwnd if obs else 0
        self.blocked = {b.lower() for b in blocked}
        self.own_pid = own_pid

    def check_window(self, hwnd: int) -> None:
        info = win32.window_info(hwnd)
        if info is None:
            raise RuntimeError("目标窗口已经不在了，请重新 observe")
        if info.pid == self.own_pid:
            raise RuntimeError("这是 Super Aide 自己的窗口，不能操作")
        if info.process.lower() in self.blocked:
            raise RuntimeError(f"{info.process} 在隐私名单里，不能操作")


_stop_handle = None


def stop_requested() -> bool:
    global _stop_handle
    if _stop_handle is None:
        _stop_handle = ctypes.windll.kernel32.OpenEventW(SYNCHRONIZE, False, STOP_EVENT) or 0
    return bool(_stop_handle) and ctypes.windll.kernel32.WaitForSingleObject(_stop_handle, 0) == WAIT_OBJECT_0


def _check_stop() -> None:
    if stop_requested():
        raise Stopped("你按了 Esc，已停止")


def _with_timeout(fn: Callable[[], object], seconds: float = PATTERN_TIMEOUT) -> bool:
    """在另一个线程里调 UIA；超时就当已经触发（比如它弹出了对话框还没关）。返回是否按时完成。"""
    box: dict = {}

    def run() -> None:
        try:
            fn()
        except BaseException as e:  # noqa: BLE001
            box["error"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if "error" in box:
        raise box["error"]
    return not t.is_alive()


def _control(el: Element) -> auto.Control:
    return auto.Control.CreateControlFromElement(el.raw)


def _live(el: Element) -> Element:
    """确认控件还在、拿到它现在的位置；不在可视区就先滚过去。认图得来的文字没有控件对象，用观察时的位置。"""
    if el.raw is None:
        return el
    try:
        r = el.raw.CurrentBoundingRectangle
        rect = (int(r.left), int(r.top), int(r.right), int(r.bottom))
        offscreen = bool(el.raw.GetCurrentPropertyValue(elements.P_OFFSCREEN))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"控件 [{el.id}] 已经不在了（界面变了），请重新 observe") from e
    if offscreen and "scrollitem" in el.patterns:
        try:
            _control(el).GetScrollItemPattern().ScrollIntoView()
            time.sleep(0.2)
            r = el.raw.CurrentBoundingRectangle
            rect = (int(r.left), int(r.top), int(r.right), int(r.bottom))
        except Exception:  # noqa: BLE001
            pass
    el.rect = rect
    return el


def _label(el: Element) -> str:
    return f"[{el.id}] {el.role} \"{el.name}\"" if el.name else f"[{el.id}] {el.role}"


class Runner:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---------- 目标 ----------

    def element(self, a: Action, which: str = "id") -> Element | None:
        number = getattr(a, which)
        if number is None:
            return None
        if self.s.obs is None or number not in self.s.obs.elements:
            raise RuntimeError(f"没有编号 {number} 的控件，请先 observe（编号只在最近一次观察里有效）")
        return _live(self.s.obs.elements[number])

    def point(self, a: Action, el: Element | None, prefix: str = "") -> tuple[int, int]:
        if el is not None:
            return el.center
        x, y = getattr(a, f"{prefix}x"), getattr(a, f"{prefix}y")
        if x is None or y is None:
            raise RuntimeError("需要控件编号 id，或者截图坐标 x、y")
        if self.s.obs is None:
            raise RuntimeError("还没有截图，坐标没法换算，请先 observe")
        return self.s.obs.to_physical(x, y)

    def front(self) -> None:
        if self.s.hwnd:
            self.s.check_window(self.s.hwnd)
            if not inputs.focus_window(self.s.hwnd):
                raise RuntimeError("没能把目标窗口切到前台（可能被更高权限的窗口挡住了）")

    # ---------- 动作 ----------

    def run(self, actions: list[Action]) -> list[str]:
        """按顺序执行。用到真实键鼠时护栏会挡住用户亲手的输入：一批做完、或者遇到等待就放开。"""
        done: list[str] = []
        keep = False  # 最后一个动鼠标的动作是悬停：鼠标得留在那里
        try:
            for i, a in enumerate(actions, 1):
                _check_stop()
                if a.do in ("wait", "wait_for", "wait_gone"):
                    GUARD.release(keep, self.s.hwnd)  # 等待的时候不挡用户
                if self.s.hwnd:
                    self.s.check_window(self.s.hwnd)
                try:
                    done.append(f"{i}. {getattr(self, '_' + a.do)(a)}")
                except (Stopped, inputs.Interrupted):
                    raise
                except Exception as e:  # noqa: BLE001 - 失败就停在这一步，把原因交给模型
                    done.append(f"{i}. 失败：{e}")
                    if i < len(actions):
                        done.append(f"（后面 {len(actions) - i} 步没有执行）")
                    break
                if a.do == "hover":
                    keep = True
                elif a.do in MOUSE_ACTIONS:
                    keep = False
        finally:
            GUARD.release(keep, self.s.hwnd)
        if GUARD.blocked:
            done.append(f"（这期间用户动了 {GUARD.blocked} 次键鼠，已经挡住，没有影响你的操作）")
        return done

    def _click(self, a: Action, button: str = "left", count: int = 1) -> str:
        el = self.element(a)
        web = el is not None and self.in_page(el)
        if el is not None and a.method != "mouse" and button == "left" and count == 1 and (not web or a.method == "uia"):
            how = self._direct_click(el, select_ok=a.method == "uia")
            if how:
                time.sleep(0.25)
                return f"点击 {_label(el)}（{how}）"
            if a.method == "uia" and el.role not in CLICK_SELECT:
                raise RuntimeError(f"{_label(el)} 不支持直接操作，请用 method=mouse")
        x, y = self.point(a, el)
        self.front()
        if el is not None and a.method != "mouse" and not self.visible(x, y):
            how = self._direct_click(el, select_ok=True)  # 被挡住或在可视区外：真点不到，退回 UIA
            if how:
                time.sleep(0.25)
                return f"点击 {_label(el)}（{how}，它在屏幕上被挡住了）"
        inputs.click(x, y, button, count)
        time.sleep(0.25)
        what = _label(el) if el else f"({a.x},{a.y})"
        verb = {("left", 1): "点击", ("left", 2): "双击", ("right", 1): "右键点击"}.get((button, count), "点击")
        return f"{verb} {what}（鼠标）"

    def _direct_click(self, el: Element, select_ok: bool) -> str:
        """用 UIA 完成这次点击，返回方式；这个控件不适合直接操作时返回空。"""
        if el.raw is None:
            return ""
        c = _control(el)
        if el.role in CLICK_INVOKE and "invoke" in el.patterns:
            finished = _with_timeout(lambda: c.GetInvokePattern().Invoke())
            return "UIA" if finished else "UIA，目标还在处理（可能弹出了对话框）"
        if el.role == "CheckBox" and "toggle" in el.patterns:
            _with_timeout(lambda: c.GetTogglePattern().Toggle())
            return "UIA 切换"
        if el.role == "ComboBox" and "expand" in el.patterns:
            pattern = c.GetExpandCollapsePattern()
            _with_timeout(lambda: pattern.Collapse() if pattern.ExpandCollapseState == 1 else pattern.Expand())
            return "UIA 展开/收起"
        if el.role in TEXT_ROLES and _try(lambda: c.SetFocus()):
            return "UIA 聚焦"
        if select_ok and el.role in CLICK_SELECT:
            if "select" in el.patterns:
                _with_timeout(lambda: c.GetSelectionItemPattern().Select())
                return "UIA 选中"
            if "invoke" in el.patterns:
                _with_timeout(lambda: c.GetInvokePattern().Invoke())
                return "UIA"
        return ""

    def in_page(self, el: Element) -> bool:
        """控件是不是网页内容（在浏览器或 Electron 应用的网页区域里）。"""
        obs = self.s.obs
        x, y = el.center
        return obs is not None and any(p[0] <= x <= p[2] and p[1] <= y <= p[3] for p in obs.pages)

    def visible(self, x: int, y: int) -> bool:
        """这一点上露出来的是不是目标窗口（没被别的窗口挡住、也没在屏幕外）。"""
        if not self.s.hwnd:
            return True
        hwnd = ctypes.windll.user32.WindowFromPoint(ctypes.wintypes.POINT(x, y))
        root = ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT) if hwnd else 0
        return root == self.s.hwnd

    def _double_click(self, a: Action) -> str:
        return self._click(a, count=2)

    def _right_click(self, a: Action) -> str:
        return self._click(a, button="right")

    def _hover(self, a: Action) -> str:
        el = self.element(a)
        x, y = self.point(a, el)
        self.front()
        inputs.move(x, y)
        time.sleep(0.4)
        return f"鼠标移到 {_label(el) if el else f'({a.x},{a.y})'}"

    def _type(self, a: Action) -> str:
        if a.text is None:
            raise RuntimeError("type 需要 text")
        el = self.element(a)
        in_browser = self.s.obs is not None and self.s.obs.process.lower() in browser.BROWSERS
        if (el is not None and a.method != "mouse" and a.replace and el.role in ("Edit", "ComboBox")
                and "value" in el.patterns and "readonly" not in el.states and not in_browser):
            c = _control(el)
            _with_timeout(lambda: c.GetValuePattern().SetValue(a.text))
            if a.enter:
                self.front()
                _try(lambda: c.SetFocus())
                inputs.press("enter")
            return f"在 {_label(el)} 填入 {len(a.text)} 个字（UIA）"
        self.front()
        if el is not None:
            # 网页里用 UIA 聚焦不可靠（新开的窗口里键盘焦点可能还在地址栏，自检实测），看得见就真点一下
            x, y = el.center
            if (in_browser or self.in_page(el) or a.method == "mouse") and self.visible(x, y):
                inputs.click(x, y)
            elif not _try(lambda: _control(el).SetFocus()):
                inputs.click(x, y)
            time.sleep(0.15)
            if not a.replace:
                inputs.press("ctrl+end")  # 点在中间时光标也在中间：追加的文字放到最后
        if a.replace:
            inputs.press("ctrl+a")
            time.sleep(0.05)
        before = _current_value(el) if el is not None and not a.replace else ""
        how = inputs.enter_text(a.text, should_stop=stop_requested)
        note = ""
        if el is not None and "value" in el.patterns and "password" not in el.states:
            if _hidden_input(el):
                # 网页终端、代码编辑器收字用的隐藏输入框，打完会自己清空：读回来的对不上不说明没输进去
                # （实测网页终端里连着 10 次报"可能没输进去"，命令其实都执行了）
                note = "；这是网页终端、编辑器的隐藏输入框，打完会自己清空，没法从框里核对：要确认就看屏幕上的结果"
            else:
                want = a.text if a.replace else before + a.text
                now = _settled_value(el, want)
                if now != want and not (not a.replace and now.endswith(a.text)):
                    note = f"；注意：输入后框里是「{now[:60]}」，和预期不一致，可能没输进去"
        if a.enter:
            inputs.press("enter")
        return f"{'在 ' + _label(el) + ' ' if el else ''}输入 {len(a.text)} 个字（{how}）{note}"

    def _key(self, a: Action) -> str:
        if not a.keys:
            raise RuntimeError("key 需要 keys，比如 ctrl+s")
        self.front()
        combos = [k.strip() for k in a.keys.split(",") if k.strip()]
        for combo in combos:
            _check_stop()
            inputs.press(combo)
            time.sleep(0.08)
        time.sleep(0.2)
        return f"按下 {', '.join(combos)}"

    def _scroll(self, a: Action) -> str:
        el = self.element(a)
        if el is None and (a.x is None or a.y is None) and self.s.obs is not None:
            x, y = self.s.obs.to_physical(self.s.obs.size[0] / 2, self.s.obs.size[1] / 2)
        else:
            x, y = self.point(a, el)
        inputs.scroll(x, y, dy=a.amount)
        time.sleep(0.3)
        return f"滚动 {a.amount} 格（{'向下' if a.amount > 0 else '向上'}）"

    def _drag(self, a: Action) -> str:
        start_el, end_el = self.element(a), self.element(a, "to_id")
        x0, y0 = self.point(a, start_el)
        x1, y1 = self.point(a, end_el, prefix="to_")
        self.front()
        inputs.drag(x0, y0, x1, y1)
        time.sleep(0.3)
        return "拖动完成"

    def _toggle(self, a: Action) -> str:
        el = self.element(a)
        if el is None or "toggle" not in el.patterns:
            raise RuntimeError("toggle 需要一个能勾选的控件编号")
        pattern = _control(el).GetTogglePattern()
        current = pattern.ToggleState == 1
        if a.on is not None and current == a.on:
            return f"{_label(el)} 本来就是{'打开' if current else '关闭'}的"
        _with_timeout(pattern.Toggle)
        time.sleep(0.2)
        return f"切换 {_label(el)} → {'打开' if not current else '关闭'}"

    def _select(self, a: Action) -> str:
        el = self.element(a)
        if el is None or not a.text:
            raise RuntimeError("select 需要下拉框或列表的编号，以及 text（选项名）")
        c = _control(el)
        combo = el.role == "ComboBox"
        # 可编辑的下拉框（里面有输入框）直接填值；不可编辑的填了也没用，Qt 还要白等半秒（实测）
        if (combo and "value" in el.patterns and _has_edit_child(el)
                and _try(lambda: _with_timeout(lambda: c.GetValuePattern().SetValue(a.text)))
                and _current_value(el) == a.text):
            return f"在 {_label(el)} 填入「{a.text}」（UIA）"
        if combo and "expanded" not in el.states:
            cx, cy = el.center
            self.front()
            if self.visible(cx, cy):
                inputs.click(cx, cy)  # 看得见就真点一下打开，比 UIA 展开快，效果也和人一样
            elif "expand" in el.patterns:
                _with_timeout(lambda: c.GetExpandCollapsePattern().Expand())
            time.sleep(0.3)
        combo = combo and "expand" in el.patterns
        option = _find_option(el, a.text)
        if option is None:
            if combo:
                _try(lambda: c.GetExpandCollapsePattern().Collapse())
            raise RuntimeError(f"在 {_label(el)} 里没找到选项「{a.text}」")
        r = option.CurrentBoundingRectangle
        x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
        self.front()
        if self.visible(x, y) or _same_process_popup(x, y, el):
            inputs.click(x, y)  # 真点一下：各框架里"选定并收起"的语义都一样
            how = "鼠标"
        else:
            oc = auto.Control.CreateControlFromElement(option)
            _try(lambda: _with_timeout(lambda: oc.GetSelectionItemPattern().Select()))
            if combo:
                inputs.press("enter")
            how = "UIA"
        time.sleep(0.25)
        if combo and _try(lambda: c.GetExpandCollapsePattern().ExpandCollapseState == 1):
            _try(lambda: c.GetExpandCollapsePattern().Collapse())
        now = _current_value(el)
        if combo and now and now != a.text:
            raise RuntimeError(f"选了「{a.text}」，但 {_label(el)} 现在显示「{now}」")
        return f"在 {_label(el)} 选了「{a.text}」（{how}）"

    def _focus(self, a: Action) -> str:
        if not a.window:
            raise RuntimeError("focus 需要 window（标题或进程名的一部分）")
        hwnd = find_window(a.window, self.s.own_pid)
        if not hwnd:
            raise RuntimeError(f"没找到窗口「{a.window}」")
        self.s.check_window(hwnd)
        self.s.hwnd = hwnd
        if not inputs.focus_window(hwnd):
            raise RuntimeError("没能把窗口切到前台")
        time.sleep(0.2)
        return f"切到窗口「{win32gui_title(hwnd)}」（之后的编号和坐标请重新 observe）"

    def _wait(self, a: Action) -> str:
        asked = max(a.seconds, 0)
        end = time.time() + min(asked, WAIT_MAX_S)
        while time.time() < end:
            _check_stop()
            time.sleep(0.1)
        if asked > WAIT_MAX_S:
            # 照实说只等了多久（原来说"等了 300 秒"，其实只等了 30 秒，模型以为等够了：实测下载模型时这样误判过）
            return (f"只等了 {WAIT_MAX_S} 秒（一次最多等 {WAIT_MAX_S} 秒，要的 {asked:g} 秒没等完）："
                    "还要等就再调一次，或者用 wait_for 等某个文字出现")
        return f"等了 {asked:g} 秒"

    def _wait_for(self, a: Action) -> str:
        if not a.text or not self.s.hwnd:
            raise RuntimeError("wait_for 需要 text，并且要先 observe 一个窗口")
        limit = min(max(a.seconds, 1), WAIT_FOR_MAX_S)
        end = time.time() + limit
        tries = 0
        while time.time() < end:
            _check_stop()
            if elements.search(self.s.hwnd, a.text, limit=1):
                return f"「{a.text}」出现了"
            tries += 1
            if tries % 3 == 0 and _seen_on_screen(self.s.hwnd, a.text):  # 界面没交出控件的地方：认图看看
                return f"「{a.text}」出现了（认图）"
            time.sleep(0.5)
        raise RuntimeError(f"等了 {limit:g} 秒，「{a.text}」没有出现"
                           + (f"（一次最多等 {WAIT_FOR_MAX_S} 秒，还要等就再调一次）" if a.seconds > WAIT_FOR_MAX_S else ""))

    def _wait_gone(self, a: Action) -> str:
        """等某个文字消失：做完了的标志常常是"正在下载""运行中"、Jupyter 的"中断"按钮没了，
        而不是出现什么新字（命令行的提示符一直都在，wait_for 会马上返回）。"""
        if not a.text or not self.s.hwnd:
            raise RuntimeError("wait_gone 需要 text，并且要先 observe 一个窗口")
        limit = min(max(a.seconds, 1), WAIT_FOR_MAX_S)
        start, first = time.time(), True
        while time.time() - start < limit:
            _check_stop()
            # 控件里找不到了，再认一次图确认（界面没交出控件的地方，字还在图上就不算消失）
            if not elements.search(self.s.hwnd, a.text, limit=1) and not _seen_on_screen(self.s.hwnd, a.text):
                return (f"「{a.text}」现在就没有（不用等；要等的字写对了吗）" if first
                        else f"「{a.text}」不见了（等了 {time.time() - start:.0f} 秒）")
            first = False
            time.sleep(0.5)
        raise RuntimeError(f"等了 {limit:g} 秒，「{a.text}」还在"
                           + (f"（一次最多等 {WAIT_FOR_MAX_S} 秒，还要等就再调一次）" if a.seconds > WAIT_FOR_MAX_S else ""))


def _seen_on_screen(hwnd: int, text: str) -> bool:
    from . import ocr

    shot = win32.capture_window(hwnd)
    want = text.replace(" ", "").lower()
    return shot is not None and any(want in line.text.replace(" ", "").lower() for line in ocr.recognize(shot))


def _try(fn: Callable[[], object]) -> bool:
    try:
        fn()
        return True
    except Exception:  # noqa: BLE001
        return False


def _has_edit_child(el: Element) -> bool:
    uia = elements._client().IUIAutomation
    try:
        return bool(el.raw.FindFirst(2, uia.CreatePropertyCondition(elements.P_TYPE, 50004)))  # 2 = 子元素
    except Exception:  # noqa: BLE001
        return False


def _current_value(el: Element) -> str:
    try:  # 新版记事本这类 RichEdit 只用 \r 分行：统一成 \n 再和要输入的比
        return newlines(str(el.raw.GetCurrentPropertyValue(elements.P_VALUE) or ""))
    except Exception:  # noqa: BLE001
        return ""


def _hidden_input(el: Element) -> bool:
    """几乎没有大小的输入框：网页终端（xterm.js）、代码编辑器（Monaco）把它藏起来专门收键盘输入，收完就清空。"""
    left, top, right, bottom = el.rect
    return right - left < HIDDEN_INPUT_PX or bottom - top < HIDDEN_INPUT_PX


def _settled_value(el: Element, want: str, timeout: float = 0.6) -> str:
    """输入后读回框里的值：程序处理粘贴要一点时间，等到和预期一致或者超时。"""
    end = time.time() + timeout
    now = _current_value(el)
    while now != want and time.time() < end:
        time.sleep(0.05)
        now = _current_value(el)
    return now


def _find_option(el: Element, text: str):
    """下拉框的选项可能在它下面，也可能在同一个进程单独弹出的窗口里。只搜这几处，不扫整个桌面（慢）。"""
    uia = elements._client().IUIAutomation
    wanted = uia.CreateAndCondition(uia.CreatePropertyCondition(elements.P_TYPE, 50007),
                                    uia.CreatePropertyCondition(elements.P_NAME, text))
    found = el.raw.FindFirst(4, wanted)
    if found:
        return found
    pid = el.raw.CurrentProcessId
    for w in win32.visible_windows():
        if w.pid == pid:
            try:
                found = uia.ElementFromHandle(w.hwnd).FindFirst(4, wanted)
            except Exception:  # noqa: BLE001
                continue
            if found:
                return found
    return None


def _same_process_popup(x: int, y: int, el: Element) -> bool:
    """这一点上是不是同一个程序弹出来的窗口（下拉框的选项列表通常是单独的弹出窗口）。"""
    hwnd = ctypes.windll.user32.WindowFromPoint(ctypes.wintypes.POINT(x, y))
    if not hwnd:
        return False
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        return pid.value == el.raw.CurrentProcessId
    except Exception:  # noqa: BLE001
        return False


def win32gui_title(hwnd: int) -> str:
    info = win32.window_info(hwnd)
    return info.title if info else str(hwnd)


def find_window(spec: str, own_pid: int) -> int:
    """按标题或进程名（的一部分）找窗口，取最上面那个；空字符串取当前前台窗口。不含 Super Aide 自己的。"""
    windows = [w for w in win32.visible_windows() if w.pid != own_pid]
    spec = spec.strip()
    if spec.isdigit() and any(w.hwnd == int(spec) for w in windows):
        return int(spec)
    if not spec:
        fg = win32.foreground()
        if fg is not None and fg.pid != own_pid and fg.title:
            return fg.hwnd
        return windows[0].hwnd if windows else 0
    needle = _plain(spec)
    for w in windows:  # visible_windows 按从上到下的顺序
        if needle in _plain(w.title) or needle in w.process.lower():
            return w.hwnd
    return 0


#: 标题里看不见的字符：Edge 的标题是 "…Microsoft\u200b Edge"，按 "Microsoft Edge" 找不到（实测）
INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff"))


def _plain(text: str) -> str:
    return text.translate(INVISIBLE).lower()
