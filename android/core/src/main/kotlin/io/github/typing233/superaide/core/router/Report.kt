package io.github.typing233.superaide.core.router

import io.github.typing233.superaide.core.i18n.tr
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import java.io.File
import java.time.DayOfWeek
import java.time.Instant
import java.time.ZoneId
import java.time.temporal.TemporalAdjusters
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * 路由表现（对应桌面版 router/report.py）：越用越省的同时，任务质量有没有变差，拿 decisions.jsonl 里的记录说话。
 * 任务 = 每次提问的那个决策；出问题 = 之后收到了明确的"没办好"信号；省下 = 所选配置的估算花费比一直用最可靠的少多少。
 */
object Report {
    const val WINDOW_DAYS = 30
    const val WEEKS = 8
    const val LEARNED_DAYS = 90
    val PROBLEM_SOURCES = setOf("status_fail", "feedback", "negative_followup", "reask")
    val TASK_VIAS = setOf("router", "rules", "pinned")
    const val MIN_TASKS = 5
    const val MIN_DOWNGRADED = 5
    const val QUALITY_GAP = 0.05

    data class TaskRow(val t: Double, val mode: String, val downgraded: Boolean, val saving: Double?, val problem: Boolean, val view: View)
    data class Period(
        val tasks: Int, val problems: Int, val problemRate: Double?, val saving: Double?, val downgraded: Int,
        val downProblemRate: Double?, val refProblemRate: Double?, val duels: Int, val duelsAsGood: Int,
    )
    data class Built(val current: Period, val previous: Period, val weeks: List<Pair<String, Period>>, val since: Double?,
                     val verdict: String, val learned: List<Map<String, Any>>)

    fun read(file: File?): List<JsonObject> {
        if (file == null || !file.exists()) return emptyList()
        return file.readLines(Charsets.UTF_8).mapNotNull { line ->
            runCatching { Json.parseToJsonElement(line).jsonObject }.getOrNull()
                ?.takeIf { it.s("type") in setOf("decision", "outcome") && it["t"] != null }
        }
    }

    fun tasksAndDuels(records: List<JsonObject>): Pair<List<TaskRow>, List<Pair<Double, Boolean>>> {
        // 任务 id → (最后用的决策, 第一次决策的时刻, 之后的结果信号)；换了配置接着做的以最后用的为准
        class Acc(var decision: JsonObject, val t: Double, val signals: MutableList<Pair<String, Double>> = mutableListOf())
        val tasks = linkedMapOf<String, Acc>()
        for (r in records) {
            if (r.s("type") != "decision" || r.s("via") !in TASK_VIAS) continue
            val key = r.s("task").ifEmpty { "old-${r.d("t")}" }
            tasks[key]?.let { it.decision = r } ?: run { tasks[key] = Acc(r, r.d("t")) }
        }
        val duels = mutableListOf<Pair<Double, Boolean>>()
        var lastDuel: JsonObject? = null
        for (o in records) {
            if (o.s("type") != "outcome") continue
            when (o.s("source")) {
                "duel" -> lastDuel = o
                "duel_ref" -> { // 后台对比：先记候选（duel），紧接着记你看到的那份（duel_ref）
                    val d = lastDuel
                    if (d != null && kotlin.math.abs(o.d("t") - d.d("t")) < 30) duels += o.d("t") to (d.d("success") >= o.d("success"))
                    lastDuel = null
                }
                else -> tasks[o.s("task")]?.signals?.add(o.s("source") to o.d("success"))
            }
        }
        val out = tasks.values.map { a ->
            val d = a.decision
            val refCost = d.d("ref_cost")
            TaskRow(
                t = a.t,
                mode = d.s("mode"),
                downgraded = d.s("ref").isNotEmpty() && d.s("ref") != "${d.s("model")} · ${d.s("effort")}",
                saving = if (refCost > 0) max(0.0, 1 - d.d("cost") / refCost) else null,
                problem = a.signals.any { (s, y) -> s in PROBLEM_SOURCES && y < 0.5 },
                view = View(d.s("mode"), d.s("kind"), d.s("domain"), d.d("band").toInt()),
            )
        }
        return out.sortedBy { it.t } to duels
    }

