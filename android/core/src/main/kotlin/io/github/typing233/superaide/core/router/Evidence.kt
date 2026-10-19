package io.github.typing233.superaide.core.router

import io.github.typing233.superaide.core.llm.Effort
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow

/**
 * 路由的学习记录（对应桌面版 router/evidence.py）：每个结果一条（files/router/outcomes.jsonl），
 * 决策时按"和这次任务有多相关"加权，得到每个配置的成功、失败次数。规则照搬桌面版：
 * - 相关度：同一类任务 1；同类型不同子类 0.5；别的类型 0.15，而且各组旁证有上限。
 * - 单调共享：同一模型低档办成了，高档也算办成（打折）；高档办不成，低档也算办不成；反方向不传。
 *   同一服务里弱的模型办成了算强的也能办成，强的办不成算弱的也办不成。
 * - 旧记录慢慢淡化（半衰期 90 天）。
 * 手机上还没有向量模型，桌面版"意思很像的旧任务"那一组先不算。
 */
@Serializable
data class Outcome(
    val t: Double,
    val mode: String,
    val kind: String,
    val domain: String,
    /** 服务 id（桌面版是引擎名） */
    val engine: String,
    val model: String,
    val effort: String,
    /** 1 办成 / 0 没办成（后台对比可以是 0.5） */
    val y: Double,
    /** 这个信号的可信度 */
    val w: Double,
    val source: String,
)

/** 汇总后的一格的键 */
data class Cell(val engine: String, val model: String, val eidx: Int, val ok: Boolean, val group: String)

class Evidence(private val file: File?, private val keep: Int = KEEP) {
    val items = mutableListOf<Outcome>()

    init {
        if (file != null && file.exists()) {
            for (line in file.readLines(Charsets.UTF_8)) {
                if (line.isBlank()) continue
                runCatching { items += json.decodeFromString(Outcome.serializer(), line) }
            }
        }
        if (items.size > keep) items.subList(0, items.size - keep).clear()
    }

    @Synchronized
    fun add(o: Outcome) {
        items += o
        runCatching {
            file?.parentFile?.mkdirs()
            file?.appendText(json.encodeToString(Outcome.serializer(), o) + "\n", Charsets.UTF_8)
        }
        if (items.size > keep * 1.2) {
            items.subList(0, items.size - keep).clear()
            runCatching {
                val f = file ?: return@runCatching
                val tmp = File(f.parentFile, f.name + ".tmp")
                tmp.writeText(items.joinToString("") { json.encodeToString(Outcome.serializer(), it) + "\n" }, Charsets.UTF_8)
                tmp.renameTo(f)
            }
        }
    }

    /** 这次任务用得上的结果，按 (服务, 模型, 强度档, 办成没有, 分组) 汇总：权重 = 相关度 × 可信度 × 新旧 */
    @Synchronized
    fun gather(mode: String, kind: String, domain: String, now: Double): Map<Cell, DoubleArray> {
        val buckets = linkedMapOf<Cell, DoubleArray>()
        for (o in items) {
            if (o.mode != mode) continue
            val (rel, group) = when {
                o.kind == kind && o.domain == domain -> 1.0 to "cell"
                o.kind == kind -> SAME_KIND to "kind"
                else -> OTHER_KIND to "mode"
            }
            val weight = rel * o.w * 0.5.pow(max(0.0, now - o.t) / 86400 / HALF_LIFE_DAYS)
            if (weight > 1e-4) {
                val cell = buckets.getOrPut(Cell(o.engine, o.model, effortIndex(o.effort), o.y >= 0.5, group)) { DoubleArray(2) }
                cell[0] += weight * o.y
                cell[1] += weight * (1.0 - o.y)
            }
        }
        return buckets
    }

    companion object {
        const val HALF_LIFE_DAYS = 90.0
        const val KEEP = 5000
        const val SAME_KIND = 0.5
        const val OTHER_KIND = 0.15
        /** 每一组旁证最多抵几次真实结果（同一类任务本身不封顶） */
        val CAPS = mapOf("cell" to null, "kind" to 6.0, "near" to 5.0, "mode" to 2.0)
        const val EFFORT_SHARE = 0.75
        const val TIER_SHARE = 0.5
        const val SIBLING_SHARE = 0.3

        val json = Json { ignoreUnknownKeys = true }

        fun effortIndex(effort: String): Int =
            Effort.entries.indexOfFirst { it.wire == effort }.let { if (it < 0) Effort.HIGH.ordinal else it }

        /** 一个结果（o…）对"engine·model·第 eidx 档"这个配置算几分（0～1）。只在同一个服务里传，只按单调的方向传 */
        fun transfer(oEngine: String, oModel: String, oEidx: Int, ok: Boolean, oTier: Int,
                     engine: String, model: String, tier: Int, eidx: Int): Double {
            if (oEngine != engine) return 0.0
            if (oModel == model) {
                if (oEidx == eidx) return 1.0
                return if ((ok && oEidx < eidx) || (!ok && oEidx > eidx)) EFFORT_SHARE else 0.0
            }
            if (oTier == tier) return if ((ok && oEidx <= eidx) || (!ok && oEidx >= eidx)) SIBLING_SHARE else 0.0
            if (ok && oTier > tier && oEidx <= eidx) return TIER_SHARE // 更弱的模型办成了
            if (!ok && oTier < tier && oEidx >= eidx) return TIER_SHARE // 更强的模型都没办成
            return 0.0
        }

        /** → (加权成功数, 加权失败数)。每组旁证超过上限时按比例缩小 */
        fun counts(buckets: Map<Cell, DoubleArray>, engine: String, model: String, tier: Int, eidx: Int,
                   tierOf: (String, String) -> Int): Pair<Double, Double> {
            val groups = linkedMapOf<String, DoubleArray>()
            for ((c, w) in buckets) {
                if (c.engine != engine) continue
                val k = transfer(c.engine, c.model, c.eidx, c.ok, tierOf(c.engine, c.model), engine, model, tier, eidx)
                if (k <= 0) continue
                val g = groups.getOrPut(c.group) { DoubleArray(2) }
                g[0] += w[0] * k
                g[1] += w[1] * k
            }
            var s = 0.0
            var f = 0.0
            for ((group, g) in groups) {
                val cap = CAPS[group]
                val n = g[0] + g[1]
                val scale = if (cap != null && n > 0) min(1.0, cap / n) else 1.0
                s += g[0] * scale
                f += g[1] * scale
            }
            return s to f
        }
    }
}
