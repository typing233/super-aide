package io.github.typing233.superaide.core.experience

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.UUID
import kotlin.math.pow

/** 一条经验（对应桌面版 experience/store.py 的 Lesson）。apps 在手机上是包名。 */
@Serializable
data class Lesson(
    val id: String,
    val title: String,
    val `when`: String,
    val advice: String,
    val triggers: List<String> = emptyList(),
    val errors: List<String> = emptyList(),
    val apps: List<String> = emptyList(),
    val domains: List<String> = emptyList(),
    val source: String = "",
    val created: Double = 0.0,
    val updated: Double = 0.0,
    val uses: Int = 0,
    val fails: Int = 0,
    val last_used: Double = 0.0,
) {
    /** 留不留的分数：成功率（新经验先给机会）× 多久没被想起 */
    fun utility(now: Double): Double {
        val success = (uses - fails + 1).toDouble() / (uses + 2)
        val idle = (now - maxOf(last_used, created)) / 86400
        return success * 0.5.pow(idle / Store.HALF_LIFE_DAYS)
    }
}

@Serializable
private data class LessonFile(val version: Int = 1, val lessons: List<Lesson> = emptyList())

/**
 * 经验库：files/experience/lessons.json。不是记事本：只有碰到相似情况时才会被想起（Recall）。
 * 有上限；用了总不管用的、很久没用到的先淘汰。
 */
class Store(private val file: File?, private val now: () -> Double = { System.currentTimeMillis() / 1000.0 }) {
    private val lessons = linkedMapOf<String, Lesson>()

    init {
        val f = file
        if (f != null && f.exists()) runCatching {
            json.decodeFromString(LessonFile.serializer(), f.readText(Charsets.UTF_8)).lessons
                .filter { it.id.isNotBlank() && it.title.isNotBlank() }
                .forEach { lessons[it.id] = it }
        }
    }

    @Synchronized fun all(): List<Lesson> = lessons.values.toList()
    @Synchronized fun get(id: String): Lesson? = lessons[id]

    @Synchronized
    fun add(title: String, `when`: String, advice: String, source: String = "", triggers: List<String> = emptyList(),
            errors: List<String> = emptyList(), apps: List<String> = emptyList(), domains: List<String> = emptyList()): Lesson {
        val t = now()
        val id = "L" + LocalDate.now().format(DateTimeFormatter.BASIC_ISO_DATE) + "-" + UUID.randomUUID().toString().replace("-", "").take(6)
        val lesson = Lesson(id, title.trim(), `when`.trim(), advice.trim(), clean(triggers), clean(errors), clean(apps), clean(domains),
            source, t, t)
        lessons[id] = lesson
        evict(t)
        save()
        return lesson
    }

    /** 合并更新：文字类字段换成新的，线索取并集，用过的次数保留 */
    @Synchronized
    fun update(id: String, title: String? = null, `when`: String? = null, advice: String? = null, source: String? = null,
               triggers: List<String>? = null, errors: List<String>? = null, apps: List<String>? = null, domains: List<String>? = null): Lesson? {
        val old = lessons[id] ?: return null
        fun text(new: String?, cur: String) = new?.trim()?.ifBlank { null } ?: cur
        fun cues(new: List<String>?, cur: List<String>) = if (new.isNullOrEmpty()) cur else clean(new + cur)
        val lesson = old.copy(
            title = text(title, old.title), `when` = text(`when`, old.`when`), advice = text(advice, old.advice),
            triggers = cues(triggers, old.triggers), errors = cues(errors, old.errors), apps = cues(apps, old.apps),
            domains = cues(domains, old.domains), source = source?.ifBlank { null } ?: old.source, updated = now(),
        )
        lessons[id] = lesson
        save()
        return lesson
    }

    /** 这些经验被交给了模型；ok 是那一轮的结果（null = 不算数，比如网络问题、中途停止） */
    @Synchronized
    fun used(ids: List<String>, ok: Boolean?) {
        if (ids.isEmpty()) return
        val t = now()
        for (id in ids) {
            var l = lessons[id] ?: continue
            l = l.copy(last_used = t)
            if (ok != null) {
                l = l.copy(uses = l.uses + 1, fails = l.fails + if (ok) 0 else 1)
                if (l.fails >= DROP_AFTER_FAILS && l.fails >= l.uses * 0.75) { lessons.remove(id); continue } // 几乎每次都没帮上忙
            }
            lessons[id] = l
        }
        save()
    }

    /** 事后发现那一轮没答好（👎、追问说不对）：已经记过一次使用，只补记失败 */
    @Synchronized
    fun failed(ids: List<String>) {
        for (id in ids) {
            val l = lessons[id] ?: continue
            if (l.fails < l.uses) lessons[id] = l.copy(fails = l.fails + 1)
        }
        save()
    }

    @Synchronized
    fun remove(id: String): Boolean = (lessons.remove(id) != null).also { if (it) save() }

    /** 删了又撤销：原样放回 */
    @Synchronized
    fun restore(lesson: Lesson) {
        lessons[lesson.id] = lesson
        save()
    }

    private fun evict(t: Double) {
        while (lessons.size > MAX_LESSONS) lessons.remove(lessons.values.minBy { it.utility(t) }.id)
    }

    private fun save() {
        val f = file ?: return
        runCatching {
            f.parentFile?.mkdirs()
            val tmp = File(f.parentFile, f.name + ".tmp")
            tmp.writeText(json.encodeToString(LessonFile.serializer(), LessonFile(1, lessons.values.toList())), Charsets.UTF_8)
            tmp.renameTo(f)
        }
    }

    companion object {
        const val MAX_LESSONS = 200
        const val HALF_LIFE_DAYS = 90.0
        const val DROP_AFTER_FAILS = 3
        private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true; prettyPrint = true }
        /** Python 的 split()：各种 Unicode 空白（安卓的 ICU 不支持 (?U)） */
        private val SPACE = Regex("[\\s\\p{Z}]+")

        fun clean(items: List<String>): List<String> {
            val out = mutableListOf<String>()
            for (item in items) {
                val text = item.trim().split(SPACE).filter { it.isNotEmpty() }.joinToString(" ").take(80)
                if (text.isNotEmpty() && out.none { it.lowercase() == text.lowercase() }) out += text
            }
            return out.take(24)
        }
    }
}
