package io.github.typing233.superaide.core.router

import io.github.typing233.superaide.core.config.Settings
import io.github.typing233.superaide.core.llm.Effort
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import java.io.File
import java.time.LocalDate
import java.time.ZoneId
import java.util.UUID
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt
import kotlin.random.Random

/** 一次任务（路由看的）。 */
data class Task(
    val mode: String,
    val question: String,
    /** 前台 App 的包名 */
    val app: String = "",
    /** 屏幕上的文字节选（判断难度用） */
    val context: String = "",
    /** 屏幕上的报错行 */
    val errors: String = "",
    var id: String = "",
)

data class View(val mode: String, val kind: String, val domain: String, val band: Int) {
    val agentic get() = mode == "act" && kind == "agentic"
    val label get() = Router.LABELS[kind to domain] ?: "这类任务"
}

data class Decision(
    val service: String,
    val model: String,
    val effort: Effort,
    val reason: String,
    val via: String = "router",
    val mode: String = "",
    val kind: String = "",
    val domain: String = "",
    val band: Int = 0,
    val candidates: List<Map<String, Any>> = emptyList(),
    val task: String = "",
    val cost: Double = 0.0,
    val ref: String = "",
    val refCost: Double = 0.0,
) {
    val name get() = "$model · ${effort.wire}"
}

class Scored(val profile: Profile, val effort: Effort, val alpha: Double, val beta: Double, val real: Double, val cost: Double, val prior: Double) {
    val engine get() = profile.service
    val model get() = profile.id
    val eidx get() = effort.ordinal
    val mean get() = alpha / (alpha + beta)
    val variance: Double get() { val n = alpha + beta; return mean * (1 - mean) / (n + 1) }
    val name get() = "$model · ${effort.wire}"
}

/**
 * 智能路由（对应桌面版 router/policy.py）：先保证办成，再求快、求省。
 * 候选 = 服务 × 模型 × 思考强度；先验看档次和难度，证据来自学习记录，合成 Beta 后验；
 * 参照默认是先验最强的，证据表明别的明显更好才换；更便宜的要过非劣效检验才降级；没办成就在同一服务里加强。
 */
