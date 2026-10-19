package io.github.typing233.superaide.core.screen

import org.junit.Test
import java.time.ZoneId
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class RenderTest {
    private fun n(role: String, text: String = "", depth: Int = 1, box: Box = Box(0, 0, 100, 50), clickable: Boolean = false,
                  editable: Boolean = false, password: Boolean = false, desc: String = "", items: Int = -1, onScreen: Boolean = true) =
        UiNode(role = role, text = text, desc = desc, box = box, depth = depth, clickable = clickable, editable = editable,
            password = password, items = items, onScreen = onScreen)

    private val chat = UiWindow(
        title = "微信", pkg = "com.tencent.mm", type = "app", active = true, focused = true, box = Box(0, 0, 1312, 2848),
        nodes = listOf(
            n("RecyclerView", items = 120, depth = 0),
            n("TextView", "张三：明天下午三点开会"),
            n("TextView", "张三：明天下午三点开会"), // 相邻重复只留一行
            n("TextView", "token=abcd1234efgh"),
            n("LinearLayout", clickable = true, depth = 1, box = Box(100, 2600, 300, 2700)),
            n("TextView", "发送", depth = 2, box = Box(120, 2620, 280, 2680)),
            n("EditText", "", editable = true, box = Box(0, 2600, 100, 2700)).copy(hint = "输入消息"),
            n("EditText", "secret", editable = true, password = true),
            n("ImageButton", desc = "更多功能", clickable = true, box = Box(1200, 2600, 1300, 2700)),
            n("TextView", "滚出去的消息", onScreen = false),
        ),
    )
    private val screen = Screen(
        time = 1_792_339_200_000, width = 1312, height = 2848, windows = listOf(chat),
        notices = listOf(Notice(1_792_339_100_000, "com.tencent.mm", "李四：收到")),
    )

    @Test fun environmentIsVerbatimTextFirst() {
        val env = EnvText.render(screen, EnvText.Extras(label = { if (it == "com.tencent.mm") "微信" else it },
            device = "HONOR PGT-AN20 · Android 16", clipboard = "复制的文字", zone = ZoneId.of("Asia/Shanghai")))
        assertTrue("前台：微信（com.tencent.mm）" in env)
        assertTrue("手机：HONOR PGT-AN20 · Android 16" in env)
        assertTrue("<clipboard>复制的文字</clipboard>" in env)
        assertTrue("微信：李四：收到" in env)
        assertEquals(1, Regex("张三：明天下午三点开会").findAll(env).count())
        assertTrue("（列表，共 120 项；下面只有已加载的部分）" in env)
        assertTrue("✎ （空）  提示：输入消息" in env)
        assertTrue("✎ （密码框，内容不读）" in env)
        assertFalse("secret" in env)
        assertFalse("abcd1234efgh" in env, "打码")
        assertTrue("［更多功能］" in env)
        assertTrue("滚出去的消息" in env)
    }

    @Test fun observationNumbersActionableElementsInShotCoordinates() {
        val scale = Observation.scaleFor(1312, 2848)
        val obs = Observation(screen, scale, (1312 * scale).toInt(), (2848 * scale).toInt())
        val text = obs.build({ "微信" })
        assertTrue(text.startsWith("前台：微信（com.tencent.mm）  截图 ${obs.shotW}×${obs.shotH}"))
        // 可点的容器用里面的文字当名字
        val send = obs.refs.first { it.name == "发送" }
        val (x, y) = obs.toShot(Box(100, 2600, 300, 2700))
        assertTrue("[${send.id}] Item \"发送\" @$x,$y" in text, text)
        assertTrue("Edit \"输入消息\"" in text, text)
        assertTrue("ImageButton \"更多功能\"" in text)
        assertTrue("列表共 120 项" in text)
        // 找：包括不能直接操作的文字，追加新编号
        val before = obs.refs.size
        assertTrue("找到" in obs.find("三点开会"))
        assertEquals(before, obs.refs.size, "已经有编号的不重复编")
        val offScreen = obs.find("滚出去")
        assertTrue("(off-screen)" in offScreen, offScreen)
        assertEquals(before + 1, obs.refs.size)
        // 密码框的内容不出现在名字里
        assertFalse("secret" in text)
        // 读：分页
        val page = obs.read(null, 0, 10)
        assertTrue("用 start=10 接着读" in page)
    }

    @Test fun partialListsCountLoadedItems() {
        val w = UiWindow("t", "p", "app", true, true, Box(0, 0, 10, 10), listOf(
            n("RecyclerView", items = 50, depth = 1),
            n("LinearLayout", clickable = true, depth = 2), n("TextView", "一", depth = 3),
            n("LinearLayout", clickable = true, depth = 2), n("TextView", "二", depth = 3),
            n("TextView", "列表外", depth = 1),
            n("RecyclerView", items = 2, depth = 1),
            n("LinearLayout", clickable = true, depth = 2), n("LinearLayout", clickable = true, depth = 2),
        ))
        assertEquals(listOf(50 to 2), w.partialLists())
    }

    @Test fun scaleMatchesDesktopRule() {
        val s = Observation.scaleFor(1312, 2848)
        assertTrue(2848 * s <= 1568.0001)
        assertTrue(1312 * s * 2848 * s <= 1_150_000.1)
        assertEquals(1.0, Observation.scaleFor(800, 600))
    }
}
