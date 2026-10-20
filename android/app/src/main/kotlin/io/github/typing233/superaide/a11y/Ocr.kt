package io.github.typing233.superaide.a11y

import android.graphics.Bitmap
import android.os.SystemClock
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import io.github.typing233.superaide.core.screen.Box
import io.github.typing233.superaide.core.screen.Opaque
import io.github.typing233.superaide.core.screen.Opaque.withOcr
import io.github.typing233.superaide.core.screen.Screen
import io.github.typing233.superaide.core.screen.UiNode
import io.github.typing233.superaide.diag.Diag
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * 截图认字（ML Kit 中文模型，打包在 App 里：不联网、不要谷歌服务）。
 * 只给不让无障碍读界面的 App 用（比如微信），认出的每一行当成一个能点的元素。
 */
object Ocr {
    private val recognizer by lazy { TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build()) }

    /** 先把模型加载好（第一次识别要多花一秒左右） */
    suspend fun warmUp() {
        runCatching { lines(Bitmap.createBitmap(64, 64, Bitmap.Config.ARGB_8888)) }
    }

    /** 认出的每一行（屏幕坐标：bitmap 的左上角在屏幕的 dx, dy），按阅读顺序 */
    suspend fun lines(bitmap: Bitmap, dx: Int = 0, dy: Int = 0): List<UiNode> {
        val start = SystemClock.uptimeMillis()
        val result = suspendCancellableCoroutine { cont ->
            recognizer.process(InputImage.fromBitmap(bitmap, 0))
                .addOnSuccessListener { cont.resume(it) }
                .addOnFailureListener { cont.resumeWithException(it) }
        }
        val lines = result.textBlocks.flatMap { it.lines }.mapNotNull { line ->
            val r = line.boundingBox ?: return@mapNotNull null
            val text = line.text.trim()
            if (text.isEmpty()) return@mapNotNull null
            UiNode(role = "OCR", text = text, box = Box(r.left + dx, r.top + dy, r.right + dx, r.bottom + dy), ocr = true)
        }
        Diag.log("ocr", "ms=${SystemClock.uptimeMillis() - start} lines=${lines.size} size=${bitmap.width}x${bitmap.height}")
        return Opaque.order(Opaque.simplify(lines))
    }

    /**
     * 前台 App 不让无障碍读界面时，用它的截图认字补上：一个节点都没有的，直接换成认出的字；
     * 会打乱节点文字的（微信），和截图对不上就当是假的，也换掉。
     * shot 是这一刻的截图，左上角在屏幕的 (dx, dy)。fullScreen = 截的是整屏（上面可能有我们的小条、悬浮球，那些地方的字不要）。
     */
    suspend fun fill(read: ScreenReader.Result, shot: Bitmap?, fullScreen: Boolean, dx: Int = 0, dy: Int = 0): ScreenReader.Result {
        val wi = read.screen.windows.indexOfFirst { it.type == "app" && it.active }.takeIf { it >= 0 }
            ?: read.screen.windows.indexOfFirst { it.type == "app" }.takeIf { it >= 0 } ?: return read
        val w = read.screen.windows[wi]
        if (w.blocked) return read
        val blank = Opaque.blank(w)
        if (!blank && w.pkg !in Opaque.SCRAMBLERS) return read
        if (shot == null) return if (blank) read.with(wi, read.screen.withOcr(wi, emptyList()), emptyList()) else read
        val lines = runCatching { lines(shot, dx, dy) }.getOrElse { Diag.error("ocr", it); return read }
            .filter { n -> n.box.cy in w.box.t..w.box.b && n.box.cx in w.box.l..w.box.r }
            .filter { n -> !fullScreen || read.own.none { o -> n.box.cx in o.l..o.r && n.box.cy in o.t..o.b } }
        if (!blank) {
            val agree = Opaque.agreement(w.nodes, lines)
            Diag.log("ocr.check", "pkg=${w.pkg} nodes=${w.nodes.size} agree=${"%.2f".format(agree)}")
            if (agree >= 0.5) return read
        }
        return read.with(wi, read.screen.withOcr(wi, lines), List(lines.size) { null })
    }

    private fun ScreenReader.Result.with(wi: Int, screen: Screen, handles: List<android.view.accessibility.AccessibilityNodeInfo?>) =
        ScreenReader.Result(screen, this.handles.mapIndexed { i, h -> if (i == wi) handles else h }, visited, ms, own)
}
