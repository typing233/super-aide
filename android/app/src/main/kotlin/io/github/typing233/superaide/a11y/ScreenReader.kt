package io.github.typing233.superaide.a11y

import android.graphics.Rect
import android.os.Build
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import io.github.typing233.superaide.core.screen.Box
import io.github.typing233.superaide.core.screen.Notice
import io.github.typing233.superaide.core.screen.Screen
import io.github.typing233.superaide.core.screen.UiNode
import io.github.typing233.superaide.core.screen.UiWindow

/**
 * 把所有窗口的无障碍节点读成 [Screen]。同时留下节点句柄（和 nodes 一一对应），供操作工具按编号用。
 * 只收有文字或能操作的节点；容器只用来往下走。
 */
class ScreenReader(
    private val ownPackage: String,
    private val blocked: Set<String>,
    private val maxNodes: Int = 4000,
    private val budgetMs: Long = 2500,
) {
    class Result(val screen: Screen, val handles: List<List<AccessibilityNodeInfo>>, val visited: Int, val ms: Long)

    fun read(windows: List<AccessibilityWindowInfo>, width: Int, height: Int, notices: List<Notice>): Result {
        val start = SystemClock.uptimeMillis()
        var visited = 0
        val outWindows = mutableListOf<UiWindow>()
        val outHandles = mutableListOf<List<AccessibilityNodeInfo>>()
        // 按层级从上到下；自己的窗口不读
        for (w in windows.sortedByDescending { it.layer }) {
            val root = rootOf(w) ?: continue
            val pkg = root.packageName?.toString().orEmpty()
            if (pkg == ownPackage) continue
            val box = Rect().also(w::getBoundsInScreen).toBox()
            if (pkg in blocked) {
                outWindows += UiWindow(w.title?.toString().orEmpty(), pkg, typeOf(w), w.isActive, w.isFocused, box, emptyList(), blocked = true, id = w.id)
                outHandles.add(emptyList())
                continue
            }
            val nodes = mutableListOf<UiNode>()
            val handles = mutableListOf<AccessibilityNodeInfo>()
            val stack = ArrayDeque<Pair<AccessibilityNodeInfo, Int>>()
            stack.addLast(root to 0)
            while (stack.isNotEmpty() && visited < maxNodes) {
                if (SystemClock.uptimeMillis() - start > budgetMs) break
                val (node, depth) = stack.removeLast()
                visited++
                node(node, depth)?.let { nodes += it; handles += node }
                for (i in node.childCount - 1 downTo 0) {
                    node.getChild(i)?.let { stack.addLast(it to depth + 1) }
                }
            }
            outWindows += UiWindow(w.title?.toString().orEmpty(), pkg, typeOf(w), w.isActive, w.isFocused, box, nodes, id = w.id)
            outHandles.add(handles)
        }
        val screen = Screen(System.currentTimeMillis(), width, height, outWindows, notices)
        return Result(screen, outHandles, visited, SystemClock.uptimeMillis() - start)
    }

    private fun rootOf(w: AccessibilityWindowInfo): AccessibilityNodeInfo? =
        if (Build.VERSION.SDK_INT >= 33) {
            w.getRoot(
                AccessibilityNodeInfo.FLAG_PREFETCH_DESCENDANTS_DEPTH_FIRST or
                    AccessibilityNodeInfo.FLAG_PREFETCH_UNINTERRUPTIBLE
            )
        } else {
            w.root
        }

    private fun node(n: AccessibilityNodeInfo, depth: Int): UiNode? {
        val text = n.text?.toString().orEmpty()
        val desc = n.contentDescription?.toString().orEmpty()
        val hint = n.hintText?.toString().orEmpty()
        val actionable = n.isClickable || n.isLongClickable || n.isEditable || n.isScrollable || n.isCheckable
        val items = n.collectionInfo?.let { maxOf(it.rowCount, it.itemCountCompat()) } ?: -1
        if (text.isBlank() && desc.isBlank() && hint.isBlank() && !actionable && items < 0) return null
        val box = Rect().also(n::getBoundsInScreen).toBox()
        return UiNode(
            role = n.className?.toString()?.substringAfterLast('.').orEmpty(),
            text = if (n.isPassword) (if (text.isEmpty()) "" else "••••") else text,
            desc = desc,
            hint = hint,
            viewId = n.viewIdResourceName?.substringAfter(":id/").orEmpty(),
            box = box,
            depth = depth,
            clickable = n.isClickable,
            longClickable = n.isLongClickable,
            editable = n.isEditable,
            scrollable = n.isScrollable,
            checkable = n.isCheckable,
            checked = n.isChecked,
            selected = n.isSelected,
            focused = n.isFocused,
            enabled = n.isEnabled,
            password = n.isPassword,
            onScreen = n.isVisibleToUser,
            items = items,
        )
    }

    private fun AccessibilityNodeInfo.CollectionInfo.itemCountCompat(): Int =
        if (Build.VERSION.SDK_INT >= 35) itemCount else rowCount * maxOf(columnCount, 1)

    private fun typeOf(w: AccessibilityWindowInfo) = when (w.type) {
        AccessibilityWindowInfo.TYPE_APPLICATION -> "app"
        AccessibilityWindowInfo.TYPE_INPUT_METHOD -> "ime"
        AccessibilityWindowInfo.TYPE_SYSTEM -> "system"
        AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY -> "overlay"
        AccessibilityWindowInfo.TYPE_SPLIT_SCREEN_DIVIDER -> "split"
        AccessibilityWindowInfo.TYPE_MAGNIFICATION_OVERLAY -> "overlay"
        else -> "other"
    }
}

fun Rect.toBox() = Box(left, top, right, bottom)
