"""窗口里打开的文件的文字：界面层（UI Automation）读不到文档内容时，直接读磁盘上的那个文件。

PowerPoint 的幻灯片区域在无障碍树里什么都没有（实测：整棵树 699 个节点，功能区占 634 个，"工作区"只有 6 个，
幻灯片上的字一个都不在；读屏软件也是靠它的对象模型读的）。原来只能拿到功能区和形状库的名字，
助手只好一次次用 PowerShell 连 COM 去读（每次 20～77 秒）。

不按应用适配：只看窗口标题里的文件名（.pptx / .docx / .xlsx 这类 Office Open XML 文件，PowerPoint、WPS、
LibreOffice 打开都一样），在"最近使用的文件"里找到它的完整路径，按文件格式把文字读出来
（每张幻灯片的文字和备注、每个工作表的单元格、文档的段落）。
读的是磁盘上保存的版本：没保存的改动看不到，所以写上最后保存的时间。
"""

from __future__ import annotations

import logging
import os
import re
import time
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

log = logging.getLogger(__name__)

EXTENSIONS = (".pptx", ".pptm", ".ppsx", ".docx", ".docm", ".xlsx", ".xlsm")
_PART = r"[^\\/:*?\"<>|\r\n]"
#: 文件名，前面可以带完整路径（有的程序标题里写的是 D:\工作\预算.xlsx）
FILENAME = re.compile(rf"((?:[A-Za-z]:\\(?:{_PART}+\\)*)?{_PART}+?(?:" + "|".join(re.escape(e) for e in EXTENSIONS) + "))",
                      re.IGNORECASE)
MAX_CHARS = 60_000
MAX_ROWS = 400       # 每个工作表最多读这么多行
MAX_FILE = 30 * 1024 * 1024   # 快照会读每个窗口：太大的文件不读（解析一个很大的表格要好几秒）
MAX_PART = 40 * 1024 * 1024   # 文件里单个部件（一张工作表的 XML）解压后最多这么大
RECENT_DIRS = (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Recent",
               Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Office" / "Recent")

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
NOTES = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"


def names_in_title(title: str) -> list[str]:
    """标题里像文件名的部分（"成本汇报.pptx - PowerPoint" → 成本汇报.pptx）；带完整路径的保留路径。"""
    return [m.group(1).strip() for m in FILENAME.finditer(title or "")]


def _shortcut_target(lnk: Path) -> str:
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()  # 已经初始化过的线程里调用也没关系
        return str(win32com.client.Dispatch("WScript.Shell").CreateShortCut(str(lnk)).Targetpath or "")
    except Exception:  # noqa: BLE001 - 快捷方式坏了、COM 不可用
        return ""


def _office_mru(base: str) -> list[Path]:
    """Office 自己记的最近文件（注册表 User MRU，值形如 "[F…][T…][O…]*D:\\a\\b.pptx"），只要文件名对得上的。
    用程序打开的（不经过资源管理器）不一定进"最近使用的文件"，但 Office 都会记在这里。"""
    import winreg

    def subkeys(key) -> list[str]:
        names, i = [], 0
        while True:
            try:
                names.append(winreg.EnumKey(key, i))
            except OSError:
                return names
            i += 1

    out: list[Path] = []
    root = r"Software\Microsoft\Office"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root) as office:
            versions = [v for v in subkeys(office) if v[:1].isdigit()]
    except OSError:
        return out
    for version in versions:  # Office\16.0\PowerPoint\User MRU\<账号>\File MRU
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\{version}") as ver:
                apps = subkeys(ver)
        except OSError:
            continue
        for app in apps:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\{version}\{app}\User MRU") as mru:
                    accounts = subkeys(mru)
            except OSError:
                continue
            for account in accounts:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                        rf"{root}\{version}\{app}\User MRU\{account}\File MRU") as files:
                        i = 0
                        while True:
                            try:
                                _name, value, _kind = winreg.EnumValue(files, i)
                            except OSError:
                                break
                            i += 1
                            path = str(value).rsplit("*", 1)[-1]
                            if Path(path).name.lower() == base:
                                out.append(Path(path))
                except OSError:
                    continue
    return out


def _running(base: str) -> list[Path]:
    """系统的"运行对象表"里登记的打开着的文档（Office 等 OLE 程序打开文件时会登记完整路径）。
    刚用程序打开、还没关过的文件不在"最近使用的文件"里，这里有。"""
    try:
        import pythoncom

        pythoncom.CoInitialize()
        ctx = pythoncom.CreateBindCtx(0)
        names = [m.GetDisplayName(ctx, None) for m in pythoncom.GetRunningObjectTable()]
    except Exception:  # noqa: BLE001
        return []
    return [Path(n) for n in names if isinstance(n, str) and Path(n).name.lower() == base]


def locate(name: str) -> Path | None:
    """文件名 → 磁盘上的完整路径：标题里本来就是路径就直接用；否则依次找运行对象表里打开着的、
    "最近使用的文件"、Office 记的最近文件里同名的，取最近改过的那个。"""
    direct = Path(name)
    if direct.is_absolute() and direct.is_file():
        return direct
    base = direct.name.lower()
    found: list[Path] = _running(base)
    for folder in RECENT_DIRS:
        try:
            links = [p for p in folder.iterdir() if p.suffix.lower() == ".lnk" and p.stem.lower() == base]
        except OSError:
            continue
        found += [Path(t) for t in map(_shortcut_target, links) if t and Path(t).name.lower() == base]
    existing = [p for p in dict.fromkeys(found) if p.is_file()]
    if not existing:
        existing = [p for p in dict.fromkeys(_office_mru(base)) if p.is_file()]
    return max(existing, key=lambda p: p.stat().st_mtime) if existing else None


