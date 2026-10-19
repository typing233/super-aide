package io.github.typing233.superaide.system

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import java.util.concurrent.ConcurrentHashMap

/** 手机上能打开的 App：名字 ↔ 包名，打开 App / 网址。 */
class Apps(private val context: Context) {
    private val labels = ConcurrentHashMap<String, String>()

    fun label(pkg: String): String = labels.getOrPut(pkg) {
        runCatching {
            val pm = context.packageManager
            pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
        }.getOrDefault(pkg)
    }

    data class App(val label: String, val pkg: String)

    fun launchable(): List<App> {
        val pm = context.packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return pm.queryIntentActivities(intent, PackageManager.ResolveInfoFlags.of(0))
            .map { App(it.loadLabel(pm).toString(), it.activityInfo.packageName) }
            .distinctBy { it.pkg }
            .sortedBy { it.label }
    }

    /** 名字或包名 → 包名：先精确，再包含 */
    fun resolve(query: String): App? {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return null
        val all = launchable()
        return all.firstOrNull { it.pkg.lowercase() == q || it.label.lowercase() == q }
            ?: all.firstOrNull { q in it.label.lowercase() || it.label.lowercase() in q && it.label.length >= 2 }
            ?: all.firstOrNull { q in it.pkg.lowercase() }
    }

    fun open(pkg: String): Boolean {
        val intent = context.packageManager.getLaunchIntentForPackage(pkg) ?: return false
        return runCatching {
            context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED))
            true
        }.getOrDefault(false)
    }

    fun openUrl(url: String): Boolean = runCatching {
        val uri = Uri.parse(if ("://" in url || url.startsWith("tel:") || url.startsWith("mailto:")) url else "https://$url")
        context.startActivity(Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    }.getOrDefault(false)
}
