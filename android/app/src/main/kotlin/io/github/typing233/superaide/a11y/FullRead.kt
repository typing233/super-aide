package io.github.typing233.superaide.a11y

import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Build
import android.view.accessibility.AccessibilityNodeInfo
import io.github.typing233.superaide.core.screen.Box
import io.github.typing233.superaide.core.screen.EnvText
import io.github.typing233.superaide.core.screen.Opaque
import io.github.typing233.superaide.core.screen.UiNode
import io.github.typing233.superaide.core.screen.UiWindow
import io.github.typing233.superaide.diag.Diag
import kotlinx.coroutines.delay

/**
 * 「读完整页」：用户点了才做。把前台 App 里最大的那个列表从当前位置往下翻，每翻一屏读一次文字，
 * 读不到新内容或者翻满 [MAX_PAGES] 屏就停，再按原样翻回去（尽量回到原处）。隐私名单里的 App 不翻。
 */
object FullRead {
    const val MAX_PAGES = 10

    /** how：怎么读到的（给模型看），空 = 无障碍读的列表、往下翻 */
    class Result(val text: String, val pages: Int, val how: String = "")

    suspend fun read(svc: AideAccessibilityService, pkg: String, blocked: Set<String>): Result? {
        if (pkg.isEmpty() || pkg in blocked) return null.also { Diag.log("fullread.skip", "pkg=$pkg") }
        val window = runCatching { svc.readScreen() }.getOrNull()?.screen?.windows?.firstOrNull { it.pkg == pkg && it.type == "app" }
        if (window != null && (window.opaque || pkg in Opaque.SCRAMBLERS)) return byOcr(svc, window)
        val list = biggestScrollable(svc, pkg) ?: return null.also { Diag.log("fullread.nolist", pkg) }
        Diag.log("fullread.start", "pkg=$pkg list=${list.className}")
        val lines = LinkedHashSet<String>()
        fun collect() {
            val w = runCatching { svc.readScreen() }.getOrNull()?.screen?.windows?.firstOrNull { it.pkg == pkg && it.type == "app" } ?: return
            EnvText.windowText(w).lineSequence().filter { it.isNotBlank() }.forEach { lines += it }
        }
        collect()
        var pages = 0
        while (pages < MAX_PAGES) {
            val before = lines.size
            if (!list.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)) break
            pages++
            delay(500) // 等列表加载、画出来
            collect()
            if (lines.size == before) break // 到底了
        }
        // 翻回去
        repeat(pages) {
            list.performAction(AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD)
            delay(150)
        }
        Diag.log("fullread", "pages=$pages lines=${lines.size}")
        return Result(lines.joinToString("\n"), pages)
    }

    /**
     * 不让无障碍读界面的 App（微信）：用手势翻页，每页截它自己的窗口认字。先往下翻；一开始就翻不动（聊天记录通常停在最底下）
     * 就往上翻读更早的内容。拖完停一下再松手，页面不会惯性滑动，翻回去的距离才对得上。
     */
    private suspend fun byOcr(svc: AideAccessibilityService, w: UiWindow): Result? {
        if (Build.VERSION.SDK_INT < 34) return null.also { Diag.log("fullread.ocr.old") }
        suspend fun page(): List<UiNode>? = svc.screenshotOfWindow(w.id)?.let { Ocr.lines(it, w.box.l, w.box.t) }
        var prev = page() ?: return null.also { Diag.log("fullread.ocr.noshot", w.pkg) }
        val pages = mutableListOf(prev)
        val step = (w.box.h * DRAG).toInt()
        var up = false
        var moved = 0
        while (moved < MAX_PAGES) {
            if (!drag(svc, w.box, up)) break
            delay(if (up) 900 else 600) // 往上翻聊天记录要等它加载更早的消息
            val next = page() ?: break
            // 和上一页重叠的部分按位置去掉（页面挪了 step 像素）：只按文字去重，认得稍有出入的同一行会重复
            val fresh = Opaque.fresh(prev, next, if (up) step else -step, (w.box.h * 0.03).toInt())
            if (fresh.isEmpty()) {
                // 没翻动（到头了），这一下不算，翻回去时也不用翻
                if (!up && moved == 0) { up = true; continue } // 一开始就在最底下：改成往上读
                break
            }
            moved++
            pages += fresh
            prev = next
        }
        repeat(moved) { drag(svc, w.box, !up); delay(250) }
        // 往上读的，后读到的在更上面：倒过来拼成从上到下
        val text = (if (up) pages.reversed() else pages).flatten().joinToString("\n") { EnvText.side(it.box, w.box) + it.text }
        Diag.log("fullread.ocr", "pkg=${w.pkg} up=$up pages=${pages.size} lines=${pages.sumOf { it.size }}")
        val how = "（这个 App 不让无障碍读界面：字是一屏屏截图认出来的，个别字可能认错；「左｜」「右｜」是靠左还是靠右，聊天里靠左一般是对方、靠右是自己。" +
            (if (up) "已经在最底下，所以往上翻了 $moved 屏，读的是更早的内容，按从上到下排）" else "从当前位置往下翻了 $moved 屏）")
        return Result(text, moved, how)
    }

    /** 一次拖动窗口高度的多少 */
    private const val DRAG = 0.45f

    /** 翻一屏：拖动窗口高度的 [DRAG]，停住再松手（不惯性滑动）。up = 看上面的内容（手指往下拖） */
    private suspend fun drag(svc: AideAccessibilityService, box: Box, up: Boolean): Boolean {
        val x = box.cx.toFloat()
        val (from, to) = (box.t + box.h * 0.3f) to (box.t + box.h * (0.3f + DRAG))
        val (y0, y1) = if (up) from to to else to to from
        val move = GestureDescription.StrokeDescription(Path().apply { moveTo(x, y0); lineTo(x, y1) }, 0, 450, true)
        if (!svc.gesture(GestureDescription.Builder().addStroke(move).build())) return false
        val hold = move.continueStroke(Path().apply { moveTo(x, y1) }, 0, 200, false)
        return svc.gesture(GestureDescription.Builder().addStroke(hold).build())
    }

    private fun biggestScrollable(svc: AideAccessibilityService, pkg: String): AccessibilityNodeInfo? {
        val root = svc.windows.mapNotNull { it.root }.firstOrNull { it.packageName?.toString() == pkg } ?: return null
        var best: AccessibilityNodeInfo? = null
        var area = 0
        val stack = ArrayDeque(listOf(root))
        var visited = 0
        while (stack.isNotEmpty() && visited < 3000) {
            val n = stack.removeLast()
            visited++
            if (n.isScrollable && n.isVisibleToUser) {
                val r = android.graphics.Rect().also(n::getBoundsInScreen)
                val a = r.width() * r.height()
                if (a > area) { area = a; best = n }
            }
            for (i in 0 until n.childCount) n.getChild(i)?.let(stack::addLast)
        }
        return best
    }
}
