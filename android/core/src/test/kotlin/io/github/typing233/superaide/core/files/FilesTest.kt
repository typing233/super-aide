package io.github.typing233.superaide.core.files

import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class OfficeTest {
    @Test fun docxRoundTrip() {
        val md = """
            # 周报
            ## 本周完成
            - 修好了 **登录** 问题
            - 上线了 `v2` 接口
            1. 第一步
            普通段落，带 [链接](https://example.com)。

            | 项目 | 进度 |
            |---|---|
            | 搜索 | 90% |
        """.trimIndent()
        val bytes = Make.docx(md)
        val names = entries(bytes)
        assertTrue("word/document.xml" in names && "word/styles.xml" in names && "[Content_Types].xml" in names)
        val text = Office.docx(bytes)
        assertTrue("# 周报" in text, text)
        assertTrue("## 本周完成" in text)
        assertTrue("• 修好了 登录 问题" in text)
        assertTrue("普通段落，带 链接（https://example.com）。" in text)
        assertTrue("| 项目 | 进度 |" in text && "| 搜索 | 90% |" in text)
    }

    @Test fun xlsxRoundTrip() {
        val content = """
            ## 支出
            日期,项目,金额
            2026-10-01,"午饭, 加饮料",35.5
            2026-10-02,电话,007
            合计,,=SUM(C2:C3)
            ## 收入
            | 月份 | 金额 |
            |---|---|
            | 10月 | 1,200 |
        """.trimIndent()
        val text = Office.xlsx(Make.xlsx(content))
        assertTrue("## 工作表：支出" in text, text)
        assertTrue("| 2026-10-01 | 午饭, 加饮料 | 35.5 |" in text)
        assertTrue("| 2026-10-02 | 电话 | 007 |" in text, "0 开头的当文字")
        assertTrue("## 工作表：收入" in text && "| 10月 | 1200 |" in text)
    }

    @Test fun xlsxDatesAndSharedStrings() {
        val bytes = zip(
            "xl/workbook.xml" to """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="表1" sheetId="1" r:id="rId1"/></sheets></workbook>""",
            "xl/_rels/workbook.xml.rels" to """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>""",
            "xl/sharedStrings.xml" to """<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>名字</t></si><si><r><t>生</t></r><r><t>日</t></r></si></sst>""",
            "xl/styles.xml" to """<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts><numFmt numFmtId="176" formatCode="yyyy&quot;年&quot;m&quot;月&quot;d&quot;日&quot;"/></numFmts><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="176"/></cellXfs></styleSheet>""",
            "xl/worksheets/sheet1.xml" to """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
                <row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>
                <row r="2"><c r="A2" t="inlineStr"><is><t>小明</t></is></c><c r="B2"><v>12.300000000000001</v></c><c r="C2" s="1"><v>45931</v></c><c r="D2" s="2"><v>45931.5</v></c></row>
                </sheetData></worksheet>""",
        )
        val text = Office.xlsx(bytes)
        assertTrue("## 工作表：表1" in text, text)
        assertTrue("| 名字 |  | 生日 |" in text)
        assertTrue("| 小明 | 12.3 | 2025-10-01 | 2025-10-01 12:00 |" in text)
    }

    @Test fun pptxSlidesInOrderWithNotes() {
        fun slide(vararg lines: String) = """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>""" +
            lines.joinToString("") { "<p:sp><p:txBody><a:p><a:r><a:t>$it</a:t></a:r></a:p></p:txBody></p:sp>" } + "</p:spTree></p:cSld></p:sld>"
        val bytes = zip(
            "ppt/slides/slide10.xml" to slide("最后一页"),
            "ppt/slides/slide2.xml" to slide("第二页标题", "要点 A"),
            "ppt/slides/slide1.xml" to slide("封面"),
            "ppt/notesSlides/notesSlide2.xml" to slide("讲稿：先讲 A", "2"),
        )
        val text = Office.pptx(bytes)
        val i1 = text.indexOf("第 1 页"); val i2 = text.indexOf("第 2 页"); val i10 = text.indexOf("第 10 页")
        assertTrue(i1 in 0 until i2 && i2 < i10, text)
        assertTrue("（备注）讲稿：先讲 A" in text)
        assertTrue("要点 A" in text)
    }

    @Test fun decodesGbkAndBom() {
        assertEquals("中文内容", Office.decode("中文内容".toByteArray(charset("GBK"))))
        assertEquals("中文", Office.decode(byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte()) + "中文".toByteArray()))
        assertEquals("héllo 你好", Office.decode("héllo 你好".toByteArray()))
    }

    @Test fun csvQuotesAndNewlines() {
        assertEquals(listOf(listOf("a", "b,c", "d\"e"), listOf("多\n行", "x")), Make.csv("a,\"b,c\",\"d\"\"e\"\n\"多\n行\",x\n"))
        assertEquals("AB", Make.colName(28))
        assertEquals("45931", Make.serial("2025-10-01"))
        assertEquals("45931.5", Make.serial("2025-10-01 12:00"))
        assertEquals(null, Make.serial("2025-02-30"))
        assertEquals(28, Office.column("AB12"))
    }

    private fun entries(bytes: ByteArray): Set<String> {
        val out = mutableSetOf<String>()
        ZipInputStream(bytes.inputStream()).use { z -> while (true) out += (z.nextEntry ?: break).name }
        return out
    }

    private fun zip(vararg files: Pair<String, String>): ByteArray {
        val bos = ByteArrayOutputStream()
        ZipOutputStream(bos).use { z -> for ((n, t) in files) { z.putNextEntry(ZipEntry(n)); z.write(t.toByteArray()); z.closeEntry() } }
        return bos.toByteArray()
    }
}

class WorkspaceTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun staysInside() {
        val ws = Workspace(tmp.newFolder("c1"))
        assertEquals("a/b.txt", ws.relative(ws.resolve("a/b.txt")))
        assertEquals("x.txt", ws.relative(ws.resolve("./x.txt")))
        for (bad in listOf("../c2/x", "/etc/passwd", "a/../../x", "", "..", "C:\\Windows\\x")) {
            assertFailsWith<Workspace.Outside>(bad) { ws.resolve(bad) }
        }
    }

    @Test fun uniqueNamesAndListing() {
        val ws = Workspace(tmp.newFolder("c1"))
        ws.unique("inbox", "合同.pdf").writeText("1")
        val second = ws.unique("inbox", "合同.pdf")
        assertEquals("合同 (2).pdf", second.name)
        second.writeText("2")
        ws.resolve("报告.docx").writeText("x")
        ws.unique("web", "a?b.pdf").writeText("y")
        assertEquals(listOf("inbox/合同 (2).pdf", "inbox/合同.pdf", "报告.docx", "web/a_b.pdf"), ws.list().map { it.path })
        assertEquals(listOf("用户给的", "用户给的", "生成的", "网上下载的"), ws.list().map { it.origin })
    }
}
