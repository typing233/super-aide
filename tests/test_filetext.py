"""界面层读不到文档内容时直接读打开的文件（snapshot/filetext.py）：标题里认文件名、按格式读出文字。"""

import zipfile

from super_aide.snapshot import filetext

A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
RELS = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
SLIDE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"


def zipped(path, parts: dict[str, str]):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in parts.items():
            z.writestr(name, text)
    return path


def slide(*paragraphs: str) -> str:
    body = "".join(f"<a:p><a:r><a:t>{p}</a:t></a:r></a:p>" for p in paragraphs)
    return f'<p:sld {A} {P}><p:cSld><p:spTree><p:sp><p:txBody>{body}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>'


def test_names_in_title():
    assert filetext.names_in_title("成本动态预测_完整汇报.pptx - PowerPoint") == ["成本动态预测_完整汇报.pptx"]
    assert filetext.names_in_title(r"D:\工作\预算.xlsx - Excel") == [r"D:\工作\预算.xlsx"]
    assert filetext.names_in_title("无标题 - 记事本") == []


def test_pptx_slides_in_presentation_order_with_notes(tmp_path):
    path = zipped(tmp_path / "汇报.pptx", {
        # 文件里的顺序和放映顺序不一样：按 presentation.xml 的 sldIdLst
        "ppt/presentation.xml": f'<p:presentation {P} {R}><p:sldIdLst><p:sldId id="256" r:id="rId2"/>'
                                f'<p:sldId id="257" r:id="rId1"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": f'<Relationships {RELS}>'
                                           f'<Relationship Id="rId1" Type="{SLIDE}" Target="slides/slide1.xml"/>'
                                           f'<Relationship Id="rId2" Type="{SLIDE}" Target="slides/slide2.xml"/></Relationships>',
        "ppt/slides/slide1.xml": slide("研究方法", "用时序模型做动态预测"),
        "ppt/slides/slide2.xml": slide("成本为何难以预测", "token 是主要可变成本"),
        "ppt/slides/_rels/slide2.xml.rels": f'<Relationships {RELS}><Relationship Id="rId9" Type="{filetext.NOTES}" '
                                            f'Target="../notesSlides/notesSlide1.xml"/></Relationships>',
        "ppt/notesSlides/notesSlide1.xml": slide("讲稿：先讲成本结构", "1"),  # 备注页上的页码不要
    })
    text = filetext.read(path)
    assert text.index("成本为何难以预测") < text.index("研究方法")
    assert "—— 第 1 张 ——\n成本为何难以预测\ntoken 是主要可变成本\n备注：讲稿：先讲成本结构" in text
    assert "备注：讲稿：先讲成本结构\n1" not in text


def test_docx_and_xlsx(tmp_path):
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    docx = zipped(tmp_path / "a.docx", {
        "word/document.xml": f"<w:document {w}><w:body><w:p><w:r><w:t>第一段</w:t></w:r><w:r><w:t>接着写</w:t></w:r></w:p>"
                             f"<w:p><w:r><w:t>第二段</w:t></w:r></w:p></w:body></w:document>"})
    assert filetext.read(docx) == "第一段接着写\n第二段"

    s = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    xlsx = zipped(tmp_path / "b.xlsx", {
        "xl/workbook.xml": f'<workbook {s} {R}><sheets><sheet name="销售" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships {RELS}><Relationship Id="rId1" Type="x" '
                                      f'Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/sharedStrings.xml": f"<sst {s}><si><t>日期</t></si><si><t>金额</t></si></sst>",
        "xl/worksheets/sheet1.xml": f'<worksheet {s}><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c>'
                                    f'<c r="B1" t="s"><v>1</v></c></row><row r="2"><c r="A2"><v>46296</v></c>'
                                    f'<c r="B2"><v>120</v></c></row></sheetData></worksheet>'})
    assert filetext.read(xlsx) == "—— 工作表「销售」——\nA1=日期  B1=金额\nA2=46296  B2=120"


def test_window_title_with_a_full_path_is_read_directly(tmp_path):
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    path = zipped(tmp_path / "说明.docx", {"word/document.xml": f"<w:document {w}><w:body><w:p><w:r><w:t>正文</w:t>"
                                                                f"</w:r></w:p></w:body></w:document>"})
    text = filetext.for_window(f"{path} - WPS 文字")
    assert text.startswith("【打开的文件的内容（直接读的") and text.endswith("正文")
    assert filetext.for_window("没保存过的演示文稿1 - PowerPoint") == ""
    assert filetext.read(tmp_path / "坏的.pptx") == ""  # 不存在、不是压缩包：读不了就算了
