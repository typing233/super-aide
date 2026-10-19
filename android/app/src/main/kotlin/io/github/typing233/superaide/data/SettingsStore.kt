package io.github.typing233.superaide.data

import android.content.Context
import io.github.typing233.superaide.core.config.Settings
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.io.File

/** 设置存成 files/settings.json；改动立即生效（界面订阅 state）。 */
class SettingsStore(context: Context) {
    private val file = File(context.filesDir, "settings.json")
    private val _state = MutableStateFlow(load())
    val state: StateFlow<Settings> = _state
    val value: Settings get() = _state.value

    @Synchronized
    fun update(change: (Settings) -> Settings) {
        val next = change(_state.value)
        val tmp = File(file.parentFile, "settings.json.tmp")
        tmp.writeText(Settings.json.encodeToString(Settings.serializer(), next))
        tmp.renameTo(file)
        _state.value = next
    }

    private fun load(): Settings = runCatching {
        Settings.json.decodeFromString(Settings.serializer(), file.readText())
    }.getOrDefault(Settings())
}
