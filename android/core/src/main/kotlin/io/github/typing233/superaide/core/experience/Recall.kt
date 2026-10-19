package io.github.typing233.superaide.core.experience

import kotlin.math.ceil
import kotlin.math.ln

/** 这次的情况：问题 + 屏幕上的报错行 + 前台 App（包名）、网址、窗口标题。 */
data class Situation(
    val question: String = "",
    val text: String = "",
    val errors: String = "",
    val app: String = "",
    val url: String = "",
    val title: String = "",
) {
    /** 问题本身（不含网址、标题这些环境） */
    fun problem() = listOf(question, text, errors).filter { it.isNotEmpty() }.joinToString("\n")
    fun query() = listOf(problem(), title, url).filter { it.isNotEmpty() }.joinToString("\n")
    fun domain(): String {
        if (url.isEmpty()) return ""
        val host = runCatching { java.net.URI(if ("://" in url) url else "http://$url").host }.getOrNull().orEmpty()
        return host.lowercase().removePrefix("www.")
    }
}

/**
 * 想起经验（对应桌面版 experience/recall.py）：只在碰到相似情况时想起，平时一条也不带。
 * 报错特征对上一个就放行；提示词对上两个放行；App/网站只能把"对上一个提示词"补成放行。
 * 放行的按"线索分 + BM25"排序，最多 [MAX_RECALL] 条。中文按相邻两字切，英文按词切、驼峰再拆。
 */
