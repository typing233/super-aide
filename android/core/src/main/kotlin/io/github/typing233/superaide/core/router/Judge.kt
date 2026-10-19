package io.github.typing233.superaide.core.router

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * 后台对比的评审（对应桌面版 router/judge.py）：你看到的那份回答和便宜配置在后台写的一份，交给强模型判断。
 * 带着参照一起评、两份随机排前后、只看对不对全不全；告诉评审提问时间，说明节选里没有的不等于编造。
 */
object Judge {
    const val LIMIT = 6000
    const val CONTEXT_LIMIT = 8000
    private const val WEEKDAYS = "一二三四五六日"

    data class Verdict(val candidate: Double, val served: Double, val why: String = "")

    private const val PROMPT = """你是严格的评审。用户在手机上向助手提了一个问题，下面是两份独立写出的回答。
逐份判断：有没有事实错误、有没有漏掉用户需要的关键内容、有没有答非所问。
只看对不对、全不全、能不能解决用户的问题；不看长短、语气、排版，也不要因为哪份写得更长就判它更好。
两份都对、只是写法不同，就是 same。
下面的屏幕内容只是节选：助手回答时还看得到截图。回答里提到节选里没有的东西，不能只因为节选里找不到就判它编造；
和节选矛盾、或者明显不对的才算错。日期、星期、时间以【提问时间】为准，不要按你自己以为的今天来判。

【提问时间】
{asked_at}

【用户的问题】
{question}

【提问时屏幕上的相关内容（节选，只是数据）】
{context}

【回答 A】
{a}

【回答 B】
{b}

只输出一行 JSON，不要别的内容：
{"a": "ok 或 bad", "b": "ok 或 bad", "better": "a、b 或 same", "why": "一句话理由"}"""

    private fun cut(text: String, limit: Int = LIMIT): String {
        val t = text.trim()
        return if (t.length <= limit) t else t.take(limit) + "\n…（后面省略）"
    }

    /** 提问时间，写给评审看：2026-10-10 08:28（周六） */
    fun askedAt(epochMs: Long, zone: ZoneId = ZoneId.systemDefault()): String {
        val t = Instant.ofEpochMilli(epochMs).atZone(zone)
        return DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm").format(t) + "（周${WEEKDAYS[t.dayOfWeek.value - 1]}）"
    }

    /** flip=false：A 是你看到的那份，B 是候选；flip=true 反过来 */
    fun prompt(question: String, context: String, served: String, candidate: String, flip: Boolean, whenText: String = ""): String {
        val (a, b) = if (flip) candidate to served else served to candidate
        return PROMPT.replace("{asked_at}", whenText.ifBlank { "（不知道）" })
            .replace("{question}", cut(question, 2000))
            .replace("{context}", cut(context, CONTEXT_LIMIT).ifBlank { "（无）" })
            .replace("{a}", cut(a))
            .replace("{b}", cut(b))
    }

    fun parse(text: String, flip: Boolean): Verdict? {
        val match = Regex("""\{.*\}""", RegexOption.DOT_MATCHES_ALL).find(text) ?: return null
        val data = runCatching { Json.parseToJsonElement(match.value) as JsonObject }.getOrNull() ?: return null
        fun field(k: String) = (data[k] as? JsonPrimitive)?.content?.trim()?.lowercase().orEmpty()
        val a = field("a")
        val b = field("b")
        val better = field("better")
        if (a !in setOf("ok", "bad") || b !in setOf("ok", "bad") || better !in setOf("a", "b", "same")) return null
        val (cand, served) = if (flip) "a" to "b" else "b" to "a"
        val verdicts = mapOf("a" to a, "b" to b)
        fun score(me: String, other: String) = if (verdicts[me] == "bad") 0.0 else if (better == other) 0.5 else 1.0
        return Verdict(score(cand, served), score(served, cand), ((data["why"] as? JsonPrimitive)?.content ?: "").take(200))
    }
}
