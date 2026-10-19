package io.github.typing233.superaide.core.session

import io.github.typing233.superaide.core.agent.Agent
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.agent.ToolHost
import io.github.typing233.superaide.core.agent.Tools
import io.github.typing233.superaide.core.agent.TurnResult
import io.github.typing233.superaide.core.config.ModelEntry
import io.github.typing233.superaide.core.events.Event
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.core.llm.Chat
import io.github.typing233.superaide.core.llm.Chats
import io.github.typing233.superaide.core.llm.Effort
import io.github.typing233.superaide.core.llm.Failure
import io.github.typing233.superaide.core.llm.ModelError
import io.github.typing233.superaide.core.llm.Part
import io.github.typing233.superaide.core.llm.Service
import io.github.typing233.superaide.core.prompts.Prompts
import kotlin.time.TimeSource

/** 一个可选的配置：哪个服务的哪个模型、用多大的思考强度。 */
data class Choice(val service: Service, val key: String, val model: ModelEntry, val effort: Effort, val reason: String = "") {
    val label get() = model.id
}

/** 每轮的记录（存历史、给路由学习） */
data class TurnRecord(
    val question: String,
    val answer: String,
    val ok: Boolean,
    val stopped: Boolean,
    val service: String,
    val model: String,
    val effort: Effort,
    val seconds: Double,
    val tools: Int,
    val trace: List<String>,
    val error: String? = null,
)

/**
 * 一段对话（对应桌面版 engines/hub.py 的 Conversation + _turn / _hand_over）：
 * 选模型 → 跑代理循环 → 模型用不了/限流/服务出错时换一个接着答（最多换 2 次，错误先压着不显示）。
 * 同一段对话里后面的追问沿用同一个模型；换了模型就带上前面问答的回顾。
 */
