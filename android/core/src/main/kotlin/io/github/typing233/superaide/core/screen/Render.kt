package io.github.typing233.superaide.core.screen

import io.github.typing233.superaide.core.redact.Redact
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** 召唤那一刻的屏幕 → 首条消息里的"提问时的环境"（文字优先，逐字原文）。 */
object EnvText {
    private const val PER_WINDOW = 12_000
    private const val TOTAL = 40_000
    private val time = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm EEEE", Locale.CHINA)
    private val clock = DateTimeFormatter.ofPattern("HH:mm")

    class Extras(
        /** 包名 → App 名 */
        val label: (String) -> String = { it },
        /** 品牌、型号、安卓版本、电量、网络等一行 */
        val device: String = "",
        val clipboard: String = "",
        val zone: ZoneId = ZoneId.systemDefault(),
    )

    /** 没有屏幕可读（在超级助手自己的对话页里问的、无障碍没开）：只给时间、手机和一句说明 */
    fun bare(now: Long, x: Extras = Extras(), note: String): String = buildString {
        appendLine("时间：" + time.format(Instant.ofEpochMilli(now).atZone(x.zone)))
        if (x.device.isNotBlank()) appendLine("手机：${x.device}")
        if (x.clipboard.isNotBlank()) appendLine("剪贴板：<clipboard>${Redact.apply(x.clipboard.take(500))}</clipboard>")
        append(note)
    }

    fun render(screen: Screen, x: Extras = Extras()): String {
        val out = StringBuilder()
        out.appendLine("时间：" + time.format(Instant.ofEpochMilli(screen.time).atZone(x.zone)))
        val front = screen.windows.firstOrNull { it.type == "app" && it.active } ?: screen.windows.firstOrNull { it.type == "app" }
        if (front != null) {
            out.append("前台：${x.label(front.pkg)}（${front.pkg}）")
            if (front.title.isNotBlank() && front.title != x.label(front.pkg)) out.append("「${front.title}」")
            if (front.blocked) out.append("（隐私名单，未采集）")
            out.appendLine()
        }
        if (x.device.isNotBlank()) out.appendLine("手机：${x.device}")
        if (x.clipboard.isNotBlank()) out.appendLine("剪贴板：<clipboard>${Redact.apply(x.clipboard.take(500))}</clipboard>")
        if (screen.notices.isNotEmpty()) {
            out.appendLine("最近的通知（新的在前）：")
            for (n in screen.notices.sortedByDescending { it.time }.take(10)) {
                val at = clock.format(Instant.ofEpochMilli(n.time).atZone(x.zone))
                out.appendLine("- $at ${x.label(n.pkg)}：${Redact.apply(n.text.take(200))}")
            }
        }
        out.appendLine()
        out.appendLine("【屏幕上的文字】召唤那一刻，按窗口从上到下（逐字原文，包括已加载但滚出屏幕的部分）：")
        var budget = TOTAL
        for (w in screen.windows) {
            if (w.type == "ime") continue
            out.appendLine("== ${x.label(w.pkg)}（${w.pkg}）${typeNote(w)} ==")
            if (w.blocked) { out.appendLine("（隐私名单里的 App，没有读取内容）"); continue }
            if (w.opaque) out.appendLine(if (w.nodes.isEmpty()) OPAQUE_BLANK else OPAQUE_OCR)
            val text = windowText(w).take(minOf(PER_WINDOW, budget))
            budget -= text.length
            if (!w.opaque || text.isNotBlank()) out.appendLine(text.ifBlank { "（这个窗口没有交出文字，看截图）" })
            if (budget <= 0) { out.appendLine("……（文字太多，后面的没列出，可以用 read 工具读）"); break }
        }
        return out.toString().trimEnd()
    }

    private fun typeNote(w: UiWindow) = when (w.type) {
        "system" -> "系统界面"
        "overlay" -> "浮层"
        else -> if (w.active) "当前窗口" else ""
    }

    /** 一个窗口的全部文字，一个元素一行；相邻重复的行只留一行。截图识别的行前面标上靠左/靠右。 */
    fun windowText(w: UiWindow): String {
        val lines = mutableListOf<String>()
        for (n in w.nodes) {
            val line = (if (n.ocr) side(n.box, w.box) + n.text else lineOf(n)) ?: continue
            if (lines.lastOrNull() != line) lines += line
        }
        return Redact.apply(lines.joinToString("\n"))
    }

    /** 截图识别的一行在窗口里靠哪边：聊天里靠左一般是对方说的，靠右是自己发的 */
    fun side(b: Box, win: Box): String {
        val w = win.w.takeIf { it > 0 } ?: return ""
        val left = (b.l - win.l).toDouble() / w
        val right = (win.r - b.r).toDouble() / w
        val center = (b.cx - win.l).toDouble() / w
        return when {
            center < 0.45 && left < 0.3 && right > 0.2 -> "左｜"
            center > 0.55 && right < 0.3 && left > 0.2 -> "右｜"
            else -> ""
        }
    }

