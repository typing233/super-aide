package io.github.typing233.superaide.core.agent

import io.github.typing233.superaide.core.llm.Part
import io.github.typing233.superaide.core.llm.ToolCall
import io.github.typing233.superaide.core.llm.ToolOutput
import io.github.typing233.superaide.core.llm.TurnInput
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ParallelToolsTest {
    private fun named(id: String, name: String) = ToolCall(id, name, JsonObject(emptyMap()), "{}")

    @Test fun webCallsRunTogetherScreenCallsInOrder() = runTest {
        val bothStarted = CompletableDeferred<Unit>()
        val started = mutableListOf<String>()
        val host = object : ToolHost {
            override suspend fun run(call: ToolCall, mode: Mode): ToolOutput {
                started += call.id
                if (call.name == "web_fetch") {
                    if (started.count { it.startsWith("w") } == 2) bothStarted.complete(Unit)
                    // 两个 web_fetch 要同时在跑，不然这里会一直等
                    withTimeout(5_000) { bothStarted.await() }
                }
                return ToolOutput(call.id, listOf(Part.Text("ok ${call.id}")))
            }
        }
        val chat = FakeChat(mutableListOf(
            { _, _ -> toolTurn(named("w1", "web_fetch"), named("w2", "web_fetch"), named("s1", "observe_screen"), named("w3", "web_search")) },
            answer("好了"),
        ))
        val r = Agent(chat, host, Mode.ASK, {}).turn(listOf(Part.Text("查一下")))
        assertTrue(r.ok)
        assertEquals(4, r.tools)
        assertEquals(listOf("w1", "w2", "s1", "w3"), started.take(2).sorted() + started.drop(2))
        // 交回去的结果顺序和调用顺序一样
        val results = chat.inputs[1] as TurnInput.Results
        assertEquals(listOf("w1", "w2", "s1", "w3"), results.outputs.map { it.callId })
    }

    @Test fun bothModesHaveWorkTools() {
        for (m in Mode.entries) {
            val names = Tools.forMode(m).map { it.name }
            assertTrue(names.containsAll(listOf("web_search", "web_fetch", "files", "read_file", "write_file", "run_js")), "$m: $names")
        }
        assertTrue("act" !in Tools.forMode(Mode.ASK).map { it.name })
    }
}
