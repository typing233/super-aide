package io.github.typing233.superaide.core.files

import java.io.ByteArrayOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * 生成 Word 和 Excel：模型写 Markdown（Word）或 CSV / Markdown 表格（Excel），这里转成真正的 docx / xlsx，
 * WPS、Office、手机自带的文件查看器都能打开。
 */
object Make {
    // ---------------- Markdown 的一行行 ----------------

    sealed interface Block {
        data class Heading(val level: Int, val text: String) : Block
        data class Para(val text: String) : Block
        data class Bullet(val text: String, val number: String? = null, val depth: Int = 0) : Block
        data class Quote(val text: String) : Block
        data class Code(val lines: List<String>) : Block
        data class Table(val rows: List<List<String>>) : Block
        data object Rule : Block
    }

    fun blocks(md: String): List<Block> {
        val out = mutableListOf<Block>()
        val lines = md.replace("\r\n", "\n").split('\n')
        var i = 0
        val para = mutableListOf<String>()
        fun flush() { if (para.isNotEmpty()) { out += Block.Para(para.joinToString(" ").trim()); para.clear() } }
        while (i < lines.size) {
            val raw = lines[i]
            val l = raw.trim()
            when {
                l.startsWith("```") -> {
                    flush()
                    val code = mutableListOf<String>()
                    i++
                    while (i < lines.size && !lines[i].trim().startsWith("```")) code += lines[i++]
                    out += Block.Code(code)
                }
                l.isEmpty() -> flush()
                HEADING.matches(l) -> { flush(); HEADING.matchEntire(l)!!.let { out += Block.Heading(it.groupValues[1].length, it.groupValues[2].trim()) } }
                RULE.matches(l) -> { flush(); out += Block.Rule }
                l.startsWith("|") -> {
                    flush()
                    val rows = mutableListOf<List<String>>()
                    while (i < lines.size && lines[i].trim().startsWith("|")) {
                        val r = lines[i].trim()
                        if (!TABLE_SEP.matches(r)) rows += r.trim('|').split('|').map { it.trim() }
                        i++
                    }
                    out += Block.Table(rows)
                    continue
                }
                BULLET.matches(raw) -> { flush(); BULLET.matchEntire(raw)!!.let { out += Block.Bullet(it.groupValues[2], depth = it.groupValues[1].length / 2) } }
                NUMBERED.matches(raw) -> {
                    flush()
                    NUMBERED.matchEntire(raw)!!.let { out += Block.Bullet(it.groupValues[3], it.groupValues[2], it.groupValues[1].length / 2) }
                }
                l.startsWith(">") -> { flush(); out += Block.Quote(l.trimStart('>', ' ')) }
                else -> para += l
            }
            i++
        }
        flush()
        return out
    }

    private val HEADING = Regex("(#{1,6})\\s+(.*)")
    private val RULE = Regex("(-{3,}|\\*{3,}|_{3,})")
    private val TABLE_SEP = Regex("\\|?\\s*:?-{2,}:?\\s*(\\|\\s*:?-{2,}:?\\s*)*\\|?")
    private val BULLET = Regex("(\\s*)[-*+]\\s+(.*)")
    private val NUMBERED = Regex("(\\s*)(\\d+[.)、])\\s*(.*)")

    /** 行内的 **粗体**、*斜体*、`代码`、[文字](链接) */
    data class Run(val text: String, val bold: Boolean = false, val italic: Boolean = false, val code: Boolean = false)

    fun runs(s: String): List<Run> {
        val out = mutableListOf<Run>()
        var last = 0
        for (m in INLINE.findAll(s)) {
            if (m.range.first > last) out += Run(s.substring(last, m.range.first))
            val g = m.groupValues
            out += when {
                g[1].isNotEmpty() -> Run(g[1], bold = true)
                g[2].isNotEmpty() -> Run(g[2], bold = true)
                g[3].isNotEmpty() -> Run(g[3], italic = true)
                g[4].isNotEmpty() -> Run(g[4], code = true)
                else -> Run(if (g[6].isBlank() || g[5] == g[6]) g[5] else "${g[5]}（${g[6]}）")
            }
            last = m.range.last + 1
        }
        if (last < s.length) out += Run(s.substring(last))
        return out.filter { it.text.isNotEmpty() }
    }

    private val INLINE = Regex("\\*\\*(.+?)\\*\\*|__(.+?)__|(?<![*\\w])\\*(?!\\s)(.+?)(?<!\\s)\\*(?!\\*)|`([^`]+)`|\\[([^]]+)]\\(([^)]*)\\)")

    // ---------------- Word ----------------

