package io.github.typing233.superaide.data

import android.content.Context
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.session.TurnRecord
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File

/** 历史记录：每段对话一个 JSON（files/history/<id>.json）。不存截图和屏幕内容。 */
class History(context: Context) {
    private val dir = File(context.filesDir, "history").apply { mkdirs() }
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    @Serializable
    data class Turn(
        val question: String, val answer: String, val ok: Boolean, val stopped: Boolean = false,
        val service: String = "", val model: String = "", val effort: String = "", val seconds: Double = 0.0,
        val tools: Int = 0, val trace: List<String> = emptyList(), val error: String? = null, val rating: Int = 0,
    )

    @Serializable
    data class Entry(val id: String, val time: Long, val mode: String, val app: String, val turns: List<Turn>)

    fun save(id: String, time: Long, mode: Mode, app: String, records: List<TurnRecord>, rating: Int = 0) {
        val entry = Entry(id, time, mode.name.lowercase(), app, records.mapIndexed { i, r ->
            Turn(r.question, r.answer, r.ok, r.stopped, r.service, r.model, r.effort.wire, r.seconds, r.tools, r.trace, r.error,
                if (i == records.lastIndex) rating else 0)
        })
        val tmp = File(dir, "$id.json.tmp")
        tmp.writeText(json.encodeToString(Entry.serializer(), entry))
        tmp.renameTo(File(dir, "$id.json"))
    }

    fun list(): List<Entry> = dir.listFiles { f -> f.name.endsWith(".json") }.orEmpty()
        .mapNotNull { f -> runCatching { json.decodeFromString(Entry.serializer(), f.readText()) }.getOrNull() }
        .sortedByDescending { it.time }

    /** 删掉：先挪进回收站，几秒内能撤销（restore），过时再清掉（purge） */
    fun delete(id: String) {
        val trash = File(dir, "trash").apply { mkdirs() }
        File(dir, "$id.json").renameTo(File(trash, "$id.json"))
    }

    fun restore(id: String) {
        File(dir, "trash/$id.json").renameTo(File(dir, "$id.json"))
    }

    fun purge(id: String) {
        File(dir, "trash/$id.json").delete()
    }

    /** 上次没来得及清的（撤销倒计时里 App 被关了）：打开历史页时清掉 */
    fun purgeAll() {
        File(dir, "trash").listFiles()?.forEach { it.delete() }
    }
}
