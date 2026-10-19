package io.github.typing233.superaide.core

import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.prompts.Prompts
import io.github.typing233.superaide.core.redact.Redact
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** 照搬桌面版 tests/test_snapshot_text.py 和 tests/test_outcome.py 的用例。 */
class RedactAndPromptsTest {
    private val secrets = listOf(
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
        "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
        "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab",
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    )

    @Test fun redactsTokens() {
        for (s in secrets) {
            val out = Redact.apply("key: $s end")
            assertFalse(s in out, s)
            assertTrue(Redact.MASK in out)
        }
    }

    @Test fun redactKeyValuesKeepsKey() {
        assertEquals("password=${Redact.MASK}", Redact.apply("password=hunter2!"))
        assertEquals("api_key: \"${Redact.MASK}\"", Redact.apply("api_key: \"abcd1234\""))
        assertEquals("普通文字不受影响", Redact.apply("普通文字不受影响"))
    }

    @Test fun reportedFailureReadsFirstLine() {
        assertEquals("没完成：Browser Use 未连接", Prompts.reportedFailure("没完成：Browser Use 未连接\n本次未修改任何东西"))
        assertEquals("没完成**：网址检查没通过", Prompts.reportedFailure("**没完成**：网址检查没通过"))
        assertEquals("暂未修复：Computer Use 被安全检查停止。", Prompts.reportedFailure("暂未修复：Computer Use 被安全检查停止。"))
        assertNull(Prompts.reportedFailure("已完成：装好了 modelscope，单元格运行正常。"))
        assertNull(Prompts.reportedFailure(""))
        assertEquals("Not done: no network", Prompts.reportedFailure("Not done: no network"))
    }

    @Test fun firstMessageHasRulesQuestionAndEnvironment() {
        val msg = Prompts.first("这是什么？", "时间：x", images = 1, mode = Mode.ASK, lessons = listOf("- 坑：建议"), uiLang = "en")
        assertTrue(msg.startsWith("当前是【问答模式】"))
        assertTrue("【以前踩过的坑】" in msg && "- 坑：建议" in msg)
        assertTrue("用户的界面语言是英文" in msg)
        assertTrue(msg.indexOf("【我的问题】\n这是什么？") < msg.indexOf("【提问时的环境】"))
        assertTrue("召唤那一刻的屏幕截图" in msg)
        assertTrue("## 操作手机" in Prompts.system(Mode.ACT))
        assertFalse("## 操作手机" in Prompts.system(Mode.ASK))
    }
}