    fun docx(markdown: String): ByteArray {
        val body = StringBuilder()
        for (b in blocks(markdown)) {
            when (b) {
                is Block.Heading -> body.append(para(runs(b.text), style = if (b.level == 1) "Title" else "Heading${minOf(b.level - 1, 3)}"))
                is Block.Para -> body.append(para(runs(b.text)))
                is Block.Bullet -> body.append(para(listOf(Run((b.number ?: "•") + " ")) + runs(b.text), indent = 360 * (b.depth + 1), hanging = 280))
                is Block.Quote -> body.append(para(runs(b.text).map { it.copy(italic = true) }, indent = 420, color = "595959"))
                is Block.Code -> b.lines.forEach { body.append(para(listOf(Run(it, code = true)), spacingAfter = 0)) }
                is Block.Table -> body.append(table(b.rows))
                Block.Rule -> body.append("<w:p><w:pPr><w:pBdr><w:bottom w:val=\"single\" w:sz=\"6\" w:space=\"1\" w:color=\"BFBFBF\"/></w:pBdr></w:pPr></w:p>")
            }
        }
        val document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="$W"><w:body>$body<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1304" w:bottom="1440" w:left="1304" w:header="851" w:footer="992" w:gutter="0"/></w:sectPr></w:body></w:document>"""
        return zip(
            "[Content_Types].xml" to """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>""",
            "_rels/.rels" to rels("http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "word/document.xml"),
            "word/_rels/document.xml.rels" to rels("http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", "styles.xml"),
            "word/document.xml" to document,
            "word/styles.xml" to WORD_STYLES,
        )
    }

    private const val W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    private fun para(runs: List<Run>, style: String? = null, indent: Int = 0, hanging: Int = 0, color: String? = null, spacingAfter: Int? = null): String =
        buildString {
            append("<w:p><w:pPr>")
            if (style != null) append("<w:pStyle w:val=\"").append(style).append("\"/>")
            if (spacingAfter != null) append("<w:spacing w:after=\"").append(spacingAfter).append("\"/>")
            if (indent > 0) append("<w:ind w:left=\"").append(indent).append("\" w:hanging=\"").append(hanging).append("\"/>")
            append("</w:pPr>")
            for (r in runs) {
                append("<w:r><w:rPr>")
                if (r.code) append("<w:rFonts w:ascii=\"Consolas\" w:hAnsi=\"Consolas\"/><w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"F2F2F2\"/>")
                if (r.bold) append("<w:b/>")
                if (r.italic) append("<w:i/>")
                if (color != null) append("<w:color w:val=\"").append(color).append("\"/>")
                append("</w:rPr><w:t xml:space=\"preserve\">").append(esc(r.text)).append("</w:t></w:r>")
            }
            append("</w:p>")
        }

    private fun table(rows: List<List<String>>): String {
        if (rows.isEmpty()) return ""
        val cols = rows.maxOf { it.size }
        val width = 9298 / cols
        return buildString {
            append("<w:tbl><w:tblPr><w:tblStyle w:val=\"TableGrid\"/><w:tblW w:w=\"0\" w:type=\"auto\"/><w:tblBorders>")
            for (side in listOf("top", "left", "bottom", "right", "insideH", "insideV")) {
                append("<w:").append(side).append(" w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"BFBFBF\"/>")
            }
            append("</w:tblBorders></w:tblPr><w:tblGrid>")
            repeat(cols) { append("<w:gridCol w:w=\"").append(width).append("\"/>") }
            append("</w:tblGrid>")
            rows.forEachIndexed { i, r ->
                append("<w:tr>")
                for (c in 0 until cols) {
                    val text = r.getOrElse(c) { "" }
                    append("<w:tc><w:tcPr><w:tcW w:w=\"").append(width).append("\" w:type=\"dxa\"/>")
                    if (i == 0) append("<w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"F2F2F2\"/>")
                    append("</w:tcPr>")
                    append(para(runs(text).map { if (i == 0) it.copy(bold = true) else it }, spacingAfter = 0))
                    append("</w:tc>")
                }
                append("</w:tr>")
            }
            append("</w:tbl><w:p/>")
        }
    }

    private val WORD_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="$W"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="微软雅黑"/><w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="300" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>""" +
        """<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>""" +
        """<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:spacing w:before="240" w:after="240"/><w:jc w:val="center"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style>""" +
        (1..3).joinToString("") { n ->
            val size = listOf(32, 28, 24)[n - 1]
            """<w:style w:type="paragraph" w:styleId="Heading$n"><w:name w:val="heading $n"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="$n"/></w:pPr><w:rPr><w:b/><w:sz w:val="$size"/></w:rPr></w:style>"""
        } +
        """<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblCellMar><w:left w:w="108" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style></w:styles>"""

    // ---------------- Excel ----------------

    /**
     * 表格内容：CSV（逗号或 Tab 分隔）或 Markdown 表格。多张工作表时每张前面一行「## 表名」。
     * 第一行加粗当表头；像数字的存成数字；以 = 开头的是公式（打开时自动算）。
     */
    fun xlsx(content: String): ByteArray {
        val sheets = sheets(content)
        val names = sheets.map { it.first }
        val files = mutableListOf(
            "[Content_Types].xml" to """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>""" +
                names.indices.joinToString("") { """<Override PartName="/xl/worksheets/sheet${it + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>""" } +
                "</Types>",
            "_rels/.rels" to rels("http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "xl/workbook.xml"),
            "xl/workbook.xml" to """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="$S" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>""" +
                names.mapIndexed { i, n -> """<sheet name="${esc(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>""" }.joinToString("") +
                """</sheets><calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>""",
            "xl/_rels/workbook.xml.rels" to """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">""" +
                names.indices.joinToString("") { """<Relationship Id="rId${it + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${it + 1}.xml"/>""" } +
                """<Relationship Id="rId${names.size + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>""",
            "xl/styles.xml" to """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="$S"><numFmts count="2"><numFmt numFmtId="164" formatCode="yyyy-mm-dd"/><numFmt numFmtId="165" formatCode="yyyy-mm-dd hh:mm"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>""",
        )
        sheets.forEachIndexed { i, (_, rows) -> files += "xl/worksheets/sheet${i + 1}.xml" to sheetXml(rows) }
        return zip(*files.toTypedArray())
    }

    private const val S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    fun sheets(content: String): List<Pair<String, List<List<String>>>> {
        val out = mutableListOf<Pair<String, List<List<String>>>>()
        var name = ""
        val buf = StringBuilder()
        fun flush() {
            if (buf.isBlank() && name.isEmpty()) return
            val rows = table(buf.toString())
            out += sheetName(name.ifEmpty { "Sheet${out.size + 1}" }, out.map { it.first }) to rows
            buf.setLength(0)
        }
        for (line in content.replace("\r\n", "\n").split('\n')) {
            val h = Regex("^#{1,3}\\s+(.+)").find(line.trim())
            if (h != null) { flush(); name = h.groupValues[1].trim(); continue }
            buf.append(line).append('\n')
        }
        flush()
        return out.ifEmpty { listOf("Sheet1" to emptyList()) }
    }

    /** 工作表名：不能超过 31 个字、不能有 []:*?/\、不能重名 */
    private fun sheetName(n: String, used: List<String>): String {
        val base = n.replace(Regex("[\\[\\]:*?/\\\\]"), " ").trim().take(31).ifBlank { "Sheet" }
        var name = base
        var i = 2
        while (used.any { it.equals(name, true) }) name = base.take(28) + " ($i)".also { i++ }
        return name
    }

    /** CSV / TSV / Markdown 表格 → 行 */
    fun table(text: String): List<List<String>> {
        val lines = text.trim('\n').split('\n').filter { it.isNotBlank() }
        if (lines.isEmpty()) return emptyList()
        if (lines.all { it.trim().startsWith("|") }) {
            return lines.map { it.trim() }.filterNot { TABLE_SEP.matches(it) }.map { r -> r.trim('|').split('|').map { it.trim() } }
        }
        val tab = lines.first().contains('\t') && !lines.first().contains(',')
        return csv(text.trim('\n'), if (tab) '\t' else ',')
    }

    /** RFC 4180：引号里可以有逗号、换行，"" 是一个引号 */
    fun csv(text: String, sep: Char = ','): List<List<String>> {
        val rows = mutableListOf<List<String>>()
        var row = mutableListOf<String>()
        val cell = StringBuilder()
        var quoted = false
        var i = 0
        while (i < text.length) {
            val c = text[i]
            if (quoted) {
                if (c == '"' && i + 1 < text.length && text[i + 1] == '"') { cell.append('"'); i++ }
                else if (c == '"') quoted = false
                else cell.append(c)
            } else when (c) {
                '"' -> if (cell.isBlank()) { cell.setLength(0); quoted = true } else cell.append(c)
                sep -> { row += cell.toString().trim(); cell.setLength(0) }
                '\n' -> { row += cell.toString().trim(); cell.setLength(0); rows += row; row = mutableListOf() }
                '\r' -> Unit
                else -> cell.append(c)
            }
            i++
        }
        if (cell.isNotEmpty() || row.isNotEmpty()) { row += cell.toString().trim(); rows += row }
        return rows.filter { r -> r.any { it.isNotEmpty() } }
    }

    private fun sheetXml(rows: List<List<String>>): String = buildString {
        val cols = rows.maxOfOrNull { it.size } ?: 0
        append("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>""").append('\n')
        append("<worksheet xmlns=\"").append(S).append("\">")
        if (rows.size > 1) append("""<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>""")
        if (cols > 0) {
            append("<cols>")
            for (c in 0 until cols) {
                val w = rows.maxOf { r -> r.getOrNull(c)?.let(::displayWidth) ?: 0 }.coerceIn(6, 60) + 2
                append("<col min=\"").append(c + 1).append("\" max=\"").append(c + 1).append("\" width=\"").append(w).append("\" customWidth=\"1\"/>")
            }
            append("</cols>")
        }
        append("<sheetData>")
        rows.forEachIndexed { ri, r ->
            append("<row r=\"").append(ri + 1).append("\">")
            r.forEachIndexed { ci, v ->
                if (v.isEmpty()) return@forEachIndexed
                val ref = colName(ci + 1) + (ri + 1)
                val style = if (ri == 0 && rows.size > 1) " s=\"1\"" else ""
                when {
                    v.startsWith("=") && v.length > 1 -> append("<c r=\"").append(ref).append('"').append(style).append("><f>").append(esc(v.substring(1))).append("</f></c>")
                    NUMBER.matches(v) -> append("<c r=\"").append(ref).append('"').append(style).append("><v>").append(v.replace(",", "")).append("</v></c>")
                    // 2026-10-01、2026-10-01 12:30 存成真正的日期（能排序、能算），表头不动
                    style.isEmpty() && serial(v) != null -> append("<c r=\"").append(ref).append("\" s=\"").append(if (v.length > 10) 3 else 2)
                        .append("\"><v>").append(serial(v)).append("</v></c>")
                    else -> append("<c r=\"").append(ref).append('"').append(style).append(" t=\"inlineStr\"><is><t xml:space=\"preserve\">").append(esc(v)).append("</t></is></c>")
                }
            }
            append("</row>")
        }
        append("</sheetData></worksheet>")
    }

    /** 像数字：-12、3.14、1,234.5（千分位）；0 开头的（电话、编号 007）当文字 */
    private val NUMBER = Regex("-?(0|[1-9]\\d{0,14}|[1-9]\\d{0,2}(,\\d{3})+)(\\.\\d+)?")

    private val DATE = Regex("(\\d{4})-(\\d{1,2})-(\\d{1,2})(?:[ T](\\d{1,2}):(\\d{2}))?")

    /** 日期 → Excel 的天数（1899-12-30 起）；不是合法日期返回 null */
    fun serial(v: String): String? {
        val m = DATE.matchEntire(v) ?: return null
        val (y, mo, d) = m.destructured.let { Triple(it.component1().toInt(), it.component2().toInt(), it.component3().toInt()) }
        val date = runCatching { java.time.LocalDate.of(y, mo, d) }.getOrNull() ?: return null
        val days = java.time.temporal.ChronoUnit.DAYS.between(java.time.LocalDate.of(1899, 12, 30), date)
        val h = m.groupValues[4].toIntOrNull() ?: return days.toString()
        val min = m.groupValues[5].toInt()
        if (h > 23) return null
        return java.math.BigDecimal(days + (h * 60 + min) / 1440.0).setScale(8, java.math.RoundingMode.HALF_UP).stripTrailingZeros().toPlainString()
    }

    private fun displayWidth(s: String) = s.sumOf { if (it.code > 0x2E80) 2 else 1 }

    fun colName(n: Int): String {
        var x = n
        val sb = StringBuilder()
        while (x > 0) { val r = (x - 1) % 26; sb.append('A' + r); x = (x - 1) / 26 }
        return sb.reverse().toString()
    }

    // ---------------- 共用 ----------------

    private fun rels(type: String, target: String) = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="$type" Target="$target"/></Relationships>"""

    private fun zip(vararg files: Pair<String, String>): ByteArray {
        val bos = ByteArrayOutputStream()
        ZipOutputStream(bos).use { z ->
            for ((name, text) in files) {
                z.putNextEntry(ZipEntry(name))
                z.write(text.toByteArray(Charsets.UTF_8))
                z.closeEntry()
            }
        }
        return bos.toByteArray()
    }

    /** XML 里的特殊字符，以及 XML 不允许的控制字符 */
    fun esc(s: String): String = buildString(s.length) {
        for (c in s) when (c) {
            '&' -> append("&amp;")
            '<' -> append("&lt;")
            '>' -> append("&gt;")
            '"' -> append("&quot;")
            '\t', '\n', '\r' -> append(c)
            else -> if (c.code < 0x20 || c == '￾' || c == '￿') Unit else append(c)
        }
    }
}
