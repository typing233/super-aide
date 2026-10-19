package io.github.typing233.superaide

import android.app.StatusBarManager
import android.content.ComponentName
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.drawable.Icon
import android.os.Build
import android.os.Bundle
import android.provider.Settings as SystemSettings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.currentStateAsState
import io.github.typing233.superaide.a11y.AideAccessibilityService
import io.github.typing233.superaide.assist.AssistantRoute
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.config.ModelEntry
import io.github.typing233.superaide.core.i18n.I18n
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.core.llm.Chats
import io.github.typing233.superaide.core.llm.Effort
import io.github.typing233.superaide.core.llm.ModelProbe
import io.github.typing233.superaide.core.llm.Service
import io.github.typing233.superaide.core.llm.Wire
import io.github.typing233.superaide.core.router.Report
import io.github.typing233.superaide.run.Aide
import io.github.typing233.superaide.secure.SecretStore
import io.github.typing233.superaide.summon.AideTileService
import io.github.typing233.superaide.ui.AideTheme
import io.github.typing233.superaide.ui.LocalTokens
import io.github.typing233.superaide.update.Updater
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.net.URI
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 设置页（App 图标点进来就是它）。改动立即生效。 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        I18n.lang = Aide.uiLang()
        // 「做」进行中的通知（带停止按钮）要通知权限
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        setContent { AideTheme { SettingsScreen() } }
    }

    @Composable
    private fun SettingsScreen() {
        val t = LocalTokens.current
        val settings by AideApp.instance.settings.state.collectAsState()
        // 回到前台时刷新权限状态
        val life by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
        val resumed = life.isAtLeast(Lifecycle.State.RESUMED)
        Column(
            Modifier.fillMaxSize().background(if (t.dark) Color(0xFF111113) else Color(0xFFF5F5F7)).safeDrawingPadding()
                .verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(getString(R.string.app_name), fontSize = 26.sp, fontWeight = FontWeight.SemiBold, color = t.text)
            Section(tr("召唤方式")) {
                val a11y = resumed && AideAccessibilityService.instance != null
                val route = if (resumed) AssistantRoute.status(this@MainActivity) else AssistantRoute.Status.NOT_HELD
                Row(tr("无障碍（读屏幕、替你操作）"), if (a11y) tr("已开") else tr("去打开")) {
                    startActivity(Intent(SystemSettings.ACTION_ACCESSIBILITY_SETTINGS))
                }
                // 从浏览器装的 App，安卓 13 起要先「允许受限设置」才能开无障碍
                if (!a11y) Row(tr("开不了？到应用信息右上角的三个点里，选「允许受限设置」"), tr("应用信息")) {
                    startActivity(Intent(SystemSettings.ACTION_APPLICATION_DETAILS_SETTINGS, android.net.Uri.parse("package:$packageName")))
                }
                Row(tr("默认数字助手（长按电源键或手势）"), when (route) {
                    AssistantRoute.Status.SESSION, AssistantRoute.Status.ACTIVITY -> tr("已是")
                    AssistantRoute.Status.REPICK -> tr("再选一次")
                    AssistantRoute.Status.NOT_HELD -> tr("去设置")
                }) { openAssistantSettings() }
                Row(tr("通知栏快捷开关"), tr("添加")) { addTile() }
                Toggle(tr("悬浮球（点一下问，长按直接做）"), settings.bubble) { on -> AideApp.instance.settings.update { it.copy(bubble = on) } }
                Row(tr("现在试一下"), "›") { Aide.summon(this@MainActivity, Mode.ASK, "settings") }
            }
            Services()
            Section(tr("外观")) {
                Choice(tr("主题"), listOf("system" to tr("跟随系统"), "light" to tr("浅色"), "dark" to tr("深色")), settings.theme) { v ->
                    AideApp.instance.settings.update { it.copy(theme = v) }
                }
                Choice(tr("语言"), listOf("system" to tr("跟随系统"), "zh" to "中文", "en" to "English"), settings.language) { v ->
                    AideApp.instance.settings.update { it.copy(language = v) }
                    I18n.lang = Aide.uiLang()
                    recreate()
                }
            }
            RouterReport()
            HistoryList()
            UpdateSection()
        }
    }

    @Composable
    private fun Services() {
        val t = LocalTokens.current
        val settings by AideApp.instance.settings.state.collectAsState()
        var report by remember { mutableStateOf("") }
        var adding by remember { mutableStateOf(false) }
        val scope = rememberCoroutineScope()
        Section(tr("模型服务")) {
            if (settings.services.isEmpty()) Text(tr("还没有模型服务：加一个才能用。"), color = t.text2, fontSize = 14.sp, modifier = Modifier.padding(12.dp))
            for (svc in settings.services) {
                Text("${svc.name} · ${URI(svc.baseUrl).host ?: svc.baseUrl}", color = t.text, fontWeight = FontWeight.Medium,
                    modifier = Modifier.padding(start = 12.dp, top = 10.dp))
                for (m in settings.models.filter { it.service == svc.id }) {
                    Toggle(m.id, m.enabled) { on ->
                        AideApp.instance.settings.update { s -> s.copy(models = s.models.map { if (it == m) it.copy(enabled = on) else it }) }
                    }
                }
            }
            Row(tr("测试连接"), "›") {
                report = tr("测试中…")
                scope.launch { report = probeAll() }
            }
            if (report.isNotBlank()) Text(report, color = t.text2, fontSize = 12.sp, modifier = Modifier.padding(12.dp))
            Row(tr("添加服务"), if (adding) "×" else "+") { adding = !adding }
            if (adding) AddService { adding = false }
        }
    }

    @Composable
    private fun AddService(done: () -> Unit) {
        var name by remember { mutableStateOf("") }
        var base by remember { mutableStateOf("") }
        var key by remember { mutableStateOf("") }
        var models by remember { mutableStateOf("") }
        var wire by remember { mutableStateOf(Wire.ANTHROPIC) }
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Choice(tr("协议"), listOf(Wire.ANTHROPIC.name to "Anthropic", Wire.OPENAI_RESPONSES.name to "OpenAI Responses",
                Wire.OPENAI_CHAT.name to "OpenAI Chat"), wire.name) { wire = Wire.valueOf(it) }
            OutlinedTextField(name, { name = it }, label = { Text(tr("名字")) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(base, { base = it }, label = { Text(tr("服务地址")) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(key, { key = it }, label = { Text("API key") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(models, { models = it }, label = { Text(tr("模型（逗号分隔）")) }, modifier = Modifier.fillMaxWidth())
            Row(tr("保存"), "✓") {
                val ids = models.split(Regex("[,，;；\\s]+")).filter { it.isNotBlank() }
                if (base.isBlank() || key.isBlank() || ids.isEmpty()) return@Row
                val id = "s" + System.currentTimeMillis()
                AideApp.instance.secrets.put(SecretStore.serviceKey(id), key.trim())
                AideApp.instance.settings.update { s ->
                    s.copy(
                        services = s.services + Service(id, name.ifBlank { URI(base.trim()).host ?: base }, wire, base.trim(), bearer = wire == Wire.ANTHROPIC && !base.contains("anthropic.com")),
                        models = s.models + ids.map { ModelEntry(id, it, vision = !it.contains("deepseek")) },
                    )
                }
                done()
            }
        }
    }

    /** 路由表现：越用越省的同时质量有没有变差（数据少时不显示） */
    @Composable
    private fun RouterReport() {
        val t = LocalTokens.current
        var built by remember { mutableStateOf<Report.Built?>(null) }
        LaunchedEffect(Unit) {
            built = withContext(Dispatchers.Default) {
                runCatching {
                    Report.build(Aide.routing.router, java.io.File(filesDir, "router/decisions.jsonl"), System.currentTimeMillis() / 1000.0)
                }.getOrNull()
            }
        }
        val b = built ?: return
        if (b.current.tasks == 0) return
        val c = b.current
        Section(tr("路由表现")) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(b.verdict, color = t.text, fontSize = 14.sp)
                Text(
                    listOfNotNull(
                        tr("最近 {days} 天 {n} 次", "days" to Report.WINDOW_DAYS, "n" to c.tasks),
                        c.problemRate?.let { tr("出问题 {p}%", "p" to (it * 100).toInt()) },
                        c.saving?.let { tr("省了约 {p}%", "p" to (it * 100).toInt()) },
                        if (c.duels > 0) tr("后台对比 {n} 次里 {good} 次一样好", "n" to c.duels, "good" to c.duelsAsGood) else null,
                    ).joinToString(" · "),
                    color = t.text3, fontSize = 12.sp,
                )
                for (l in b.learned) {
                    Text(
                        if (l["change"] == "cheaper") tr("{label}：用 {use}，不用 {instead}（一样能办成，更省）", "label" to l["label"], "use" to l["use"], "instead" to l["instead"])
                        else tr("{label}：换成更可靠的 {use}（{instead} 没办成过）", "label" to l["label"], "use" to l["use"], "instead" to l["instead"]),
                        color = t.text2, fontSize = 13.sp,
                    )
                }
            }
        }
    }

    @Composable
    private fun HistoryList() {
        val t = LocalTokens.current
        val entries = remember { Aide.history.list().take(20) }
        if (entries.isEmpty()) return
        val fmt = remember { SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()) }
        Section(tr("历史")) {
            for (e in entries) {
                val first = e.turns.firstOrNull() ?: continue
                Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp)) {
                    Text(first.question.lineSequence().first().take(60), color = t.text, fontSize = 14.sp, maxLines = 1)
                    Text("${fmt.format(Date(e.time))} · ${e.app} · ${first.model} · ${first.effort}" + if (first.ok) "" else " · ✗",
                        color = t.text3, fontSize = 12.sp)
                }
            }
        }
    }

    /** 版本和更新 */
    @Composable
    private fun UpdateSection() {
        val st by Updater.state.collectAsState()
        val scope = rememberCoroutineScope()
        LaunchedEffect(Unit) { if (st is Updater.State.Idle && !BuildConfig.DEBUG) Updater.check() }
        val s = st
        val status = when (s) {
            Updater.State.Idle -> tr("检查更新")
            Updater.State.Checking -> tr("正在检查…")
            Updater.State.UpToDate -> tr("已是最新")
            is Updater.State.Available -> tr("更新到 {version}", "version" to s.release.version)
            is Updater.State.Downloading -> tr("正在下载 {percent}%", "percent" to s.percent)
            Updater.State.Installing -> tr("正在安装…")
            is Updater.State.Failed -> tr("打开发布页")
        }
        Section(tr("版本")) {
            Row(Updater.current, status) {
                when (s) {
                    is Updater.State.Available -> scope.launch { Updater.install(this@MainActivity, s.release) }
                    is Updater.State.Failed -> startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(Updater.RELEASES)))
                    Updater.State.Idle, Updater.State.UpToDate -> scope.launch { Updater.check() }
                    else -> Unit
                }
            }
            if (s is Updater.State.Failed) Text(s.message, color = LocalTokens.current.err, fontSize = 12.sp,
                modifier = Modifier.padding(start = 12.dp, end = 12.dp, bottom = 10.dp))
        }
    }

    @Composable
    private fun Section(title: String, content: @Composable () -> Unit) {
        val t = LocalTokens.current
        Column {
            Text(title, color = t.text2, fontSize = 13.sp, modifier = Modifier.padding(start = 4.dp, bottom = 6.dp))
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(if (t.dark) Color(0xFF1C1C1F) else Color.White)) {
                content()
            }
        }
    }

    @Composable
    private fun Row(label: String, value: String, onClick: () -> Unit) {
        val t = LocalTokens.current
        androidx.compose.foundation.layout.Row(
            Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(label, color = t.text, fontSize = 15.sp, modifier = Modifier.weight(1f))
            Text(value, color = t.askA, fontSize = 15.sp)
        }
    }

    @Composable
    private fun Toggle(label: String, on: Boolean, onChange: (Boolean) -> Unit) {
        val t = LocalTokens.current
        androidx.compose.foundation.layout.Row(
            Modifier.fillMaxWidth().clickable { onChange(!on) }.padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(label, color = t.text, fontSize = 15.sp, modifier = Modifier.weight(1f))
            Switch(on, onChange)
        }
    }

    @Composable
    private fun Choice(label: String, options: List<Pair<String, String>>, value: String, onPick: (String) -> Unit) {
        val t = LocalTokens.current
        Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
            Text(label, color = t.text2, fontSize = 13.sp)
            Spacer(Modifier.height(6.dp))
            androidx.compose.foundation.layout.Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for ((v, name) in options) {
                    val sel = v == value
                    Text(name, color = if (sel) Color.White else t.text, fontSize = 14.sp,
                        modifier = Modifier.clip(RoundedCornerShape(999.dp)).background(if (sel) t.askA else t.hover)
                            .clickable { onPick(v) }.padding(horizontal = 12.dp, vertical = 6.dp))
                }
            }
        }
    }

    private fun openAssistantSettings() {
        val tries = listOf(
            Intent("android.settings.MANAGE_DEFAULT_APPS_SETTINGS"),
            Intent(SystemSettings.ACTION_VOICE_INPUT_SETTINGS),
            Intent(SystemSettings.ACTION_SETTINGS),
        )
        for (i in tries) if (runCatching { startActivity(i) }.isSuccess) return
    }

    private fun addTile() {
        if (Build.VERSION.SDK_INT >= 33) {
            getSystemService(StatusBarManager::class.java).requestAddTileService(
                ComponentName(this, AideTileService::class.java),
                getString(R.string.app_name),
                Icon.createWithResource(this, R.drawable.ic_tile),
                mainExecutor,
            ) {}
        }
    }

    private suspend fun probeAll(): String {
        val app = AideApp.instance
        val settings = app.settings.value
        if (settings.services.isEmpty()) return tr("还没有模型服务")
        val lines = mutableListOf<String>()
        for (m in settings.models.filter { it.enabled }) {
            val service = settings.service(m.service) ?: continue
            val key = app.secrets.get(SecretStore.serviceKey(service.id)) ?: continue
            val r = ModelProbe.run({ system, tools -> Chats.open(service, key, m.id, Effort.LOW, system, tools, m.vision) },
                if (m.vision) redJpeg() else null)
            lines += "${m.id}：" + (if (r.ok) tr("能用") + " · ${r.totalMs}ms" + (if (m.vision && !r.vision) " · " + tr("没认出图") else "")
            else tr("不能用") + " · ${r.error}")
        }
        return lines.joinToString("\n")
    }

    private fun redJpeg(): ByteArray {
        val bmp = Bitmap.createBitmap(64, 64, Bitmap.Config.ARGB_8888).apply { eraseColor(android.graphics.Color.RED) }
        return ByteArrayOutputStream().also { bmp.compress(Bitmap.CompressFormat.JPEG, 90, it) }.toByteArray()
    }
}
