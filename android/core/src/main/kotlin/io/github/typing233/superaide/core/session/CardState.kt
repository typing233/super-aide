package io.github.typing233.superaide.core.session

import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.events.Event

/** 一问一答（界面上的一轮）。 */
data class Exchange(val question: String, val answer: String, val ok: Boolean)

/**
 * 回答卡片的状态：收到一个事件就算出新状态（和桌面版 ui/web/app.js 处理事件的方式一样）。
 * 纯函数，界面只管显示。
 */
data class CardState(
    val mode: Mode = Mode.ASK,
    val question: String = "",
    /** 同一段对话里前面几轮 */
    val earlier: List<Exchange> = emptyList(),
    /** 进度（不含"正在思考…"这种临时状态） */
    val steps: List<String> = emptyList(),
    /** 临时状态（正在思考…），有新进度或回答就清掉 */
    val transient: String? = null,
    val answer: String = "",
    val running: Boolean = false,
    val done: Boolean = false,
    val ok: Boolean = true,
    val stopped: Boolean = false,
    val error: String? = null,
    /** 模型 · 思考强度 */
    val route: String = "",
    /** 问答模式下回答说要动手：显示「让我来做」 */
    val handOff: Boolean = false,
    /** 操作模式汇报没完成时的第一行 */
    val reported: String? = null,
    /** 用户的评价：1 / -1 / 0 */
    val rating: Int = 0,
    /** 屏幕上的列表只加载了一部分：问答答完后给一个「读完整页」 */
    val fullPage: Boolean = false,
) {
    fun reduce(e: Event): CardState = when (e.type) {
        "route" -> copy(route = listOfNotNull(e.data["model"], e.data["effort"]).joinToString(" · "))
        "status" -> if (e.data["transient"] == true) copy(transient = e.text) else copy(steps = steps + e.text, transient = null)
        "new_message", "retract" -> copy(answer = "")
        "delta" -> copy(answer = answer + e.text, transient = null)
        "error" -> copy(error = e.text)
        "done" -> {
            val ok = e.data["ok"] == true
            copy(
                running = false,
                done = true,
                ok = ok,
                stopped = e.data["stopped"] == true,
                transient = null,
                error = (e.data["error"] as? String)?.takeIf { !ok } ?: error.takeIf { !ok },
                reported = e.data["reported"] as? String,
                handOff = mode == Mode.ASK && ok && wantsHandOff(answer),
            )
        }
        else -> this
    }

    /** 新一轮追问：把这一轮收进 earlier */
    fun next(question: String): CardState = CardState(
        mode = mode,
        question = question,
        earlier = if (this.question.isBlank()) earlier else earlier + Exchange(this.question, answer, ok),
        running = true,
        route = route,
    )

    /** 结果的一行摘要（收起后的小条、操作完成的提示） */
    fun summary(): String {
        val first = answer.lineSequence().map { it.trim(' ', '*', '#', '>', '-') }.firstOrNull { it.isNotBlank() }.orEmpty()
        return first.removePrefix("已完成：").removePrefix("Done:").trim().take(80)
    }

    companion object {
        private val HAND_OFF = Regex("让我来做|Do it for me", RegexOption.IGNORE_CASE)
        fun wantsHandOff(answer: String) = HAND_OFF.containsMatchIn(answer)
    }
}
