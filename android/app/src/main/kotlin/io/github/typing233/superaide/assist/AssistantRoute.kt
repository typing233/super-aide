package io.github.typing233.superaide.assist

import android.app.role.RoleManager
import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.provider.Settings
import io.github.typing233.superaide.diag.Diag
import io.github.typing233.superaide.host.AssistActivity

/**
 * 默认助手走哪条路。正常的安卓：系统绑定我们的 VoiceInteractionService，手势打开会话窗口（还给屏幕结构和截图）。
 * MagicOS 这类系统把语音交互服务锁给自家助手（YOYO），我们被选成「数字助理应用」后系统去启动一个不存在的组件，什么都不出来。
 * 这时关掉自己的 VoiceInteractionService：用户在设置里再选一次，系统就改用透明 Activity（ACTION_ASSIST）。
 */
object AssistantRoute {
    enum class Status { NOT_HELD, SESSION, ACTIVITY, REPICK }

    private fun vis(context: Context) = ComponentName(context, AideVoiceInteractionService::class.java)

    fun held(context: Context): Boolean = runCatching {
        context.getSystemService(RoleManager::class.java).isRoleHeld(RoleManager.ROLE_ASSISTANT)
    }.getOrDefault(false)

    private fun visEnabled(context: Context) =
        context.packageManager.getComponentEnabledSetting(vis(context)) != PackageManager.COMPONENT_ENABLED_STATE_DISABLED

    /** 系统设置里记的助手组件；读不到（有的系统不让读）返回 null */
    private fun assistantSetting(context: Context): String? =
        runCatching { Settings.Secure.getString(context.contentResolver, "assistant") }.getOrNull()

    fun status(context: Context): Status {
        if (!held(context)) return Status.NOT_HELD
        if (AideVoiceInteractionService.active != null) return Status.SESSION
        val setting = assistantSetting(context)
        if (setting != null && setting.endsWith(AssistActivity::class.java.name)) return Status.ACTIVITY
        return if (visEnabled(context)) Status.SESSION else Status.REPICK
    }

    /**
     * App 起来一会儿以后调用：我们是默认助手、组件也开着，系统却没绑定（active 还是空）→ 关掉它，等用户再选一次。
     */
    fun adapt(context: Context) {
        if (!held(context) || AideVoiceInteractionService.active != null || !visEnabled(context)) return
        Diag.log("assist.route", "VoiceInteractionService 没被系统绑定，改走 Activity")
        context.packageManager.setComponentEnabledSetting(vis(context), PackageManager.COMPONENT_ENABLED_STATE_DISABLED, PackageManager.DONT_KILL_APP)
    }
}
