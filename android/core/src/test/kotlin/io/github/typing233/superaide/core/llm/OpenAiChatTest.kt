package io.github.typing233.superaide.core.llm

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Before
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** 用录好的 SSE 流回放两种 OpenAI 兼容协议（不连网）。 */
class OpenAiChatTest {
    private val server = MockWebServer()
    private val tool = ToolSpec("get_time", "time", Json.parseToJsonElement("""{"type":"object","properties":{}}""").jsonObject)

    @Before fun start() = server.start()
    @After fun stop() = server.close()

    private fun sse(vararg events: String) = MockResponse.Builder()
        .addHeader("Content-Type", "text/event-stream")
        .body(events.joinToString("") { "data: $it\n\n" })
        .build()

    private fun chat(wire: Wire, vision: Boolean = true) =
        OpenAiChat(Service("s", "s", wire, server.url("/v1").toString()), "k", "m1", Effort.MAX, "sys", listOf(tool), vision)

    @Test fun responsesToolCallThenAnswer() = runTest {
        server.enqueue(sse(
            """{"type":"response.output_item.added","item":{"type":"reasoning"}}""",
            """{"type":"response.output_item.added","item":{"type":"function_call","name":"get_time"}}""",
            """{"type":"response.completed","response":{"model":"m1-2026","status":"completed","output":[
                {"id":"rs_1","type":"reasoning","encrypted_content":"xyz"},
                {"id":"fc_1","type":"function_call","call_id":"call_1","name":"get_time","arguments":"{}"}],
                "usage":{"input_tokens":30,"output_tokens":4,"input_tokens_details":{"cached_tokens":10}}}}""".replace("\n", ""),
        ))
        server.enqueue(sse(
            """{"type":"response.output_text.delta","delta":"现在 "}""",
            """{"type":"response.output_text.delta","delta":"14:05"}""",
            """{"type":"response.completed","response":{"model":"m1-2026","status":"completed","output":[
                {"id":"msg_1","type":"message","content":[{"type":"output_text","text":"现在 14:05"}]}],
                "usage":{"input_tokens":40,"output_tokens":3}}}""".replace("\n", ""),
        ))
        val c = chat(Wire.OPENAI_RESPONSES)
        val deltas = mutableListOf<Delta>()
        val first = c.send(TurnInput.User(listOf(Part.Image(byteArrayOf(1, 2)), Part.Text("几点")))) { deltas += it }
        assertEquals(Stop.TOOL_USE, first.stop)
        assertEquals("call_1", first.calls.single().id)
        assertEquals(Usage(30, 4, 10), first.usage)
        assertEquals("m1-2026", first.model)
        assertTrue(deltas.contains(Delta.Thinking) && deltas.contains(Delta.ToolStart("get_time")))
        val second = c.send(TurnInput.Results(listOf(ToolOutput("call_1", listOf(Part.Text("14:05"), Part.Image(byteArrayOf(3))))))) {}
        assertEquals("现在 14:05", second.text)
        assertEquals(Stop.END, second.stop)

        val req1 = Json.parseToJsonElement(server.takeRequest().body!!.utf8()).jsonObject
        assertEquals("xhigh", req1["reasoning"]!!.jsonObject["effort"]!!.jsonPrimitive.content)
        assertEquals(false, req1["store"]!!.jsonPrimitive.content.toBoolean())
        val req2 = Json.parseToJsonElement(server.takeRequest().body!!.utf8()).jsonObject
        val input = req2["input"]!!.jsonArray.map { it.jsonObject }
        // 原样追加模型的输出（去掉 id），工具结果之后跟一条带图片的用户消息
        assertEquals(listOf("user", "reasoning", "function_call", "function_call_output", "user"),
            input.map { it["type"]?.jsonPrimitive?.content ?: it["role"]!!.jsonPrimitive.content })
        assertFalse(input.any { "id" in it })
        assertEquals("xyz", input[1]["encrypted_content"]!!.jsonPrimitive.content)
    }

