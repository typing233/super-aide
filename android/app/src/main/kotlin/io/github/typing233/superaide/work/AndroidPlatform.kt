package io.github.typing233.superaide.work

import android.content.Context
import android.graphics.Bitmap
import android.graphics.ImageDecoder
import io.github.typing233.superaide.a11y.Ocr
import io.github.typing233.superaide.a11y.Shots
import io.github.typing233.superaide.core.work.JsFiles
import io.github.typing233.superaide.core.work.Platform
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.nio.ByteBuffer

/** 通用工具在手机上的那一半：内置浏览器、PDF、图片缩放和认字、JS 沙箱。 */
class AndroidPlatform(private val context: Context) : Platform {
    override suspend fun render(url: String) = Browser.render(context, url)

    override suspend fun pdf(file: File) = Pdfs.read(file)

    override suspend fun writePdf(markdown: String, file: File) = Pdfs.write(markdown, file)

    override suspend fun image(bytes: ByteArray): ByteArray? = withContext(Dispatchers.Default) {
        val b = decode(bytes, MAX_SIDE) ?: return@withContext null
        // 透明背景的图（PNG 图标、图表）转 JPEG 会变黑底：先铺一层白
        val flat = if (!b.hasAlpha()) b else Bitmap.createBitmap(b.width, b.height, Bitmap.Config.ARGB_8888).also {
            android.graphics.Canvas(it).apply { drawColor(android.graphics.Color.WHITE); drawBitmap(b, 0f, 0f, null) }
        }
        Shots.jpeg(flat, 85)
    }

    override suspend fun ocr(image: ByteArray): String? {
        val bmp = withContext(Dispatchers.Default) { decode(image, 2000) } ?: return null
        return runCatching { Ocr.lines(bmp).joinToString("\n") { it.text } }.getOrNull()
    }

    override suspend fun runJs(code: String, timeoutMs: Long, files: JsFiles) = JsSandbox.run(context, code, timeoutMs, files)

    companion object {
        /** 发给模型的图片最长边（再大模型也是缩了再看） */
        private const val MAX_SIDE = 1568

        /** 解码（照片的旋转方向、HEIC 都由系统处理），缩到最长边不超过 max */
        fun decode(bytes: ByteArray, max: Int): Bitmap? = runCatching {
            ImageDecoder.decodeBitmap(ImageDecoder.createSource(ByteBuffer.wrap(bytes))) { decoder, info, _ ->
                val side = maxOf(info.size.width, info.size.height)
                if (side > max) {
                    val s = max.toFloat() / side
                    decoder.setTargetSize((info.size.width * s).toInt().coerceAtLeast(1), (info.size.height * s).toInt().coerceAtLeast(1))
                }
                decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
            }
        }.getOrNull()
    }
}
