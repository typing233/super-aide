package io.github.typing233.superaide.core.events

/**
 * 和桌面版同一套事件（engines/base.py 的 Event）：
 * route（谁来答）/ status（一行进度，transient 的不算步骤）/ new_message / delta（回答增量）/
 * retract（前面的字是调用工具前的旁白，清掉）/ error / done（这一轮结束）。
 * 安卓版多一个 file（助手在工作区里生成或更新了文件，text 是相对路径）。
 */
data class Event(val type: String, val text: String = "", val data: Map<String, Any?> = emptyMap()) {
    companion object {
        fun route(service: String, model: String, effort: String, reason: String) =
            Event("route", "", mapOf("engine" to service, "model" to model, "effort" to effort, "reason" to reason))

        fun status(text: String, tool: String? = null, transient: Boolean = false) =
            Event("status", text, buildMap {
                if (tool != null) put("tool", tool)
                if (transient) put("transient", true)
            })

        fun delta(text: String) = Event("delta", text)
        val newMessage = Event("new_message")
        val retract = Event("retract")
        fun error(text: String) = Event("error", text)
        fun done(data: Map<String, Any?>) = Event("done", "", data)
        fun file(path: String, bytes: Long) = Event("file", path, mapOf("bytes" to bytes))
    }
}
