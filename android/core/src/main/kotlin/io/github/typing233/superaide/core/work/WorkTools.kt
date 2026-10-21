package io.github.typing233.superaide.core.work

import io.github.typing233.superaide.core.files.Make
import io.github.typing233.superaide.core.files.Office
import io.github.typing233.superaide.core.files.Workspace
import io.github.typing233.superaide.core.llm.Part
import io.github.typing233.superaide.core.llm.ToolCall
import io.github.typing233.superaide.core.llm.ToolOutput
import io.github.typing233.superaide.core.web.Readable
import io.github.typing233.superaide.core.web.Search
import io.github.typing233.superaide.core.web.Web
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive
import java.io.File

/** 只有手机上才有的能力（浏览器、PDF、认字、JS 沙箱），App 实现；电脑上测试时可以不给 */
interface Platform {
    class Rendered(val url: String, val html: String)
    class Pdf(val pages: Int, val text: String)
    class Js(val output: String, val error: String?)

    /** 用内置浏览器（能跑 JS、带 Cookie）打开网页，返回渲染完的 HTML */
    suspend fun render(url: String): Rendered? = null
    suspend fun pdf(file: File): Pdf? = null
    /** 图片缩到适合发给模型的大小（JPEG）；认不出的格式返回 null */
    suspend fun image(bytes: ByteArray): ByteArray? = null
    suspend fun ocr(image: ByteArray): String? = null
    suspend fun writePdf(markdown: String, file: File) { throw UnsupportedOperationException("这台设备不支持生成 PDF") }
    suspend fun runJs(code: String, timeoutMs: Long, files: JsFiles): Js = Js("", "这台设备不支持运行代码")
}

/** JS 沙箱里的 files.read / files.write */
interface JsFiles {
    suspend fun read(path: String): String
    suspend fun write(path: String, text: String): String
}

/**
 * Claude Code / Codex 那样的通用工具：联网搜索、读网页、读写这段对话的工作区、跑 JS。
 * 和模型服务无关（DeepSeek、中转站都能用）。生成或改了文件就通过 [onFile] 告诉界面。
 */
