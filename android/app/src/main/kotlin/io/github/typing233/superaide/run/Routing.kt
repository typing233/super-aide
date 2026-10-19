package io.github.typing233.superaide.run

import io.github.typing233.superaide.AideApp
import io.github.typing233.superaide.core.agent.Agent
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.agent.ToolHost
import io.github.typing233.superaide.core.config.ModelEntry
import io.github.typing233.superaide.core.llm.Chats
import io.github.typing233.superaide.core.llm.Effort
import io.github.typing233.superaide.core.llm.Failure
import io.github.typing233.superaide.core.llm.Part
import io.github.typing233.superaide.core.llm.ToolCall
import io.github.typing233.superaide.core.llm.ToolOutput
import io.github.typing233.superaide.core.prompts.Prompts
import io.github.typing233.superaide.core.router.Decision
import io.github.typing233.superaide.core.router.Judge
import io.github.typing233.superaide.core.router.Router
import io.github.typing233.superaide.core.router.Task
import io.github.typing233.superaide.core.session.Choice
import io.github.typing233.superaide.diag.Diag
import io.github.typing233.superaide.secure.SecretStore
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File
import kotlin.random.Random

/**
 * 路由和学习接到 App 上（对应桌面版 engines/hub.py 里和路由有关的部分）：
 * 每问一句先决策；结果、👍👎、追问说不对、很快又问同一个问题都记下来；没办成下一轮加强；
 * 问答答完、没看实时屏幕的，空闲时在后台用便宜的配置再答一遍，让强模型评判。
 */
class Routing(private val app: AideApp) {
    val router = Router({ app.settings.value }, File(app.filesDir, "router"))
    private val duelLock = Mutex()

    /** 这一轮用的决策（按 模型·强度 找回来） */
    private val decisions = mutableMapOf<String, Decision>()

    fun task(mode: Mode, question: String, app: String, context: String, errors: String) =
        Task(if (mode == Mode.ACT) "act" else "ask", question, app, context, errors)

    /** Session 要的候选：路由选的排第一，再按它给的候选顺序；去掉这一问里试过的 */
    fun choices(task: Task, exclude: Set<String>, override: Decision? = null): List<Choice> {
        router.rebuild()
        val first = override ?: runCatching { router.decide(task) }.getOrElse { Diag.error("router.decide", it); return emptyList() }
        val arms = listOf(first.model to first.effort) + first.candidates.mapNotNull { c ->
            val (model, effort) = (c["arm"] as String).split(" · ")
            model to (Effort.entries.firstOrNull { it.wire == effort } ?: return@mapNotNull null)
        }
        val settings = app.settings.value
        return arms.distinctBy { it.first }.filter { it.first !in exclude }.mapNotNull { (model, effort) ->
            val entry = settings.models.firstOrNull { it.id == model && it.enabled } ?: return@mapNotNull null
            choice(entry, effort, if (model == first.model) first.reason else "")?.also {
                decisions[key(it)] = (if (model == first.model) first else first.copy(model = model, effort = effort, service = entry.service))
            }
        }
    }

    private fun choice(m: ModelEntry, effort: Effort, reason: String): Choice? {
        val svc = app.settings.value.service(m.service) ?: return null
        val key = app.secrets.get(SecretStore.serviceKey(svc.id)) ?: return null
        return Choice(svc, key, m, effort, reason)
    }

    private fun key(c: Choice) = "${c.service.id}|${c.model.id}|${c.effort.wire}"

    fun decisionOf(c: Choice?): Decision? = c?.let { decisions[key(it)] }

    /** 模型服务出问题：先放一边（模型 / 整个服务） */
    fun sideline(c: Choice, kind: Failure.Kind) {
        val k = when (kind) {
            Failure.Kind.MODEL -> "model"
            Failure.Kind.AUTH -> "auth"
            Failure.Kind.SERVICE -> "service"
            Failure.Kind.NONE -> return
        }
        router.sideline(c.service.id, c.model.id, k)
        Diag.log("router.sideline", "${c.service.id}/${c.model.id} $k")
    }

    fun record(d: Decision?, success: Double, source: String) {
        if (d == null) return
        router.record(d, success, source)
        Diag.log("router.record", "${d.name} $source=$success")
    }

