"""屏幕指引：在屏幕上把要点的地方圈出来，带编号和一句说明（问答模式里"教你怎么点"时用）。

一个不抢焦点、鼠标穿透、不进截图的分层窗口，画圆角框（问答模式的蓝紫色）和说明标签。
到时间、下一次指引、或者 Super Aide 收起回答时（命名事件）消失。
"""

from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes

import win32api
import win32con
import win32gui
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .signals import GUIDE_CLEAR as CLEAR_EVENT
ACCENT, ACCENT_2 = (91, 140, 255), (155, 107, 255)
PAD = 18  # 框外留给光晕和标签的边
WDA_EXCLUDEFROMCAPTURE = 0x11
user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p, wintypes.HDC,
                                       ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                   wintypes.HANDLE, wintypes.DWORD]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


class _BlendFunction(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("msyhbd.ttc", "msyh.ttc", "segoeuib.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def monitor_of(rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """框所在的那块屏幕（物理像素）。"""
    try:
        return tuple(win32api.GetMonitorInfo(win32api.MonitorFromRect(rect, win32con.MONITOR_DEFAULTTONEAREST))["Monitor"])
    except Exception:  # noqa: BLE001 - 取不到就不限制
        return (-(1 << 30), -(1 << 30), 1 << 30, 1 << 30)


def render(targets: list[tuple[tuple[int, int, int, int], str]], origin: tuple[int, int],
           size: tuple[int, int], scale: float, screen=monitor_of) -> Image.Image:
    """画出所有指引框（物理像素）。origin/size 是这张透明画布在屏幕上的位置和大小；screen(框) 给出框所在的屏幕。"""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    d = ImageDraw.Draw(img)
    width, radius = max(2, round(3 * scale)), round(8 * scale)
    font = _font(round(13 * scale))
    for number, ((x0, y0, x1, y1), label) in enumerate(targets, 1):
        box = (x0 - origin[0] - 3, y0 - origin[1] - 3, x1 - origin[0] + 3, y1 - origin[1] + 3)
        gd.rounded_rectangle(box, radius, outline=ACCENT + (150,), width=width * 3)
        d.rounded_rectangle(box, radius, outline=ACCENT + (255,), width=width)
        text = f"{number}  {label}" if len(targets) > 1 or label else str(number)
        tw = d.textlength(text, font=font)
        th, gap = round(22 * scale), round(6 * scale)
        lw = round(tw) + round(16 * scale)
        # 编号标签按屏幕摆（原来按画布判断，框贴着屏幕上沿、右沿时标签整个画到了屏幕外，看不出是第几步）：
        # 放在框上面，上面没地方就放下面；左边和框对齐，右边出了屏幕就往左挪
        mx0, my0, mx1, _my1 = screen((x0, y0, x1, y1))
        above = y0 - 3 - gap - th
        sy = above if above >= my0 else y1 + 3 + gap
        sx = max(mx0, min(x0 - 3, mx1 - lw))
        lx = max(0, min(sx - origin[0], size[0] - lw))
        ly = max(0, min(sy - origin[1], size[1] - th))
        d.rounded_rectangle((lx, ly, lx + lw, ly + th), th // 2, fill=ACCENT_2 + (240,))
        d.text((lx + round(8 * scale), ly + th / 2), text, fill=(255, 255, 255, 255), font=font, anchor="lm")
    glow = glow.filter(ImageFilter.GaussianBlur(radius=4 * scale))
    cut = ImageDraw.Draw(glow)  # 直接写像素（不混合）：把框里面的光晕擦掉
    for (x0, y0, x1, y1), _label in targets:
        cut.rounded_rectangle((x0 - origin[0] - 1, y0 - origin[1] - 1, x1 - origin[0] + 1, y1 - origin[1] + 1),
                              round(8 * scale), fill=(0, 0, 0, 0))
    return Image.alpha_composite(glow, img)


def render_note(text: str, scale: float) -> Image.Image:
    """一枚深色小胶囊，写一句提示（比如护栏挡住你的键鼠时）。"""
    font = _font(round(13 * scale))
    width = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(text, font=font)
    h, pad = round(30 * scale), round(14 * scale)
    img = Image.new("RGBA", (round(width) + 2 * pad, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, img.width - 1, h - 1), h // 2, fill=(28, 28, 32, 235),
                        outline=(255, 255, 255, 56), width=max(1, round(scale)))  # 细亮边：深色界面上也看得清
    d.text((pad, h / 2), text, fill=(255, 255, 255, 255), font=font, anchor="lm")
    return img


class Highlighter:
    """在自己的线程里维护一个透明窗口；show / note / clear 可以从任何线程调用。"""

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._deadline = 0.0
        self._clear_event = 0
        self._thread = threading.Thread(target=self._run, name="guide", daemon=True)
        self._thread.start()

    def show(self, targets: list[tuple[tuple[int, int, int, int], str]], seconds: float, scale: float = 1.0) -> None:
        self._q.put(("show", targets, seconds, scale))

    def note(self, text: str, pos: tuple[int, int], seconds: float = 1.5, scale: float = 1.0) -> None:
        """在 pos（物理像素，通常是鼠标位置）右下方显示一句提示，几秒后自己消失。"""
        self._q.put(("note", text, pos, seconds, scale))

    def clear(self) -> None:
        self._q.put(("clear",))

    # ---------- 窗口线程 ----------

    def _run(self) -> None:
        wc = win32gui.WNDCLASS()
        wc.lpszClassName = "SuperAideGuide"
        wc.lpfnWndProc = lambda h, m, w, l: win32gui.DefWindowProc(h, m, w, l)
        wc.hInstance = win32gui.GetModuleHandle(None)
        try:
            win32gui.RegisterClass(wc)
        except Exception:  # noqa: BLE001 - 已经注册过
            pass
        ex = (win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST
              | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE)
        self.hwnd = win32gui.CreateWindowEx(ex, wc.lpszClassName, "Super Aide 指引", win32con.WS_POPUP,
                                            0, 0, 1, 1, 0, 0, wc.hInstance, None)
        user32.SetWindowDisplayAffinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE)  # 不出现在任何截图里
        self._clear_event = ctypes.windll.kernel32.CreateEventW(None, False, False, CLEAR_EVENT)
        while True:
            try:
                cmd = self._q.get(timeout=0.05)
            except queue.Empty:
                cmd = None
            win32gui.PumpWaitingMessages()
            if cmd and cmd[0] == "show":
                self._paint(*cmd[1:])
            elif cmd and cmd[0] == "note":
                self._paint_note(*cmd[1:])
            elif cmd and cmd[0] == "clear":
                self._hide()
            if self._deadline and time.time() > self._deadline:
                self._hide()
            if self._clear_event and ctypes.windll.kernel32.WaitForSingleObject(self._clear_event, 0) == 0:
                self._hide()

    def _hide(self) -> None:
        self._deadline = 0.0
        win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)

    def _paint(self, targets, seconds: float, scale: float) -> None:
        if not targets:
            self._hide()
            return
        x0 = min(r[0] for r, _ in targets) - PAD - round(220 * scale)
        y0 = min(r[1] for r, _ in targets) - PAD - round(40 * scale)
        x1 = max(r[2] for r, _ in targets) + PAD + round(220 * scale)
        y1 = max(r[3] for r, _ in targets) + PAD + round(40 * scale)
        size = (x1 - x0, y1 - y0)
        img = render(targets, (x0, y0), size, scale)
        self._blit(img, (x0, y0))
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
        self._deadline = time.time() + max(3.0, min(seconds, 300.0))

    def _paint_note(self, text: str, pos: tuple[int, int], seconds: float, scale: float) -> None:
        img = render_note(text, scale)
        self._blit(img, (pos[0] + round(18 * scale), pos[1] + round(20 * scale)))
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
        self._deadline = time.time() + seconds

    def _blit(self, img: Image.Image, pos: tuple[int, int]) -> None:
        """把 RGBA 图画到分层窗口上（UpdateLayeredWindow 要预乘 alpha 的 BGRA）。"""
        w, h = img.size
        data = _premultiply(img)
        screen = user32.GetDC(0)
        mem = gdi32.CreateCompatibleDC(screen)
        header = _BitmapInfoHeader(biSize=ctypes.sizeof(_BitmapInfoHeader), biWidth=w, biHeight=-h, biPlanes=1,
                                   biBitCount=32, biCompression=0)
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(screen, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, data, len(data))
        old = gdi32.SelectObject(mem, bitmap)
        blend = _BlendFunction(0, 0, 255, 1)  # AC_SRC_OVER，按每像素 alpha
        user32.UpdateLayeredWindow(self.hwnd, screen, ctypes.byref(wintypes.POINT(*pos)),
                                   ctypes.byref(wintypes.SIZE(w, h)), mem, ctypes.byref(wintypes.POINT(0, 0)),
                                   0, ctypes.byref(blend), 2)  # ULW_ALPHA
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(0, screen)


def _premultiply(img: Image.Image) -> bytes:
    """RGBA → 预乘 alpha 的 BGRA 字节（每个颜色通道乘以 alpha / 255）。"""
    r, g, b, a = img.split()
    return Image.merge("RGBA", [ImageChops.multiply(c, a) for c in (b, g, r)] + [a]).tobytes()
