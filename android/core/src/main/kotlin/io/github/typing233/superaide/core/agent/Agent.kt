package io.github.typing233.superaide.core.agent

import io.github.typing233.superaide.core.events.Event
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.core.llm.Chat
import io.github.typing233.superaide.core.llm.Delta
import io.github.typing233.superaide.core.llm.Part
import io.github.typing233.superaide.core.llm.Stop
import io.github.typing233.superaide.core.llm.ToolCall
import io.github.typing233.superaide.core.llm.ToolOutput
import io.github.typing233.superaide.core.llm.TurnInput
import io.github.typing233.superaide.core.llm.Usage
import io.github.typing233.superaide.core.prompts.Prompts
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope

/** 一轮（用户说一句 → 模型答完）的结果。 */
data class TurnResult(
    val answer: String,
    val ok: Boolean,
    val stopped: Boolean = false,
    val tools: Int = 0,
    val trace: List<String> = emptyList(),
    val usage: Usage = Usage(),
    val model: String = "",
    val stop: Stop = Stop.END,
    /** 操作模式汇报「没完成：…」时的第一行 */
    val reported: String? = null,
)

/**
 * 代理循环：发消息 → 模型要调工具就执行、把结果交回去 → 直到它答完。
 * 历史只追加不改写。被停止（停止键或协程取消）时还没交回结果的工具调用，
 * 下一轮先补上结果（已执行的用真结果，没执行的写"已停止"），否则接口会报 400。
 */
class Agent(
    private val chat: Chat,
    private val tools: ToolHost,
    val mode: Mode,
    private val emit: (Event) -> Unit,
    private val maxSteps: Int = if (mode == Mode.ACT) 80 else 40,
) {
    /** 用户按了停止：当前工具做完就不再往下做 */
    @Volatile
    var stopped = false

    val model: String get() = chat.model

    /** 同一服务里换模型或思考强度（历史保留） */
    fun switchModel(model: String, effort: io.github.typing233.superaide.core.llm.Effort) = chat.switchModel(model, effort)

    /** 模型要调、但还没把结果交回去的工具，和已经拿到的结果 */
    private var pending: List<ToolCall> = emptyList()
    private val done = mutableListOf<ToolOutput>()

    suspend fun turn(parts: List<Part>): TurnResult {
        stopped = false
        var input: TurnInput = if (pending.isEmpty()) TurnInput.User(parts) else TurnInput.Results(closePending(), parts)
        var toolCount = 0
        var steps = 0
        val trace = mutableListOf<String>()
        var usage = Usage()
        while (true) {
            emit(Event.newMessage)
            val answer = StringBuilder()
            val turn = chat.send(input) { d ->
                when (d) {
                    is Delta.Text -> { answer.append(d.text); emit(Event.delta(d.text)) }
                    is Delta.Thinking -> emit(Event.status(tr("正在思考…"), transient = true))
                    is Delta.ToolStart -> { answer.setLength(0); emit(Event.retract) }
                }
            }
            usage += turn.usage
            if (turn.calls.isEmpty()) {
                val text = turn.text.ifBlank { answer.toString() }
                return TurnResult(
                    answer = text,
                    ok = turn.stop == Stop.END && text.isNotBlank(),
                    tools = toolCount,
                    trace = trace,
                    usage = usage,
                    model = turn.model,
                    stop = turn.stop,
                    reported = if (mode == Mode.ACT) Prompts.reportedFailure(text) else null,
                )
            }
            pending = turn.calls
            done.clear()
            // 连着的几个联网、读文件这类调用一起跑；看屏幕、操作手机的一个一个来
            val calls = turn.calls
            var i = 0
            while (i < calls.size && !stopped) {
                val batch = if (calls[i].name in Tools.parallel) calls.drop(i).takeWhile { it.name in Tools.parallel } else listOf(calls[i])
                for (call in batch) {
                    val line = Tools.status(call)
                    trace += line
                    emit(Event.status(line, tool = call.name))
                }
                done += if (batch.size == 1) listOf(run(batch[0])) else coroutineScope { batch.map { async { run(it) } }.awaitAll() }
                toolCount += batch.size
                i += batch.size
            }
            if (stopped) {
                return TurnResult(turn.text, ok = false, stopped = true, tools = toolCount, trace = trace, usage = usage, model = turn.model)
            }
            val outputs = done.toList()
            pending = emptyList()
            done.clear()
            steps++
            input = if (steps >= maxSteps) {
                TurnInput.Results(outputs, listOf(Part.Text("（已经操作了很多步，请停下来，汇报现在的进展。）")))
            } else {
                TurnInput.Results(outputs)
            }
        }
    }

    private suspend fun run(call: ToolCall): ToolOutput {
        if (call.input == null) {
            return ToolOutput(call.id, listOf(Part.Text("参数不是合法的 JSON（可能被截断了），请重新调用。")), isError = true)
        }
        return try {
            tools.run(call, mode)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ToolOutput(call.id, listOf(Part.Text("工具出错：${e.message ?: e}")), isError = true)
        }
    }

    private fun closePending(): List<ToolOutput> {
        val have = done.associateBy { it.callId }
        val out = pending.map { have[it.id] ?: ToolOutput(it.id, listOf(Part.Text("用户按了停止，这一步没有执行。")), isError = true) }
        pending = emptyList()
        done.clear()
        return out
    }
}

operator fun Usage.plus(o: Usage) = Usage(input + o.input, output + o.output, cacheRead + o.cacheRead, cacheWrite + o.cacheWrite)