    const val OPAQUE_OCR = "（这个 App 不让无障碍读界面，下面是截图文字识别（OCR）的结果：个别字可能认错，没有字的图标、输入框不在里面。" +
        "按位置从上到下排；「左｜」「右｜」是这一行靠左还是靠右，聊天里靠左一般是对方说的，靠右是自己发的）"
    const val OPAQUE_BLANK = "（这个 App 不让无障碍读界面，也没能从截图里识别出文字：只能看截图）"

    private fun lineOf(n: UiNode): String? {
        val label = when {
            n.text.isNotBlank() && n.desc.isNotBlank() && n.desc != n.text -> "${n.text}（${n.desc}）"
            n.text.isNotBlank() -> n.text
            n.desc.isNotBlank() -> "［${n.desc}］"
            else -> ""
        }
        val line = when {
            n.password -> "✎ （密码框，内容不读）"
            n.editable -> "✎ " + label.ifBlank { "（空）" } + (if (n.hint.isNotBlank() && n.hint != n.text) "  提示：${n.hint}" else "")
            n.checkable -> (if (n.checked) "☑ " else "☐ ") + label.ifBlank { n.hint }
            n.items > 0 -> "（列表，共 ${n.items} 项；下面只有已加载的部分）" + (if (label.isNotBlank()) " $label" else "")
            else -> label
        }
        if (line.isBlank()) return null
        return line + (if (n.selected) "（已选中）" else "") + (if (!n.enabled) "（不可用）" else "")
    }
}

/**
 * observe_screen 给模型看的文字版：每个能操作的元素一行，编号和截图上的标记一致，坐标是截图像素。
 * 对应桌面版 cu/observe.py 的 describe()。
 */
class Observation(val screen: Screen, val scale: Double, val shotW: Int, val shotH: Int) {
    /** 编号 → (窗口下标, 节点下标) */
    data class Ref(val id: Int, val window: Int, val node: Int, val name: String)

    val refs = mutableListOf<Ref>()

    fun node(ref: Ref): UiNode = screen.windows[ref.window].nodes[ref.node]
    fun byId(id: Int): Ref? = refs.firstOrNull { it.id == id }

    /** 节点中心换算成截图坐标 */
    fun toShot(b: Box): Pair<Int, Int> =
        ((b.cx * scale).toInt().coerceIn(0, shotW - 1)) to ((b.cy * scale).toInt().coerceIn(0, shotH - 1))

    fun toScreen(x: Int, y: Int): Pair<Float, Float> = (x / scale).toFloat() to (y / scale).toFloat()

    fun build(label: (String) -> String, limit: Int = LIMIT): String {
        refs.clear()
        val lines = mutableListOf<String>()
        val front = screen.windows.firstOrNull { it.type == "app" && it.active } ?: screen.windows.firstOrNull()
        lines += "前台：" + (front?.let { "${label(it.pkg)}（${it.pkg}）" } ?: "（无）") + "  截图 ${shotW}×${shotH}，下面的坐标都按这张截图"
        screen.windows.forEachIndexed { wi, w ->
            if (w.type == "ime" || w.blocked) return@forEachIndexed
            w.nodes.forEachIndexed { ni, n ->
                if ((n.actionable() || n.ocr) && !n.box.isEmpty()) refs += Ref(refs.size + 1, wi, ni, nameOf(w.nodes, ni))
            }
        }
        screen.windows.firstOrNull { it.opaque && !it.blocked }?.let { w ->
            lines += if (w.nodes.isEmpty()) "${label(w.pkg)} 不让无障碍读界面，也没能从截图里识别出文字：看截图，用截图坐标 x、y 操作。"
            else "${label(w.pkg)} 不让无障碍读界面：标 OCR 的是从截图里识别出的文字（位置准，个别字可能认错），用它的编号就是点那个位置；" +
                "图标、输入框这类没有字的地方看截图，用截图坐标 x、y。输入文字：先点输入框，再 type（不给 id），字会进当前有焦点的输入框。"
        }
        // 能操作的太少（自绘界面、网页里的纯文字链接等）：把有字的元素也编上号
        if (refs.size < FEW) screen.windows.forEachIndexed { wi, w ->
            if (w.type == "ime" || w.blocked) return@forEachIndexed
            w.nodes.forEachIndexed { ni, n ->
                if (!n.actionable() && n.onScreen && !n.box.isEmpty() && (n.text.isNotBlank() || n.desc.isNotBlank())) {
                    refs += Ref(refs.size + 1, wi, ni, nameOf(w.nodes, ni))
                }
            }
        }
        screen.windows.flatMap { it.nodes }.firstOrNull { it.focused && it.editable }?.let { f ->
            refs.firstOrNull { node(it) === f }?.let { lines += "焦点：[${it.id}] ${roleOf(f)} \"${it.name}\"" }
        }
        if (refs.isEmpty()) {
            lines += "这个界面没有交出可操作的元素（自绘界面、游戏、画布等），请看截图用坐标操作。"
            return lines.joinToString("\n")
        }
        lines += "可操作的元素（[编号] 类型 \"名字\" 值/状态 @中心坐标）："
        for (r in refs.take(limit)) lines += lineOf(r)
        if (refs.size > limit) lines += "……还有 ${refs.size - limit} 个没列出，可以用 find 按名字找"
        lines += screen.windows.flatMap { it.nodes }.filter { it.items > 0 }.map { "（${it.role} 列表共 ${it.items} 项，只加载了一部分：要找的不在就 scroll 再看）" }.distinct()
        return Redact.apply(lines.joinToString("\n"))
    }

