package io.github.typing233.superaide.diag

import android.content.Context
import android.util.Log
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File

/**
 * 诊断日志：files/debug/log.jsonl，一行一条。调试时用 `adb shell run-as <包名> cat files/debug/log.jsonl` 读。
 * 不写屏幕内容和 key，只写事件、耗时和错误。
 */
object Diag {
    private const val TAG = "SuperAide"
    private const val MAX_BYTES = 1_000_000L
    private var file: File? = null

    fun init(context: Context) {
        val dir = File(context.filesDir, "debug").apply { mkdirs() }
        file = File(dir, "log.jsonl")
    }

    fun log(event: String, detail: String = "") {
        Log.i(TAG, "$event $detail")
        write(event, detail)
    }

    fun error(event: String, e: Throwable) {
        Log.e(TAG, event, e)
        write(event, e.stackTraceToString().take(4000))
    }

    @Synchronized
    private fun write(event: String, detail: String) {
        val f = file ?: return
        runCatching {
            if (f.length() > MAX_BYTES) f.renameTo(File(f.parentFile, "log.old.jsonl"))
            val line = buildJsonObject {
                put("t", System.currentTimeMillis())
                put("event", event)
                if (detail.isNotEmpty()) put("detail", detail)
            }
            f.appendText(line.toString() + "\n")
        }
    }
}
