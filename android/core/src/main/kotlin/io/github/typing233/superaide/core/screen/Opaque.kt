package io.github.typing233.superaide.core.screen

/**
 * 不让无障碍读界面的 App（微信 8.0.52 以后：节点是空的，或者文字被随机打乱）。
 * 这时界面上的字只能从截图里认（OCR）；这里是和平台无关的那部分：排顺序、并进 [Screen]、判断读到的节点是不是假的。
 */
object Opaque {
    /** 已知会打乱节点文字的 App：读到了节点也要和截图对一下 */
    val SCRAMBLERS = setOf("com.tencent.mm")

    /** 这个窗口要不要靠截图认字：一个节点都没交出来的 App 窗口 */
    fun blank(w: UiWindow) = w.type == "app" && !w.blocked && w.nodes.isEmpty()

    /** 识别出的行按阅读顺序排：先按行（竖直方向重叠一半以上算同一行），同一行从左到右 */
    fun order(lines: List<UiNode>): List<UiNode> {
        val rows = mutableListOf<MutableList<UiNode>>()
        for (n in lines.sortedBy { it.box.cy }) {
            val row = rows.lastOrNull()
            val ref = row?.first()
            if (ref != null && overlap(ref.box, n.box) >= 0.5) row.add(n) else rows += mutableListOf(n)
        }
        return rows.flatMap { r -> r.sortedBy { it.box.l } }
    }

    private fun overlap(a: Box, b: Box): Double {
        val inter = minOf(a.b, b.b) - maxOf(a.t, b.t)
        return if (inter <= 0) 0.0 else inter.toDouble() / minOf(a.h, b.h).coerceAtLeast(1)
    }

    /** 把第 [window] 个窗口换成截图识别的结果 */
    fun Screen.withOcr(window: Int, lines: List<UiNode>): Screen =
        copy(windows = windows.mapIndexed { i, w -> if (i == window) w.copy(nodes = lines, opaque = true) else w })

    /**
     * 节点上的字有多少在截图里也认得出（0–1）。打乱的节点文字是从别处随机取来的，大多对不上；
     * 能比的字太少（少于 3 个节点有字）时返回 1（看不出来，就信节点）。
     */
    fun agreement(tree: List<UiNode>, ocr: List<UiNode>): Double {
        val seen = ocr.joinToString("") { norm(it.text) }
        val texts = tree.filter { it.onScreen }.map { norm(it.text.ifBlank { it.desc }) }.filter { it.length >= 2 }.distinct()
        if (texts.size < 3) return 1.0
        val grams = seen.windowed(2).toHashSet()
        val hits = texts.count { t -> t in seen || t.windowed(2).let { g -> g.count { it in grams } >= g.size * 0.6 } }
        return hits.toDouble() / texts.size
    }

    private fun norm(s: String) = s.filter { it.isLetterOrDigit() }.lowercase()

    /**
     * 翻一页以后新认出的行里，哪些是上一页没有的。页面挪了 shift 像素（往上看为正：内容往下移），
     * 上一页里有一样的字、或者在挪过去的位置上有差不多的字（同一行这次认得稍有出入、上次被屏幕边缘切掉一截），就是重复的。
     */
    fun fresh(prev: List<UiNode>, next: List<UiNode>, shift: Int, tol: Int): List<UiNode> = next.filter { n ->
        val t = norm(n.text)
        prev.none { p ->
            val q = norm(p.text)
            q == t || (Math.abs(p.box.cy + shift - n.box.cy) <= tol && similar(q, t))
        }
    }

    private fun similar(a: String, b: String): Boolean {
        if (a.isEmpty() || b.isEmpty()) return a == b
        if (a in b || b in a) return true
        val ga = a.windowed(2).toSet()
        val gb = b.windowed(2).toSet()
        if (ga.isEmpty() || gb.isEmpty()) return false
        return ga.intersect(gb).size >= minOf(ga.size, gb.size) * 0.6
    }

    /** 繁体 → 简体（逐字，OpenCC 的表） */
    private val t2s: Map<Char, Char> by lazy {
        Opaque::class.java.getResourceAsStream("/ocr/t2s.txt")!!.bufferedReader(Charsets.UTF_8).useLines { lines ->
            lines.filter { it.length == 2 && !it.startsWith("#") }.associate { it[0] to it[1] }
        }
    }
    private val tradOnly by lazy { t2s.keys - t2s.values.toSet() }
    private val simpOnly by lazy { t2s.values.toSet() - t2s.keys }

    /**
     * 认字模型会把简体字认成繁体（「通讯录」认成「通訊录」）：屏幕上简体字占多数时，把夹杂的繁体字改回简体，
     * 不然按名字找（find）对不上。整屏本来就是繁体的不动。
     */
    fun simplify(lines: List<UiNode>): List<UiNode> {
        val all = lines.joinToString("") { it.text }
        val trad = all.count { it in tradOnly }
        if (trad == 0 || trad > all.count { it in simpOnly }) return lines
        return lines.map { n -> n.copy(text = String(CharArray(n.text.length) { i -> n.text[i].let { c -> t2s[c] ?: c } })) }
    }
}
