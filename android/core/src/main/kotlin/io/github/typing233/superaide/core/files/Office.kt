package io.github.typing233.superaide.core.files

import org.xml.sax.Attributes
import org.xml.sax.helpers.DefaultHandler
import java.io.ByteArrayInputStream
import java.nio.ByteBuffer
import java.nio.charset.Charset
import java.nio.charset.CodingErrorAction
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.zip.ZipInputStream
import javax.xml.parsers.SAXParserFactory

/**
 * 读 Word / Excel / PowerPoint（docx / xlsx / pptx，都是压缩包里的 XML）和各种文本文件，转成给模型读的文字。
 * 标题、列表、表格保留成轻量的 Markdown。老格式（doc / xls / ppt）不认。
 */
object Office {
    /** 抽出来的字最多这么多（再多模型也读不完，分页读就够了） */
    const val MAX_CHARS = 2_000_000

    fun extract(name: String, bytes: ByteArray): String? = when (Workspace.ext(name)) {
        "docx", "docm", "dotx" -> docx(bytes)
        "xlsx", "xlsm" -> xlsx(bytes)
        "pptx", "pptm", "ppsx" -> pptx(bytes)
        else -> if (Workspace.isText(name)) decode(bytes) else null
    }

    /** 文本文件的编码：有 BOM 按 BOM，是合法 UTF-8 就是 UTF-8，不然按 GB18030（国内老文件常见 GBK） */
    fun decode(bytes: ByteArray): String {
        if (bytes.size >= 3 && bytes[0] == 0xEF.toByte() && bytes[1] == 0xBB.toByte() && bytes[2] == 0xBF.toByte()) {
            return String(bytes, 3, bytes.size - 3, Charsets.UTF_8)
        }
        if (bytes.size >= 2 && bytes[0] == 0xFF.toByte() && bytes[1] == 0xFE.toByte()) return String(bytes, 2, bytes.size - 2, Charsets.UTF_16LE)
        if (bytes.size >= 2 && bytes[0] == 0xFE.toByte() && bytes[1] == 0xFF.toByte()) return String(bytes, 2, bytes.size - 2, Charsets.UTF_16BE)
        return runCatching {
            Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(bytes)).toString()
        }.getOrElse { String(bytes, Charset.forName("GB18030")) }
    }

    /** 压缩包里的文件（只取 XML 和关系表，图片不要） */
    private fun unzip(bytes: ByteArray, want: (String) -> Boolean): Map<String, ByteArray> {
        val out = mutableMapOf<String, ByteArray>()
        ZipInputStream(ByteArrayInputStream(bytes)).use { z ->
            while (true) {
                val e = z.nextEntry ?: break
                if (!e.isDirectory && want(e.name)) out[e.name] = z.readBytes()
            }
        }
        return out
    }

    private fun sax(xml: ByteArray, handler: DefaultHandler) {
        val f = SAXParserFactory.newInstance().apply { isNamespaceAware = true }
        f.newSAXParser().parse(ByteArrayInputStream(xml), handler)
    }

    // ---------------- Word ----------------

    fun docx(bytes: ByteArray): String {
        val parts = unzip(bytes) { it == "word/document.xml" || it == "word/footnotes.xml" }
        val doc = parts["word/document.xml"] ?: return ""
        val out = StringBuilder()
        sax(doc, WordHandler(out))
        parts["word/footnotes.xml"]?.let { f ->
            val notes = StringBuilder()
            sax(f, WordHandler(notes))
            if (notes.isNotBlank()) out.append("\n\n## 脚注\n").append(notes)
        }
        return tidy(out)
    }

    private class WordHandler(val out: StringBuilder) : DefaultHandler() {
        private val para = StringBuilder()
        private var prefix = ""
        private var inText = false
        private var tableDepth = 0
        private val row = mutableListOf<String>()
        private var cell: StringBuilder? = null

        override fun startElement(uri: String?, local: String, qName: String?, a: Attributes) {
            when (local) {
                "p" -> { para.setLength(0); prefix = "" }
                "pStyle" -> {
                    val v = a.getValue(uri, "val") ?: a.getValue("w:val").orEmpty()
                    val level = Regex("(?i)heading\\s*(\\d)|^(\\d)$|标题\\s*(\\d)").find(v)?.groupValues?.drop(1)?.firstOrNull { it.isNotEmpty() }?.toIntOrNull()
                    prefix = when {
                        v.equals("Title", true) -> "# "
                        level != null -> "#".repeat(minOf(level + 1, 4)) + " "
                        else -> prefix
                    }
                }
                "numPr" -> if (prefix.isEmpty()) prefix = "- "
                "t" -> inText = true
                "tab" -> para.append('\t')
                "br", "cr" -> para.append('\n')
                "tbl" -> tableDepth++
                "tr" -> row.clear()
                "tc" -> cell = StringBuilder()
            }
        }

        override fun characters(ch: CharArray, start: Int, length: Int) {
            if (inText) para.appendRange(ch, start, start + length)
        }

        override fun endElement(uri: String?, local: String, qName: String?) {
            when (local) {
                "t" -> inText = false
                "p" -> {
                    val text = para.toString().trim()
                    val c = cell
                    if (c != null) { if (text.isNotEmpty()) { if (c.isNotEmpty()) c.append(' '); c.append(text) } }
                    else if (text.isNotEmpty()) out.append(prefix).append(text).append("\n\n")
                    para.setLength(0)
                }
                "tc" -> { row += cell.toString().replace('|', '｜'); cell = null }
                "tr" -> if (tableDepth > 0 && row.any { it.isNotBlank() }) out.append("| ").append(row.joinToString(" | ")).append(" |\n")
                "tbl" -> { tableDepth--; out.append('\n') }
            }
        }
    }

    // ---------------- PowerPoint ----------------

    fun pptx(bytes: ByteArray): String {
        val parts = unzip(bytes) { SLIDE.matches(it) || NOTES.matches(it) }
        val slides = parts.keys.mapNotNull { k -> SLIDE.matchEntire(k)?.groupValues?.get(1)?.toInt()?.let { it to k } }.sortedBy { it.first }
        val out = StringBuilder()
        for ((n, k) in slides) {
            out.append("## 第 ").append(n).append(" 页\n")
            out.append(slideText(parts.getValue(k)))
            parts["ppt/notesSlides/notesSlide$n.xml"]?.let { slideText(it) }?.takeIf { it.isNotBlank() }?.let {
                out.append("（备注）").append(it.trim()).append('\n')
            }
            out.append('\n')
        }
        return tidy(out)
    }

    private val SLIDE = Regex("ppt/slides/slide(\\d+)\\.xml")
    private val NOTES = Regex("ppt/notesSlides/notesSlide(\\d+)\\.xml")

    private fun slideText(xml: ByteArray): String {
        val out = StringBuilder()
        val para = StringBuilder()
        var inText = false
        sax(xml, object : DefaultHandler() {
            override fun startElement(uri: String?, local: String, qName: String?, a: Attributes) {
                if (local == "t") inText = true
                if (local == "p") para.setLength(0)
                if (local == "br") para.append('\n')
            }
            override fun characters(ch: CharArray, start: Int, length: Int) { if (inText) para.appendRange(ch, start, start + length) }
            override fun endElement(uri: String?, local: String, qName: String?) {
                if (local == "t") inText = false
                if (local == "p") { val t = para.toString().trim(); if (t.isNotEmpty() && !t.all { it.isDigit() }) out.append(t).append('\n') }
            }
        })
        return out.toString()
    }

    // ---------------- Excel ----------------

    fun xlsx(bytes: ByteArray): String {
        val parts = unzip(bytes) {
            it == "xl/workbook.xml" || it == "xl/_rels/workbook.xml.rels" || it == "xl/sharedStrings.xml" || it == "xl/styles.xml" ||
                it.startsWith("xl/worksheets/sheet")
        }
        val shared = parts["xl/sharedStrings.xml"]?.let(::sharedStrings).orEmpty()
        val dates = parts["xl/styles.xml"]?.let(::dateStyles).orEmpty()
        val rels = parts["xl/_rels/workbook.xml.rels"]?.let(::relations).orEmpty()
        val sheets = parts["xl/workbook.xml"]?.let(::sheetList).orEmpty()
            .mapNotNull { (name, rid) -> rels[rid]?.let { t -> name to "xl/" + t.removePrefix("/xl/").removePrefix("xl/") } }
            .ifEmpty { parts.keys.filter { it.startsWith("xl/worksheets/sheet") }.sorted().map { it.substringAfterLast('/').removeSuffix(".xml") to it } }
        val out = StringBuilder()
        for ((name, path) in sheets) {
            val xml = parts[path] ?: continue
            out.append("## 工作表：").append(name).append('\n')
            sheet(xml, shared, dates, out)
            out.append('\n')
            if (out.length > MAX_CHARS) break
        }
        return out.toString().trimEnd()
    }

    private fun sharedStrings(xml: ByteArray): List<String> {
        val list = mutableListOf<String>()
        val cur = StringBuilder()
        var inT = false
        var inRph = false
        sax(xml, object : DefaultHandler() {
            override fun startElement(uri: String?, local: String, qName: String?, a: Attributes) {
                when (local) { "si" -> cur.setLength(0); "t" -> inT = true; "rPh" -> inRph = true }
            }
            override fun characters(ch: CharArray, start: Int, length: Int) { if (inT && !inRph) cur.appendRange(ch, start, start + length) }
            override fun endElement(uri: String?, local: String, qName: String?) {
                when (local) { "si" -> list += cur.toString(); "t" -> inT = false; "rPh" -> inRph = false }
            }
        })
        return list
    }

    /** 哪些单元格样式是日期（内置格式 14–22、45–47，或自定义格式里有年月日时分） */
    private fun dateStyles(xml: ByteArray): Set<Int> {
        val custom = mutableMapOf<Int, String>()
        val xfs = mutableListOf<Int>()
        var inCellXfs = false
        sax(xml, object : DefaultHandler() {
            override fun startElement(uri: String?, local: String, qName: String?, a: Attributes) {
                when (local) {
                    "numFmt" -> a.getValue("numFmtId")?.toIntOrNull()?.let { custom[it] = a.getValue("formatCode").orEmpty() }
                    "cellXfs" -> inCellXfs = true
                    "xf" -> if (inCellXfs) xfs += a.getValue("numFmtId")?.toIntOrNull() ?: 0
                }
            }
            override fun endElement(uri: String?, local: String, qName: String?) { if (local == "cellXfs") inCellXfs = false }
        })
        return xfs.indices.filter { i ->
            val id = xfs[i]
            id in 14..22 || id in 45..47 || custom[id]?.let { f -> DATE_CODE.containsMatchIn(f.replace(QUOTED, "")) } == true
        }.toSet()
    }

    private val QUOTED = Regex("\"[^\"]*\"|\\[[^]]*]")
    private val DATE_CODE = Regex("[ymdhs]", RegexOption.IGNORE_CASE)

    private fun relations(xml: ByteArray): Map<String, String> {
        val m = mutableMapOf<String, String>()
        sax(xml, object : DefaultHandler() {
            override fun startElement(uri: String?, local: String, qName: String?, a: Attributes) {
                if (local == "Relationship") m[a.getValue("Id").orEmpty()] = a.getValue("Target").orEmpty()
            }
        })
        return m
    }

    private fun sheetList(xml: ByteArray): List<Pair<String, String>> {
        val l = mutableListOf<Pair<String, String>>()
        sax(xml, object : DefaultHandler() {
            override fun startElement(uri: String?, local: String, qName: String?, a: Attributes) {
                if (local != "sheet") return
                val rid = (0 until a.length).firstOrNull { a.getLocalName(it) == "id" }?.let { a.getValue(it) }.orEmpty()
                l += a.getValue("name").orEmpty() to rid
            }
        })
        return l
    }

    private fun sheet(xml: ByteArray, shared: List<String>, dates: Set<Int>, out: StringBuilder) {
        val row = sortedMapOf<Int, String>()
        var col = 0
        var type = ""
        var style = 0
        val value = StringBuilder()
        var inValue = false
        var rows = 0
        sax(xml, object : DefaultHandler() {
            override fun startElement(uri: String?, local: String, qName: String?, a: Attributes) {
                when (local) {
                    "row" -> { row.clear(); col = 0 }
                    "c" -> {
                        col = a.getValue("r")?.let(::column) ?: (col + 1)
                        type = a.getValue("t").orEmpty()
                        style = a.getValue("s")?.toIntOrNull() ?: 0
                        value.setLength(0)
                    }
                    "v", "t" -> inValue = true
                }
            }
            override fun characters(ch: CharArray, start: Int, length: Int) { if (inValue) value.appendRange(ch, start, start + length) }
            override fun endElement(uri: String?, local: String, qName: String?) {
                when (local) {
                    "v", "t" -> inValue = false
                    "c" -> {
                        val v = value.toString()
                        val text = when (type) {
                            "s" -> v.toIntOrNull()?.let { shared.getOrNull(it) }.orEmpty()
                            "b" -> if (v == "1") "TRUE" else "FALSE"
                            "inlineStr", "str", "e" -> v
                            else -> if (style in dates) serialDate(v) ?: v else number(v)
                        }
                        if (text.isNotEmpty()) row[col] = text.replace('|', '｜').replace('\n', ' ')
                    }
                    "row" -> if (row.isNotEmpty() && out.length < MAX_CHARS) {
                        out.append("| ").append((1..row.lastKey()).joinToString(" | ") { row[it].orEmpty() }).append(" |\n")
                        rows++
                    }
                }
            }
        })
        if (rows == 0) out.append("（空）\n")
    }

    /** A1 → 1，AB12 → 28 */
    fun column(ref: String): Int {
        var n = 0
        for (ch in ref) { if (ch !in 'A'..'Z') break; n = n * 26 + (ch - 'A' + 1) }
        return n
    }

    /** 1.0E3、12.300000000000001 这类浮点写法收一收 */
    private fun number(v: String): String {
        val d = v.toDoubleOrNull() ?: return v
        if (d == Math.rint(d) && kotlin.math.abs(d) < 1e15) return d.toLong().toString()
        return java.math.BigDecimal(d).round(java.math.MathContext(12)).stripTrailingZeros().toPlainString()
    }

    /** Excel 的日期是 1899-12-30 起的天数 */
    fun serialDate(v: String): String? {
        val d = v.toDoubleOrNull() ?: return null
        if (d < 0 || d > 2_958_465) return null
        val base = LocalDateTime.of(1899, 12, 30, 0, 0)
        val t = base.plusSeconds(Math.round(d * 86400))
        return if (d == Math.floor(d)) t.toLocalDate().toString()
        else if (d < 1) t.format(DateTimeFormatter.ofPattern("HH:mm:ss"))
        else t.format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"))
    }

    private fun tidy(sb: StringBuilder): String = sb.toString().replace(Regex("\n{3,}"), "\n\n").trim()
}