    fun period(tasks: List<TaskRow>, duels: List<Pair<Double, Boolean>>, start: Double, end: Double): Period {
        val ts = tasks.filter { it.t >= start && it.t < end }
        val down = ts.filter { it.downgraded }
        val rest = ts.filter { !it.downgraded }
        val savings = ts.mapNotNull { it.saving }
        val ds = duels.filter { it.first >= start && it.first < end }
        fun rate(g: List<TaskRow>) = if (g.isEmpty()) null else g.count { it.problem }.toDouble() / g.size
        return Period(ts.size, ts.count { it.problem }, rate(ts), if (savings.isEmpty()) null else savings.average(), down.size,
            rate(down), rate(rest), ds.size, ds.count { it.second })
    }

    private fun pct(x: Double?) = ((x ?: 0.0) * 100).roundToInt()

    /** 一句话结论：质量变没变差、省了多少 */
    fun verdict(cur: Period): String = when {
        cur.tasks < MIN_TASKS -> tr("数据还少（{n} 次），多用一阵才看得出趋势。", "n" to cur.tasks)
        cur.downgraded == 0 -> tr("一直用最可靠的配置：更省的配置还没证明一样能办成，所以还没换。后台对比在攒证据（{duels} 次里 {good} 次一样好）。",
            "duels" to cur.duels, "good" to cur.duelsAsGood)
        cur.downgraded < MIN_DOWNGRADED -> tr("开始在部分任务上换用更省的配置（{n} 次），质量还要再看几次。", "n" to cur.downgraded)
        (cur.downProblemRate ?: 0.0) - (cur.refProblemRate ?: 0.0) <= QUALITY_GAP ->
            tr("质量没变差：换成更省配置的任务出问题的比例 {down}%，用最可靠配置的 {ref}%；平均省了约 {saving}%。",
                "down" to pct(cur.downProblemRate), "ref" to pct(cur.refProblemRate), "saving" to pct(cur.saving))
        else -> tr("更省的配置出问题偏多（{down}% 对 {ref}%）：路由会根据这些失败自动退回更可靠的配置。",
            "down" to pct(cur.downProblemRate), "ref" to pct(cur.refProblemRate))
    }

    fun build(router: Router?, file: File?, now: Double, zone: ZoneId = ZoneId.systemDefault()): Built {
        val (tasks, duels) = tasksAndDuels(read(file))
        val window = WINDOW_DAYS * 86400.0
        val cur = period(tasks, duels, now - window, now + 1)
        val prev = period(tasks, duels, now - 2 * window, now - window)
        val monday = Instant.ofEpochMilli((now * 1000).toLong()).atZone(zone).toLocalDate().with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
        val weeks = (WEEKS - 1 downTo 0).map { i ->
            val start = monday.minusWeeks(i.toLong())
            val s = start.atStartOfDay(zone).toEpochSecond().toDouble()
            val e = start.plusWeeks(1).atStartOfDay(zone).toEpochSecond().toDouble()
            start.toString() to period(tasks, duels, s, e)
        }
        val recent = tasks.filter { it.t >= now - LEARNED_DAYS * 86400 }.map { it.view }
        // 每类任务按最常见的难度档看
        val kinds = recent.groupingBy { it }.eachCount().entries.sortedByDescending { it.value }
            .map { it.key }.distinctBy { Triple(it.mode, it.kind, it.domain) }
        val learned = router?.let { r -> runCatching { r.learned(kinds) }.getOrDefault(emptyList()) }.orEmpty()
            .map { it + ("label" to tr(it["label"] as String)) }
        return Built(cur, prev, weeks, tasks.firstOrNull()?.t, verdict(cur), learned)
    }

    private fun JsonObject.s(k: String) = (this[k] as? JsonPrimitive)?.contentOrNull.orEmpty()
    private fun JsonObject.d(k: String) = (this[k] as? JsonPrimitive)?.doubleOrNull ?: 0.0
}
