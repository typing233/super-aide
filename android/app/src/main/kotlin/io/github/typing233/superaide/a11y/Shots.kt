package io.github.typing233.superaide.a11y

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import java.io.ByteArrayOutputStream

/** 截图的缩放、标号和编码。标号的样子和桌面版一样：品红细框，左上角一个实心编号牌。 */
object Shots {
    private val MARK = Color.rgb(255, 64, 129)

    fun scaled(src: Bitmap, scale: Double): Bitmap =
        if (scale >= 0.999) src
        else Bitmap.createScaledBitmap(src, (src.width * scale).toInt().coerceAtLeast(1), (src.height * scale).toInt().coerceAtLeast(1), true)

    /** 在（已缩放的）截图上画编号框。boxes：编号 → 截图坐标的框 */
    fun annotate(src: Bitmap, boxes: List<Pair<Int, RectF>>): Bitmap {
        val out = src.copy(Bitmap.Config.ARGB_8888, true)
        val canvas = Canvas(out)
        val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = MARK; style = Paint.Style.STROKE; strokeWidth = 2f }
        val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = MARK; style = Paint.Style.FILL }
        val text = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = (out.width / 48f).coerceIn(11f, 18f)
            isFakeBoldText = true
        }
        for ((id, r) in boxes) {
            canvas.drawRect(r, stroke)
            val label = id.toString()
            val w = text.measureText(label) + 6
            val h = text.textSize + 4
            val top = (r.top - h).coerceAtLeast(0f)
            canvas.drawRect(r.left, top, r.left + w, top + h, fill)
            canvas.drawText(label, r.left + 3, top + h - 4, text)
        }
        return out
    }

    fun jpeg(bitmap: Bitmap, quality: Int = 82): ByteArray =
        ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.JPEG, quality, it) }.toByteArray()

    fun png(bitmap: Bitmap): ByteArray =
        ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
}
