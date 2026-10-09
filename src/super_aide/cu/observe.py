"""观察一个窗口：截图（缩到模型合适的大小）+ 能操作的控件列表 + 截图上画好的编号。

和模型交流用截图上的像素坐标；这里记住截图的原点和缩放比，动作执行时换回物理像素。
Chromium / Electron 系的窗口（Edge、Chrome、VS Code……）要先"唤醒"无障碍树才会把网页内容交出来。
"""

from __future__ import annotations

import ctypes
import io
import math
import time
from dataclasses import dataclass, field

import win32gui
from PIL import Image, ImageDraw, ImageFont

from ..snapshot import chromium, uiawalk, win32
from . import browser, ocr
from .elements import Element, _client, query

MAX_EDGE, MAX_PIXELS = 1568, 1_150_000  # Claude 推荐的截图上限；超过会被服务端压缩，点击就不准了
MARK = (255, 64, 129)  # 编号框的颜色：洋红，在常见界面上都醒目
OCR_SPARSE = 8  # 能操作的控件少于这么多：多半是画布、远程桌面、游戏、自绘界面，用 OCR 补上屏幕上的字
OCR_ROLE = "OCR"  # 认图认出来的字：没有控件对象，只能用鼠标点


@dataclass
class Observation:
    hwnd: int
    title: str
    process: str
    origin: tuple[int, int]         # 截图左上角的物理坐标
    scale: float                    # 截图像素 / 物理像素
    size: tuple[int, int]           # 截图尺寸
    elements: dict[int, Element] = field(default_factory=dict)
    image: Image.Image | None = None  # 发给模型的（缩放、画了编号）
    full: Image.Image | None = None   # 原始分辨率（zoom 用）
    url: str = ""
    focused: Element | None = None
    pages: list[tuple[int, int, int, int]] = field(default_factory=list)  # 网页内容区（物理像素）
    taken: float = field(default_factory=time.time)

    def to_physical(self, x: float, y: float) -> tuple[int, int]:
        x = min(max(x, 0), self.size[0] - 1)
        y = min(max(y, 0), self.size[1] - 1)
        return round(self.origin[0] + x / self.scale), round(self.origin[1] + y / self.scale)

    def to_image(self, px: float, py: float) -> tuple[int, int]:
        return round((px - self.origin[0]) * self.scale), round((py - self.origin[1]) * self.scale)


def fit(w: int, h: int) -> float:
    """缩放比：长边不超过 MAX_EDGE、总像素不超过 MAX_PIXELS，不放大。"""
    return min(1.0, MAX_EDGE / max(w, h), math.sqrt(MAX_PIXELS / (w * h)))


def unresponsive(title: str) -> str:
    return (f"「{title[:40]}」现在没有响应（程序正忙或者页面太大）。先别再操作它，也别关掉它；"
            "等一会儿再观察，或者告诉用户它卡住了。")


def _has_content(found: list[Element], pages: list[tuple[int, int, int, int]]) -> bool:
    return any(p[0] <= e.center[0] <= p[2] and p[1] <= e.center[1] <= p[3] for e in found for p in pages)


def ocr_elements(shot: Image.Image, origin: tuple[int, int], found: list[Element], start: int,
                 phrases: list[ocr.Line] | None = None) -> list[Element]:
    """截图上认出来的文字块变成编号（坐标换成物理像素）。控件本身已经标着同样文字的不重复。"""
    out: list[Element] = []
    for p in ocr.phrases(shot) if phrases is None else phrases:
        text = p.text.strip()
        if not text:
            continue
        rect = (origin[0] + p.rect[0], origin[1] + p.rect[1], origin[0] + p.rect[2], origin[1] + p.rect[3])
        cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        flat = text.replace(" ", "").lower()
        if any(e.rect[0] <= cx <= e.rect[2] and e.rect[1] <= cy <= e.rect[3] and e.name
               and (flat in e.name.replace(" ", "").lower() or e.name.replace(" ", "").lower() in flat)
               for e in found):
            continue
        out.append(Element(id=start + len(out), role=OCR_ROLE, name=text, rect=rect))
    return out


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "arialbd.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def annotate(img: Image.Image, marks: list[tuple[int, tuple[int, int, int, int]]]) -> Image.Image:
    """在截图上画编号框。框画在控件边上，编号贴在左上角外侧，尽量不挡住控件本身的文字。"""
    out = img.convert("RGB")
    draw = ImageDraw.Draw(out, "RGBA")
    font = _font(11)
    for number, (x0, y0, x1, y1) in marks:
        draw.rectangle((x0, y0, x1, y1), outline=MARK + (230,), width=1)
        label = str(number)
        tw = draw.textlength(label, font=font)
        lx, ly = x0, max(0, y0 - 13)
        draw.rectangle((lx, ly, lx + tw + 4, ly + 12), fill=MARK + (235,))
        draw.text((lx + 2, ly - 1), label, fill=(255, 255, 255), font=font)
    return out


