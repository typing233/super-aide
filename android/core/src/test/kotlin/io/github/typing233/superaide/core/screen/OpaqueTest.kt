package io.github.typing233.superaide.core.screen

import io.github.typing233.superaide.core.screen.Opaque.withOcr
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** 不让无障碍读界面的 App（微信）：截图认字的结果怎么排、怎么并、怎么给模型看。 */
class OpaqueTest {
    private val win = Box(0, 0, 1312, 2848)
    private fun ocr(text: String, l: Int, t: Int, r: Int, b: Int) = UiNode(role = "OCR", text = text, box = Box(l, t, r, b), ocr = true)
    private fun node(text: String, onScreen: Boolean = true) = UiNode(role = "TextView", text = text, box = Box(0, 0, 10, 10), onScreen = onScreen)

    private val wechat = UiWindow("微信", "com.tencent.mm", "app", active = true, focused = true, box = win, nodes = emptyList(), opaque = true)

    @Test fun readingOrderIsRowsThenLeftToRight() {
        val lines = listOf(
            ocr("发现", 783, 2785, 855, 2821),
            ocr("微信", 126, 2783, 198, 2821),
            ocr("文件传输助手", 252, 400, 600, 450),
            ocr("21:45", 1100, 405, 1250, 445),
            ocr("通讯录", 434, 2784, 547, 2821),
        )
        assertEquals(listOf("文件传输助手", "21:45", "微信", "通讯录", "发现"), Opaque.order(lines).map { it.text })
    }

    @Test fun scrambledTreeIsDetectedAgainstTheScreenshot() {
        val seen = listOf(ocr("文件传输助手", 0, 0, 1, 1), ocr("张三 明天下午三点开会", 0, 0, 1, 1), ocr("通讯录 发现 我", 0, 0, 1, 1))
        // 打乱的节点：字是从别处随机拿来的
        val fake = listOf(node("李四"), node("周末去爬山吗"), node("收到了谢谢"), node("订单已发货"))
        assertTrue(Opaque.agreement(fake, seen) < 0.5)
        val real = listOf(node("文件传输助手"), node("张三"), node("明天下午三点开会"), node("通讯录"))
        assertTrue(Opaque.agreement(real, seen) >= 0.5)
        // 能比的字太少：看不出来，信节点
        assertEquals(1.0, Opaque.agreement(listOf(node("我")), seen))
    }

    @Test fun strayTraditionalCharactersAreSimplified() {
        val lines = listOf(ocr("通訊录", 0, 0, 1, 1), ocr("微信", 0, 0, 1, 1), ocr("发现", 0, 0, 1, 1))
        assertEquals(listOf("通讯录", "微信", "发现"), Opaque.simplify(lines).map { it.text })
        // 整屏本来就是繁体的不动
        val trad = listOf(ocr("通訊錄", 0, 0, 1, 1), ocr("發現", 0, 0, 1, 1), ocr("設定", 0, 0, 1, 1))
        assertEquals(listOf("通訊錄", "發現", "設定"), Opaque.simplify(trad).map { it.text })
    }

    @Test fun overlappingPagesKeepOnlyNewLines() {
        // 往上翻了 1000 像素：内容往下挪，上一页 y=500 的行现在在 y≈1500
        val prev = listOf(ocr("文件传输助手", 400, 150, 900, 220), ocr("昨天 21:49", 500, 480, 800, 520), ocr("按住 说话", 400, 2700, 900, 2760))
        val next = listOf(
            ocr("文件传输助手", 400, 150, 900, 220), // 标题栏不动
            ocr("9月7日 12:23", 500, 700, 800, 740), // 新的
            ocr("昨夭 21:49", 500, 1478, 800, 1518), // 同一行：挪了位置，这次把「天」认成了「夭」
            ocr("按住 说话", 400, 2700, 900, 2760),
        )
        assertEquals(listOf("9月7日 12:23"), Opaque.fresh(prev, next, shift = 1000, tol = 85).map { it.text })
        // 差不多的字但不在挪过去的位置上：是另一行
        val elsewhere = listOf(ocr("昨夭 21:49", 500, 900, 800, 940))
        assertEquals(1, Opaque.fresh(prev, elsewhere, shift = 1000, tol = 85).size)
    }

    @Test fun ocrWindowIsLabelledAndShowsWhichSideEachLineIsOn() {
        val lines = listOf(
            ocr("张三", 200, 400, 330, 450),
            ocr("明天下午三点开会", 200, 470, 700, 520),
            ocr("好的，我准时到", 600, 600, 1130, 650),
            ocr("昨天 21:49", 540, 700, 770, 740),
        )
        val screen = Screen(1_792_339_200_000, 1312, 2848, listOf(wechat)).withOcr(0, lines)
        val env = EnvText.render(screen, EnvText.Extras(label = { "微信" }))
        assertTrue(EnvText.OPAQUE_OCR in env)
        assertTrue("左｜明天下午三点开会" in env)
        assertTrue("右｜好的，我准时到" in env)
        assertTrue("\n昨天 21:49" in env) // 居中的不标
        assertFalse("这个窗口没有交出文字" in env)
    }

    @Test fun blankWindowWithoutOcrSaysSo() {
        val env = EnvText.render(Screen(0, 1312, 2848, listOf(wechat)), EnvText.Extras(label = { "微信" }))
        assertTrue(EnvText.OPAQUE_BLANK in env)
    }

    @Test fun ocrLinesGetIdsAndTapByPosition() {
        val lines = listOf(ocr("文件传输助手", 252, 400, 600, 450), ocr("发送", 1150, 2600, 1280, 2680))
        val screen = Screen(0, 1312, 2848, listOf(wechat)).withOcr(0, lines)
        val o = Observation(screen, 0.5, 656, 1424)
        val text = o.build({ "微信" })
        assertTrue("[1] OCR \"文件传输助手\" @213,212" in text, text)
        assertTrue("[2] OCR \"发送\"" in text)
        assertTrue("微信 不让无障碍读界面" in text)
        assertTrue("type（不给 id）" in text)
        assertTrue("找到 1 个" in o.find("发送"))
    }
}
