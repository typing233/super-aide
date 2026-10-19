package io.github.typing233.superaide.core.llm

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assume.assumeTrue
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * 真实服务的冒烟测试：一轮工具调用 + 回传结果。只在设了 AIDE_LIVE=1 时跑（scripts/android/live_probe.py 会设）。
 * 地址和 key 从环境变量读，不进代码。
 */
class LiveProbeTest {
    private val env = System.getenv()
    private val tool = ToolSpec(
        name = "get_time",
        description = "Returns the current time in a city.",
        schema = Json.parseToJsonElement(
            """{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}"""
        ).jsonObject,
    )
    private val system = "You are a test assistant. Use tools when asked. Answer in one short sentence."

    private fun roundTrip(chat: Chat) = runBlocking {
        val deltas = StringBuilder()
        val first = chat.send(TurnInput.User(listOf(Part.Text("What time is it in Paris? Use the tool.")))) {
            if (it is Delta.Text) deltas.append(it.text)
        }
        println("[${chat.model}] first: stop=${first.stop} calls=${first.calls} usage=${first.usage} model=${first.model}")
        assertEquals(Stop.TOOL_USE, first.stop)
        val call = first.calls.single()
        assertEquals("get_time", call.name)
        val second = chat.send(TurnInput.Results(listOf(ToolOutput(call.id, listOf(Part.Text("14:05")))))) {
            if (it is Delta.Text) deltas.append(it.text)
        }
        println("[${chat.model}] second: stop=${second.stop} text=${second.text} usage=${second.usage}")
        assertEquals(Stop.END, second.stop)
        assertTrue(Regex("""(14|2)[:：.]05""").containsMatchIn(second.text), second.text)
        assertTrue(second.text in deltas.toString())
    }

    @Test fun anthropic() {
        assumeTrue(env["AIDE_LIVE"] == "1" && env["AIDE_ANTHROPIC_BASE"] != null)
        val service = Service("a", "a", Wire.ANTHROPIC, env["AIDE_ANTHROPIC_BASE"]!!, bearer = true)
        roundTrip(AnthropicChat(service, env["AIDE_ANTHROPIC_KEY"]!!, env["AIDE_ANTHROPIC_MODEL"] ?: "claude-haiku-5-5", Effort.LOW, system, listOf(tool)))
    }

    @Test fun responses() {
        assumeTrue(env["AIDE_LIVE"] == "1" && env["AIDE_OPENAI_BASE"] != null)
        val service = Service("o", "o", Wire.OPENAI_RESPONSES, env["AIDE_OPENAI_BASE"]!!)
        roundTrip(OpenAiChat(service, env["AIDE_OPENAI_KEY"]!!, env["AIDE_OPENAI_MODEL"] ?: "gpt-6-luna", Effort.LOW, system, listOf(tool)))
    }

    @Test fun chatCompletions() {
        assumeTrue(env["AIDE_LIVE"] == "1" && env["AIDE_OPENAI_BASE"] != null)
        val service = Service("c", "c", Wire.OPENAI_CHAT, env["AIDE_OPENAI_BASE"]!!)
        roundTrip(OpenAiChat(service, env["AIDE_OPENAI_KEY"]!!, env["AIDE_CHAT_MODEL"] ?: "gpt-6-luna", Effort.LOW, system, listOf(tool)))
    }
}