    fun lineOf(r: Ref): String {
        val n = node(r)
        val (x, y) = toShot(n.box)
        val value = if (n.editable && !n.password && n.text.isNotBlank() && n.text != r.name) " value=\"${n.text.take(80)}\"" else ""
        val states = buildList {
            if (n.focused) add("focused")
            if (!n.enabled) add("disabled")
            if (n.checkable) add(if (n.checked) "checked" else "unchecked")
            if (n.selected) add("selected")
            if (n.scrollable) add("scrollable")
            if (n.longClickable && !n.clickable) add("long-press")
            if (!n.onScreen) add("off-screen")
        }
        return "[${r.id}] ${roleOf(n)} \"${r.name}\"$value" + (if (states.isEmpty()) "" else " (${states.joinToString()})") + " @$x,$y"
    }

    /** 按名字找（包括屏幕外、不能直接操作的文字），找到的追加新编号。 */
    fun find(query: String): String {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return "要找什么？"
        val found = mutableListOf<Ref>()
        screen.windows.forEachIndexed { wi, w ->
            if (w.type == "ime" || w.blocked) return@forEachIndexed
            w.nodes.forEachIndexed { ni, n ->
                val hay = listOf(n.text, n.desc, n.hint, n.viewId).joinToString(" ").lowercase()
                if (q in hay) {
                    val existing = refs.firstOrNull { it.window == wi && it.node == ni }
                    found += existing ?: Ref(refs.size + 1, wi, ni, nameOf(w.nodes, ni)).also { refs += it }
                }
            }
        }
        if (found.isEmpty()) return "没找到「$query」。可能还没加载（列表要往下翻），或者名字不一样：看看截图。"
        return Redact.apply((listOf("找到 ${found.size} 个：") + found.take(30).map(::lineOf)).joinToString("\n"))
    }

    /** 逐字读：某个元素（及其里面的所有文字）或整个屏幕，分页。 */
    fun read(id: Int?, start: Int, max: Int): String {
        val text = if (id == null) {
            screen.windows.filter { it.type != "ime" && !it.blocked }.joinToString("\n\n") { EnvText.windowText(it) }
        } else {
            val r = byId(id) ?: return "没有编号 [$id]：编号只在最近一次观察里有效，先 observe_screen。"
            val w = screen.windows[r.window]
            val d = w.nodes[r.node].depth
            val sub = listOf(w.nodes[r.node]) + w.nodes.drop(r.node + 1).takeWhile { it.depth > d }
            EnvText.windowText(w.copy(nodes = sub))
        }
        if (start >= text.length) return "共 ${text.length} 字，start=$start 已经读完了。"
        val end = minOf(text.length, start + max)
        val rest = text.length - end
        return text.substring(start, end) + if (rest > 0) "\n\n（共 ${text.length} 字，后面还有 $rest 字：用 start=$end 接着读）" else ""
    }

    private fun roleOf(n: UiNode) = when {
        n.ocr -> "OCR"
        n.editable -> "Edit"
        n.role.isBlank() || n.role == "View" || n.role.endsWith("Layout") || n.role == "ViewGroup" -> if (n.clickable) "Item" else "View"
        else -> n.role
    }

    /** 名字：自己的文字/描述；没有就用里面的文字（可点的容器常这样） */
    private fun nameOf(nodes: List<UiNode>, i: Int): String {
        val n = nodes[i]
        if (n.password) return "密码框" + (if (n.hint.isNotBlank()) "：${n.hint.oneLine(40)}" else "")
        val own = n.text.ifBlank { n.desc }.ifBlank { n.hint }
        if (own.isNotBlank()) return own.oneLine(60)
        val inner = nodes.drop(i + 1).takeWhile { it.depth > n.depth }
            .map { it.text.ifBlank { it.desc } }.filter { it.isNotBlank() }.take(3)
        return inner.joinToString(" · ").oneLine(60).ifBlank { n.viewId.replace('_', ' ') }
    }

    private fun String.oneLine(max: Int): String {
        val s = replace(Regex("\\s+"), " ").trim()
        return if (s.length <= max) s else s.take(max - 1) + "…"
    }

    companion object {
        const val LIMIT = 220
        const val FEW = 8

        /** 截图缩放：长边 ≤1568、总像素 ≤1.15M，不放大（和桌面版一样，按 Claude 的建议） */
        fun scaleFor(w: Int, h: Int): Double =
            minOf(1.0, 1568.0 / maxOf(w, h), Math.sqrt(1_150_000.0 / (w.toDouble() * h)))
    }
}

private fun UiNode.actionable() = clickable || longClickable || editable || scrollable || checkable
