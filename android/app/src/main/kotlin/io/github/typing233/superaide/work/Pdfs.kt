package io.github.typing233.superaide.work

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.graphics.pdf.PdfRenderer
import android.os.Build
import android.os.ParcelFileDescriptor
import android.text.Layout
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.StaticLayout
import android.text.TextPaint
import android.text.style.StyleSpan
import android.text.style.TypefaceSpan
import androidx.annotation.RequiresApi
import io.github.typing233.superaide.a11y.Ocr
import io.github.typing233.superaide.core.files.Make
import io.github.typing233.superaide.core.work.Platform
import io.github.typing233.superaide.diag.Diag
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/** 读 PDF（安卓 15 起系统能直接给文字；扫描件和更老的系统把页面画出来认字）和生成 PDF。 */
object Pdfs {
    /** 认字最多认这么多页（每页半秒左右） */
    private const val OCR_PAGES = 30

    suspend fun read(file: File): Platform.Pdf? = withContext(Dispatchers.IO) {
        val fd = runCatching { ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY) }.getOrElse { return@withContext null }
        val renderer = try {
            PdfRenderer(fd)
        } catch (e: SecurityException) {
            fd.close()
            return@withContext Platform.Pdf(0, "（这个 PDF 有密码，读不了：请用户去掉密码后再发过来）")
        } catch (e: Exception) {
            fd.close()
            Diag.error("pdf.open", e)
            return@withContext null
        }
        renderer.use { r ->
            val out = StringBuilder()
            var ocred = 0
            for (i in 0 until r.pageCount) {
                val text = r.openPage(i).use { page ->
                    val t = if (Build.VERSION.SDK_INT >= 35) systemText(page) else ""
                    // 系统给不出字（扫描件、老系统）：画出来认
                    if (t.trim().length >= 20 || ocred >= OCR_PAGES) t
                    else { ocred++; ocr(page).ifBlank { t } }
                }
                out.append("## 第 ").append(i + 1).append(" 页\n").append(text.trim()).append("\n\n")
            }
            if (ocred >= OCR_PAGES && r.pageCount > OCR_PAGES) out.append("（后面的页是扫描的图片，只认了前 $OCR_PAGES 页）")
            Platform.Pdf(r.pageCount, out.toString().trim())
        }
    }

    @RequiresApi(35)
    private fun systemText(page: PdfRenderer.Page): String =
        runCatching { page.textContents.joinToString("\n") { it.text } }.getOrDefault("")

    private suspend fun ocr(page: PdfRenderer.Page): String {
        val w = 1240
        val h = (w.toFloat() * page.height / page.width).toInt().coerceIn(1, 4000)
        val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        bmp.eraseColor(Color.WHITE)
        page.render(bmp, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
        return runCatching { Ocr.lines(bmp).joinToString("\n") { it.text } }.getOrDefault("").also { bmp.recycle() }
    }

    // ---------------- 生成 ----------------

    private const val PAGE_W = 595 // A4，单位是点
    private const val PAGE_H = 842
    private const val MARGIN = 54f

    /** Markdown → PDF：标题加粗放大，列表缩进，表格按行画，代码等宽 */
    suspend fun write(markdown: String, file: File) = withContext(Dispatchers.Default) {
        val doc = PdfDocument()
        var pageNo = 0
        var page: PdfDocument.Page? = null
        var y = MARGIN
        val width = (PAGE_W - 2 * MARGIN).toInt()
        fun newPage() {
            page?.let { doc.finishPage(it) }
            page = doc.startPage(PdfDocument.PageInfo.Builder(PAGE_W, PAGE_H, ++pageNo).create())
            y = MARGIN
        }
        /** 一段排好的字：放不下就换页，比一页还长的按行拆开 */
        fun draw(layout: StaticLayout, indent: Float = 0f, after: Float = 6f) {
            var line = 0
            while (line < layout.lineCount) {
                if (page == null || y + (layout.getLineBottom(line) - layout.getLineTop(line)) > PAGE_H - MARGIN) newPage()
                var last = line
                while (last + 1 < layout.lineCount && y + layout.getLineBottom(last + 1) - layout.getLineTop(line) <= PAGE_H - MARGIN) last++
                val c: Canvas = page!!.canvas
                c.save()
                c.translate(MARGIN + indent, y - layout.getLineTop(line))
                c.clipRect(0f, layout.getLineTop(line).toFloat(), layout.width.toFloat(), layout.getLineBottom(last).toFloat())
                layout.draw(c)
                c.restore()
                y += layout.getLineBottom(last) - layout.getLineTop(line)
                line = last + 1
            }
            y += after
        }
        fun layout(text: CharSequence, size: Float, w: Int = width, bold: Boolean = false, mono: Boolean = false, color: Int = Color.rgb(33, 33, 33)) =
            StaticLayout.Builder.obtain(text, 0, text.length, TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
                textSize = size
                this.color = color
                typeface = if (mono) Typeface.MONOSPACE else Typeface.create(Typeface.DEFAULT, if (bold) Typeface.BOLD else Typeface.NORMAL)
            }, w).setAlignment(Layout.Alignment.ALIGN_NORMAL).setLineSpacing(0f, 1.25f).build()

        for (b in Make.blocks(markdown)) when (b) {
            is Make.Block.Heading -> { y += 6f; draw(layout(rich(b.text), listOf(20f, 16f, 14f, 12.5f)[minOf(b.level, 4) - 1], bold = true), after = 8f) }
            is Make.Block.Para -> draw(layout(rich(b.text), 11f))
            is Make.Block.Bullet -> {
                val indent = 14f * (b.depth + 1)
                draw(layout(SpannableStringBuilder(b.number ?: "•").append("  ").append(rich(b.text)), 11f, w = (width - indent).toInt()), indent, after = 3f)
            }
            is Make.Block.Quote -> draw(layout(rich(b.text), 11f, w = width - 16, color = Color.rgb(96, 96, 96)), 16f)
            is Make.Block.Code -> draw(layout(b.lines.joinToString("\n"), 9.5f, mono = true, color = Color.rgb(60, 60, 60)))
            is Make.Block.Table -> {
                // 列宽按内容分（太宽的按比例缩），每行高度取最高的格子；放不下就换页
                val cols = b.rows.maxOfOrNull { it.size } ?: 0
                if (cols > 0) {
                    val pad = 5f
                    val measure = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 10f }
                    val natural = (0 until cols).map { c -> b.rows.maxOf { r -> measure.measureText(r.getOrElse(c) { "" }) } + 2 * pad + 2 }
                    val total = natural.sum()
                    val widths = if (total <= width) natural else natural.map { maxOf(36f, it * width / total) }.let { w -> w.map { it * width / w.sum() } }
                    val grid = Paint().apply { color = Color.rgb(200, 200, 200); strokeWidth = 0.6f; style = Paint.Style.STROKE }
                    val head = Paint().apply { color = Color.rgb(242, 242, 242) }
                    y += 2f
                    b.rows.forEachIndexed { i, r ->
                        val cells = (0 until cols).map { c -> layout(rich(r.getOrElse(c) { "" }), 10f, w = (widths[c] - 2 * pad).toInt().coerceAtLeast(10), bold = i == 0) }
                        val h = cells.maxOf { it.height } + 2 * pad
                        if (page == null || y + h > PAGE_H - MARGIN) newPage()
                        val cv = page!!.canvas
                        var x = MARGIN
                        if (i == 0) cv.drawRect(MARGIN, y, MARGIN + widths.sum(), y + h, head)
                        cells.forEachIndexed { c, l ->
                            cv.save(); cv.translate(x + pad, y + pad); l.draw(cv); cv.restore()
                            cv.drawRect(x, y, x + widths[c], y + h, grid)
                            x += widths[c]
                        }
                        y += h
                    }
                    y += 10f
                }
            }
            Make.Block.Rule -> { if (page == null) newPage(); page!!.canvas.drawLine(MARGIN, y, PAGE_W - MARGIN, y, Paint().apply { color = Color.LTGRAY }); y += 10f }
        }
        if (page == null) newPage()
        doc.finishPage(page!!)
        file.outputStream().use { doc.writeTo(it) }
        doc.close()
    }

    /** 行内的粗体、斜体、代码 */
    private fun rich(s: String): CharSequence {
        val sb = SpannableStringBuilder()
        for (r in Make.runs(s)) {
            val start = sb.length
            sb.append(r.text)
            if (r.bold) sb.setSpan(StyleSpan(Typeface.BOLD), start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            if (r.italic) sb.setSpan(StyleSpan(Typeface.ITALIC), start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            if (r.code) sb.setSpan(TypefaceSpan("monospace"), start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        return sb
    }
}
