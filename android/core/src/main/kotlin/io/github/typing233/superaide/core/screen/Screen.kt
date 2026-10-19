package io.github.typing233.superaide.core.screen

import kotlinx.serialization.Serializable

@Serializable
data class Box(val l: Int, val t: Int, val r: Int, val b: Int) {
    val w get() = r - l
    val h get() = b - t
    val cx get() = (l + r) / 2
    val cy get() = (t + b) / 2
    fun isEmpty() = w <= 0 || h <= 0
}

/** 界面上的一个元素（无障碍节点的精简版）。 */
@Serializable
data class UiNode(
    /** 类名短名：Button、TextView、EditText… */
    val role: String,
    val text: String = "",
    val desc: String = "",
    val hint: String = "",
    val viewId: String = "",
    val box: Box,
    val depth: Int = 0,
    val clickable: Boolean = false,
    val longClickable: Boolean = false,
    val editable: Boolean = false,
    val scrollable: Boolean = false,
    val checkable: Boolean = false,
    val checked: Boolean = false,
    val selected: Boolean = false,
    val focused: Boolean = false,
    val enabled: Boolean = true,
    val password: Boolean = false,
    /** 在屏幕上看得见（滚出去的为 false） */
    val onScreen: Boolean = true,
    /** 列表的总项数（CollectionInfo），不是列表为 -1 */
    val items: Int = -1,
)

@Serializable
data class UiWindow(
    val title: String,
    val pkg: String,
    /** app / system / ime / overlay / split */
    val type: String,
    val active: Boolean,
    val focused: Boolean,
    val box: Box,
    val nodes: List<UiNode>,
    /** 在隐私名单里：没读内容 */
    val blocked: Boolean = false,
    /** 无障碍窗口 id（截某个窗口用），-1 表示不知道 */
    val id: Int = -1,
)

@Serializable
data class Notice(val time: Long, val pkg: String, val text: String)

/** 召唤那一刻屏幕的样子。 */
@Serializable
data class Screen(
    val time: Long,
    val width: Int,
    val height: Int,
    val windows: List<UiWindow>,
    val notices: List<Notice> = emptyList(),
    /** a11y（无障碍）或 assist（默认助手给的结构） */
    val source: String = "a11y",
)
