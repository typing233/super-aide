package io.github.typing233.superaide.a11y

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.provider.Settings
import io.github.typing233.superaide.diag.Diag

/**
 * 无障碍自愈。国产系统清理后台、划掉最近任务都会强行停止 App，强行停止会把我们从"已开启的无障碍服务"里删掉。
 * 在电脑上执行一次 `adb shell pm grant <包名> android.permission.WRITE_SECURE_SETTINGS` 之后，
 * App 每次起来（打开设置、点通知栏开关、召唤）都能自己把无障碍加回去。
 */
object SelfHeal {
    fun canHeal(context: Context) =
        context.checkSelfPermission(Manifest.permission.WRITE_SECURE_SETTINGS) == PackageManager.PERMISSION_GRANTED

    fun component(context: Context) = ComponentName(context, AideAccessibilityService::class.java).flattenToString()

    fun enabled(context: Context): Boolean {
        val list = Settings.Secure.getString(context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES).orEmpty()
        return list.split(':').any { it.equals(component(context), ignoreCase = true) }
    }

    /** 没开就加回去（有权限才行）。返回现在是否开着。 */
    fun ensure(context: Context): Boolean {
        if (enabled(context)) return true
        if (!canHeal(context)) return false
        return runCatching {
            val cr = context.contentResolver
            val list = Settings.Secure.getString(cr, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES).orEmpty()
                .split(':').filter { it.isNotBlank() }
            Settings.Secure.putString(cr, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES, (list + component(context)).joinToString(":"))
            Settings.Secure.putInt(cr, Settings.Secure.ACCESSIBILITY_ENABLED, 1)
            Diag.log("a11y.healed")
            true
        }.getOrElse { Diag.error("a11y.heal", it); false }
    }
}
