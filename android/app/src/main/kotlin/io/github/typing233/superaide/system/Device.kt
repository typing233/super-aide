package io.github.typing233.superaide.system

import android.content.ClipboardManager
import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Build
import java.util.Locale

/** 环境里的"手机"一行和剪贴板。 */
object Device {
    fun line(context: Context): String {
        val parts = mutableListOf("${Build.BRAND} ${Build.MODEL}", "Android ${Build.VERSION.RELEASE}")
        prop("ro.build.version.magic")?.let { parts += it }
        runCatching {
            val battery = context.getSystemService(BatteryManager::class.java).getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
            if (battery in 0..100) parts += "电量 $battery%"
        }
        runCatching {
            val cm = context.getSystemService(ConnectivityManager::class.java)
            val caps = cm.getNetworkCapabilities(cm.activeNetwork)
            parts += when {
                caps == null -> "没联网"
                caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "Wi‑Fi"
                caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "移动数据"
                else -> "已联网"
            }
            if (caps?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true) parts += "VPN"
        }
        parts += "系统语言 ${Locale.getDefault().toLanguageTag()}"
        return parts.joinToString(" · ")
    }

    /** 剪贴板只能在我们的窗口有焦点时读（安卓 10 起），读不到就空 */
    fun clipboard(context: Context): String = runCatching {
        val clip = context.getSystemService(ClipboardManager::class.java).primaryClip ?: return ""
        if (clip.itemCount == 0) "" else clip.getItemAt(0).coerceToText(context).toString()
    }.getOrDefault("")

    private fun prop(name: String): String? = runCatching {
        val cls = Class.forName("android.os.SystemProperties")
        (cls.getMethod("get", String::class.java).invoke(null, name) as String).takeIf { it.isNotBlank() }
    }.getOrNull()
}