class Session(
    val mode: Mode,
    private val tools: ToolHost,
    /** 按优先顺序给出候选（已经去掉被暂时拉黑的）。exclude 是这一问里已经试过的模型 */
    private val pick: (exclude: Set<String>) -> List<Choice>,
    /** 这个配置出了 kind 类的错：拉黑它（模型或整个服务） */
    private val sideline: (Choice, Failure.Kind) -> Unit,
    private val emit: (Event) -> Unit,
    private val uiLang: () -> String = { "zh" },
    private val open: (Choice, String, List<io.github.typing233.superaide.core.llm.ToolSpec>) -> Chat = { c, system, specs ->
        Chats.open(c.service, c.key, c.model.id, c.effort, system, specs, c.model.vision)
    },
    private val maxHandovers: Int = 2,
) {
    var choice: Choice? = null
        private set
    private var agent: Agent? = null
    val records = mutableListOf<TurnRecord>()

    /** 用户按了停止 */
    fun stop() {
        agent?.stopped = true
    }

    /** 第一轮发出去的内容（截图 + 首条消息），后台对比用同样的内容再问一遍 */
    var firstParts: List<Part> = emptyList()
        private set

    /** 下一轮换成这个配置（没办成后加强）：同一服务就在原来的对话里换模型，不同服务就新开一段、带上前面问答的回顾 */
    fun switchTo(c: Choice) {
        val a = agent
        if (a != null && choice?.service?.id == c.service.id) a.switchModel(c.model.id, c.effort) else agent = null
        choice = c
    }

    /**
     * 问一句（第一句或追问）。env 是召唤/追问那一刻屏幕的文字，images 是截图。
     * 返回这一轮的结果；事件（包括 done）都经 emit 发出去。
     */
    suspend fun ask(
        question: String,
        env: String,
        images: List<Part.Image>,
        notes: List<String> = emptyList(),
        lessons: List<String> = emptyList(),
    ): TurnResult {
        val started = TimeSource.Monotonic.markNow()
        val followup = records.isNotEmpty()
        val tried = mutableSetOf<String>()
        val trace = mutableListOf<String>()
        var extraNotes = notes
        var handovers = 0
        while (true) {
            val c = choice ?: pick(tried).firstOrNull() ?: return finish(
                question, started, TurnResult(tr("没有能用的模型：在设置里加一个模型服务，或者打开被关掉的模型。"), ok = false), null, trace,
                error = tr("没有能用的模型"),
            )
            if (agent == null) {
                if (followup && handovers == 0) extraNotes = notes + recap() // 换了服务的追问：新开的对话不知道前面说过什么
                agent = Agent(open(c, Prompts.system(mode), Tools.forMode(mode)), tools, mode, { e ->
                    if (e.type == "status" && e.data["transient"] != true) trace += e.text
                    emit(e)
                })
                choice = c
            }
            emit(Event.route(c.service.name, c.model.id, c.effort.wire, c.reason))
            tried += c.model.id
            val text = if (followup && handovers == 0) {
                Prompts.followup(question, env, images.size, mode, extraNotes, lessons, uiLang())
            } else {
                Prompts.first(question, env, images.size, mode, extraNotes, lessons, uiLang())
            }
            try {
                val parts = images + Part.Text(text)
                if (!followup) firstParts = parts
                val r = agent!!.turn(parts)
                return finish(question, started, r, c, trace)
            } catch (e: ModelError) {
                val kind = Failure.kind(e)
                val next = if (kind != Failure.Kind.NONE && handovers < maxHandovers) {
                    sideline(c, kind)
                    pick(tried).firstOrNull()
                } else null
                if (next == null) {
                    emit(Event.error(Failure.friendly(e)))
                    return finish(question, started, TurnResult("", ok = false, model = c.model.id), c, trace, error = Failure.friendly(e))
                }
                // 换一个接着答：新开一段（历史不能跨服务带过去），带上前面问答的回顾和已经做过的步骤
                handovers++
                emit(Event.retract)
                emit(Event.status(tr("{model} {reason}，换 {other} 接着答…", "model" to c.model.id, "reason" to Failure.reason(e), "other" to next.model.id)))
                agent = null
                choice = next
                extraNotes = notes + recap() + takeover(trace)
            }
        }
    }

    private fun recap(): List<String> {
        if (records.isEmpty()) return emptyList()
        val lines = records.takeLast(6).joinToString("\n") { "问：${it.question}\n答：${it.answer.take(1500)}" }
        return listOf("这是同一段对话里的追问。前面的问答：\n$lines")
    }

    private fun takeover(trace: List<String>): List<String> =
        if (mode != Mode.ACT || trace.isEmpty()) emptyList()
        else listOf("另一个模型做到一半出了故障，它已经做了这些步骤：\n" + trace.takeLast(15).joinToString("\n") { "- $it" } +
            "\n先看清现在的状态，已经做完的不要重复。")

    private fun finish(
        question: String,
        started: TimeSource.Monotonic.ValueTimeMark,
        r: TurnResult,
        c: Choice?,
        trace: List<String>,
        error: String? = null,
    ): TurnResult {
        val seconds = started.elapsedNow().inWholeMilliseconds / 1000.0
        val ok = r.ok && r.reported == null
        records += TurnRecord(question, r.answer, ok, r.stopped, c?.service?.id.orEmpty(), r.model.ifBlank { c?.model?.id.orEmpty() },
            c?.effort ?: Effort.MEDIUM, seconds, r.tools, trace.toList(), error ?: r.reported)
        emit(Event.done(buildMap {
            put("ok", ok)
            put("stopped", r.stopped)
            put("model", r.model.ifBlank { c?.model?.id })
            put("seconds", seconds)
            put("tools", r.tools)
            if (r.reported != null) { put("reason", "reported"); put("reported", r.reported); put("error", r.reported) }
            if (error != null) put("error", error)
            if (r.stopped) put("reason", "interrupted")
        }))
        return r
    }
}
