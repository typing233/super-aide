package io.github.typing233.superaide.a11y

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.graphics.Rect
import android.graphics.RectF
import android.os.Bundle
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.agent.ToolHost
import io.github.typing233.superaide.core.llm.Part
import io.github.typing233.superaide.core.llm.ToolCall
import io.github.typing233.superaide.core.llm.ToolOutput
import io.github.typing233.superaide.core.screen.Observation
import io.github.typing233.superaide.core.screen.Opaque
import io.github.typing233.superaide.system.Apps
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * 手机上的工具（对应桌面版 cu/server.py）。看：observe_screen / find / read / zoom / apps / point；做：act。
 * 编号只在最近一次观察里有效。问答模式下 act 不在工具表里，这里再拦一次。
 */
class PhoneTools(
    private val apps: Apps,
    private val recall: (String) -> String = { "没有相关的经验。" },
    private val isStopped: () -> Boolean = { false },
) : ToolHost {
    private var read: ScreenReader.Result? = null
    private var obs: Observation? = null
    /** 最近一次截图（原始分辨率，屏幕坐标） */
    private var full: Bitmap? = null

    private val service get() = AideAccessibilityService.instance ?: throw IllegalStateException("无障碍服务没开：在设置里打开「超级助手」的无障碍权限后才能看屏幕、操作手机。")

    override suspend fun run(call: ToolCall, mode: Mode): ToolOutput {
        val a = call.input ?: JsonObject(emptyMap())
        val parts: List<Part> = when (call.name) {
            "observe_screen" -> observe(a.bool("screenshot") ?: true)
            "find" -> listOf(text(obs?.find(a.str("text").orEmpty()) ?: "先用 observe_screen 看一下屏幕。"))
            "read" -> listOf(text(readText(a)))
            "zoom" -> zoom(a)
            "apps" -> listOf(text(listApps(a.str("query").orEmpty())))
            "point" -> listOf(text(point(a)))
            "recall" -> listOf(text(recall(a.str("query").orEmpty())))
            "act" -> if (mode != Mode.ACT) listOf(text("问答模式不能操作手机：给出步骤，让用户点「让我来做」。")) else act(a)
            else -> listOf(text("没有这个工具：${call.name}"))
        }
        return ToolOutput(call.id, parts)
    }

    // ---------------- 看 ----------------

    private suspend fun observe(screenshot: Boolean): List<Part> {
        val svc = service
        var r = withContext(Dispatchers.Default) { svc.readScreen() }
        // 不让无障碍读界面的 App（微信）：不管要不要图都得截一张来认字
        val front = r.screen.windows.firstOrNull { it.type == "app" && it.active } ?: r.screen.windows.firstOrNull { it.type == "app" }
        val needsOcr = front != null && !front.blocked && (front.opaque || front.pkg in Opaque.SCRAMBLERS)
        val cap = if (screenshot || needsOcr) capture(svc, r.screen) else null
        val shot = cap?.first
        if (needsOcr) r = withContext(Dispatchers.Default) { Ocr.fill(r, shot, fullScreen = cap?.second == false) }
        read = r
        val screen = r.screen
        val scale = Observation.scaleFor(screen.width, screen.height)
        val o = Observation(screen, scale, (screen.width * scale).toInt(), (screen.height * scale).toInt())
        val described = o.build(apps::label)
        obs = o
        if (!screenshot) return listOf(text(described))
        if (shot == null) return listOf(text(described + "\n（这次没截到图：可能是受保护的页面，比如密码、支付）"))
        full = shot
        val small = Shots.scaled(shot, scale)
        val boxes = o.refs.take(Observation.LIMIT).mapNotNull { ref ->
            val n = o.node(ref)
            if (!n.onScreen) null else ref.id to RectF((n.box.l * scale).toFloat(), (n.box.t * scale).toFloat(), (n.box.r * scale).toFloat(), (n.box.b * scale).toFloat())
        }
        return listOf(text(described), Part.Image(Shots.jpeg(Shots.annotate(small, boxes))))
    }

    /** 优先只截前台 App 的窗口（我们自己的界面不在上面）；不行再截整屏。返回（截图, 是不是只截了那个窗口） */
    private suspend fun capture(svc: AideAccessibilityService, screen: io.github.typing233.superaide.core.screen.Screen): Pair<Bitmap, Boolean>? {
        val front = screen.windows.firstOrNull { it.type == "app" && it.active }
        if (front != null && front.box.l <= 0 && front.box.t <= 0 && front.box.w >= screen.width && front.box.h >= screen.height) {
            svc.screenshotOfWindow(front.id)?.let { if (it.width == screen.width) return it to true }
        }
        return svc.screenshot()?.let { it to false }
    }

    private fun readText(a: JsonObject): String {
        val o = obs ?: return "先用 observe_screen 看一下屏幕。"
        return o.read(a.int("id"), a.int("start") ?: 0, (a.int("max_chars") ?: 8000).coerceIn(500, 20000))
    }

    private fun zoom(a: JsonObject): List<Part> {
        val o = obs ?: return listOf(text("先用 observe_screen 看一下屏幕。"))
        val src = full ?: return listOf(text("还没有截图：先 observe_screen（screenshot=true）。"))
        val (x0, y0) = o.toScreen(minOf(a.int("x0") ?: 0, a.int("x1") ?: 0), minOf(a.int("y0") ?: 0, a.int("y1") ?: 0))
        val (x1, y1) = o.toScreen(maxOf(a.int("x0") ?: 0, a.int("x1") ?: 0), maxOf(a.int("y0") ?: 0, a.int("y1") ?: 0))
        val rect = Rect(x0.toInt().coerceIn(0, src.width - 1), y0.toInt().coerceIn(0, src.height - 1),
            x1.toInt().coerceIn(1, src.width), y1.toInt().coerceIn(1, src.height))
        if (rect.width() < 2 || rect.height() < 2) return listOf(text("区域太小了。"))
        val crop = Bitmap.createBitmap(src, rect.left, rect.top, rect.width(), rect.height())
        val fit = Observation.scaleFor(crop.width, crop.height)
        return listOf(text("区域 (${a.int("x0")},${a.int("y0")})-(${a.int("x1")},${a.int("y1")}) 的原始分辨率图："),
            Part.Image(Shots.png(Shots.scaled(crop, fit)), "image/png"))
    }

    private fun listApps(query: String): String {
        val all = apps.launchable()
        val hits = if (query.isBlank()) all else all.filter { query.lowercase() in it.label.lowercase() || query.lowercase() in it.pkg.lowercase() }
        if (hits.isEmpty()) return "没有名字里带「$query」的 App。"
        return hits.take(200).joinToString("\n") { "- ${it.label}（${it.pkg}）" }
    }

    private fun point(a: JsonObject): String {
        val o = obs ?: return "先用 observe_screen 看一下屏幕。"
        val marks = a["targets"]?.jsonArray.orEmpty().mapNotNull { t ->
            val m = t.jsonObject
            val label = m.str("label").orEmpty()
            val id = m.int("id")
            val box = if (id != null) {
                val ref = o.byId(id) ?: return@mapNotNull null
                o.node(ref).box.let { RectF(it.l.toFloat(), it.t.toFloat(), it.r.toFloat(), it.b.toFloat()) }
            } else {
                val (x0, y0) = o.toScreen(m.int("x0") ?: return@mapNotNull null, m.int("y0") ?: return@mapNotNull null)
                val (x1, y1) = o.toScreen(m.int("x1") ?: return@mapNotNull null, m.int("y1") ?: return@mapNotNull null)
                RectF(minOf(x0, x1), minOf(y0, y1), maxOf(x0, x1), maxOf(y0, y1))
            }
            Marks.Mark(box, label)
        }
        if (marks.isEmpty()) return "没有能圈的目标：用 observe_screen 里的编号 id，或截图坐标框。"
        service.marks.show(marks, a.double("seconds") ?: 30.0)
        return "已经在屏幕上圈出 ${marks.size} 处（编号 1–${marks.size}，和你回答里的步骤对应）。"
    }

    // ---------------- 做 ----------------

    private suspend fun act(a: JsonObject): List<Part> {
        val svc = service
        val actions = a["actions"]?.jsonArray.orEmpty().map { it.jsonObject }
        if (actions.isEmpty()) return listOf(text("没有动作。"))
        val lines = mutableListOf<String>()
        run {
            for ((i, action) in actions.withIndex()) {
                if (isStopped()) { lines += "已停止：你按了停止"; break }
                val result = runCatching { step(svc, action) }.getOrElse { Fail(it.message ?: it.toString()) }
                lines += "${i + 1}. " + when (result) {
                    is Ok -> result.text
                    is Fail -> "失败：${result.text}"
                }
                if (result is Fail) {
                    if (i < actions.size - 1) lines += "（后面 ${actions.size - 1 - i} 步没有执行）"
                    break
                }
                delay(350)
            }
        }
        val out = mutableListOf<Part>(text(lines.joinToString("\n")))
        if (a.bool("observe_after") != false && !isStopped()) {
            delay(500)
            out += runCatching { observe(true) }.getOrElse { listOf(text("（执行完再观察失败：${it.message}）")) }
        }
        return out
    }

    private sealed interface Outcome
    private class Ok(val text: String) : Outcome
    private class Fail(val text: String) : Outcome

    private suspend fun step(svc: AideAccessibilityService, s: JsonObject): Outcome {
        return when (val d = s.str("do").orEmpty()) {
            "tap", "long_press", "double_tap" -> {
                val target = target(s) ?: return Fail("要给 id 或截图坐标 x、y")
                if (target.blocked) return Fail("这个 App 在隐私名单里，不能操作")
                val (x, y) = target.point
                when (d) {
                    "tap" -> if (target.node != null && click(target.node, AccessibilityNodeInfo.ACTION_CLICK)) Ok("点击 ${target.name}")
                    else if (svc.tap(x, y)) Ok("点击 ${target.name}（手势）") else Fail("点不了 ${target.name}")
                    "long_press" -> if (target.node != null && click(target.node, AccessibilityNodeInfo.ACTION_LONG_CLICK)) Ok("长按 ${target.name}")
                    else if (svc.tap(x, y, 700)) Ok("长按 ${target.name}（手势）") else Fail("长按不了 ${target.name}")
                    else -> if (svc.tap(x, y) && run { delay(90); svc.tap(x, y) }) Ok("双击 ${target.name}") else Fail("双击不了 ${target.name}")
                }
            }

            "type" -> {
                val text = s.str("text").orEmpty()
                val t = if (s.int("id") != null) target(s) else null
                // 截图认出的字（没有节点）：先点它，让它所在的输入框拿到焦点
                if (t != null && t.node == null) { svc.tap(t.point.first, t.point.second); delay(400) }
                val replace = s.bool("replace") == true
                val append = s.bool("append") == true
                val node = t?.node ?: svc.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)?.takeIf { it.refresh() && it.isEditable }
                if (node == null || !node.isEditable) {
                    // 读不到输入框节点（微信这样不让读界面的 App）：用无障碍输入法往有焦点的输入框里写
                    val field = svc.imeField()
                        ?: return Fail(if (node != null) "[${s.int("id")}] 不是输入框" else "没有输入框：给输入框的 id，或者先点一下输入框（看截图用坐标点）")
                    guard(field.text, field.multiLine, replace, append)?.let { return Fail(it) }
                    return svc.imeType(text, replace, s.bool("enter") == true)?.let { typed += text; Ok(it) } ?: Fail("没有获得焦点的输入框：先点一下输入框")
                }
                node.refresh()
                val existing = if (node.isShowingHintText) "" else node.text?.toString().orEmpty()
                if (!node.isPassword) guard(existing, node.isMultiLine, replace, append)?.let { return Fail(it) }
                typed += text
                val value = if (replace) text else existing + text
                val args = Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, value) }
                if (!node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
                    // 不让直接填字的输入框：点一下让它拿到焦点，再像输入法一样写进去
                    node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    delay(300)
                    return svc.imeType(text, replace, s.bool("enter") == true)?.let { Ok(it) } ?: Fail("这个输入框不让直接填字")
                }
                delay(150)
                node.refresh()
                val now = node.text?.toString().orEmpty()
                val warn = if (!node.isPassword && now != value) "（填完读回来是「${now.take(60)}」，和要填的不一样，看一下）" else ""
                if (s.bool("enter") == true) {
                    val sent = node.performAction(AccessibilityAction.ACTION_IME_ENTER.id)
                    Ok("输入「${text.take(40)}」并回车" + (if (sent) "" else "（回车没生效，可以点搜索/发送按钮）") + warn)
                } else Ok("输入「${text.take(40)}」$warn")
            }

            "scroll" -> {
                val dir = s.str("direction") ?: "down"
                val times = (s.double("amount") ?: 1.0).toInt().coerceIn(1, 10)
                val node = scrollable(s)
                var moved = 0
                repeat(times) {
                    val ok = node != null && node.performAction(scrollAction(dir)) ||
                        node != null && node.performAction(if (dir == "down" || dir == "right") AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD) ||
                        swipeFor(svc, dir)
                    if (ok) moved++
                    delay(250)
                }
                if (moved > 0) Ok("往${dirName(dir)}滚动 $moved 屏") else Fail("滚不动（可能到头了）")
            }

            "swipe" -> {
                val from = point(s.int("x"), s.int("y")) ?: return Fail("要给起点 x、y")
                val to = point(s.int("to_x"), s.int("to_y")) ?: return Fail("要给终点 to_x、to_y")
                val path = Path().apply { moveTo(from.first, from.second); lineTo(to.first, to.second) }
                if (svc.gesture(GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(path, 0, 350)).build())) Ok("滑动")
                else Fail("滑动没成功")
            }

            "back" -> global(svc, AccessibilityService.GLOBAL_ACTION_BACK, "返回")
            "home" -> global(svc, AccessibilityService.GLOBAL_ACTION_HOME, "回到桌面")
            "recents" -> global(svc, AccessibilityService.GLOBAL_ACTION_RECENTS, "打开最近任务")
            "notifications" -> global(svc, AccessibilityService.GLOBAL_ACTION_NOTIFICATIONS, "打开通知栏")

            "wait" -> {
                val sec = (s.double("seconds") ?: 1.0).coerceIn(0.1, 30.0)
                delay((sec * 1000).toLong()); Ok("等了 ${"%.1f".format(sec)} 秒")
            }

            "wait_for" -> {
                val want = s.str("text").orEmpty().ifBlank { return Fail("要给 text") }
                val deadline = System.currentTimeMillis() + ((s.double("seconds") ?: 10.0).coerceIn(1.0, 60.0) * 1000).toLong()
                while (System.currentTimeMillis() < deadline && !isStopped()) {
                    val r = withContext(Dispatchers.Default) { svc.readScreen() }
                    if (r.screen.windows.any { w -> w.nodes.any { want in it.text || want in it.desc } }) return Ok("「$want」出现了")
                    delay(500)
                }
                Fail("等到超时也没看到「$want」")
            }

            "open_app" -> {
                val app = apps.resolve(s.str("app").orEmpty()) ?: return Fail("手机上没找到「${s.str("app")}」：用 apps 工具看看都有哪些")
                if (apps.open(app.pkg)) { delay(800); Ok("打开「${app.label}」") } else Fail("打不开「${app.label}」")
            }

            "open_url" -> {
                val url = s.str("url").orEmpty().ifBlank { return Fail("要给 url") }
                if (apps.openUrl(url)) { delay(800); Ok("打开 ${url.take(80)}") } else Fail("没有 App 能打开 ${url.take(80)}")
            }

            else -> Fail("不认识的动作「$d」")
        }
    }

    /** 这段对话里自己输入过的字：输入框里只有这些的，不算用户的草稿 */
    private val typed = mutableListOf<String>()

    /**
     * 输入框里原来就有字时拦一下。多行的（聊天框、正文）里不是自己刚输入的字，多半是用户没发的草稿：
     * 不清掉、不接在后面（接上再发出去，草稿就替用户发了）。单行的（搜索框）说明要换掉还是接上就行。
     */
    private fun guard(existing: String, multiLine: Boolean, replace: Boolean, append: Boolean): String? {
        if (existing.isEmpty()) return null
        val ours = existing == typed.joinToString("") || existing in typed
        if (multiLine && !ours) return "输入框里有用户没发的草稿「${existing.take(80)}」，这次没有输入。不要清掉、改动它，也不要接在后面发出去：" +
            "停下来，汇报第一行写「待你确认：」，说输入框里有草稿，请用户先处理（发掉、删掉或者存起来）。"
        if (!replace && !append) return "输入框里已经有字「${existing.take(80)}」，这次没有输入：要换掉就给 replace=true，要接在后面就给 append=true。"
        return null
    }

    private class Target(val node: AccessibilityNodeInfo?, val point: Pair<Float, Float>, val name: String, val blocked: Boolean = false)

    /** id → 节点（和它的中心）；或截图坐标 → 屏幕坐标 */
    private fun target(s: JsonObject): Target? {
        val o = obs
        val id = s.int("id")
        if (id != null) {
            val ref = o?.byId(id) ?: throw IllegalArgumentException("没有编号 [$id]：编号只在最近一次观察里有效，先 observe_screen")
            val w = o.screen.windows[ref.window]
            val handle = read?.handles?.getOrNull(ref.window)?.getOrNull(ref.node)
            val box = o.node(ref).box
            return Target(handle, box.cx.toFloat() to box.cy.toFloat(), "[$id] \"${ref.name}\"", w.blocked)
        }
        val p = point(s.int("x"), s.int("y")) ?: return null
        return Target(null, p, "(${s.int("x")},${s.int("y")})")
    }

    private fun point(x: Int?, y: Int?): Pair<Float, Float>? {
        if (x == null || y == null) return null
        return obs?.toScreen(x, y) ?: (x.toFloat() to y.toFloat())
    }

    /** 自己能点就点自己，不能就往上找能点的父元素（列表项常这样） */
    private fun click(node: AccessibilityNodeInfo, action: Int): Boolean {
        var n: AccessibilityNodeInfo? = node
        var hops = 0
        while (n != null && hops < 6) {
            n.refresh()
            val can = if (action == AccessibilityNodeInfo.ACTION_CLICK) n.isClickable else n.isLongClickable
            if (can && n.isEnabled) return n.performAction(action)
            n = n.parent
            hops++
        }
        return false
    }

    private fun scrollable(s: JsonObject): AccessibilityNodeInfo? {
        s.int("id")?.let { id ->
            var n = target(s)?.node
            while (n != null) { if (n.isScrollable) return n; n = n.parent }
        }
        // 没指定：前台窗口里屏幕上最大的可滚动元素
        val r = read ?: return null
        var best: AccessibilityNodeInfo? = null
        var area = 0
        r.screen.windows.forEachIndexed { wi, w ->
            if (w.type != "app" || w.blocked) return@forEachIndexed
            w.nodes.forEachIndexed { ni, n ->
                val sz = n.box.w * n.box.h
                if (n.scrollable && n.onScreen && sz > area) { area = sz; best = r.handles[wi].getOrNull(ni) }
            }
        }
        return best
    }

    private fun scrollAction(dir: String) = when (dir) {
        "up" -> AccessibilityAction.ACTION_SCROLL_UP.id
        "left" -> AccessibilityAction.ACTION_SCROLL_LEFT.id
        "right" -> AccessibilityAction.ACTION_SCROLL_RIGHT.id
        else -> AccessibilityAction.ACTION_SCROLL_DOWN.id
    }

    /** 看下面的内容 = 手指从下往上划 */
    private suspend fun swipeFor(svc: AideAccessibilityService, dir: String): Boolean {
        val m = svc.resources.displayMetrics
        val w = m.widthPixels.toFloat()
        val h = m.heightPixels.toFloat()
        val (from, to) = when (dir) {
            "up" -> (w / 2 to h * 0.3f) to (w / 2 to h * 0.75f)
            "left" -> (w * 0.2f to h / 2) to (w * 0.8f to h / 2)
            "right" -> (w * 0.8f to h / 2) to (w * 0.2f to h / 2)
            else -> (w / 2 to h * 0.75f) to (w / 2 to h * 0.3f)
        }
        val path = Path().apply { moveTo(from.first, from.second); lineTo(to.first, to.second) }
        return svc.gesture(GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(path, 0, 300)).build())
    }

    private fun dirName(dir: String) = mapOf("up" to "上", "down" to "下", "left" to "左", "right" to "右")[dir] ?: dir

    private fun global(svc: AideAccessibilityService, action: Int, name: String): Outcome =
        if (svc.performGlobalAction(action)) Ok(name) else Fail("$name 没成功")

    fun clearMarks() = AideAccessibilityService.instance?.marks?.hide()

    private fun text(s: String) = Part.Text(s)
}

private fun JsonObject.str(k: String) = (this[k] as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNull
private fun JsonObject.int(k: String) = (this[k] as? kotlinx.serialization.json.JsonPrimitive)?.let { it.intOrNull ?: it.doubleOrNull?.toInt() }
private fun JsonObject.double(k: String) = (this[k] as? kotlinx.serialization.json.JsonPrimitive)?.doubleOrNull
private fun JsonObject.bool(k: String) = (this[k] as? kotlinx.serialization.json.JsonPrimitive)?.booleanOrNull
private fun kotlinx.serialization.json.JsonArray?.orEmpty() = this ?: emptyList()

