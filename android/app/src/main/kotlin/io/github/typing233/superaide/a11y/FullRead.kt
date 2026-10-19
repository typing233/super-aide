package io.github.typing233.superaide.a11y

import android.view.accessibility.AccessibilityNodeInfo
import io.github.typing233.superaide.core.screen.EnvText
import io.github.typing233.superaide.diag.Diag
import kotlinx.coroutines.delay

/**
 * 「读完整页」：用户点了才做。把前台 App 里最大的那个列表从当前位置往下翻，每翻一屏读一次文字，
 * 读不到新内容或者翻满 [MAX_PAGES] 屏就停，再按原样翻回去（尽量回到原处）。隐私名单里的 App 不翻。
 */
object FullRead {
    const val MAX_PAGES = 10

    class Result(val text: String, val pages: Int)

    suspend fun read(svc: AideAccessibilityService, pkg: String, blocked: Set<String>): Result? {
        if (pkg.isEmpty() || pkg in blocked) return null.also { Diag.log("fullread.skip", "pkg=$pkg") }
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
