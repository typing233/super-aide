package io.github.typing233.superaide.core.router

import io.github.typing233.superaide.core.config.Settings
import io.github.typing233.superaide.core.llm.Effort
import io.github.typing233.superaide.core.llm.Wire

/**
 * 模型档案（对应桌面版 router/catalog.py）：每个可路由的模型是哪一档、支持哪些思考强度、大概多贵多快。
 * 桌面版按引擎（claude / codex / dsh）分，手机上按模型服务分；档次、价格、先验能力的规则不变。
 */
data class Profile(
    val service: String,
    val wire: Wire,
    val id: String,
    /** 0 旗舰 / 1 主力 / 2 轻量 */
    val tier: Int,
    /** 能用的思考强度，由低到高，已按设置里的上限截断 */
    val efforts: List<Effort>,
    /** 起步能力（档次减去"旧一代"的折扣） */
    val skill: Double,
    /** 输入、输出：美元 / 百万 token */
    val price: Pair<Double, Double>,
    val order: Int = 0,
)

object Catalog {
    val TIER_NAMES = listOf("旗舰", "主力", "轻量")
    val TIER_SKILL = doubleArrayOf(0.90, 0.80, 0.66)
    val TIER_PRICE = listOf(4.0 to 20.0, 2.0 to 10.0, 1.0 to 5.0)
    val TIER_SPEED = doubleArrayOf(55.0, 85.0, 140.0)
    /** 首字前的固定开销（秒）。M0 实测：直连接口没有桌面版 CLI 的启动开销；之后按实测校准 */
    val OVERHEAD_S = mapOf(Wire.ANTHROPIC to 2.0, Wire.OPENAI_RESPONSES to 2.5, Wire.OPENAI_CHAT to 2.5)
    val EFFORT_TOKENS = mapOf(Effort.LOW to 0.35, Effort.MEDIUM to 0.6, Effort.HIGH to 1.0, Effort.XHIGH to 1.7, Effort.MAX to 3.0)
    val OUTPUT_TOKENS = mapOf("ask" to 600, "act" to 1500)
    const val INPUT_TOKENS = 8000

    private val NAME_TIERS = listOf(
        Regex("""opus|fable|mythos|(^|[-_.])astra($|[-_.])""", RegexOption.IGNORE_CASE),
        Regex("""sonnet|(^|[-_.])(sol|terra)($|[-_.])""", RegexOption.IGNORE_CASE),
        Regex("""haiku|(^|[-_.])luna($|[-_.])|mini|nano|lite|flash|small""", RegexOption.IGNORE_CASE),
    )
    private val CLAUDE = Regex("""claude-(opus|sonnet|haiku|fable|mythos)-(\d+)(?:-(\d))?(?:-\d{8})?$""")

    /** Claude 官方价（2026-09，美元 / 百万 token），按型号前缀匹配，取最长的那个 */
    val CLAUDE_PRICES = mapOf(
        "claude-fable-5" to (10.0 to 50.0), "claude-mythos" to (10.0 to 50.0),
        "claude-opus-5-5" to (4.0 to 20.0), "claude-opus-5" to (5.0 to 25.0), "claude-opus-4" to (5.0 to 25.0),
        "claude-sonnet-5" to (2.0 to 10.0), "claude-sonnet-4" to (3.0 to 15.0), "claude-haiku-4-5" to (1.0 to 5.0),
    )

    fun tierOf(id: String): Int = NAME_TIERS.indexOfFirst { it.containsMatchIn(id) }.let { if (it < 0) 1 else it }

    /** claude-opus-4-8 → ("opus", 4.8)；claude-opus-4-20250514 → ("opus", 4.0)；认不出返回 null */
    fun claudeVersion(id: String): Pair<String, Double>? {
        val m = CLAUDE.matchEntire(id) ?: return null
        val minor = m.groupValues[3].takeIf { it.isNotEmpty() }?.toInt()?.div(10.0) ?: 0.0
        return m.groupValues[1] to m.groupValues[2].toInt() + minor
    }

    /** 官方资料：4.7 起五档都有，4.6 没有 xhigh，Opus 4.5 只有前三档，更早的不支持 effort（只给一个名义上的 high） */
    fun claudeEfforts(id: String): List<Effort> {
        val (line, version) = claudeVersion(id) ?: return Effort.entries
        if (version >= 4.7 && !(line == "haiku" && version < 5)) return Effort.entries
        if (version >= 4.6 && line != "haiku") return listOf(Effort.LOW, Effort.MEDIUM, Effort.HIGH, Effort.MAX)
        if (version >= 4.5 && line == "opus") return listOf(Effort.LOW, Effort.MEDIUM, Effort.HIGH)
        return listOf(Effort.HIGH)
    }

    /** OpenAI 兼容协议实际能分出的档（OpenAiChat 把高的几档映射到同一个值，不重复成多个配置） */
    fun wireEfforts(wire: Wire): List<Effort> = when (wire) {
        Wire.OPENAI_RESPONSES -> listOf(Effort.LOW, Effort.MEDIUM, Effort.HIGH, Effort.XHIGH)
        Wire.OPENAI_CHAT -> listOf(Effort.LOW, Effort.MEDIUM, Effort.HIGH)
        Wire.ANTHROPIC -> Effort.entries
    }

    private fun capped(efforts: List<Effort>, cap: Effort): List<Effort> =
        efforts.filter { it.ordinal <= cap.ordinal }.ifEmpty { listOf(efforts.minByOrNull { it.ordinal } ?: Effort.HIGH) }

    fun build(settings: Settings): Map<String, List<Profile>> {
        val out = mutableMapOf<String, List<Profile>>()
        for (svc in settings.services) {
            val all = settings.models.filter { it.service == svc.id }
            // 每条 Claude 产品线里最新的版本（含没打开的），给旧一代打折
            val newest = mutableMapOf<String, Double>()
            for (m in all) claudeVersion(m.id)?.let { (line, v) -> newest[line] = maxOf(newest[line] ?: 0.0, v) }
            out[svc.id] = all.filter { it.enabled }.mapIndexed { order, m ->
                val tier = tierOf(m.id)
                val v = claudeVersion(m.id)
                val efforts = if (v != null) claudeEfforts(m.id).filter { it in wireEfforts(svc.wire) } else wireEfforts(svc.wire)
                val price = CLAUDE_PRICES.filterKeys { m.id.startsWith(it) }.maxByOrNull { it.key.length }?.value ?: TIER_PRICE[tier]
                val penalty = if (v != null) minOf(0.08, 0.03 * (newest.getValue(v.first) - v.second)) else 0.0
                Profile(svc.id, svc.wire, m.id, tier, capped(efforts, m.maxEffort), TIER_SKILL[tier] - penalty, price, order)
            }
        }
        return out
    }

    /** 一次回答大概要多久（秒）：首字开销 + 输出量 / 速度。只用来比较快慢 */
    fun latency(p: Profile, effort: Effort, mode: String): Double {
        val tokens = (OUTPUT_TOKENS[mode] ?: 600) * (EFFORT_TOKENS[effort] ?: 1.0)
        return (OVERHEAD_S[p.wire] ?: 3.0) + tokens / TIER_SPEED[p.tier]
    }

    fun cost(p: Profile, effort: Effort, mode: String): Double {
        val tokens = (OUTPUT_TOKENS[mode] ?: 600) * (EFFORT_TOKENS[effort] ?: 1.0)
        return (INPUT_TOKENS * p.price.first + tokens * p.price.second) / 1e6
    }
}