    /** 上一轮没办成：同一服务里更强的配置（下一轮用） */
    fun escalate(d: Decision?): Decision? = d?.let { router.escalate(it) }

    // ---------------- 后台对比 ----------------

    /**
     * 问答答完以后：值得对比就等用户空闲（15 秒后、最多等 10 分钟），用候选配置把同一个问题再答一遍（不给看实时屏幕的工具），
     * 让最强的模型评判两份，两份都记下来。一次只跑一个。
     */
    suspend fun duel(served: Decision, question: String, firstMessage: List<Part>, answer: String, context: String, askedAt: Long,
                     idle: () -> Boolean) {
        val candidate = router.duelCandidate(served) ?: return
        if (!duelLock.tryLock()) return
        try {
            delay(15_000)
            withTimeoutOrNull(10 * 60_000L) { while (!idle()) delay(5_000) } ?: return
            router.countDuel()
            Diag.log("duel.start", "${served.name} vs ${candidate.name}")
            val c = choices(Task("ask", question), emptySet(), candidate).firstOrNull { it.model.id == candidate.model } ?: return
            val chat = Chats.open(c.service, c.key, c.model.id, c.effort, Prompts.system(Mode.ASK), emptyList(), c.model.vision)
            val other = runCatching { Agent(chat, NoTools, Mode.ASK, {}).turn(firstMessage) }.getOrNull() ?: return
            if (!other.ok) { record(candidate, 0.0, "duel"); return }
            val verdict = judge(question, context, answer, other.answer, askedAt) ?: return
            router.recordDuel(served, candidate, verdict)
            Diag.log("duel.result", "candidate=${verdict.candidate} served=${verdict.served} ${verdict.why}")
        } catch (e: Exception) {
            Diag.error("duel", e)
        } finally {
            duelLock.unlock()
        }
    }

    /** 评审：最强的那个模型 */
    private suspend fun judge(question: String, context: String, served: String, candidate: String, askedAt: Long): Judge.Verdict? {
        val flip = Random.nextBoolean()
        val prompt = Judge.prompt(question, context, served, candidate, flip, Judge.askedAt(askedAt))
        return complete("你是严格的评审，只输出要求的 JSON。", prompt)?.let { Judge.parse(it, flip) }
    }

    /** 后台小活（评审、总结经验）：最强的模型，一次不带工具的调用。用不了返回 null */
    suspend fun complete(system: String, prompt: String): String? {
        router.rebuild()
        val strongest = router.available().mapNotNull(router::bestModel).minWithOrNull(compareBy({ it.tier }, { it.order })) ?: return null
        val entry = app.settings.value.models.firstOrNull { it.id == strongest.id && it.service == strongest.service } ?: return null
        val c = choice(entry, Effort.HIGH, "") ?: return null
        val chat = Chats.open(c.service, c.key, c.model.id, c.effort, system, emptyList(), c.model.vision)
        return runCatching { chat.send(io.github.typing233.superaide.core.llm.TurnInput.User(listOf(Part.Text(prompt)))) {}.text }
            .onFailure { Diag.error("complete", it) }.getOrNull()
    }

    private object NoTools : ToolHost {
        override suspend fun run(call: ToolCall, mode: Mode) =
            ToolOutput(call.id, listOf(Part.Text("后台对比时不能看实时屏幕：只根据消息里的环境回答。")), isError = true)
    }

    companion object {
        /** 追问里说上一轮不对（对应桌面版 NEGATIVE_FOLLOWUP） */
        val NEGATIVE = Regex(
            "不对|错了|没用|不行|还是不|不是这个|答非所问|没解决|你没|wrong|not working|doesn'?t work|didn'?t work|that'?s not",
            RegexOption.IGNORE_CASE,
        )

        /** 两个问题差不多是同一个（很快又问一遍 = 上次没答好）：字符二元组的重合度 */
        fun similar(a: String, b: String): Double {
            fun grams(s: String) = s.lowercase().filter { !it.isWhitespace() }.windowed(2).toSet()
            val ga = grams(a)
            val gb = grams(b)
            if (ga.isEmpty() || gb.isEmpty()) return if (a.trim() == b.trim()) 1.0 else 0.0
            return 2.0 * ga.intersect(gb).size / (ga.size + gb.size)
        }
    }
}
