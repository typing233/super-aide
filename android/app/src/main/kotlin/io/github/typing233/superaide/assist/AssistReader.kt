package io.github.typing233.superaide.assist

import android.app.assist.AssistStructure
import android.text.InputType
import android.view.View
import io.github.typing233.superaide.core.screen.Box
import io.github.typing233.superaide.core.screen.Screen
import io.github.typing233.superaide.core.screen.UiNode
import io.github.typing233.superaide.core.screen.UiWindow

/** 默认助手拿到的屏幕结构（AssistStructure）→ 和无障碍一样的 [Screen]。没开无障碍时「问」靠它。 */
object AssistReader {
    fun read(structure: AssistStructure, width: Int, height: Int, blocked: Set<String>): Screen {
        val pkg = structure.activityComponent?.packageName.orEmpty()
        val windows = (0 until structure.windowNodeCount).map { i ->
            val w = structure.getWindowNodeAt(i)
            val box = Box(w.left, w.top, w.left + w.width, w.top + w.height)
            val nodes = mutableListOf<UiNode>()
            if (pkg !in blocked) visit(w.rootViewNode, w.left, w.top, 0, nodes)
            UiWindow(w.title?.toString().orEmpty(), pkg, "app", active = i == 0, focused = i == 0, box = box, nodes = nodes, blocked = pkg in blocked)
        }
        return Screen(System.currentTimeMillis(), width, height, windows, source = "assist")
    }

    private fun visit(n: AssistStructure.ViewNode?, ox: Int, oy: Int, depth: Int, out: MutableList<UiNode>) {
        n ?: return
        if (n.visibility != View.VISIBLE) return
        val x = ox + n.left
        val y = oy + n.top
        val text = n.text?.toString().orEmpty()
        val desc = n.contentDescription?.toString().orEmpty()
        val hint = n.hint.orEmpty()
        val cls = n.className.orEmpty()
        val variation = n.inputType and InputType.TYPE_MASK_VARIATION
        val password = n.inputType != 0 && (variation == InputType.TYPE_TEXT_VARIATION_PASSWORD ||
            variation == InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD ||
            (n.inputType and InputType.TYPE_MASK_CLASS == InputType.TYPE_CLASS_NUMBER && variation == InputType.TYPE_NUMBER_VARIATION_PASSWORD))
        val editable = cls.endsWith("EditText") || n.inputType != 0
        if (text.isNotBlank() || desc.isNotBlank() || hint.isNotBlank() || n.isClickable || editable || n.isCheckable) {
            out += UiNode(
                role = cls.substringAfterLast('.'),
                text = if (password && text.isNotEmpty()) "••••" else text,
                desc = desc,
                hint = hint,
                viewId = n.idEntry.orEmpty(),
                box = Box(x, y, x + n.width, y + n.height),
                depth = depth,
                clickable = n.isClickable,
                longClickable = n.isLongClickable,
                editable = editable,
                checkable = n.isCheckable,
                checked = n.isChecked,
                selected = n.isSelected,
                focused = n.isFocused,
                enabled = n.isEnabled,
                password = password,
            )
        }
        for (i in 0 until n.childCount) visit(n.getChildAt(i), x - n.scrollX, y - n.scrollY, depth + 1, out)
    }
}
