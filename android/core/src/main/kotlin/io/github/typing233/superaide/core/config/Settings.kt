package io.github.typing233.superaide.core.config

import io.github.typing233.superaide.core.llm.Effort
import io.github.typing233.superaide.core.llm.Service
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** 一个可路由的模型（属于某个服务）。 */
@Serializable
data class ModelEntry(
    val service: String,
    val id: String,
    val enabled: Boolean = true,
    val maxEffort: Effort = Effort.MAX,
    /** 收不收图片；不收的就只给文字 */
    val vision: Boolean = true,
)

@Serializable
data class Settings(
    val services: List<Service> = emptyList(),
    val models: List<ModelEntry> = emptyList(),
    /** system / light / dark */
    val theme: String = "system",
    /** system / zh / en */
    val language: String = "system",
    /** 隐私名单：这些包名的界面不读、不操作 */
    val blockedApps: List<String> = DEFAULT_BLOCKED,
    val bubble: Boolean = true,
    /** 后台对比：用更便宜的配置重答一遍，让强模型评判 */
    val shadowEval: Boolean = true,
    val shadowDaily: Int = 20,
    val setupDone: Boolean = false,
    val tourDone: Boolean = false,
) {
    fun service(id: String) = services.firstOrNull { it.id == id }

    companion object {
        val DEFAULT_BLOCKED = listOf(
            "com.x8bit.bitwarden",
            "com.agilebits.onepassword",
            "keepass2android.keepass2android",
            "com.kunzisoft.keepass.free",
            "com.lastpass.lpandroid",
        )
        val json = Json { ignoreUnknownKeys = true; encodeDefaults = true; prettyPrint = true }
    }
}
