package io.github.typing233.superaide.a11y

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RectF
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.WindowManager

/**
 * point 工具：在用户屏幕上圈出要点的地方（编号和回答里的步骤对应）。
 * 无障碍浮层、不可触摸，不挡用户操作；到时间或收起回答时清掉。
 */
class Marks(private val service: AideAccessibilityService) {
    data class Mark(val box: RectF, val label: String)

    private val main = Handler(Looper.getMainLooper())
    private var view: View? = null
    private val clear = Runnable { hide() }

    fun show(marks: List<Mark>, seconds: Double) = main.post {
        hide()
        val v = MarksView(service, marks)
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply { layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS }
        runCatching { service.getSystemService(WindowManager::class.java).addView(v, lp) }.onSuccess {
            view = v
            main.postDelayed(clear, (seconds.coerceIn(3.0, 300.0) * 1000).toLong())
        }
    }

    fun hide() {
        main.removeCallbacks(clear)
        view?.let { v -> runCatching { service.getSystemService(WindowManager::class.java).removeView(v) } }
        view = null
    }

    private class MarksView(context: Context, private val marks: List<Mark>) : View(context) {
        private val accent = Color.rgb(91, 140, 255)
        private val density = context.resources.displayMetrics.density
        private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = accent; style = Paint.Style.STROKE; strokeWidth = 3 * density }
        private val badge = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = accent }
        private val badgeText = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; textSize = 13 * density; isFakeBoldText = true; textAlign = Paint.Align.CENTER }
        private val labelBg = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(235, 27, 27, 31) }
        private val labelText = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; textSize = 13 * density }

        override fun onDraw(canvas: Canvas) {
            val pad = 4 * density
            val r = 10 * density
            // 窗口铺满全屏，坐标换成相对窗口的
            val loc = IntArray(2).also(::getLocationOnScreen)
            marks.forEachIndexed { i, m ->
                val box = RectF(m.box.left - loc[0] - pad, m.box.top - loc[1] - pad, m.box.right - loc[0] + pad, m.box.bottom - loc[1] + pad)
                canvas.drawRoundRect(box, r, r, ring)
                val cx = box.left
                val cy = box.top
                canvas.drawCircle(cx, cy, 11 * density, badge)
                canvas.drawText("${i + 1}", cx, cy + 4.5f * density, badgeText)
                if (m.label.isNotBlank()) {
                    val w = labelText.measureText(m.label) + 16 * density
                    val h = 26 * density
                    val left = box.left.coerceIn(8 * density, width - w - 8 * density)
                    val top = if (box.bottom + h + 6 * density < height) box.bottom + 6 * density else box.top - h - 6 * density
                    canvas.drawRoundRect(RectF(left, top, left + w, top + h), h / 2, h / 2, labelBg)
                    canvas.drawText(m.label, left + 8 * density, top + h / 2 + 4.5f * density, labelText)
                }
            }
        }
    }
}