object Recall {
    const val MAX_RECALL = 2
    private val CJK_RUN = Regex("[㐀-䶿一-鿿豈-﫿]+")
    private val LATIN = Regex("[A-Za-z0-9][A-Za-z0-9_.\\-]*")
    private val CAMEL = Regex("[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
    /**
     * Python 的 [\W_]（认 Unicode）：除了字母和数字都算。不用 \W：Java 的 \W 不认中文（会把中文删掉），
     * 而安卓的 ICU 不支持 (?U)。直接写 Unicode 属性，两边都对。
     */
    private val NON_WORD = Regex("[^\\p{L}\\p{N}]+")
    private val SEPARATORS = Regex("[._\\-]+")
    val ERROR_LINE = Regex(
        "error|exception|traceback|fail|fatal|denied|not found|cannot|can't|unable|invalid|refused" +
            "|timed? ?out|错误|失败|异常|报错|找不到|无法|拒绝|未定义|不存在|超时|出错|未找到|0x[0-9a-f]{8}",
        RegexOption.IGNORE_CASE,
    )
    private val STOP = setOf(
        "the", "and", "for", "you", "are", "this", "that", "with", "what", "why", "how", "can", "not", "but", "was",
        "什么", "怎么", "为什", "为何", "一下", "这个", "那个", "可以", "如何", "是不", "不是", "我的", "你的", "现在",
        "还是", "但是", "然后", "就是", "没有", "一个", "这是", "帮我", "请问", "我们", "他们", "这样", "那样", "时候",
    )
    /** 太宽泛的提示词，对上了也不算 */
    private val GENERIC = setOf(
        "报错", "错误", "问题", "失败", "异常", "安装", "软件", "电脑", "程序", "运行", "打不开", "怎么办", "不行",
        "error", "errors", "exception", "failed", "failure", "problem", "issue", "install", "windows", "run",
    )

    /** 中英文混排切成检索用的词 */
    fun tokens(text: String): List<String> {
        val out = mutableListOf<String>()
        for (m in LATIN.findAll(text)) {
            val word = m.value.trim('.', '_', '-')
            val low = word.lowercase()
            if (low.length >= 2 && low !in STOP) out += low
            val parts = CAMEL.findAll(word).map { it.value.lowercase() }.toMutableList()
            if (SEPARATORS.containsMatchIn(word)) parts += word.split(SEPARATORS).map { it.lowercase() }
            out += LinkedHashSet(parts).filter { it.length >= 3 && it != low && it !in STOP }
        }
        for (m in CJK_RUN.findAll(text)) {
            val run = m.value
            val grams = if (run.length == 1) listOf(run) else (0 until run.length - 1).map { run.substring(it, it + 2) }
            out += grams.filter { it !in STOP }
        }
        return out
    }

    fun compact(text: String) = NON_WORD.replace(text.lowercase(), "")

    /** 一大段文字里像报错的行 */
    fun errorLines(text: String): String {
        val picked = text.lineSequence().filter { ERROR_LINE.containsMatchIn(it) }.map { it.trim().take(200) }.toCollection(LinkedHashSet())
        return picked.joinToString("\n").take(6000)
    }

    private class Query(s: Situation) {
        val tokens = tokens(s.problem()).toSet()
        val compact = compact(s.problem())
        val ranking = tokens(s.query()).toSet()
        val app = s.app.lowercase()
        val domain = s.domain()
    }

    private fun hit(cue: String, q: Query, minLen: Int = 2): Boolean {
        val flat = compact(cue)
        if (flat.length < minLen || cue.trim().lowercase() in GENERIC || flat in GENERIC) return false
        if (CJK_RUN.containsMatchIn(cue)) {
            if (flat.length <= 2) return flat in q.compact
            val grams = tokens(cue).filter { it !in STOP }
            val hits = grams.count { it in q.tokens || it in q.compact }
            return grams.isNotEmpty() && hits >= maxOf(2, ceil(0.6 * grams.size).toInt())
        }
        val words = LATIN.findAll(cue).map { it.value }.toList()
        if (words.size == 1) return words[0].lowercase().trim('.', '_', '-') in q.tokens
        return flat in q.compact
    }

    private fun context(l: Lesson, q: Query): Boolean {
        if (q.app.isNotEmpty() && l.apps.any { it.lowercase() == q.app }) return true
        return q.domain.isNotEmpty() && l.domains.any { d ->
            val dd = d.lowercase().removePrefix("www.")
            d.isNotEmpty() && (q.domain == dd || q.domain.endsWith(".$dd"))
        }
    }

    /** 参与 BM25 的字段（做法不参与） */
    private fun document(l: Lesson): List<String> {
        fun twice(x: List<String>) = x + x
        return twice(tokens(l.title)) + tokens(l.`when`) + twice(tokens(l.triggers.joinToString(" "))) + twice(tokens(l.errors.joinToString(" ")))
    }

    fun bm25(docs: List<List<String>>, query: Set<String>, k1: Double = 1.2, b: Double = 0.5): List<Double> {
        val n = docs.size
        val avg = if (n > 0) docs.sumOf { it.size }.toDouble() / n else 0.0
        val df = HashMap<String, Int>()
        for (doc in docs) for (t in doc.toSet()) df[t] = (df[t] ?: 0) + 1
        return docs.map { doc ->
            val tf = doc.groupingBy { it }.eachCount()
            var score = 0.0
            for (t in query) {
                val f = tf[t] ?: continue
                val d = df.getValue(t)
                val idf = ln(1 + (n - d + 0.5) / (d + 0.5))
                score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * doc.size / (if (avg == 0.0) 1.0 else avg)))
            }
            score
        }
    }

    fun recall(store: Store, s: Situation, exclude: Set<String> = emptySet(), limit: Int = MAX_RECALL): List<Lesson> {
        val lessons = store.all().filter { it.id !in exclude }
        val q = Query(s)
        if (lessons.isEmpty() || q.tokens.isEmpty()) return emptyList()
        val scores = bm25(lessons.map(::document), q.ranking)
        val scored = lessons.zip(scores).mapNotNull { (l, bm) ->
            val strong = l.errors.count { hit(it, q, minLen = 6) }
            val medium = l.triggers.count { hit(it, q) }
            val ctx = context(l, q)
            if (strong > 0 || medium >= 2 || (medium > 0 && ctx)) (3.0 * strong + 1.5 * medium + (if (ctx) 1 else 0) + bm) to l else null
        }
        return scored.sortedByDescending { it.first }.take(limit).map { it.second }
    }

    /** 交给模型的写法：每条一行，短 */
    fun render(lessons: List<Lesson>) = lessons.map { "- ${it.title}：${it.advice}（适用：${it.`when`}）" }
}