class Router(
    private val settings: () -> Settings,
    dir: File?,
    private val now: () -> Double = { System.currentTimeMillis() / 1000.0 },
    private val random: Random = Random.Default,
    private val zone: ZoneId = ZoneId.systemDefault(),
) {
    val evidence = Evidence(dir?.let { File(it, "outcomes.jsonl") })
    private val stateFile = dir?.let { File(it, "state.json") }
    private val decisionsFile = dir?.let { File(it, "decisions.jsonl") }
    private var state: MutableMap<String, Any> = loadState()

    /** 限流、过载、断网的服务 → 时刻 */
    private val unavailable = mutableMapOf<String, Double>()
    /** (服务, 模型) → (时刻, 歇多久) */
    private val modelsDown = mutableMapOf<Pair<String, String>, Pair<Double, Double>>()

    var profiles: Map<String, List<Profile>> = Catalog.build(settings())
        private set

    fun rebuild() {
        profiles = Catalog.build(settings())
    }

    // ---------- 能用哪些 ----------

    private fun down(service: String, model: String): Boolean {
        val (since, seconds) = modelsDown[service to model] ?: return false
        return now() - since < seconds
    }

    fun usable(service: String): List<Profile> = profiles[service].orEmpty().filter { !down(service, it.id) }

    fun available(): List<String> = profiles.keys.filter { s ->
        usable(s).isNotEmpty() && now() - (unavailable[s] ?: 0.0) > UNAVAILABLE_S
    }

    private fun profile(service: String, model: String) = profiles[service]?.firstOrNull { it.id == model }

    private fun tierOf(service: String, model: String) = profile(service, model)?.tier ?: Catalog.tierOf(model)

    fun bestModel(service: String): Profile? =
        usable(service).minWithOrNull(compareBy<Profile>({ it.tier }, { -it.skill }, { it.order }))

    /**
     * 这个配置因为模型服务没办成，先放一边（对应 sideline）：
     * model → 只歇这个模型；auth → 整个服务；service → 有别的服务就整个服务歇，只有它一个就只歇这个模型。
     * 歇了以后什么都用不了就不歇，返回 false。
     */
    fun sideline(service: String, model: String, kind: String): Boolean {
        val savedU = unavailable.toMap()
        val savedM = modelsDown.toMap()
        when {
            kind == "model" -> modelsDown[service to model] = now() to MODEL_DOWN_S
            kind == "auth" || available().any { it != service } -> unavailable[service] = now()
            else -> modelsDown[service to model] = now() to UNAVAILABLE_S
        }
        if (available().isNotEmpty()) return true
        unavailable.clear(); unavailable.putAll(savedU)
        modelsDown.clear(); modelsDown.putAll(savedM)
        return false
    }

    // ---------- 看任务 ----------

    fun describe(task: Task): View {
        val (kind, domain) = taskKind(task)
        var d = simpleDifficulty(task.question)
        val extra = listOf(task.context.take(4000), task.errors.take(2000)).filter { it.isNotEmpty() }.joinToString("\n\n")
        if (extra.isNotEmpty()) d = max(d, simpleDifficulty("${task.question}\n\n$extra"))
        var band = BAND_LIMITS.count { d >= it }
        if (THINK_HINT.containsMatchIn(task.question)) band = min(2, band + 1)
        return View(task.mode, kind, domain, band)
    }

    fun referenceEffort(p: Profile, view: View): Effort {
        val level = REFERENCE.getValue(view.mode)[view.band].ordinal
        return p.efforts.firstOrNull { it.ordinal >= level } ?: p.efforts.last()
    }

    private fun prior(p: Profile, effort: Effort, view: View): Double {
        val skill = p.skill - EFFORT_STEP * max(0, referenceEffort(p, view).ordinal - effort.ordinal)
        val z = SLOPE * (skill - DIFFICULTY.getValue(view.mode)[view.band])
        return 1.0 / (1.0 + exp(-z.coerceIn(-20.0, 20.0)))
    }

    /** 实测校准的倍数。这个服务还没测过时，用测过的服务的平均 */
    private fun factor(table: String, service: String, mode: String): Double {
        @Suppress("UNCHECKED_CAST")
        val known = state[table] as? Map<String, Double> ?: return 1.0
        known["$service|$mode"]?.let { return it }
        val others = known.filterKeys { it.endsWith("|$mode") }.values
        return if (others.isEmpty()) 1.0 else others.average()
    }

    private fun cost(p: Profile, effort: Effort, mode: String): Double {
        val usd = Catalog.cost(p, effort, mode) * factor("price", p.service, mode)
        val seconds = Catalog.latency(p, effort, mode) * factor("speed", p.service, mode)
        return usd + LATENCY_USD_PER_S * seconds
    }

    fun score(view: View, services: List<String>): List<Scored> {
        val buckets = evidence.gather(view.mode, view.kind, view.domain, now())
        val out = mutableListOf<Scored>()
        for (s in services) for (p in usable(s)) for (effort in p.efforts) {
            val pr = prior(p, effort, view)
            val (succ, fail) = Evidence.counts(buckets, p.service, p.id, p.tier, effort.ordinal, ::tierOf)
            out += Scored(p, effort, PRIOR_N * pr + succ, PRIOR_N * (1 - pr) + fail, succ + fail, cost(p, effort, view.mode), pr)
        }
        return out
    }

    // ---------- 决策 ----------

    fun decide(task: Task): Decision {
        val services = available()
        require(services.isNotEmpty()) { "没有可用的模型：请在设置里至少打开一个模型" }
        if (task.id.isEmpty()) task.id = UUID.randomUUID().toString().replace("-", "").take(12)
        val view = describe(task)
        val decision = runCatching { route(view, services) }.getOrElse { rules(view, services) }.copy(task = task.id)
        log("decision", task, decision)
        return decision
    }

    class Pick(val chosen: Scored, val ref: Scored, val default: Scored, val confidence: Double, val scored: List<Scored>)

    fun pick(view: View, services: List<String>): Pick = pickFrom(score(view, services))

    private fun route(view: View, services: List<String>): Decision {
        val pk = pick(view, services)
        val top = pk.scored.sortedWith(compareBy<Scored>({ -it.mean }, { it.cost })).take(6)
        return Decision(
            service = pk.chosen.engine, model = pk.chosen.model, effort = pk.chosen.effort,
            reason = reason(view, pk), mode = view.mode, kind = view.kind, domain = view.domain, band = view.band,
            candidates = top.map { mapOf("arm" to it.name, "engine" to it.engine, "quality" to round(it.mean, 3),
                "n" to round(it.real, 1), "cost" to round(it.cost, 3)) },
            cost = round(pk.chosen.cost, 4), ref = pk.ref.name, refCost = round(pk.ref.cost, 4),
        )
    }

    private fun reason(view: View, pk: Pick): String {
        val (chosen, ref, default) = Triple(pk.chosen, pk.ref, pk.default)
        if (chosen !== ref) {
            return "${chosen.name} 在${view.label}上已证明和最可靠的配置（${ref.name}）几乎一样能办成（把握 ${(pk.confidence * 100).toInt()}%），更快、更省"
        }
        if (ref !== default) {
            if (ref.model == default.model && ref.eidx > default.eidx) return "${view.label}用 ${default.effort.wire} 没办成过，思考强度提高到 ${ref.effort.wire}"
            return "${ref.name} 在${view.label}上比 ${default.name} 更可靠"
        }
        val cheaper = pk.scored.any { it.cost < chosen.cost * (1 - MIN_SAVING) }
        return "先保证办成：${chosen.name}" + if (cheaper) "（更便宜、更快的配置在这类任务上还没证明一样能办成）" else ""
    }

    private fun rules(view: View, services: List<String>): Decision {
        val p = services.mapNotNull(::bestModel).minWithOrNull(compareBy({ it.tier }, { it.order }))!!
        return Decision(p.service, p.id, referenceEffort(p, view), "规则路由", via = "rules", mode = view.mode,
            kind = view.kind, domain = view.domain, band = view.band)
    }

    /** 这几类任务现在实际会用的配置，和最可靠的那个不一样的（"路由表现"列出来） */
    fun learned(kinds: List<View>): List<Map<String, Any>> {
        val services = available()
        if (services.isEmpty()) return emptyList()
        return kinds.mapNotNull { view ->
            val pk = runCatching { pick(view, services) }.getOrNull() ?: return@mapNotNull null
            when {
                pk.chosen !== pk.ref -> mapOf("mode" to view.mode, "label" to view.label, "change" to "cheaper", "use" to pk.chosen.name,
                    "instead" to pk.ref.name, "confidence" to round(pk.confidence, 3),
                    "saving" to if (pk.ref.cost > 0) round(1 - pk.chosen.cost / pk.ref.cost, 3) else 0.0)
                pk.ref !== pk.default -> mapOf("mode" to view.mode, "label" to view.label, "change" to "stronger",
                    "use" to pk.ref.name, "instead" to pk.default.name)
                else -> null
            }
        }
    }

    // ---------- 没办成：同一段对话里加强 ----------

    /** 同一个服务里换更强的配置：更高的思考强度，或者更强的模型。没有返回 null */
    fun escalate(decision: Decision): Decision? {
        if (decision.service !in available()) return null
        val view = View(decision.mode, decision.kind, decision.domain, decision.band)
        val current = profile(decision.service, decision.model)
        val level = decision.effort.ordinal
        val stronger = score(view, listOf(decision.service)).filter { s ->
            (s.model == decision.model && s.eidx > level) ||
                (current != null && s.profile.tier < current.tier && s.eidx >= max(level, referenceEffort(s.profile, view).ordinal))
        }
        if (stronger.isEmpty()) return null
        val chosen = best(stronger)
        return decision.copy(service = chosen.engine, model = chosen.model, effort = chosen.effort,
            reason = "上一轮没办成，换更强的配置：${chosen.name}", via = "escalated")
    }

    // ---------- 后台对比（只在问答模式） ----------

    fun duelsLeft(): Int {
        val today = LocalDate.now(zone).toString()
        @Suppress("UNCHECKED_CAST")
        val used = state["duels"] as? Map<String, Any> ?: emptyMap()
        val n = if (used["date"] == today) (used["n"] as? Number)?.toInt() ?: 0 else 0
        return max(0, settings().shadowDaily - n)
    }

    fun countDuel() {
        val today = LocalDate.now(zone).toString()
        @Suppress("UNCHECKED_CAST")
        val used = state["duels"] as? Map<String, Any> ?: emptyMap()
        val n = if (used["date"] == today) (used["n"] as? Number)?.toInt() ?: 0 else 0
        state["duels"] = mapOf("date" to today, "n" to n + 1)
        saveState()
    }

    /** 问答答完以后，值得在后台试一试的另一个配置：更便宜、有可能过关、还没过关的；偶尔是另一个服务的 */
    fun duelCandidate(decision: Decision): Decision? {
        if (decision.mode != "ask" || !settings().shadowEval || duelsLeft() <= 0) return null
        if ((decision.kind to decision.domain) == ("qa_factual" to "ui_help") || decision.via in setOf("pinned", "rules")) return null
        val view = View(decision.mode, decision.kind, decision.domain, decision.band)
        val scored = score(view, available())
        val served = scored.firstOrNull { it.engine == decision.service && it.model == decision.model && it.effort == decision.effort } ?: return null
        val cheaper = scored.mapNotNull { s ->
            if (s === served || s.cost > served.cost * (1 - MIN_SAVING)) return@mapNotNull null
            val p = noninferior(s, served)
            if (p >= DUEL_MIN_P && !(p >= CONFIDENCE && s.real >= MIN_EVIDENCE)) p * (served.cost - s.cost) to s else null
        }
        val rivals = scored.filter { it.engine != served.engine && it.real < MIN_EVIDENCE * 2 }
        val pick = when {
            rivals.isNotEmpty() && (cheaper.isEmpty() || random.nextDouble() < DUEL_RIVAL) -> best(rivals)
            cheaper.isNotEmpty() -> cheaper.maxBy { it.first }.second
            else -> return null
        }
        return decision.copy(service = pick.engine, model = pick.model, effort = pick.effort,
            reason = "后台对比：${pick.name} 在${view.label}上能不能和 ${served.name} 一样好", via = "duel")
    }

    fun recordDuel(served: Decision, candidate: Decision, verdict: Judge.Verdict) {
        record(candidate, verdict.candidate, "duel")
        record(served, verdict.served, "duel_ref")
    }

    // ---------- 学习 ----------

    fun record(decision: Decision?, success: Double, source: String) {
        decision ?: return
        val mode = decision.mode.ifEmpty { "act" }
        val weight = when (val w = SIGNALS[source]) {
            is Double -> w
            is Map<*, *> -> (w[mode] as? Double) ?: 0.3
            else -> 0.3
        }
        evidence.add(Outcome(now(), mode, decision.kind, decision.domain, decision.service, decision.model,
            decision.effort.wire, success, weight, source))
        log("outcome", null, decision, mapOf("arm" to "${decision.service}|${decision.model}|${decision.effort.wire}",
            "success" to success, "source" to source))
    }

    /** 第一轮实际用了多久、花了多少：校准这个服务在这个模式下的耗时（和花费）估计 */
    fun observe(decision: Decision, seconds: Double, costUsd: Double? = null) {
        val p = profile(decision.service, decision.model) ?: return
        if (seconds <= 0 || decision.mode !in setOf("ask", "act")) return
        val key = "${decision.service}|${decision.mode}"
        @Suppress("UNCHECKED_CAST")
        val speed = (state["speed"] as? Map<String, Double>)?.toMutableMap() ?: mutableMapOf()
        speed[key] = round(ema(speed[key], seconds / Catalog.latency(p, decision.effort, decision.mode)), 4)
        state["speed"] = speed
        if (costUsd != null && costUsd > 0) {
            @Suppress("UNCHECKED_CAST")
            val price = (state["price"] as? Map<String, Double>)?.toMutableMap() ?: mutableMapOf()
            price[key] = round(ema(price[key], costUsd / Catalog.cost(p, decision.effort, decision.mode)), 4)
            state["price"] = price
        }
        saveState()
    }

    // ---------- 存取 ----------

    private fun loadState(): MutableMap<String, Any> {
        val f = stateFile ?: return mutableMapOf()
        if (!f.exists()) return mutableMapOf()
        return runCatching {
            val obj = Json.parseToJsonElement(f.readText()).jsonObject
            val out = mutableMapOf<String, Any>()
            for (table in listOf("speed", "price")) (obj[table] as? JsonObject)?.let { t ->
                out[table] = t.mapValues { (it.value as JsonPrimitive).doubleOrNull ?: 1.0 }
            }
            (obj["duels"] as? JsonObject)?.let { d ->
                out["duels"] = mapOf("date" to (d["date"] as? JsonPrimitive)?.content.orEmpty(), "n" to ((d["n"] as? JsonPrimitive)?.intOrNull ?: 0))
            }
            out
        }.getOrDefault(mutableMapOf())
    }

    private fun saveState() {
        val f = stateFile ?: return
        runCatching {
            val obj = buildJsonObject {
                for (table in listOf("speed", "price")) {
                    @Suppress("UNCHECKED_CAST")
                    (state[table] as? Map<String, Double>)?.let { t -> put(table, JsonObject(t.mapValues { JsonPrimitive(it.value) })) }
                }
                @Suppress("UNCHECKED_CAST")
                (state["duels"] as? Map<String, Any>)?.let { d ->
                    put("duels", buildJsonObject { put("date", d["date"].toString()); put("n", (d["n"] as Number).toInt()) })
                }
            }
            f.parentFile?.mkdirs()
            val tmp = File(f.parentFile, f.name + ".tmp")
            tmp.writeText(obj.toString())
            tmp.renameTo(f)
        }
    }

    private fun log(type: String, task: Task?, d: Decision, extra: Map<String, Any> = emptyMap()) {
        val f = decisionsFile ?: return
        runCatching {
            val record = buildJsonObject {
                put("t", now()); put("type", type); put("mode", d.mode); put("app", task?.app.orEmpty())
                put("kind", d.kind); put("domain", d.domain); put("band", d.band); put("engine", d.service)
                put("model", d.model); put("effort", d.effort.wire); put("via", d.via); put("reason", d.reason)
                put("task", d.task.ifEmpty { task?.id.orEmpty() })
                if (type == "decision") { put("cost", d.cost); put("ref", d.ref); put("ref_cost", d.refCost) }
                for ((k, v) in extra) when (v) {
                    is Number -> put(k, v.toDouble())
                    else -> put(k, v.toString())
                }
            }
            f.parentFile?.mkdirs()
            f.appendText(record.toString() + "\n")
        }
    }

    companion object {
        /** 参照强度：按模式和难度（0 一般 / 1 较难 / 2 很难） */
        val REFERENCE = mapOf("ask" to listOf(Effort.MEDIUM, Effort.HIGH, Effort.XHIGH), "act" to listOf(Effort.HIGH, Effort.XHIGH, Effort.MAX))
        val DIFFICULTY = mapOf("ask" to doubleArrayOf(0.30, 0.50, 0.65), "act" to doubleArrayOf(0.50, 0.62, 0.75))
        val BAND_LIMITS = doubleArrayOf(0.45, 0.70)
        const val SLOPE = 6.0
        const val EFFORT_STEP = 0.06
        const val PRIOR_N = 3.0
        const val MARGIN = 0.03
        const val CONFIDENCE = 0.90
        const val MIN_EVIDENCE = 4.0
        const val MIN_SAVING = 0.15
        const val UP_MARGIN = 0.03
        const val UP_CONFIDENCE = 0.70
        const val TIE = 0.002
        const val LATENCY_USD_PER_S = 0.02
        const val UNAVAILABLE_S = 300.0
        const val MODEL_DOWN_S = 1800.0
        const val DUEL_MIN_P = 0.15
        const val DUEL_RIVAL = 0.2

        /** 各类结果信号的可信度（学习权重） */
        val SIGNALS: Map<String, Any> = mapOf(
            "status_ok" to mapOf("ask" to 0.1, "act" to 0.3), "status_fail" to 0.7, "feedback" to 1.0, "negative_followup" to 0.8,
            "reask" to 0.5, "acted_on" to 0.4, "duel" to 0.8, "duel_ref" to 0.8,
        )

        private val WRITE_HINT = Regex("帮我写|回复|润色|改写|起草|写一|拟|回个")
        private val TRANSLATE_HINT = Regex("翻译|translate", RegexOption.IGNORE_CASE)
        private val PROBLEM_HINT = Regex("为什么|怎么回事|报错|错误|失败|不行|打不开|闪退|error|fail|why", RegexOption.IGNORE_CASE)
        private val HOWTO_HINT = Regex("怎么|如何|怎样|在哪|哪里|找不到|how (do|to|can)|where", RegexOption.IGNORE_CASE)
        private val SYSTEM_HINT = Regex(
            "设置|权限|通知|蓝牙|WLAN|wi-?fi|存储|内存|电池|耗电|流量|更新|安装|卸载|发热|卡顿|空间|热点|定位|vpn|代理|默认应用",
            RegexOption.IGNORE_CASE,
        )
        /** 你明说要多想想：难度至少升一档 */
        val THINK_HINT = Regex("仔细|认真想|深入|好好想|慢慢想|想清楚|深度思考|think (hard|carefully)", RegexOption.IGNORE_CASE)

        val LABELS = mapOf(
            ("translation" to "screen_text") to "翻译", ("creative" to "writing") to "写作", ("code_fix" to "explain_error") to "报错分析",
            ("qa_factual" to "ui_help") to "界面问答", ("qa_factual" to "system_help") to "手机设置问题", ("qa_factual" to "general") to "一般问答",
            ("agentic" to "chat") to "聊天软件里的操作", ("agentic" to "browser") to "浏览器操作", ("agentic" to "shop") to "购物软件里的操作",
            ("agentic" to "system") to "系统设置操作", ("agentic" to "app") to "App 操作",
        )

        private val CHAT = setOf(
            "com.tencent.mm", "com.tencent.mobileqq", "com.ss.android.lark", "com.alibaba.android.rimet", "com.tencent.wework",
            "org.telegram.messenger", "com.whatsapp", "com.discord", "com.facebook.orca", "com.hihonor.mms", "com.android.mms",
            "com.google.android.apps.messaging", "com.huawei.meetime",
        )
        private val SHOP = setOf(
            "com.taobao.taobao", "com.jingdong.app.mall", "com.xunmeng.pinduoduo", "com.sankuai.meituan", "com.taobao.idlefish",
            "com.dianping.v1", "com.eg.android.AlipayGphone", "com.tmall.wireless", "com.achievo.vipshop",
        )

        /** 前台 App 是哪一类（只用来分开学习不同场景） */
        fun appCategory(pkg: String): String = when {
            pkg in CHAT -> "chat"
            pkg in SHOP -> "shop"
            "browser" in pkg || pkg in setOf("com.android.chrome", "com.UCMobile", "com.tencent.mtt", "org.mozilla.firefox", "com.microsoft.emmx") -> "browser"
            pkg == "com.android.settings" || "launcher" in pkg || pkg == "com.android.systemui" || "permissioncontroller" in pkg -> "system"
            else -> "app"
        }

        /** → (任务类型, 子类)。只用来分开学习不同场景 */
        fun taskKind(task: Task): Pair<String, String> {
            if (task.mode == "act") return "agentic" to appCategory(task.app)
            val q = task.question
            return when {
                TRANSLATE_HINT.containsMatchIn(q) -> "translation" to "screen_text"
                WRITE_HINT.containsMatchIn(q) -> "creative" to "writing"
                task.errors.isNotBlank() && PROBLEM_HINT.containsMatchIn(q) -> "code_fix" to "explain_error"
                SYSTEM_HINT.containsMatchIn(q) || appCategory(task.app) == "system" -> "qa_factual" to "system_help"
                HOWTO_HINT.containsMatchIn(q) -> "qa_factual" to "ui_help"
                else -> "qa_factual" to "general"
            }
        }

        /** 桌面版没装 llmrouter 时用的简单难度估计（llmrouter 是用户本机的独立项目，没有移植） */
        fun simpleDifficulty(text: String): Double {
            val code = listOf("Traceback", "Error", "error:", "def ", "class ", "{", "};", "=>").sumOf { k -> text.windowed(k.length).count { it == k } }
            return min(0.9, 0.2 + 0.1 * min(3, code) + min(0.3, text.length / 20000.0))
        }

        /** P(c 的成功率 ≥ r 的成功率 − margin)，两个 Beta 后验的均值和方差（正态近似） */
        fun noninferior(c: Scored, r: Scored, margin: Double = MARGIN): Double {
            val v = c.variance + r.variance
            if (v <= 0) return if (c.mean >= r.mean - margin) 1.0 else 0.0
            val z = (c.mean - r.mean + margin) / sqrt(v)
            return 0.5 * (1 + Erf.erf(z / sqrt(2.0)))
        }

        fun superior(c: Scored, r: Scored, margin: Double = UP_MARGIN) = noninferior(c, r, -margin)

        /**
         * 参照和降级（对应 _reference + _pick）：参照默认是先验最强的，证据表明别的大概率明显更好才换；
         * 再按花费从低到高找一个过了非劣效检验、自己有足够真实结果、能省至少 15% 的。
         */
        fun pickFrom(scored: List<Scored>): Pick {
            val default = best(scored) { it.prior }
            val better = scored.filter { it !== default && superior(it, default) >= UP_CONFIDENCE }
            val ref = if (better.isEmpty()) default else best(better)
            var chosen = ref
            var confidence = 0.0
            for (s in scored.sortedBy { it.cost }) {
                if (s.cost > ref.cost * (1 - MIN_SAVING)) break
                if (s.real < MIN_EVIDENCE) continue
                val p = noninferior(s, ref)
                if (p >= CONFIDENCE) { chosen = s; confidence = p; break }
            }
            return Pick(chosen, ref, default, confidence, scored)
        }

        /** 预测成功率最高的；差不多一样高时选最省、最快的 */
        fun best(scored: List<Scored>, key: (Scored) -> Double = { it.mean }): Scored {
            val top = scored.maxOf(key)
            return scored.filter { key(it) >= top - TIE }.minWith(compareBy<Scored>({ it.cost }, { it.profile.tier }, { it.profile.order }))
        }

        fun ema(old: Double?, new: Double, rate: Double = 0.2): Double {
            val n = new.coerceIn(0.2, 20.0)
            return if (old == null) n else old + rate * (n - old)
        }

        /** Python 的 round：银行家舍入 */
        fun round(x: Double, digits: Int): Double =
            java.math.BigDecimal(x).setScale(digits, java.math.RoundingMode.HALF_EVEN).toDouble()
    }
}
