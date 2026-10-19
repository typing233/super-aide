package io.github.typing233.superaide.core.llm

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.add
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSource
import java.io.IOException
import java.util.Base64
import java.util.concurrent.TimeUnit
import kotlin.coroutines.cancellation.CancellationException

/**
 * OpenAI 兼容服务（官方、DeepSeek、各种中转站），Responses 或 Chat Completions 协议。
 * 自己写而不用 SDK：中转站各有出入（reasoning_content、不认的参数、usage 要单独要）。
 * 工具结果里的图片统一放进紧跟着的一条用户消息，两种协议都认。
 */
class OpenAiChat(
    private val service: Service,
    private val key: String,
    model: String,
    private var effort: Effort,
    private val system: String,
    private val tools: List<ToolSpec>,
    /** 模型收不收图片（DeepSeek 不收） */
    private val vision: Boolean = true,
    http: OkHttpClient = defaultHttp,
) : Chat {
    override var model: String = model
        private set

    private val http = http.newBuilder()
        .apply { AnthropicChat.proxyOf(service.proxy)?.let { proxy(it) } }
        .build()
    private val base = service.baseUrl.trimEnd('/').let { if (Regex("""/v\d+$""").containsMatchIn(it)) it else "$it/v1" }
    private val history = mutableListOf<JsonObject>()

    override fun switchModel(model: String, effort: Effort) {
        this.model = model
        this.effort = effort
    }

    override suspend fun send(input: TurnInput, onDelta: (Delta) -> Unit): Turn {
        val responses = service.wire == Wire.OPENAI_RESPONSES
        when (input) {
            is TurnInput.User -> history += userItem(input.parts, responses)
            is TurnInput.Results -> {
                val images = mutableListOf<Part>()
                for (out in input.outputs) {
                    val text = out.parts.filterIsInstance<Part.Text>().joinToString("\n") { it.text }
                        .let { if (out.isError) "错误：$it" else it }
                    images += out.parts.filterIsInstance<Part.Image>()
                    history += if (responses) buildJsonObject {
                        put("type", "function_call_output"); put("call_id", out.callId); put("output", text)
                    } else buildJsonObject {
                        put("role", "tool"); put("tool_call_id", out.callId); put("content", text)
                    }
                }
                val extra = input.extra + images
                if (extra.isNotEmpty()) history += userItem(listOf(Part.Text("（上面工具返回的图片）")) + extra, responses)
            }
        }
        return if (responses) responsesTurn(onDelta) else chatTurn(onDelta)
    }

    // ---------------- Responses ----------------

    private suspend fun responsesTurn(onDelta: (Delta) -> Unit): Turn {
        val body = buildJsonObject {
            put("model", model)
            put("instructions", system)
            put("input", JsonArray(history))
            if (tools.isNotEmpty()) putJsonArray("tools") {
                tools.forEach { t ->
                    addJsonObject {
                        put("type", "function"); put("name", t.name)
                        put("description", t.description); put("parameters", t.schema)
                    }
                }
            }
            put("stream", true)
            put("store", false)
            putJsonArray("include") { add("reasoning.encrypted_content") }
            putJsonObject("reasoning") { put("effort", responsesEffort(effort)) }
        }
        var completed: JsonObject? = null
        stream("$base/responses", body) { data ->
            val type = data["type"]?.jsonPrimitive?.contentOrNull
            when (type) {
                "response.output_text.delta" -> data.str("delta")?.let { onDelta(Delta.Text(it)) }
                "response.output_item.added" -> {
                    val item = data["item"]?.jsonObject
                    when (item?.str("type")) {
                        "function_call" -> onDelta(Delta.ToolStart(item.str("name").orEmpty()))
                        "reasoning" -> onDelta(Delta.Thinking)
                    }
                }
                "response.completed", "response.incomplete" -> completed = data["response"]?.jsonObject
                "response.failed" -> {
                    val err = data["response"]?.jsonObject?.get("error")?.jsonObject
                    throw ModelError(null, err?.str("code"), err?.str("message") ?: "response.failed")
                }
                "error" -> throw ModelError(null, data.str("code") ?: data.str("type"), data.str("message") ?: data.toString())
            }
        }
        val response = completed ?: throw ModelError(null, "stream", "流提前结束了，没有收到完整回答")
        val output = response["output"]?.jsonArray.orEmpty().map { it.jsonObject }
        // 原样追加（去掉 id：store=false 时服务端没有这些条目）
        output.forEach { item -> history += JsonObject(item - "id") }

        val text = StringBuilder()
        val calls = mutableListOf<ToolCall>()
        for (item in output) when (item.str("type")) {
            "message" -> item["content"]?.jsonArray?.forEach { c ->
                if (c.jsonObject.str("type") == "output_text") text.append(c.jsonObject.str("text").orEmpty())
            }
            "function_call" -> {
                val raw = item.str("arguments").orEmpty()
                calls += ToolCall(item.str("call_id").orEmpty(), item.str("name").orEmpty(), AnthropicChat.parseObject(raw), raw)
            }
        }
        val usage = response["usage"]?.jsonObject
        val incomplete = response.str("status") == "incomplete"
        return Turn(
            text = text.toString(),
            calls = calls,
            stop = when {
                calls.isNotEmpty() -> Stop.TOOL_USE
                incomplete -> Stop.MAX_TOKENS
                else -> Stop.END
            },
            usage = Usage(
                input = usage.long("input_tokens"),
                output = usage.long("output_tokens"),
                cacheRead = usage?.get("input_tokens_details")?.jsonObject.long("cached_tokens"),
            ),
            model = response.str("model") ?: model,
        )
    }

    // ---------------- Chat Completions ----------------

    private suspend fun chatTurn(onDelta: (Delta) -> Unit): Turn {
        val body = buildJsonObject {
            put("model", model)
            putJsonArray("messages") {
                addJsonObject { put("role", "system"); put("content", system) }
                history.forEach { add(it) }
            }
            if (tools.isNotEmpty()) putJsonArray("tools") {
                tools.forEach { t ->
                    addJsonObject {
                        put("type", "function")
                        putJsonObject("function") {
                            put("name", t.name); put("description", t.description); put("parameters", t.schema)
                        }
                    }
                }
            }
            put("stream", true)
            putJsonObject("stream_options") { put("include_usage", true) }
            put("reasoning_effort", chatEffort(effort))
        }
        val text = StringBuilder()
        val reasoning = StringBuilder()
        val calls = sortedMapOf<Int, Triple<StringBuilder, StringBuilder, StringBuilder>>() // id, name, args
        var finish: String? = null
        var usage: JsonObject? = null
        var answered: String? = null
        var thinking = false
        stream("$base/chat/completions", body) { data ->
            data["error"]?.jsonObject?.let { throw ModelError(null, it.str("code") ?: it.str("type"), it.str("message") ?: it.toString()) }
            data.str("model")?.let { answered = it }
            (data["usage"] as? JsonObject)?.let { usage = it }
            val choice = data["choices"]?.jsonArray?.firstOrNull()?.jsonObject ?: return@stream
            choice.str("finish_reason")?.let { finish = it }
            val delta = choice["delta"]?.jsonObject ?: return@stream
            delta.str("reasoning_content")?.let {
                reasoning.append(it)
                if (!thinking) { thinking = true; onDelta(Delta.Thinking) }
            }
            delta.str("content")?.let { if (it.isNotEmpty()) { text.append(it); onDelta(Delta.Text(it)) } }
            delta["tool_calls"]?.jsonArray?.forEach { tc ->
                val o = tc.jsonObject
                val index = o["index"]?.jsonPrimitive?.int ?: calls.size
                val slot = calls.getOrPut(index) { Triple(StringBuilder(), StringBuilder(), StringBuilder()) }
                o.str("id")?.let { slot.first.append(it) }
                o["function"]?.jsonObject?.let { f ->
                    f.str("name")?.let { if (slot.second.isEmpty()) onDelta(Delta.ToolStart(it)); slot.second.append(it) }
                    f.str("arguments")?.let { slot.third.append(it) }
                }
            }
        }
        val toolCalls = calls.values.map { (id, name, args) ->
            ToolCall(id.toString(), name.toString(), AnthropicChat.parseObject(args.toString().ifBlank { "{}" }), args.toString())
        }
        history += buildJsonObject {
            put("role", "assistant")
            put("content", text.toString())
            if (reasoning.isNotEmpty()) put("reasoning_content", reasoning.toString())
            if (toolCalls.isNotEmpty()) putJsonArray("tool_calls") {
                toolCalls.forEach { c ->
                    addJsonObject {
                        put("id", c.id); put("type", "function")
                        putJsonObject("function") { put("name", c.name); put("arguments", c.raw.ifBlank { "{}" }) }
                    }
                }
            }
        }
        return Turn(
            text = text.toString(),
            calls = toolCalls,
            stop = when (finish) {
                "tool_calls" -> Stop.TOOL_USE
                "length" -> Stop.MAX_TOKENS
                "content_filter" -> Stop.REFUSAL
                else -> if (toolCalls.isNotEmpty()) Stop.TOOL_USE else Stop.END
            },
            usage = Usage(
                input = usage.long("prompt_tokens"),
                output = usage.long("completion_tokens"),
                cacheRead = usage?.get("prompt_tokens_details")?.jsonObject.long("cached_tokens")
                    .takeIf { it > 0 } ?: usage.long("prompt_cache_hit_tokens"),
            ),
            model = answered ?: model,
        )
    }

    // ---------------- 公共 ----------------

    private fun userItem(parts: List<Part>, responses: Boolean): JsonObject = buildJsonObject {
        put("role", "user")
        putJsonArray("content") {
            for (p in parts) when (p) {
                is Part.Text -> addJsonObject { put("type", if (responses) "input_text" else "text"); put("text", p.text) }
                is Part.Image -> if (vision) addJsonObject {
                    val url = "data:${p.mediaType};base64," + Base64.getEncoder().encodeToString(p.bytes)
                    if (responses) { put("type", "input_image"); put("image_url", url) }
                    else { put("type", "image_url"); putJsonObject("image_url") { put("url", url) } }
                } else addJsonObject {
                    put("type", if (responses) "input_text" else "text"); put("text", "（截图略：这个模型不收图片）")
                }
            }
        }
    }

    /** 发请求并逐条处理 SSE 的 data；协程取消时掐断连接。 */
    private suspend fun stream(url: String, body: JsonObject, onData: (JsonObject) -> Unit) = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(url)
            .header("Authorization", "Bearer $key")
            .header("Accept", "text/event-stream")
            .post(body.toString().toRequestBody(JSON))
            .build()
        val call = http.newCall(request)
        val job = currentCoroutineContext()[Job]
        val handle = job?.invokeOnCompletion { call.cancel() }
        try {
            call.execute().use { response ->
                if (!response.isSuccessful) throw errorOf(response.code, response.body.string())
                readSse(response.body.source()) { data ->
                    if (data == "[DONE]") return@readSse false
                    val obj = runCatching { json.parseToJsonElement(data).jsonObject }.getOrNull() ?: return@readSse true
                    onData(obj)
                    true
                }
            }
        } catch (e: IOException) {
            currentCoroutineContext().ensureActive()
            throw ModelError(null, "network", e.message ?: e.toString(), e)
        } finally {
            handle?.dispose()
        }
    }

    companion object {
        private val JSON = "application/json".toMediaType()
        private val json = Json { ignoreUnknownKeys = true }

        val defaultHttp: OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(5, TimeUnit.MINUTES)
            .build()

        fun responsesEffort(e: Effort) = when (e) { Effort.MAX -> "xhigh"; else -> e.wire }
        fun chatEffort(e: Effort) = when (e) { Effort.XHIGH, Effort.MAX -> "high"; else -> e.wire }

        /** 错误体通常是 {"error": {"message", "type", "code"}}，中转站也可能只给一段文字 */
        fun errorOf(status: Int, body: String): ModelError {
            val err = runCatching { json.parseToJsonElement(body).jsonObject["error"] }.getOrNull()
            return when (err) {
                is JsonObject -> ModelError(status, err.str("code") ?: err.str("type"), err.str("message") ?: body.take(500))
                is JsonPrimitive -> ModelError(status, null, err.content)
                else -> ModelError(status, null, body.take(500).ifBlank { "HTTP $status" })
            }
        }

        /** 最小的 SSE 解析：多行 data 用换行拼起来，空行分隔事件。onData 返回 false 就停。 */
        fun readSse(source: BufferedSource, onData: (String) -> Boolean) {
            val data = StringBuilder()
            while (true) {
                val line = source.readUtf8Line() ?: break
                if (line.isEmpty()) {
                    if (data.isNotEmpty()) {
                        val keepGoing = onData(data.toString())
                        data.setLength(0)
                        if (!keepGoing) return
                    }
                    continue
                }
                if (line.startsWith("data:")) {
                    if (data.isNotEmpty()) data.append('\n')
                    data.append(line.removePrefix("data:").removePrefix(" "))
                }
            }
            if (data.isNotEmpty()) onData(data.toString())
        }

        private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.contentOrNull
        private fun JsonObject?.long(key: String): Long = (this?.get(key) as? JsonPrimitive)?.longOrNull ?: 0
    }
}

private fun JsonArray?.orEmpty(): List<JsonElement> = this ?: emptyList()
