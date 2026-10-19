package io.github.typing233.superaide.core.agent

import io.github.typing233.superaide.core.events.Event
import io.github.typing233.superaide.core.llm.Chat
import io.github.typing233.superaide.core.llm.Delta
import io.github.typing233.superaide.core.llm.Effort
import io.github.typing233.superaide.core.llm.Part
import io.github.typing233.superaide.core.llm.Stop
import io.github.typing233.superaide.core.llm.ToolCall
import io.github.typing233.superaide.core.llm.ToolOutput
import io.github.typing233.superaide.core.llm.Turn
import io.github.typing233.superaide.core.llm.TurnInput
import io.github.typing233.superaide.core.llm.Usage
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** 按剧本回答的假模型：记下每次收到的输入。 */
class FakeChat(private val script: MutableList<(TurnInput, (Delta) -> Unit) -> Turn>) : Chat {
    override var model = "fake-1"
    val inputs = mutableListOf<TurnInput>()
    override suspend fun send(input: TurnInput, onDelta: (Delta) -> Unit): Turn {
        inputs += input
        return script.removeAt(0)(input, onDelta)
    }
    override fun switchModel(model: String, effort: Effort) { this.model = model }
}

fun call(id: String, name: String = "observe_screen") = ToolCall(id, name, JsonObject(mapOf("screenshot" to JsonPrimitive(false))), "{}")
fun toolTurn(vararg calls: ToolCall) = Turn("", calls.toList(), Stop.TOOL_USE, Usage(10, 5), "fake-1")
fun answer(text: String): (TurnInput, (Delta) -> Unit) -> Turn = { _, d -> d(Delta.Text(text)); Turn(text, emptyList(), Stop.END, Usage(10, 5), "fake-1") }

class AgentTest {
    private class Host(val onRun: (ToolCall) -> Unit = {}) : ToolHost {
        val ran = mutableListOf<String>()
        override suspend fun run(call: ToolCall, mode: Mode): ToolOutput {
            ran += call.id
            onRun(call)
            return ToolOutput(call.id, listOf(Part.Text("ok ${call.id}")))
        }
    }

    @Test fun toolLoopThenAnswer() = runTest {
        val chat = FakeChat(mutableListOf(
            { _, d -> d(Delta.Text("我先看看")); d(Delta.ToolStart("observe_screen")); toolTurn(call("t1")) },
            answer("这是设置页。"),
        ))
        val events = mutableListOf<Event>()
        val host = Host()
        val r = Agent(chat, host, Mode.ASK, { events += it }).turn(listOf(Part.Text("这是什么")))
        assertTrue(r.ok)
        assertEquals("这是设置页。", r.answer)
        assertEquals(1, r.tools)
        assertEquals(listOf("t1"), host.ran)
        assertEquals(Usage(20, 10), r.usage)
        assertTrue(events.any { it.type == "retract" })
        assertTrue(events.any { it.type == "status" && it.data["tool"] == "observe_screen" })
        val results = chat.inputs[1] as TurnInput.Results
        assertEquals("t1", results.outputs.single().callId)
    }

    @Test fun stopClosesPendingCallsOnNextTurn() = runTest {
        lateinit var agent: Agent
        val host = Host { if (it.id == "a") agent.stopped = true }
        val chat = FakeChat(mutableListOf(
            { _, _ -> toolTurn(call("a"), call("b")) },
            answer("好的，停了。"),
        ))
        agent = Agent(chat, host, Mode.ACT, {})
        val first = agent.turn(listOf(Part.Text("帮我打开设置")))
        assertTrue(first.stopped)
        assertEquals(listOf("a"), host.ran) // b 没执行
        val second = agent.turn(listOf(Part.Text("算了")))
        assertTrue(second.ok)
        val input = chat.inputs[1] as TurnInput.Results
        assertEquals(listOf("a", "b"), input.outputs.map { it.callId })
        assertTrue(!input.outputs[0].isError && input.outputs[1].isError)
        assertEquals("算了", (input.extra.single() as Part.Text).text)
    }

    @Test fun actReportsFailureFirstLine() = runTest {
        val chat = FakeChat(mutableListOf(answer("没完成：需要指纹验证\n已停在付款页。")))
        val r = Agent(chat, Host(), Mode.ACT, {}).turn(listOf(Part.Text("付款")))
        assertEquals("没完成：需要指纹验证", r.reported)
    }

    @Test fun badToolJsonGetsErrorResultWithoutRunning() = runTest {
        val host = Host()
        val chat = FakeChat(mutableListOf(
            { _, _ -> Turn("", listOf(ToolCall("x", "act", null, "{\"actions\": [")), Stop.TOOL_USE, Usage(), "fake-1") },
            answer("重试后完成"),
        ))
        Agent(chat, host, Mode.ACT, {}).turn(listOf(Part.Text("做")))
        assertTrue(host.ran.isEmpty())
        assertTrue((chat.inputs[1] as TurnInput.Results).outputs.single().isError)
    }
}
