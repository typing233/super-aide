package io.github.typing233.superaide.update

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.provider.Settings
import io.github.typing233.superaide.BuildConfig
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.diag.Diag
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/**
 * App 内更新：查最新版 → 下载 APK → 核对校验和 → 交给系统安装（系统会弹确认）。
 * 先看官网的 latest.json（github.io 在国内通常比 github.com 稳），不行再问 GitHub；APK 也是先从官网下、不行再从 Release 下。
 */
object Updater {
    const val SITE = "https://typing233.github.io/super-aide/"
    const val RELEASES = "https://github.com/typing233/super-aide/releases/latest"
    private const val API = "https://api.github.com/repos/typing233/super-aide/releases/latest"
    private const val ACTION_INSTALLED = "io.github.typing233.superaide.UPDATE_STATUS"

    data class Release(val version: String, val urls: List<String>, val sha256: String, val size: Long)

    sealed interface State {
        data object Idle : State
        data object Checking : State
        data object UpToDate : State
        data class Available(val release: Release) : State
        data class Downloading(val release: Release, val percent: Int) : State
        data object Installing : State
        data class Failed(val message: String) : State
    }

    private val _state = MutableStateFlow<State>(State.Idle)
    val state: StateFlow<State> = _state

    private val http = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).build()
    private val json = Json { ignoreUnknownKeys = true }

    /** 当前版本（去掉 -debug / -staging） */
    val current: String get() = BuildConfig.VERSION_NAME.substringBefore('-')

    /** 版本号比大小：1.10.0 > 1.9.3 */
    fun newer(a: String, b: String): Boolean {
        val x = a.split('.').map { it.takeWhile(Char::isDigit).toIntOrNull() ?: 0 }
        val y = b.split('.').map { it.takeWhile(Char::isDigit).toIntOrNull() ?: 0 }
        for (i in 0 until maxOf(x.size, y.size)) {
            val d = (x.getOrElse(i) { 0 }) - (y.getOrElse(i) { 0 })
            if (d != 0) return d > 0
        }
        return false
    }

    suspend fun check(): State = withContext(Dispatchers.IO) {
        _state.value = State.Checking
        val release = runCatching { fromSite() }.getOrNull() ?: runCatching { fromGitHub() }.getOrNull()
        val next = when {
            release == null -> State.Failed(tr("查不到新版本信息（网络不通？）"))
            newer(release.version, current) -> State.Available(release)
            else -> State.UpToDate
        }
        _state.value = next
        next
    }

    private fun get(url: String): String = http.newCall(Request.Builder().url(url).header("User-Agent", "SuperAide").build()).execute().use {
        if (!it.isSuccessful) error("HTTP ${it.code}")
        it.body.string()
    }

    /** 官网的 latest.json：{version, android: {file, size, sha256, github}} */
    private fun fromSite(): Release? {
        val data = json.parseToJsonElement(get(SITE + "latest.json")).jsonObject
        val android = data["android"] as? JsonObject ?: return null
        val version = data.s("version") ?: return null
        val urls = listOfNotNull(android.s("file")?.let { SITE + it }, android.s("github"))
        return Release(version, urls, android.s("sha256").orEmpty(), (android["size"] as? JsonPrimitive)?.longOrNull ?: 0)
    }

    /** GitHub 的最新 Release：SuperAide.apk 加上 SHA256SUMS.txt 里它那一行 */
    private fun fromGitHub(): Release? {
        val data = json.parseToJsonElement(get(API)).jsonObject
        val version = data.s("tag_name")?.removePrefix("v") ?: return null
        val assets = data["assets"]!!.jsonArray.map { it.jsonObject }
        val apk = assets.firstOrNull { it.s("name") == "SuperAide.apk" } ?: return null
        val sums = assets.firstOrNull { it.s("name") == "SHA256SUMS.txt" }?.s("browser_download_url")?.let { runCatching { get(it) }.getOrNull() }
        val sha = sums?.lineSequence()?.map { it.trim().split(Regex("\\s+")) }?.firstOrNull { it.size == 2 && it[1] == "SuperAide.apk" }?.get(0)
        return Release(version, listOfNotNull(apk.s("browser_download_url")), sha.orEmpty(), (apk["size"] as? JsonPrimitive)?.longOrNull ?: 0)
    }

    /** 下载、核对，然后交给系统安装。没有"安装未知应用"的权限就先带用户去开 */
    suspend fun install(context: Context, release: Release) {
        if (!context.packageManager.canRequestPackageInstalls()) {
            context.startActivity(
                Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
            _state.value = State.Available(release)
            return
        }
        val file = withContext(Dispatchers.IO) { download(context, release) } ?: return
        _state.value = State.Installing
        withContext(Dispatchers.IO) {
            val installer = context.packageManager.packageInstaller
            val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
                setAppPackageName(context.packageName)
            }
            val id = installer.createSession(params)
            installer.openSession(id).use { session ->
                session.openWrite("SuperAide.apk", 0, file.length()).use { out ->
                    file.inputStream().use { it.copyTo(out) }
                    session.fsync(out)
                }
                val intent = Intent(ACTION_INSTALLED).setClass(context, StatusReceiver::class.java)
                val pending = PendingIntent.getBroadcast(context, id, intent, PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
                session.commit(pending.intentSender)
            }
        }
    }

    private fun download(context: Context, release: Release): File? {
        val dir = File(context.cacheDir, "update").apply { mkdirs() }
        val file = File(dir, "SuperAide-${release.version}.apk")
        for (url in release.urls) {
            try {
                http.newCall(Request.Builder().url(url).header("User-Agent", "SuperAide").build()).execute().use { r ->
                    if (!r.isSuccessful) error("HTTP ${r.code}")
                    val total = r.body.contentLength().takeIf { it > 0 } ?: release.size
                    val digest = MessageDigest.getInstance("SHA-256")
                    var done = 0L
                    file.outputStream().use { out ->
                        r.body.byteStream().use { input ->
                            val buf = ByteArray(64 * 1024)
                            while (true) {
                                val n = input.read(buf)
                                if (n < 0) break
                                out.write(buf, 0, n)
                                digest.update(buf, 0, n)
                                done += n
                                if (total > 0) _state.value = State.Downloading(release, (done * 100 / total).toInt())
                            }
                        }
                    }
                    val sha = digest.digest().joinToString("") { "%02x".format(it) }
                    if (release.sha256.isNotEmpty() && !sha.equals(release.sha256, ignoreCase = true)) error("校验和对不上")
                    return file
                }
            } catch (e: Exception) {
                Diag.log("update.download.failed", "$url ${e.message}")
            }
        }
        file.delete()
        _state.value = State.Failed(tr("下载失败：可以到发布页手动下载"))
        return null
    }

    /** 系统安装的结果：要用户确认就把确认界面打开 */
    class StatusReceiver : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
                PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                    @Suppress("DEPRECATION")
                    val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT) ?: return
                    context.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }
                PackageInstaller.STATUS_SUCCESS -> _state.value = State.UpToDate
                else -> {
                    val msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE).orEmpty()
                    Diag.log("update.install.failed", msg)
                    _state.value = State.Failed(tr("安装没成功：{error}", "error" to msg))
                }
            }
        }
    }

    /** 每天最多自己查一次；有新版就发一条通知（点开是设置页） */
    suspend fun dailyCheck(context: Context) {
        val prefs = context.getSharedPreferences("update", Context.MODE_PRIVATE)
        val now = System.currentTimeMillis()
        if (now - prefs.getLong("checked", 0) < 24 * 3600_000L) return
        prefs.edit().putLong("checked", now).apply()
        val s = check()
        if (s is State.Available && prefs.getString("notified", "") != s.release.version) {
            prefs.edit().putString("notified", s.release.version).apply()
            notifyAvailable(context, s.release.version)
        }
    }

    private fun notifyAvailable(context: Context, version: String) {
        if (context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) return
        val nm = context.getSystemService(android.app.NotificationManager::class.java)
        if (nm.getNotificationChannel("update") == null) {
            nm.createNotificationChannel(android.app.NotificationChannel("update", tr("更新"), android.app.NotificationManager.IMPORTANCE_DEFAULT))
        }
        val open = PendingIntent.getActivity(context, 0, Intent(context, io.github.typing233.superaide.MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE)
        nm.notify(2, android.app.Notification.Builder(context, "update")
            .setSmallIcon(io.github.typing233.superaide.R.drawable.ic_tile)
            .setContentTitle(tr("超级助手 {version} 可以更新了", "version" to version))
            .setContentText(tr("点开设置，一键更新"))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build())
    }

    private fun JsonObject.s(k: String) = (this[k] as? JsonPrimitive)?.contentOrNull
}
