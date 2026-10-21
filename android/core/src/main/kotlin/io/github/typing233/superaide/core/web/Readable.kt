package io.github.typing233.superaide.core.web

import org.jsoup.Jsoup
import org.jsoup.nodes.Document
import org.jsoup.nodes.Element
import org.jsoup.nodes.Node
import org.jsoup.nodes.TextNode
import java.io.ByteArrayInputStream

/**
 * 网页 → 给模型读的正文：去掉脚本、导航、页脚这类，标题、列表、表格保留成轻量的 Markdown；
 * 正文里的链接另列出来（模型要接着点进去时用）。
 */
object Readable {
    data class Page(val title: String, val text: String, val links: List<Pair<String, String>>)

    /** charset 是响应头里给的（可能为空，jsoup 再看 meta） */
    fun parse(bytes: ByteArray, charset: String?, url: String): Document =
        Jsoup.parse(ByteArrayInputStream(bytes), charset, url)

    fun extract(html: String, url: String): Page = extract(Jsoup.parse(html, url))

    fun extract(doc: Document): Page {
        val title = doc.title().trim().ifBlank { doc.selectFirst("meta[property=og:title]")?.attr("content")?.trim().orEmpty() }
        doc.select(JUNK).remove()
        val body = doc.body() ?: return Page(title, "", emptyList())
        val root = main(body) ?: body
        root.select(CHROME).remove()
        val out = StringBuilder()
        render(root, out, pre = false)
        val text = tidy(out.toString())
        return Page(title, text, links(root))
    }

    /** 正文太短，多半是靠 JS 才渲染出来的空壳、跳转页或"请开启 JavaScript"：要用浏览器再打开一次 */
    fun looksEmpty(text: String): Boolean = text.length < 300

    private const val JUNK = "script, style, noscript, template, svg, canvas, iframe, object, embed, link, meta, [hidden], [aria-hidden=true]"
    private const val CHROME = "nav, footer, aside, [role=navigation], [role=banner], [role=contentinfo], [role=complementary], " +
        ".nav, .navbar, .menu, .breadcrumb, .footer, .sidebar, .advert, .ads, .share, .comment-form, #footer, #nav, #sidebar"

    /** 有明确正文区域（article / main）、而且字够多就只读它 */
    private fun main(body: Element): Element? {
        val total = body.text().length
        val candidates = body.select("article, main, [role=main], #content, #article, .article, .post, .entry-content, .rich_media_content")
        return candidates.maxByOrNull { it.text().length }?.takeIf { it.text().length >= maxOf(400, total / 3) }
    }

    private val BLOCK = setOf(
        "p", "div", "section", "article", "main", "header", "ul", "ol", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot",
        "blockquote", "figure", "figcaption", "form", "fieldset", "details", "summary", "address", "hr",
    )

    private fun render(node: Node, out: StringBuilder, pre: Boolean) {
        when (node) {
            is TextNode -> out.append(if (pre) node.wholeText else node.text())
            is Element -> {
                val tag = node.normalName()
                when {
                    tag == "br" -> out.append('\n')
                    tag == "pre" -> { out.append("\n```\n"); node.childNodes().forEach { render(it, out, true) }; out.append("\n```\n") }
                    tag.length == 2 && tag[0] == 'h' && tag[1] in '1'..'6' -> {
                        val level = minOf(tag[1] - '0', 3)
                        out.append("\n\n").append("#".repeat(level)).append(' ').append(node.text().trim()).append("\n\n")
                    }
                    tag == "li" -> { out.append("\n- "); node.childNodes().forEach { render(it, out, pre) } }
                    tag == "tr" -> {
                        val cells = node.children().filter { it.normalName() == "td" || it.normalName() == "th" }.map { it.text().trim() }
                        if (cells.any { it.isNotEmpty() }) out.append("\n| ").append(cells.joinToString(" | ")).append(" |")
                    }
                    tag == "img" -> node.attr("alt").trim().takeIf { it.length in 2..80 }?.let { out.append("［图：").append(it).append("］") }
                    tag in BLOCK -> { out.append('\n'); node.childNodes().forEach { render(it, out, pre) }; out.append('\n') }
                    else -> node.childNodes().forEach { render(it, out, pre) }
                }
            }
        }
    }

    /** 行内空白压成一个，空行最多留一个 */
    fun tidy(s: String): String {
        val out = StringBuilder()
        var blank = 0
        var inCode = false
        for (raw in s.lines()) {
            val fence = raw.trim() == "```"
            // 代码块里原样保留（缩进有意义），只去掉行尾空白
            val l = if (inCode && !fence) raw.trimEnd() else raw.replace(SPACES, " ").trim()
            if (fence) inCode = !inCode
            if (l.isEmpty() && !inCode) { blank++; continue }
            if (out.isNotEmpty()) out.append(if (blank > 0) "\n\n" else "\n")
            blank = 0
            out.append(l)
        }
        return out.toString()
    }

    private val SPACES = Regex("[ \\t\\u00a0\\u3000]+")

    private fun links(root: Element): List<Pair<String, String>> {
        val seen = mutableSetOf<String>()
        return root.select("a[href]").mapNotNull { a ->
            val href = a.absUrl("href").substringBefore('#')
            val text = a.text().trim()
            if (!href.startsWith("http") || text.length !in 2..80 || !seen.add(href)) null else text to href
        }.take(40)
    }
}