def encode(img: Image.Image, fmt: str = "JPEG") -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=82)
    else:
        img.save(buf, fmt)
    return buf.getvalue()


def observe(hwnd: int, marks: bool = True, use_ocr: bool | None = None) -> Observation:
    """use_ocr：None = 控件太少时自动用 OCR 补上屏幕上的字；True = 总是补；False = 不用。"""
    info = win32.window_info(hwnd)
    if info is None:
        raise RuntimeError("窗口已经不在了")
    if not uiawalk.wait_responsive(hwnd):
        raise RuntimeError(unresponsive(info.title))
    if info.minimized:
        ctypes.windll.user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE：还原但不抢焦点
        time.sleep(0.25)
        info = win32.window_info(hwnd) or info
    bounds = win32.dwm_rect(hwnd) or info.rect
    shot = win32.capture_window(hwnd)
    if shot is None:  # 截不到（比如受保护的内容）：退回屏幕上这块区域
        import mss

        with mss.MSS() as sct:
            raw = sct.grab({"left": bounds[0], "top": bounds[1],
                            "width": bounds[2] - bounds[0], "height": bounds[3] - bounds[1]})
            shot = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    hosts = chromium.children(hwnd)
    if hosts and not uiawalk.web_documents(_client().IUIAutomation, hwnd, hosts):
        # 网页内容还没交出来：唤醒后等文档节点出现（每次只是一个很小的调用），最多 2 秒，然后只取一次。
        # 以前是反复整窗查询，大网页上会把浏览器卡死（实测）
        chromium.wake(hwnd)
        for _ in range(10):
            time.sleep(0.2)
            if uiawalk.web_documents(_client().IUIAutomation, hwnd, hosts):
                break
    found = query(hwnd, bounds)
    pages = [win32gui.GetWindowRect(c) for c in hosts]
    if pages and not _has_content(found, pages):  # 文档节点有了、里面的东西还没跟上：再取一次就好
        time.sleep(0.5)
        found = query(hwnd, bounds)

    if use_ocr or (use_ocr is None and len(found) < OCR_SPARSE):
        found += ocr_elements(shot, (bounds[0], bounds[1]), found, max((e.id for e in found), default=0) + 1)

    scale = fit(shot.width, shot.height)
    size = (max(1, round(shot.width * scale)), max(1, round(shot.height * scale)))
    obs = Observation(hwnd=hwnd, title=info.title, process=info.process, origin=(bounds[0], bounds[1]),
                      scale=scale, size=size, full=shot)
    obs.elements = {e.id: e for e in found}
    obs.pages = pages
    obs.focused = next((e for e in found if "focused" in e.states), None)
    if info.process.lower() in browser.BROWSERS:
        obs.url = browser.current_url(hwnd)
    image = shot.resize(size, Image.LANCZOS) if scale < 1 else shot
    if marks and found:
        boxes = []
        for e in found:
            x0, y0 = obs.to_image(e.rect[0], e.rect[1])
            x1, y1 = obs.to_image(e.rect[2], e.rect[3])
            boxes.append((e.id, (max(0, x0), max(0, y0), min(size[0] - 1, x1), min(size[1] - 1, y1))))
        image = annotate(image, boxes)
    obs.image = image
    return obs


def describe(obs: Observation, limit: int = 220) -> str:
    """给模型看的文字版：窗口、焦点、网址，以及每个控件一行（编号和截图上的标记一致，坐标是截图像素）。"""
    lines = [f"窗口：{obs.title}（{obs.process}）  截图 {obs.size[0]}×{obs.size[1]}，下面的坐标都按这张截图"]
    if obs.url:
        lines.append(f"网址：{obs.url}")
    if obs.focused is not None:
        lines.append(f"焦点：[{obs.focused.id}] {obs.focused.role} \"{obs.focused.name}\"")
    if not obs.elements:
        lines.append("这个窗口没有交出可操作的控件（自绘界面、游戏、画布等），请看截图用坐标操作。")
        return "\n".join(lines)
    lines.append("可操作的控件（[编号] 类型 \"名字\" 值/状态 @中心坐标）：")
    for e in list(obs.elements.values())[:limit]:
        cx, cy = obs.to_image(*e.center)
        extra = f" value=\"{e.value}\"" if e.value else ""
        states = f" ({', '.join(e.states)})" if e.states else ""
        lines.append(f"[{e.id}] {e.role} \"{e.name}\"{extra}{states} @{cx},{cy}")
    if len(obs.elements) > limit:
        lines.append(f"……还有 {len(obs.elements) - limit} 个没列出，可以用 find 按名字找")
    if any(e.role == OCR_ROLE for e in obs.elements.values()):
        lines.append(f"（{OCR_ROLE} 是从截图上认出来的字：界面没交出控件的地方也能按编号点，会用真实鼠标点它的中心；"
                     "个别字可能认错）")
    return "\n".join(lines)
