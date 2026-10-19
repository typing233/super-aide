package io.github.typing233.superaide.core.session

import io.github.typing233.superaide.core.agent.FakeChat
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.agent.ToolHost
import io.github.typing233.superaide.core.agent.answer
import io.github.typing233.superaide.core.config.ModelEntry
import io.github.typing233.superaide.core.events.Event
import io.github.typing233.superaide.core.llm.Effort
import io.github.typing233.superaide.core.llm.Failure
import io.github.typing233.superaide.core.llm.ModelError
import io.github.typing233.superaide.core.llm.Part
import io.github.typing233.superaide.core.llm.Service
import io.github.typing233.superaide.core.llm.ToolCall
import io.github.typing233.superaide.core.llm.ToolOutput
import io.github.typing233.superaide.core.llm.TurnInput
import io.github.typing233.superaide.core.llm.Wire
import kotlinx.coroutines.test.runTest
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class SessionTest {
    private val claude = Service("claude", "Claude", Wire.ANTHROPIC, "https://x")
    private val openai = Service("openai", "OpenAI", Wire.OPENAI_RESPONSES, "https://y")
    private val choices = listOf(
        Choice(claude, "k", ModelEntry("claude", "opus"), Effort.MEDIUM),
        Choice(openai, "k", ModelEntry("openai", "astra"), Effort.MEDIUM),
        Choice(openai, "k", ModelEntry("openai", "luna"), Effort.MEDIUM),
    )
    private val noTools = object : ToolHost {
        override suspend fun run(call: ToolCall, mode: Mode) = ToolOutput(call.id, listOf(Part.Text("ok")))
    }

    private fun failing(e: ModelError) = FakeChat(mutableListOf({ _, _ -> throw e }))

    @Test fun handsOverOnModelUnavailableAndHoldsErrorsBack() = runTest {
        val events = mutableListOf<Event>()
        val sidelined = mutableListOf<Pair<String, Failure.Kind>>()
        val chats = ArrayDeque(listOf(
            failing(ModelError(404, "not_found_error", "model: opus not found")),
            FakeChat(mutableListOf(answer("答案"))),
        ))
        val opened = mutableListOf<String>()
        val s = Session(Mode.ASK, noTools, pick = { ex -> choices.filter { it.model.id !in ex } },
            sideline = { c, k -> sidelined += c.model.id to k }, emit = { events += it },
            open = { c, _, _ -> opened += c.model.id; chats.removeFirst() })
        val r = s.ask("这是什么", "环境", emptyList())
        assertTrue(r.ok)
        assertEquals(listOf("opus", "astra"), opened)
        assertEquals(listOf("opus" to Failure.Kind.MODEL), sidelined)
        assertFalse(events.any { it.type == "error" }, "换成功了就不显示错误")
        assertTrue(events.any { it.type == "status" && "换 astra 接着答" in it.text })
        assertEquals(true, events.last { it.type == "done" }.data["ok"])
        assertEquals("astra", s.choice?.model?.id)
    }

    @Test fun relayUnknownProviderCountsAsModelUnavailable() {
        // 中转站对不认识的模型回 400（2026-10-19 实测）
        val e = ModelError(400, "invalid_request_error", "400: {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"unknown provider for model claude-opus-9-9\"}}")
        assertEquals(Failure.Kind.MODEL, Failure.kind(e))
        assertEquals(Failure.Kind.NONE, Failure.kind(ModelError(400, "invalid_request_error", "messages: text content blocks must be non-empty")))
    }

    @Test fun badRequestIsNotHandedOver() = runTest {
        val events = mutableListOf<Event>()
        val s = Session(Mode.ASK, noTools, pick = { ex -> choices.filter { it.model.id !in ex } }, sideline = { _, _ -> error("不该拉黑") },
            emit = { events += it }, open = { _, _, _ -> failing(ModelError(400, "invalid_request_error", "messages: bad")) })
        val r = s.ask("问", "环境", emptyList())
        assertFalse(r.ok)
        assertEquals(1, events.count { it.type == "error" })
        assertEquals(false, events.last().data["ok"])
    }

    @Test fun givesUpAfterTwoHandovers() = runTest {
        val s = Session(Mode.ASK, noTools, pick = { ex -> choices.filter { it.model.id !in ex } }, sideline = { _, _ -> },
            emit = {}, open = { _, _, _ -> failing(ModelError(529, "overloaded_error", "Overloaded")) })
        assertFalse(s.ask("问", "环境", emptyList()).ok)
        assertEquals(1, s.records.size)
    }

    @Test fun followupKeepsModelAndUsesFollowupPrompt() = runTest {
        val chat = FakeChat(mutableListOf(answer("一"), answer("二")))
        val s = Session(Mode.ASK, noTools, pick = { choices }, sideline = { _, _ -> }, emit = {}, open = { _, _, _ -> chat })
        s.ask("第一问", "环境1", emptyList())
        s.ask("第二问", "环境2", emptyList())
        val second = ((chat.inputs[1] as TurnInput.User).parts.last() as Part.Text).text
        assertTrue("【追问】\n第二问" in second)
        assertEquals(2, s.records.size)
    }

    @Test fun cardStateFollowsEvents() {
        var c = CardState(Mode.ASK).next("怎么关掉自动更新？")
        for (e in listOf(
            Event.route("Claude", "opus", "medium", ""),
            Event.status("正在思考…", transient = true),
            Event.newMessage, Event.delta("我先看看"), Event.retract,
            Event.status("正在看屏幕…", tool = "observe_screen"),
            Event.newMessage, Event.delta("1. 打开设置\n2. 关掉"), Event.delta("\n\n点「让我来做」，我直接帮你做"),
            Event.done(mapOf("ok" to true)),
        )) c = c.reduce(e)
        assertEquals("opus · medium", c.route)
        assertEquals(listOf("正在看屏幕…"), c.steps)
        assertTrue(c.answer.startsWith("1. 打开设置"))
        assertTrue(c.handOff && c.done && c.ok)
        val next = c.next("还有呢")
        assertEquals("怎么关掉自动更新？", next.earlier.single().question)
        assertEquals("", next.answer)
    }
}
