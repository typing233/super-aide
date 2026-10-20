package io.github.typing233.superaide.core.llm

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.time.TimeSource

object Chats {
    /** 服务说某个模型不收图片（服务 id, 模型）：App 记进设置，以后不再给它发图 */
    @Volatile
    var onNoVision: ((String, String) -> Unit)? = null

    fun open(
        service: Service,
        key: String,
        model: String,
        effort: Effort,
        system: String,
        tools: List<ToolSpec>,
        vision: Boolean = true,
    ): Chat = when (service.wire) {
        Wire.ANTHROPIC -> AnthropicChat(service, key, model, effort, system, tools)
        Wire.OPENAI_RESPONSES, Wire.OPENAI_CHAT -> OpenAiChat(service, key, model, effort, system, tools, vision)
    }
}

/**
 * 测一个模型能不能用：一次请求里同时验证流式输出、工具调用和看图。
 * 给它一张纯色图，让它调 report_color 报颜色，再把结果交回去拿最终回答。
 */
object ModelProbe {
    data class Report(
        val ok: Boolean,
        val model: String,
        val firstDeltaMs: Long = -1,
        val totalMs: Long = -1,
        val tool: Boolean = false,
        val vision: Boolean = false,
        val color: String = "",
        val error: String? = null,
    )

    private val tool = ToolSpec(
        name = "report_color",
        description = "Report the main color of the image.",
        schema = Json.parseToJsonElement(
            """{"type":"object","properties":{"color":{"type":"string","description":"one English word"}},"required":["color"]}"""
        ).jsonObject,
    )

    suspend fun run(open: (system: String, tools: List<ToolSpec>) -> Chat, image: ByteArray?): Report {
        val started = TimeSource.Monotonic.markNow()
        var first = -1L
        val chat = runCatching { open("You are a connection test. Do exactly what is asked, briefly.", listOf(tool)) }
            .getOrElse { return Report(false, "", error = it.message ?: it.toString()) }
        return try {
            val parts = buildList {
                if (image != null) add(Part.Image(image))
                add(Part.Text("Call report_color with the main color of the image. Then reply with just: done."))
            }
            val turn = chat.send(TurnInput.User(parts)) {
                if (first < 0 && (it is Delta.Text || it is Delta.ToolStart)) first = started.elapsedNow().inWholeMilliseconds
            }
            val call = turn.calls.firstOrNull { it.name == tool.name }
            val color = call?.input?.get("color")?.jsonPrimitive?.content.orEmpty()
            if (call != null) chat.send(TurnInput.Results(listOf(ToolOutput(call.id, listOf(Part.Text("ok")))))) {}
            Report(
                ok = call != null,
                model = turn.model,
                firstDeltaMs = first,
                totalMs = started.elapsedNow().inWholeMilliseconds,
                tool = call != null,
                vision = color.contains("red", ignoreCase = true),
                color = color,
                error = if (call == null) "没有调用工具：${turn.text.take(200)}" else null,
            )
        } catch (e: ModelError) {
            Report(false, chat.model, totalMs = started.elapsedNow().inWholeMilliseconds, error = "${e.status ?: ""} ${e.message}".trim())
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            // 地址写错这类（请求都发不出去）：报出来，别让设置页崩掉
            Report(false, chat.model, totalMs = started.elapsedNow().inWholeMilliseconds, error = e.message ?: e.toString())
        }
    }
}
