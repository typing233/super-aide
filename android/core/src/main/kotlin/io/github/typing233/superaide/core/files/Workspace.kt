package io.github.typing233.superaide.core.files

import java.io.File

/**
 * 一段对话的工作区（files/work/<对话 id>/）：用户给的文件在 inbox/，网上下载的在 web/，助手生成的在根目录。
 * 工具只能读写这里面，路径一律相对工作区，跳不出去。
 */
class Workspace(val root: File) {
    data class Entry(val path: String, val bytes: Long, val modified: Long) {
        val name get() = path.substringAfterLast('/')
        val origin get() = when {
            path.startsWith("$INBOX/") -> "用户给的"
            path.startsWith("$WEB/") -> "网上下载的"
            else -> "生成的"
        }
    }

    class Outside(path: String) : IllegalArgumentException("路径「$path」不在工作区里：只能用 files 列出来的相对路径")

    /** 相对路径 → 文件；跳出工作区（../、绝对路径）就报错 */
    fun resolve(path: String): File {
        val clean = path.trim().replace('\\', '/').removePrefix("./")
        if (clean.isEmpty() || clean.startsWith("/") || Regex("^[A-Za-z]:").containsMatchIn(clean)) throw Outside(path)
        val base = root.canonicalFile
        val f = File(base, clean).canonicalFile
        if (f == base || !f.path.startsWith(base.path + File.separator)) throw Outside(path)
        return f
    }

    fun relative(f: File): String = f.canonicalFile.relativeTo(root.canonicalFile).invariantSeparatorsPath

    fun list(): List<Entry> {
        if (!root.exists()) return emptyList()
        return root.walkTopDown().filter { it.isFile && !it.name.startsWith(".") }
            .map { Entry(relative(it), it.length(), it.lastModified()) }
            .sortedWith(compareBy({ order(it.path) }, { it.path }))
            .toList()
    }

    private fun order(p: String) = when {
        p.startsWith("$INBOX/") -> 0
        p.startsWith("$WEB/") -> 2
        else -> 1
    }

    /** dir 下不重名的文件：同名的加 (2)、(3)… */
    fun unique(dir: String, name: String): File {
        val safe = safeName(name)
        val d = if (dir.isEmpty()) root else File(root, dir)
        d.mkdirs()
        val stem = safe.substringBeforeLast('.', safe)
        val ext = safe.substringAfterLast('.', "").let { if (it.isEmpty() || it == safe) "" else ".$it" }
        var f = File(d, safe)
        var i = 2
        while (f.exists()) f = File(d, "$stem ($i)$ext").also { i++ }
        return f
    }

    companion object {
        const val INBOX = "inbox"
        const val WEB = "web"

        /** 文件名里不能有的字符换掉；太长的截短（保留扩展名） */
        fun safeName(name: String): String {
            val n = name.replace(Regex("[\\\\/:*?\"<>|\\x00-\\x1f]"), "_").trim().trimStart('.').ifBlank { "file" }
            if (n.length <= 80) return n
            val ext = n.substringAfterLast('.', "").take(10)
            return n.take(80 - ext.length - 1) + if (ext.isEmpty()) "" else ".$ext"
        }

        fun ext(name: String) = name.substringAfterLast('.', "").lowercase()

        private val MIME = mapOf(
            "pdf" to "application/pdf",
            "docx" to "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx" to "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pptx" to "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "doc" to "application/msword", "xls" to "application/vnd.ms-excel", "ppt" to "application/vnd.ms-powerpoint",
            "txt" to "text/plain", "md" to "text/markdown", "csv" to "text/csv", "tsv" to "text/tab-separated-values",
            "html" to "text/html", "htm" to "text/html", "json" to "application/json", "xml" to "text/xml",
            "js" to "text/javascript", "svg" to "image/svg+xml",
            "png" to "image/png", "jpg" to "image/jpeg", "jpeg" to "image/jpeg", "webp" to "image/webp", "gif" to "image/gif",
            "bmp" to "image/bmp", "heic" to "image/heic",
            "zip" to "application/zip", "epub" to "application/epub+zip",
        )

        fun mime(name: String) = MIME[ext(name)] ?: "application/octet-stream"

        /** 按扩展名猜的 MIME → 扩展名（从别的 App 分享来的文件可能没有扩展名） */
        fun extFor(mime: String): String? = MIME.entries.firstOrNull { it.value == mime.lowercase() }?.key

        private val TEXT = setOf(
            "txt", "md", "markdown", "csv", "tsv", "json", "xml", "html", "htm", "js", "ts", "kt", "java", "py", "c", "cpp", "h",
            "cs", "go", "rs", "rb", "php", "sh", "bat", "ps1", "sql", "yaml", "yml", "toml", "ini", "cfg", "conf", "log", "srt",
            "vtt", "css", "svg", "tex", "rtf", "properties", "gradle", "kts", "swift", "lua", "r", "m", "vue", "jsx", "tsx",
        )
        private val IMAGE = setOf("png", "jpg", "jpeg", "webp", "gif", "bmp", "heic", "heif")

        fun isText(name: String) = ext(name) in TEXT
        fun isImage(name: String) = ext(name) in IMAGE

        /** 文件大小给人看 */
        fun size(bytes: Long): String = when {
            bytes < 1024 -> "$bytes B"
            bytes < 1024 * 1024 -> "${(bytes + 512) / 1024} KB"
            else -> String.format(java.util.Locale.ROOT, "%.1f MB", bytes / 1024.0 / 1024.0)
        }
    }
}
