package io.github.typing233.superaide.core.llm

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/** 一个模型服务说话用的协议。 */
@Serializable
enum class Wire { ANTHROPIC, OPENAI_RESPONSES, OPENAI_CHAT }

/** 思考强度，从低到高；各家协议再各自映射。 */
@Serializable
enum class Effort { LOW, MEDIUM, HIGH, XHIGH, MAX;
    val wire: String get() = name.lowercase()
}

/** 一个模型服务：地址 + 协议。key 不在这里，单独加密存。 */
@Serializable
data class Service(
    val id: String,
    val name: String,
    val wire: Wire,
    val baseUrl: String,
    /** Anthropic 协议下用 Authorization: Bearer（中转站常见）而不是 x-api-key */
    val bearer: Boolean = false,
    /** 可选代理，如 http://127.0.0.1:7890 */
    val proxy: String = "",
) {
    /** 请求用的地址：只填了域名的（api.example.com）补上 https:// */
    val url: String get() = baseUrl.trim().let { if (SCHEME.containsMatchIn(it)) it else "https://$it" }

    companion object {
        private val SCHEME = Regex("^[A-Za-z][A-Za-z0-9+.-]*://")
    }
}

sealed interface Part {
    data class Text(val text: String) : Part
    class Image(val bytes: ByteArray, val mediaType: String = "image/jpeg") : Part
}

class ToolSpec(val name: String, val description: String, val schema: JsonObject)

/** 模型要调的工具。input 为 null 表示参数不是合法 JSON（流式工具参数可能被截断）。 */
data class ToolCall(val id: String, val name: String, val input: JsonObject?, val raw: String)

class ToolOutput(val callId: String, val parts: List<Part>, val isError: Boolean = false)

enum class Stop { END, TOOL_USE, MAX_TOKENS, REFUSAL, PAUSE, OTHER }

data class Usage(val input: Long = 0, val output: Long = 0, val cacheRead: Long = 0, val cacheWrite: Long = 0)

/** 一轮模型输出（直到它停下来或要调工具）。 */
data class Turn(
    val text: String,
    val calls: List<ToolCall>,
    val stop: Stop,
    val usage: Usage,
    /** 实际作答的模型（服务端回退时可能和请求的不一样） */
    val model: String,
    val refusal: String? = null,
)

/** 流式过程中给界面的增量。 */
sealed interface Delta {
    data class Text(val text: String) : Delta
    data object Thinking : Delta
    data class ToolStart(val name: String) : Delta
}

sealed interface TurnInput {
    class User(val parts: List<Part>) : TurnInput
    class Results(val outputs: List<ToolOutput>, val extra: List<Part> = emptyList()) : TurnInput
}

/** 一段对话。历史只追加不改写，换模型时保留历史。 */
interface Chat {
    val model: String
    suspend fun send(input: TurnInput, onDelta: (Delta) -> Unit): Turn
    fun switchModel(model: String, effort: Effort)
}

/** 模型调用失败。status 是 HTTP 状态码（网络错误时为 null）。 */
class ModelError(
    val status: Int?,
    val type: String?,
    message: String,
    cause: Throwable? = null,
) : Exception(message, cause)
