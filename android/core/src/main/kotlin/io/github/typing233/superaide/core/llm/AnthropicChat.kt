package io.github.typing233.superaide.core.llm

import com.anthropic.client.AnthropicClient
import com.anthropic.client.okhttp.AnthropicOkHttpClient
import com.anthropic.core.JsonValue
import com.anthropic.core.jsonMapper
import com.anthropic.errors.AnthropicIoException
import com.anthropic.errors.AnthropicServiceException
import com.anthropic.helpers.MessageAccumulator
import com.anthropic.models.messages.Base64ImageSource
import com.anthropic.models.messages.CacheControlEphemeral
import com.anthropic.models.messages.ContentBlockParam
import com.anthropic.models.messages.ImageBlockParam
import com.anthropic.models.messages.MessageCreateParams
import com.anthropic.models.messages.MessageParam
import com.anthropic.models.messages.OutputConfig
import com.anthropic.models.messages.StopReason
import com.anthropic.models.messages.TextBlockParam
import com.anthropic.models.messages.Tool
import com.anthropic.models.messages.ToolResultBlockParam
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URI
import java.time.Duration
import java.util.Base64
import kotlin.concurrent.thread
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Anthropic Messages API（官方 Java SDK）。 */
class AnthropicChat(
    private val service: Service,
    key: String,
    model: String,
    private var effort: Effort,
    private val system: String,
    tools: List<ToolSpec>,
    private val maxTokens: Long = 32_000,
) : Chat {
    override var model: String = model
        private set

    private val client: AnthropicClient = AnthropicOkHttpClient.builder()
        .baseUrl(service.url.trimEnd('/').removeSuffix("/v1"))
        .apply { if (service.bearer) authToken(key) else apiKey(key) }
        .apply { proxyOf(service.proxy)?.let { proxy(it) } }
        .timeout(Duration.ofMinutes(10))
        .maxRetries(1)
        .build()

    private val official = runCatching { URI(service.url).host.orEmpty() }.getOrDefault("").endsWith("anthropic.com")
    private val toolList = tools.map(::toTool)
    private val history = mutableListOf<MessageParam>()

    private var caching = true

    override fun switchModel(model: String, effort: Effort) {
        this.model = model
        this.effort = effort
    }

    private fun params(): MessageCreateParams = MessageCreateParams.builder()
        .model(model)
        .maxTokens(maxTokens)
        .systemOfTextBlockParams(listOf(TextBlockParam.builder().text(system).build()))
        .messages(history.toList())
        .tools(toolList.map { com.anthropic.models.messages.ToolUnion.ofTool(it) })
        .outputConfig(OutputConfig.builder().effort(OutputConfig.Effort.of(effort.wire)).build())
        .apply {
            if (caching) cacheControl(CacheControlEphemeral.builder().build())
            // 拒答时由服务端换模型接着答（只有官方地址认这个参数）
            if (official) {
                putAdditionalHeader("anthropic-beta", "server-side-fallback-2026-07-01")
                putAdditionalBodyProperty("fallbacks", JsonValue.from("default"))
            }
        }
        .build()

    override suspend fun send(input: TurnInput, onDelta: (Delta) -> Unit): Turn {
        history += when (input) {
            is TurnInput.User -> userMessage(input.parts.map(::block))
            is TurnInput.Results -> userMessage(input.outputs.map(::resultBlock) + input.extra.map(::block))
        }
        val message = try {
            stream(params(), onDelta)
        } catch (e: ModelError) {
            // 有的中转站自己给请求加了 1 小时缓存，和我们的冲突：那就交给它缓存
            if (!caching || e.status != 400 || "cache_control" !in e.message.orEmpty()) throw e
            caching = false
            stream(params(), onDelta)
        }
        // 逐块转回历史：SDK 不认识的块（比如服务端拒答后换模型留下的 fallback 块）跳过，别让整轮失败
        history += MessageParam.builder()
            .role(MessageParam.Role.ASSISTANT)
            .contentOfBlockParams(message.content().mapNotNull { runCatching { it.toParam() }.getOrNull() })
            .build()

        val text = StringBuilder()
        val calls = mutableListOf<ToolCall>()
        for (block in message.content()) {
            block.text().ifPresent { text.append(it.text()) }
            block.toolUse().ifPresent { use ->
                val raw = jsonMapper().writeValueAsString(use._input())
                calls += ToolCall(use.id(), use.name(), parseObject(raw), raw)
            }
        }
        val stop = message.stopReason().map {
            when (it) {
                StopReason.END_TURN, StopReason.STOP_SEQUENCE -> Stop.END
                StopReason.TOOL_USE -> Stop.TOOL_USE
                StopReason.MAX_TOKENS -> Stop.MAX_TOKENS
                StopReason.REFUSAL -> Stop.REFUSAL
                StopReason.PAUSE_TURN -> Stop.PAUSE
                else -> Stop.OTHER
            }
        }.orElse(Stop.OTHER)
        val usage = message.usage().let {
            Usage(
                input = it.inputTokens(),
                output = it.outputTokens(),
                cacheRead = it.cacheReadInputTokens().orElse(0),
                cacheWrite = it.cacheCreationInputTokens().orElse(0),
            )
        }
        val refusal = message.stopDetails().flatMap { it.category() }.map { it.toString() }.orElse(null)
        return Turn(text.toString(), calls, stop, usage, message.model().asString(), refusal)
    }

    /** SDK 的流是阻塞的：放到独立线程读，协程取消时关流。 */
    private suspend fun stream(
        params: MessageCreateParams,
        onDelta: (Delta) -> Unit,
    ): com.anthropic.models.messages.Message = withContext(Dispatchers.IO) {
        currentCoroutineContext().ensureActive()
        suspendCancellableCoroutine { cont ->
            val response = try {
                client.messages().createStreaming(params)
            } catch (e: Throwable) {
                cont.resumeWithException(wrap(e)); return@suspendCancellableCoroutine
            }
            cont.invokeOnCancellation { runCatching { response.close() } }
            thread(name = "anthropic-stream", isDaemon = true) {
                val acc = MessageAccumulator.create()
                try {
                    response.use { r ->
                        r.stream().forEach { event ->
                            acc.accumulate(event)
                            event.contentBlockStart().ifPresent { start ->
                                val block = start.contentBlock()
                                block.toolUse().ifPresent { onDelta(Delta.ToolStart(it.name())) }
                                if (block.isThinking() || block.isRedactedThinking()) onDelta(Delta.Thinking)
                            }
                            event.contentBlockDelta().ifPresent { d ->
                                d.delta().text().ifPresent { onDelta(Delta.Text(it.text())) }
                            }
                        }
                    }
                    if (cont.isActive) cont.resume(acc.message())
                } catch (e: Throwable) {
                    // Error 也要接住（比如类初始化失败），不然线程死了、协程永远等不到结果
                    if (cont.isActive) cont.resumeWithException(wrap(e))
                }
            }
        }
    }

    private fun userMessage(blocks: List<ContentBlockParam>) = MessageParam.builder()
        .role(MessageParam.Role.USER)
        .contentOfBlockParams(blocks)
        .build()

    private fun block(part: Part): ContentBlockParam = when (part) {
        is Part.Text -> ContentBlockParam.ofText(TextBlockParam.builder().text(part.text).build())
        is Part.Image -> ContentBlockParam.ofImage(image(part))
    }

    private fun image(part: Part.Image) = ImageBlockParam.builder()
        .source(
            Base64ImageSource.builder()
                .data(Base64.getEncoder().encodeToString(part.bytes))
                .mediaType(Base64ImageSource.MediaType.of(part.mediaType))
                .build()
        )
        .build()

    private fun resultBlock(out: ToolOutput): ContentBlockParam {
        val content = out.parts.map {
            when (it) {
                is Part.Text -> ToolResultBlockParam.Content.Block.ofText(TextBlockParam.builder().text(it.text).build())
                is Part.Image -> ToolResultBlockParam.Content.Block.ofImage(image(it))
            }
        }
        return ContentBlockParam.ofToolResult(
            ToolResultBlockParam.builder()
                .toolUseId(out.callId)
                .contentOfBlocks(content)
                .isError(out.isError)
                .build()
        )
    }

    private fun toTool(spec: ToolSpec): Tool {
        val props = spec.schema["properties"]?.jsonObject ?: JsonObject(emptyMap())
        val required = (spec.schema["required"] as? JsonArray)?.map { (it as JsonPrimitive).content } ?: emptyList()
        return Tool.builder()
            .name(spec.name)
            .description(spec.description)
            .inputSchema(
                Tool.InputSchema.builder()
                    .properties(
                        Tool.InputSchema.Properties.builder()
                            .apply { props.forEach { (k, v) -> putAdditionalProperty(k, JsonValue.from(plain(v))) } }
                            .build()
                    )
                    .required(required)
                    .build()
            )
            .eagerInputStreaming(true)
            .build()
    }

    private fun wrap(e: Throwable): Exception = when (e) {
        is ModelError -> e
        is AnthropicServiceException -> {
            val body = runCatching { jsonMapper().writeValueAsString(e.body()) }.getOrNull()
            val type = body?.let { Regex(""""type"\s*:\s*"([a-z_]+_error)"""").find(it)?.groupValues?.get(1) }
            ModelError(e.statusCode(), type, e.message ?: "HTTP ${e.statusCode()}", e)
        }
        is AnthropicIoException -> ModelError(null, "network", e.message ?: "network error", e)
        else -> ModelError(null, null, e.message ?: e.toString(), e)
    }

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        fun parseObject(raw: String): JsonObject? =
            runCatching { json.parseToJsonElement(raw) as? JsonObject }.getOrNull()

        /** kotlinx JSON → Java 普通对象，给 SDK 的 JsonValue.from 用 */
        fun plain(e: JsonElement): Any? = when (e) {
            is JsonNull -> null
            is JsonObject -> e.mapValues { plain(it.value) }
            is JsonArray -> e.map(::plain)
            is JsonPrimitive -> when {
                e.isString -> e.content
                e.booleanOrNull != null -> e.booleanOrNull
                e.longOrNull != null -> e.longOrNull
                else -> e.doubleOrNull
            }
        }

        fun proxyOf(url: String): Proxy? {
            if (url.isBlank()) return null
            val u = URI(if ("://" in url) url else "http://$url")
            val type = if (u.scheme.startsWith("socks")) Proxy.Type.SOCKS else Proxy.Type.HTTP
            return Proxy(type, InetSocketAddress.createUnresolved(u.host, if (u.port > 0) u.port else 80))
        }
    }
}