def _xml(z: zipfile.ZipFile, name: str):
    try:
        if z.getinfo(name).file_size > MAX_PART:
            return None
        return ElementTree.fromstring(z.read(name))
    except (KeyError, ElementTree.ParseError):
        return None


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """一个部件的关系：id → (类型, 目标部件的完整路径)。"""
    folder, file = part.rsplit("/", 1) if "/" in part else ("", part)
    root = _xml(z, f"{folder}/_rels/{file}.rels" if folder else f"_rels/{file}.rels")
    out = {}
    for r in root.findall("rel:Relationship", NS) if root is not None else []:
        target = r.get("Target", "")
        full = str(PurePosixPath(folder, target)) if not target.startswith("/") else target.lstrip("/")
        parts: list[str] = []
        for seg in full.split("/"):  # 规范化 ../
            if seg == "..":
                if parts:
                    parts.pop()
            elif seg and seg != ".":
                parts.append(seg)
        out[r.get("Id", "")] = (r.get("Type", ""), "/".join(parts))
    return out


def _paragraphs(root, para: str, run: str) -> list[str]:
    lines = []
    for p in root.iter(para):
        text = "".join(t.text or "" for t in p.iter(run)).strip()
        if text:
            lines.append(text)
    return lines


def _pptx(z: zipfile.ZipFile) -> str:
    pres = _xml(z, "ppt/presentation.xml")
    rels = _rels(z, "ppt/presentation.xml")
    order = [rels.get(s.get(f"{{{NS['r']}}}id"), ("", ""))[1] for s in pres.iter(f"{{{NS['p']}}}sldId")] \
        if pres is not None else []
    out = []
    for i, part in enumerate([p for p in order if p], 1):
        slide = _xml(z, part)
        if slide is None:
            continue
        lines = _paragraphs(slide, f"{{{NS['a']}}}p", f"{{{NS['a']}}}t")
        block = [f"—— 第 {i} 张 ——"] + lines
        notes = next((target for kind, target in _rels(z, part).values() if kind == NOTES), "")
        note_root = _xml(z, notes) if notes else None
        if note_root is not None:
            note_lines = [x for x in _paragraphs(note_root, f"{{{NS['a']}}}p", f"{{{NS['a']}}}t") if not x.isdigit()]
            if note_lines:
                block.append("备注：" + "\n".join(note_lines))
        out.append("\n".join(block))
    return "\n\n".join(out)


def _docx(z: zipfile.ZipFile) -> str:
    root = _xml(z, "word/document.xml")
    return "\n".join(_paragraphs(root, f"{{{NS['w']}}}p", f"{{{NS['w']}}}t")) if root is not None else ""


def _xlsx(z: zipfile.ZipFile) -> str:
    shared_root = _xml(z, "xl/sharedStrings.xml")
    shared = ["".join(t.text or "" for t in si.iter(f"{{{NS['s']}}}t"))
              for si in shared_root.findall("s:si", NS)] if shared_root is not None else []
    book = _xml(z, "xl/workbook.xml")
    rels = _rels(z, "xl/workbook.xml")
    out = []
    for sheet in book.iter(f"{{{NS['s']}}}sheet") if book is not None else []:
        part = rels.get(sheet.get(f"{{{NS['r']}}}id"), ("", ""))[1]
        root = _xml(z, part) if part else None
        if root is None:
            continue
        rows = []
        for row in root.iter(f"{{{NS['s']}}}row"):
            if len(rows) >= MAX_ROWS:
                rows.append("…（后面的行省略）")
                break
            cells = []
            for c in row.findall("s:c", NS):
                v = c.find("s:v", NS)
                kind = c.get("t", "")
                if kind == "s" and v is not None and (v.text or "").isdigit() and int(v.text) < len(shared):
                    text = shared[int(v.text)]
                elif kind == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter(f"{{{NS['s']}}}t"))
                else:
                    text = v.text if v is not None and v.text else ""
                if text:
                    cells.append(f"{c.get('r', '')}={text}")
            if cells:
                rows.append("  ".join(cells))
        out.append(f"—— 工作表「{sheet.get('name', '')}」——\n" + "\n".join(rows))
    return "\n\n".join(out)


def read(path: Path) -> str:
    """按格式读出文件里的文字；读不了返回空字符串。"""
    try:
        if path.stat().st_size > MAX_FILE:
            return ""
        with zipfile.ZipFile(path) as z:
            ext = path.suffix.lower()
            text = _pptx(z) if ext.startswith((".ppt", ".pps")) else _docx(z) if ext.startswith(".doc") else _xlsx(z)
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as e:  # 加了密码、正在写、不是这种格式
        log.debug("读文件内容失败 %s：%s", path, e)
        return ""
    return text[:MAX_CHARS]


def for_window(title: str) -> str:
    """窗口标题里那个文件的内容，带上路径和最后保存的时间；找不到、读不了就是空字符串。"""
    for name in names_in_title(title):
        path = locate(name)
        if path is None:
            continue
        text = read(path)
        if text.strip():
            saved = time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))
            return (f"【打开的文件的内容（直接读的 {path}，最后保存于 {saved}；界面上没保存的改动这里看不到）】\n{text}")
    return ""