class WorkTools(
    val workspace: Workspace,
    private val platform: Platform = object : Platform {},
    private val web: Web = Web(),
    private val onFile: (Workspace.Entry) -> Unit = {},
    /** 诊断日志（App 接到 Diag；只记网址的域名、数量这类，不记内容） */
    private val log: (String, String) -> Unit = { _, _ -> },
) {
    /** 读过的网页和文件的全文（分页接着读时不用重新下载、重新解析） */
    private val pages = object : LinkedHashMap<String, Doc>(16, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Doc>?) = size > 8
    }

    private class Doc(val header: String, val text: String, val tail: String = "")

    suspend fun run(call: ToolCall): ToolOutput? {
        val a = call.input ?: JsonObject(emptyMap())
        val parts: List<Part> = when (call.name) {
            "web_search" -> listOf(Part.Text(search(a.str("query").orEmpty(), (a.int("max_results") ?: 8).coerceIn(1, 20))))
            "web_fetch" -> fetch(a.str("url").orEmpty(), a.int("start") ?: 0, a.int("max_chars") ?: PAGE)
            "files" -> listOf(Part.Text(listFiles()))
            "read_file" -> readFile(a.str("path").orEmpty(), a.int("start") ?: 0, a.int("max_chars") ?: PAGE)
            "write_file" -> listOf(Part.Text(write(a.str("path").orEmpty(), a.str("content").orEmpty(), a.bool("append") == true)))
            "run_js" -> listOf(Part.Text(runJs(a.str("code").orEmpty(), (a.int("timeout_seconds") ?: 30).coerceIn(1, 120))))
            else -> return null
        }
        return ToolOutput(call.id, parts)
    }

    // ---------------- 搜索 ----------------

    suspend fun search(query: String, max: Int): String {
        if (query.isBlank()) return "query 不能为空。"
        suspend fun all(engines: List<Search.Engine>, browser: Boolean) = coroutineScope {
            engines.map { e -> async { e to runCatching { searchOne(e, query, browser) }.getOrElse { emptyList() } } }.map { it.await() }
        }
        val primary = Search.Engine.entries.filterNot { it.backup }
        // 先直接请求（快）；结果够了就不再用浏览器（一次要好几秒）
        var results = all(primary, browser = false)
        if (results.sumOf { it.second.size } < ENOUGH) {
            val retried = all(results.filter { it.second.isEmpty() }.map { it.first }, browser = true).toMap()
            results = results.map { (e, hits) -> e to (retried[e] ?: hits) }
        }
        // 都被拦了、或者几乎没结果：再问后备的
        if (results.sumOf { it.second.size } < ENOUGH) results = results + all(Search.Engine.entries.filter { it.backup }, browser = true)
        val used = results.filter { it.second.isNotEmpty() }.map { it.first.label }
        return Search.render(query, Search.merge(results.map { it.second }, max), used.ifEmpty { results.map { it.first.label } })
    }

    /** browser = 直接请求没结果时用内置浏览器再开一次 */
    private suspend fun searchOne(e: Search.Engine, query: String, browser: Boolean): List<Search.Hit> {
        val url = e.url(query)
        if (browser) return platform.render(url)?.takeUnless { Search.blocked(it.html) }?.let { e.parse(it.html, it.url) }.orEmpty()
        val r = runCatching { web.get(url, 4L * 1024 * 1024) }.onFailure { log("search.${e.name}", "error=${it.message}") }.getOrNull()
        if (r != null && r.ok) {
            val html = String(r.bytes, runCatching { charset(r.charset ?: "UTF-8") }.getOrDefault(Charsets.UTF_8))
            val blocked = Search.blocked(html)
            val hits = if (blocked) emptyList() else e.parse(html, r.url)
            log("search.${e.name}", "status=${r.status} bytes=${r.bytes.size} blocked=$blocked hits=${hits.size}")
            return hits
        }
        return emptyList()
    }

    // ---------------- 读网页 ----------------

    suspend fun fetch(rawUrl: String, start: Int, max: Int): List<Part> {
        val url = Web.normalize(rawUrl) ?: return listOf(Part.Text("网址不对：$rawUrl（只能读 http / https 网址）"))
        pages[url]?.let { return listOf(Part.Text(page(it, start, max))) }
        val r = try {
            web.get(url)
        } catch (e: Web.TooBig) {
            return listOf(Part.Text("$url 的内容太大，没下载（超过 ${Web.MAX_BYTES / 1024 / 1024} MB）。"))
        } catch (e: java.net.UnknownHostException) {
            return listOf(Part.Text("打不开 $url：${e.message}（网址对吗？有的网站在国内要代理）"))
        } catch (e: java.io.IOException) {
            // 连不上、超时：有的网站只认浏览器
            val rendered = platform.render(url) ?: return listOf(Part.Text("打不开 $url：${e.message ?: e}（有的网站在国内要代理）"))
            return listOf(Part.Text(page(html(rendered.url, rendered.html, rendered = true).also { pages[url] = it }, start, max)))
        }
        if (r.isPdf || (!r.isHtml && !r.isText && !r.isImage && r.ok)) {
            if (!r.ok) return listOf(Part.Text("打不开 $url：HTTP ${r.status}"))
            val name = r.fileName.ifBlank { "download" }.let { if (r.isPdf && !it.endsWith(".pdf", true)) "$it.pdf" else it }
            val f = workspace.unique(Workspace.WEB, name)
            f.writeBytes(r.bytes)
            val rel = workspace.relative(f)
            onFile(Workspace.Entry(rel, f.length(), f.lastModified()))
            val doc = extract(f) ?: return listOf(Part.Text("下载了 $url，存为 $rel（${Workspace.size(f.length())}），但读不出里面的文字。"))
            val d = Doc("网址：${r.url}\n已存为工作区的 $rel（${doc.header}）", doc.text)
            pages[url] = d
            return listOf(Part.Text(page(d, start, max)))
        }
        if (r.isImage) {
            val img = platform.image(r.bytes)
            return listOfNotNull(Part.Text("网址：${r.url}\n这是一张图片（${Workspace.size(r.bytes.size.toLong())}）。"), img?.let { Part.Image(it) })
        }
        if (r.isText && !r.isHtml) {
            val d = Doc("网址：${r.url}（${r.type}）", Office.decode(r.bytes))
            pages[url] = d
            return listOf(Part.Text(page(d, start, max)))
        }
        val raw = Readable.parse(r.bytes, r.charset, r.url).outerHtml()
        var d = html(r.url, raw, rendered = false)
        val direct = d.text.length
        // 拿到的是空壳（靠 JS 渲染）、被拦了（403、验证页）：用内置浏览器再开一次
        val retry = !r.ok || Search.blocked(raw) || Readable.looksEmpty(d.text)
        if (retry) {
            val rendered = platform.render(url)
            if (rendered != null) {
                val again = html(rendered.url, rendered.html, rendered = true)
                if (again.text.length > d.text.length) d = again
            }
        }
        log("fetch", "host=${r.url.substringAfter("://").substringBefore('/')} status=${r.status} direct=$direct browser=$retry text=${d.text.length}")
        if (!r.ok && d.text.length < 200) return listOf(Part.Text("打不开 $url：HTTP ${r.status}\n${d.text.take(500)}"))
        pages[url] = d
        return listOf(Part.Text(page(d, start, max)))
    }

    private fun html(url: String, html: String, rendered: Boolean): Doc {
        val p = Readable.extract(html, url)
        val links = if (p.links.isEmpty()) "" else "\n\n正文里的链接：\n" + p.links.joinToString("\n") { (t, u) -> "- $t → $u" }
        return Doc("网页：${p.title.ifBlank { "（无标题）" }}\n网址：$url" + if (rendered) "（用内置浏览器打开）" else "", p.text, links)
    }

    /** 一页：头 + 这一段正文 + 还有多少 + 链接（只在最后一页给） */
    private fun page(d: Doc, start: Int, max: Int): String {
        val total = d.text.length
        val s = start.coerceIn(0, maxOf(0, total))
        val e = minOf(total, s + max.coerceIn(500, 40_000))
        val more = if (e < total) "\n\n（第 ${s + 1}–$e 字，共 $total 字。接着读：start=$e）" else if (s > 0) "\n\n（第 ${s + 1}–$e 字，共 $total 字，读完了）" else ""
        val body = d.text.substring(s, e).ifBlank { "（没有正文）" }
        return "${d.header}\n\n$body$more" + if (e >= total) d.tail else ""
    }

    // ---------------- 文件 ----------------

    fun listFiles(): String {
        val all = workspace.list()
        if (all.isEmpty()) return "工作区是空的：用户没给文件，你也还没生成文件。"
        return "工作区里的文件：\n" + all.joinToString("\n") { "- ${it.path}（${Workspace.size(it.bytes)}，${it.origin}）" }
    }

    suspend fun readFile(path: String, start: Int, max: Int): List<Part> {
        val f = try { workspace.resolve(path) } catch (e: Workspace.Outside) { return listOf(Part.Text(e.message!!)) }
        if (!f.isFile) return listOf(Part.Text("没有这个文件：$path。用 files 看有哪些。"))
        val rel = workspace.relative(f)
        val key = "file:$rel:${f.lastModified()}:${f.length()}"
        pages[key]?.let { return listOf(Part.Text(page(it, start, max))) }
        if (Workspace.isImage(f.name)) {
            val bytes = f.readBytes()
            val img = platform.image(bytes)
            val text = platform.ocr(img ?: bytes)?.takeIf { it.isNotBlank() }
            return listOfNotNull(
                Part.Text("图片：$rel（${Workspace.size(f.length())}）" + (text?.let { "\n图里认出的字（可能有个别错字）：\n$it" } ?: "")),
                img?.let { Part.Image(it) },
            ).ifEmpty { listOf(Part.Text("读不了这张图片：$rel")) }
        }
        val doc = extract(f) ?: return listOf(Part.Text(unreadable(f.name, rel)))
        val d = Doc("文件：$rel（${doc.header}）", doc.text)
        pages[key] = d
        return listOf(Part.Text(page(d, start, max)))
    }

    private class Extracted(val header: String, val text: String)

    private suspend fun extract(f: File): Extracted? {
        val size = Workspace.size(f.length())
        val ext = Workspace.ext(f.name)
        if (f.length() > MAX_FILE) return Extracted("$size", "文件太大（超过 ${MAX_FILE / 1024 / 1024} MB），没有读。")
        if (ext == "pdf" || (ext.isEmpty() && magic(f) == "%PDF")) {
            val p = platform.pdf(f) ?: return null
            return Extracted("PDF，${p.pages} 页，$size", p.text)
        }
        val text = runCatching { Office.extract(f.name, f.readBytes()) }.getOrNull() ?: return null
        val kind = when (ext) {
            "docx", "docm", "dotx" -> "Word"
            "xlsx", "xlsm" -> "Excel"
            "pptx", "pptm", "ppsx" -> "PowerPoint"
            else -> ext.ifEmpty { "文本" }
        }
        return Extracted("$kind，$size", text.take(Office.MAX_CHARS))
    }

    private fun magic(f: File): String = f.inputStream().use { i -> ByteArray(4).let { b -> String(b, 0, maxOf(0, i.read(b))) } }

    private fun unreadable(name: String, rel: String) = when (Workspace.ext(name)) {
        "doc", "xls", "ppt" -> "$rel 是老版 Office 格式，读不了：请用户用 WPS 或 Office 另存为 docx / xlsx / pptx 再发过来。"
        "zip", "rar", "7z" -> "$rel 是压缩包，读不了：请用户解压后把里面的文件发过来。"
        else -> "$rel 的格式读不了（${Workspace.ext(name).ifEmpty { "没有扩展名" }}）。"
    }

    suspend fun write(path: String, content: String, append: Boolean): String {
        val f = try { workspace.resolve(path) } catch (e: Workspace.Outside) { return e.message!! }
        if (workspace.relative(f).startsWith("${Workspace.INBOX}/")) return "inbox/ 里是用户给的原件，不能改：换个文件名写到工作区根目录。"
        f.parentFile?.mkdirs()
        val ext = Workspace.ext(f.name)
        val existed = f.exists()
        try {
            when (ext) {
                "docx" -> f.writeBytes(Make.docx(content))
                "xlsx" -> f.writeBytes(Make.xlsx(content))
                "pdf" -> platform.writePdf(content, f)
                else -> if (append && existed) f.appendText(content) else f.writeText(content)
            }
        } catch (e: UnsupportedOperationException) {
            return e.message ?: "这台设备不支持生成 $ext"
        }
        val rel = workspace.relative(f)
        onFile(Workspace.Entry(rel, f.length(), f.lastModified()))
        val note = if (append && ext in setOf("docx", "xlsx", "pdf")) "（$ext 不能追加，已整个重写）" else ""
        return "已${if (existed) "更新" else "生成"} $rel（${Workspace.size(f.length())}）$note。用户在回答下面能看到它，点一下就能打开、分享或存到手机。"
    }

    // ---------------- 跑代码 ----------------

    suspend fun runJs(code: String, seconds: Int): String {
        if (code.isBlank()) return "code 不能为空。"
        val bridge = object : JsFiles {
            override suspend fun read(path: String): String {
                val f = workspace.resolve(path)
                if (!f.isFile) throw IllegalArgumentException("没有这个文件：$path")
                return extract(f)?.text ?: throw IllegalArgumentException(unreadable(f.name, workspace.relative(f)))
            }

            override suspend fun write(path: String, text: String): String = this@WorkTools.write(path, text, append = false)
        }
        val r = platform.runJs(code, seconds * 1000L, bridge)
        val out = r.output.let { if (it.length > 20_000) it.take(20_000) + "\n…（输出太长，后面截掉了）" else it }
        return buildString {
            if (out.isNotBlank()) append(out.trimEnd()) else if (r.error == null) append("（没有输出：用 console.log 打印，或者 return 一个值）")
            if (r.error != null) { if (isNotEmpty()) append("\n\n"); append("出错：").append(r.error) }
        }
    }

    companion object {
        const val PAGE = 10_000
        /** 搜到这么多条就够了，不再用浏览器补 */
        private const val ENOUGH = 5
        const val MAX_FILE = 60L * 1024 * 1024
        private fun JsonObject.str(k: String) = this[k]?.jsonPrimitive?.contentOrNull
        private fun JsonObject.int(k: String) = this[k]?.jsonPrimitive?.let { it.intOrNull ?: it.contentOrNull?.toDoubleOrNull()?.toInt() }
        private fun JsonObject.bool(k: String) = this[k]?.jsonPrimitive?.booleanOrNull
    }
}