    @Test fun chatCompletionsAccumulatesToolCallsAndReasoning() = runTest {
        server.enqueue(sse(
            """{"model":"m1","choices":[{"delta":{"reasoning_content":"想一想"}}]}""",
            """{"model":"m1","choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"get_time","arguments":"{\"ci"}}]}}]}""",
            """{"model":"m1","choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"ty\":\"x\"}"}}]},"finish_reason":"tool_calls"}]}""",
            """{"model":"m1","choices":[],"usage":{"prompt_tokens":12,"completion_tokens":7,"prompt_cache_hit_tokens":5}}""",
            "[DONE]",
        ))
        server.enqueue(sse("""{"model":"m1","choices":[{"delta":{"content":"好"},"finish_reason":"stop"}]}""", "[DONE]"))
        val c = chat(Wire.OPENAI_CHAT, vision = false)
        val first = c.send(TurnInput.User(listOf(Part.Image(byteArrayOf(1)), Part.Text("几点")))) {}
        assertEquals("""{"city":"x"}""", first.calls.single().raw)
        assertEquals(Usage(12, 7, 5), first.usage)
        c.send(TurnInput.Results(listOf(ToolOutput("c1", listOf(Part.Text("14:05")))))) {}
        server.takeRequest()
        val req2 = Json.parseToJsonElement(server.takeRequest().body!!.utf8()).jsonObject
        val msgs = req2["messages"]!!.jsonArray.map { it.jsonObject }
        assertEquals(listOf("system", "user", "assistant", "tool"), msgs.map { it["role"]!!.jsonPrimitive.content })
        assertEquals("想一想", msgs[2]["reasoning_content"]!!.jsonPrimitive.content)
        // 不收图片的模型：图片换成文字说明
        assertTrue("截图略" in msgs[1].toString())
        assertEquals("high", req2["reasoning_effort"]!!.jsonPrimitive.content)
    }

    @Test fun httpErrorBecomesModelError() = runTest {
        server.enqueue(MockResponse.Builder().code(404).body("""{"error":{"message":"model not found","code":"model_not_found"}}""").build())
        val e = assertFailsWith<ModelError> { chat(Wire.OPENAI_CHAT).send(TurnInput.User(listOf(Part.Text("hi")))) {} }
        assertEquals(404, e.status)
        assertEquals("model_not_found", e.type)
    }

    @Test fun modelThatRejectsImagesIsRetriedWithoutThemAndRemembered() = runTest {
        server.enqueue(MockResponse.Builder().code(400)
            .body("""{"error":{"message":"unknown variant `image_url`, expected `text`","type":"invalid_request_error"}}""").build())
        server.enqueue(sse("""{"model":"m1","choices":[{"delta":{"content":"好"},"finish_reason":"stop"}]}""", "[DONE]"))
        val noted = mutableListOf<String>()
        Chats.onNoVision = { service, model -> noted += "$service/$model" }
        try {
            val r = chat(Wire.OPENAI_CHAT).send(TurnInput.User(listOf(Part.Image(byteArrayOf(1)), Part.Text("这是什么")))) {}
            assertEquals("好", r.text)
        } finally {
            Chats.onNoVision = null
        }
        assertEquals(listOf("s/m1"), noted)
        assertTrue("image_url" in server.takeRequest().body!!.utf8())
        val retried = server.takeRequest().body!!.utf8()
        assertFalse("image_url" in retried)
        assertTrue("截图略" in retried)
    }

    @Test fun otherBadRequestsAreNotRetried() = runTest {
        server.enqueue(MockResponse.Builder().code(400).body("""{"error":{"message":"max_tokens too large"}}""").build())
        assertFailsWith<ModelError> { chat(Wire.OPENAI_CHAT).send(TurnInput.User(listOf(Part.Image(byteArrayOf(1)), Part.Text("hi")))) {} }
        assertEquals(1, server.requestCount)
    }

    @Test fun bareDomainGetsHttps() {
        assertEquals("https://api.example.com/v1", Service("s", "s", Wire.OPENAI_CHAT, " api.example.com/v1 ").url)
        assertEquals("http://127.0.0.1:8080", Service("s", "s", Wire.OPENAI_CHAT, "http://127.0.0.1:8080").url)
    }

    @Test fun streamErrorEventBecomesModelError() = runTest {
        server.enqueue(sse("""{"type":"error","code":"overloaded","message":"busy"}"""))
        val e = assertFailsWith<ModelError> { chat(Wire.OPENAI_RESPONSES).send(TurnInput.User(listOf(Part.Text("hi")))) {} }
        assertEquals("overloaded", e.type)
    }
}
