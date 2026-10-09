"""文字识别：Windows 自带的离线 OCR（Windows.Media.Ocr），不联网、不用额外模型。

两个用处：
- 框选区域里的文字逐字交给引擎（模型看图时会把 modescope 自动"纠正"成 modelscope，逐字的文字不会，实测）；
- 不交出控件的界面（画布、远程桌面、游戏、部分自绘界面）里，给每行字一个位置，可以按文字精确点击。
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import math
import re
from dataclasses import dataclass

from PIL import Image, ImageOps, ImageStat

log = logging.getLogger(__name__)
CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")
MAX_SIDE = 9000  # Windows OCR 的上限是 10000 像素
MAX_WORK_PIXELS = 12_000_000  # 放大后的总像素上限：再大一张图要认好几秒
PHRASE_GAP = 0.9  # 同一行里两个词隔开超过字高的这么多倍，就算两个东西（菜单栏、工具栏上的一个个按钮）


@dataclass
class Line:
    text: str
    rect: tuple[int, int, int, int]  # 在原图里的像素位置


_engine = None


def available() -> bool:
    return _get_engine() is not None


def _get_engine():
    global _engine
    if _engine is None:
        try:
            from winrt.windows.media.ocr import OcrEngine

            _engine = OcrEngine.try_create_from_user_profile_languages() or False
            if not _engine:
                langs = list(OcrEngine.available_recognizer_languages)
                _engine = OcrEngine.try_create_from_language(langs[0]) if langs else False
            atexit.register(_release)
        except Exception as e:  # noqa: BLE001 - 没装 OCR 组件或者系统不支持：只是少了这项能力
            log.info("Windows OCR 不可用：%s", e)
            _engine = False
    return _engine or None


def _release() -> None:
    """退出前先放掉 OCR 引擎。comtypes（UI Automation 用它）退出时会关掉 COM，引擎留到那之后再释放，
    进程会在退出时崩溃（0xC0000005，实测）。这个函数在 comtypes 导入之后才注册，所以先于它执行。"""
    global _engine
    _engine = None


def _join(words: list[str]) -> str:
    """Windows OCR 把中文按字分开、中间加空格；中文之间不要空格，英文单词之间保留。"""
    out = ""
    for w in words:
        if out and not (CJK.search(out[-1]) or CJK.search(w[:1])):
            out += " "
        out += w
    return out


async def _recognize(img: Image.Image):
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.storage.streams import DataWriter

    rgba = img.convert("RGBA")
    writer = DataWriter()
    writer.write_bytes(rgba.tobytes("raw", "BGRA"))
    bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8,
                                                    rgba.width, rgba.height)
    return await _get_engine().recognize_async(bitmap)


def _prepare(img: Image.Image, invert: bool) -> tuple[Image.Image, float]:
    """OCR 喜欢白底黑字、字大一点：转灰度、深色主题反色、拉开对比度、放大（实测：代码的识别率明显提高）。"""
    gray = ImageOps.grayscale(img)
    if invert:
        gray = ImageOps.invert(gray)
    gray = ImageOps.autocontrast(gray)
    fits = MAX_SIDE / max(gray.width, gray.height)
    scale = min(3.0, fits, math.sqrt(MAX_WORK_PIXELS / (gray.width * gray.height)))
    scale = max(scale, min(1.0, fits))  # 只在超过 OCR 的尺寸上限时才缩小
    if scale != 1:
        gray = gray.resize((round(gray.width * scale), round(gray.height * scale)), Image.LANCZOS)
    return gray.convert("RGB"), scale


def _raw(img: Image.Image, invert: bool) -> list[list[Line]]:
    """OCR 的原始结果：每行一组词，坐标换回原图像素。"""
    work, scale = _prepare(img, invert)
    try:
        result = asyncio.run(_recognize(work))
    except Exception as e:  # noqa: BLE001
        log.warning("OCR 失败：%s", e)
        return []
    lines: list[list[Line]] = []
    for line in result.lines:
        words = []
        for w in line.words:
            b = w.bounding_rect
            words.append(Line(w.text, (round(b.x / scale), round(b.y / scale),
                                       round((b.x + b.width) / scale), round((b.y + b.height) / scale))))
        if words:
            lines.append(words)
    return lines


def _chars(lines: list[list[Line]]) -> int:
    return sum(len(w.text) for words in lines for w in words)


def _best(img: Image.Image) -> list[list[Line]]:
    """先按画面明暗决定要不要反色；识别出来的字太少，再换一种试试（深浅混排的界面）。"""
    if _get_engine() is None or img.width < 4 or img.height < 4:
        return []
    dark = ImageStat.Stat(ImageOps.grayscale(img)).mean[0] < 128
    lines = _raw(img, invert=dark)
    if _chars(lines) < 8:
        other = _raw(img, invert=not dark)
        if _chars(other) > _chars(lines):
            lines = other
    return lines


def _merge(words: list[Line]) -> Line:
    return Line(_join([w.text for w in words]), (min(w.rect[0] for w in words), min(w.rect[1] for w in words),
                                                 max(w.rect[2] for w in words), max(w.rect[3] for w in words)))


def _split(words: list[Line]) -> list[Line]:
    """一行里隔得远的词分开（菜单项、工具栏按钮），隔得近的连成一句（中文每个字都是一个"词"）。"""
    groups = [[words[0]]]
    for w in words[1:]:
        prev = groups[-1][-1]
        height = max(prev.rect[3] - prev.rect[1], w.rect[3] - w.rect[1], 1)
        if w.rect[0] - prev.rect[2] > PHRASE_GAP * height:
            groups.append([w])
        else:
            groups[-1].append(w)
    return [_merge(g) for g in groups]


def _rows(pieces: list[Line]) -> list[Line]:
    """Windows OCR 会把同一行拆成几段（比如 from / modescope / import…）：按垂直位置归成行，行内从左到右拼起来。"""
    rows: list[list[Line]] = []
    for piece in sorted(pieces, key=lambda p: (p.rect[1] + p.rect[3]) / 2):
        cy, h = (piece.rect[1] + piece.rect[3]) / 2, piece.rect[3] - piece.rect[1]
        if rows:
            last = rows[-1]
            ly = sum((p.rect[1] + p.rect[3]) / 2 for p in last) / len(last)
            if abs(cy - ly) < max(h, 1) * 0.6:
                last.append(piece)
                continue
        rows.append([piece])
    out = []
    for row in rows:
        row.sort(key=lambda p: p.rect[0])
        rect = (min(p.rect[0] for p in row), min(p.rect[1] for p in row),
                max(p.rect[2] for p in row), max(p.rect[3] for p in row))
        out.append(Line(" ".join(p.text for p in row), rect))
    return out


def recognize(img: Image.Image) -> list[Line]:
    """识别图里的文字，按行返回（坐标是原图像素）。不可用时返回空列表。"""
    return _rows([_merge(words) for words in _best(img)])


def phrases(img: Image.Image) -> list[Line]:
    """图里可以点的文字块（一个按钮、一个菜单项、一句话），坐标是原图像素。"""
    return [p for words in _best(img) for p in _split(words)]


def text_of(img: Image.Image) -> str:
    return "\n".join(line.text for line in recognize(img))
