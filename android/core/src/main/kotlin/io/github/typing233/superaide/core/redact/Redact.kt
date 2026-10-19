package io.github.typing233.superaide.core.redact

/** 发给模型之前给文本打码：密钥、令牌、密码一类的值。照搬桌面版 snapshot/redact.py。 */
object Redact {
    const val MASK = "[已打码]"

    private val tokenPatterns = listOf(
        Regex("""\bsk-ant-[A-Za-z0-9_\-]{20,}"""),
        Regex("""\bsk-[A-Za-z0-9_\-]{20,}"""),
        Regex("""\bgh[pousr]_[A-Za-z0-9]{30,}"""),
        Regex("""\bgithub_pat_[A-Za-z0-9_]{30,}"""),
        Regex("""\bAKIA[0-9A-Z]{16}\b"""),
        Regex("""\bxox[abprs]-[A-Za-z0-9\-]{10,}"""),
        Regex("""\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"""),
        Regex("""-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"""),
    )

    // "password: xxx"、"api_key=xxx" 这类键值对只遮住值
    private val keyValue = Regex(
        """(?i)\b(password|passwd|pwd|secret|token|api[_\-]?key|access[_\-]?key|auth[_\-]?token)""" +
            """(\s*[:=]\s*)(["']?)([^\s"']{4,})\3"""
    )

    fun apply(text: String): String {
        if (text.isEmpty()) return text
        var out = text
        for (p in tokenPatterns) out = p.replace(out, MASK)
        return keyValue.replace(out) { m ->
            val (key, sep, quote) = m.destructured
            "$key$sep$quote$MASK$quote"
        }
    }
}
