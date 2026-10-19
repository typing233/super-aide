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
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
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
import io.github.typing233.superaide.ui.HistoryPage
import io.github.typing233.superaide.ui.LessonsPage
import io.github.typing233.superaide.ui.LocalTokens
import io.github.typing233.superaide.ui.PrivacyPage
import io.github.typing233.superaide.ui.SettingsChoice
import io.github.typing233.superaide.ui.SettingsRow
import io.github.typing233.superaide.ui.SettingsSection
import io.github.typing233.superaide.ui.SettingsToggle
import io.github.typing233.superaide.ui.pageBackground
import io.github.typing233.superaide.update.Updater
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.net.URI

/** 设置页（App 图标点进来就是它）。改动立即生效；历史、经验、隐私名单是二级页面。 */
class MainActivity : ComponentActivity() {
    private enum class Page { HOME, HISTORY, LESSONS, PRIVACY }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        I18n.lang = Aide.uiLang()
        // 「做」进行中的通知（带停止按钮）要通知权限
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        setContent {
            AideTheme {
                // 转屏、换深浅色时 Activity 会重建：停在原来的页面
                var page by rememberSaveable { mutableStateOf(Page.HOME) }
                BackHandler(enabled = page != Page.HOME) { page = Page.HOME }
                val back = { page = Page.HOME }
                when (page) {
                    Page.HOME -> SettingsScreen { page = it }
                    Page.HISTORY -> HistoryPage(Aide.history, back)
                    Page.LESSONS -> LessonsPage(Aide.experience, back)
                    Page.PRIVACY -> PrivacyPage(AideApp.instance.settings, Aide.apps, back)
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        Aide.settingsOpen.value = true
    }

    override fun onStop() {
        Aide.settingsOpen.value = false
        super.onStop()
    }

    @Composable
    private fun SettingsScreen(open: (Page) -> Unit) {
        val t = LocalTokens.current
        val settings by AideApp.instance.settings.state.collectAsState()
        // 回到前台时刷新权限状态
        val life by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
        val resumed = life.isAtLeast(Lifecycle.State.RESUMED)
        Column(
            Modifier.fillMaxSize().background(pageBackground()).safeDrawingPadding()
                .verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(getString(R.string.app_name), fontSize = 26.sp, fontWeight = FontWeight.SemiBold, color = t.text)
            SettingsSection(tr("召唤方式")) {
                val a11y = resumed && AideAccessibilityService.instance != null
                val route = if (resumed) AssistantRoute.status(this@MainActivity) else AssistantRoute.Status.NOT_HELD
                SettingsRow(tr("无障碍（读屏幕、替你操作）"), if (a11y) tr("已开") else tr("去打开")) {
                    startActivity(Intent(SystemSettings.ACTION_ACCESSIBILITY_SETTINGS))
                }
                // 从浏览器装的 App，安卓 13 起要先「允许受限设置」才能开无障碍
                if (!a11y) SettingsRow(tr("开不了？到应用信息右上角的三个点里，选「允许受限设置」"), tr("应用信息")) {
                    startActivity(Intent(SystemSettings.ACTION_APPLICATION_DETAILS_SETTINGS, android.net.Uri.parse("package:$packageName")))
                }
                SettingsRow(tr("默认数字助手（长按电源键或手势）"), when (route) {
                    AssistantRoute.Status.SESSION, AssistantRoute.Status.ACTIVITY -> tr("已是")
                    AssistantRoute.Status.REPICK -> tr("再选一次")
                    AssistantRoute.Status.NOT_HELD -> tr("去设置")
                }) { openAssistantSettings() }
                SettingsRow(tr("通知栏快捷开关"), tr("添加")) { addTile() }
                SettingsToggle(tr("悬浮球（点一下问，长按直接做）"), settings.bubble) { on -> AideApp.instance.settings.update { it.copy(bubble = on) } }
                SettingsRow(tr("现在试一下"), "›") { Aide.summon(this@MainActivity, Mode.ASK, "settings") }
            }
            Services()
            SettingsSection(tr("外观")) {
                SettingsChoice(tr("主题"), listOf("system" to tr("跟随系统"), "light" to tr("浅色"), "dark" to tr("深色")), settings.theme) { v ->
                    AideApp.instance.settings.update { it.copy(theme = v) }
                }
                SettingsChoice(tr("语言"), listOf("system" to tr("跟随系统"), "zh" to "中文", "en" to "English"), settings.language) { v ->
                    AideApp.instance.settings.update { it.copy(language = v) }
                    I18n.lang = Aide.uiLang()
                    recreate()
                }
            }
            RouterReport()
            SettingsSection(tr("记录和隐私")) {
                val conversations = remember { Aide.history.list().size }
                val lessons = remember { Aide.experience.all().size }
                SettingsRow(tr("历史"), tr("{n} 条", "n" to conversations) + " ›") { open(Page.HISTORY) }
                SettingsRow(tr("经验"), tr("{n} 条", "n" to lessons) + " ›", sub = tr("踩过的坑，碰到相似情况才会想起")) { open(Page.LESSONS) }
                SettingsRow(tr("隐私名单"), tr("{n} 个 App", "n" to settings.blockedApps.size) + " ›", sub = tr("这些 App 不读、不截、不操作")) {
                    open(Page.PRIVACY)
                }
                SettingsToggle(tr("后台对比（空闲时用更便宜的配置重答一遍，让强模型评判）"), settings.shadowEval) { on ->
                    AideApp.instance.settings.update { it.copy(shadowEval = on) }
                }
            }
            UpdateSection()
        }
    }

    @Composable
    private fun Services() {
        val t = LocalTokens.current
        val settings by AideApp.instance.settings.state.collectAsState()
        var report by remember { mutableStateOf("") }
        var adding by remember { mutableStateOf(false) }
        var confirmDelete by remember { mutableStateOf<String?>(null) }
        val scope = rememberCoroutineScope()
        LaunchedEffect(confirmDelete) { if (confirmDelete != null) { delay(3_000); confirmDelete = null } }
        SettingsSection(tr("模型服务")) {
            if (settings.services.isEmpty()) Text(tr("还没有模型服务：加一个才能用。"), color = t.text2, fontSize = 14.sp, modifier = Modifier.padding(12.dp))
            for (svc in settings.services) {
                Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 4.dp, top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("${svc.name} · ${runCatching { URI(svc.baseUrl).host }.getOrNull() ?: svc.baseUrl}", color = t.text,
                        fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
                    // 删除要点两次：第一次变成"再点一次删除"
                    Text(if (confirmDelete == svc.id) tr("再点一次删除") else tr("删除"), color = if (confirmDelete == svc.id) t.err else t.text3,
                        fontSize = 13.sp, modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable {
                            if (confirmDelete != svc.id) { confirmDelete = svc.id; return@clickable }
                            AideApp.instance.secrets.remove(SecretStore.serviceKey(svc.id))
                            AideApp.instance.settings.update { s ->
                                s.copy(services = s.services.filter { it.id != svc.id }, models = s.models.filter { it.service != svc.id })
                            }
                            confirmDelete = null
                        }.padding(10.dp))
                }
                for (m in settings.models.filter { it.service == svc.id }) {
                    SettingsToggle(m.id, m.enabled, trailing = {
                        // 思考强度上限：点一下换一档
                        Text(tr("上限 {effort}", "effort" to m.maxEffort.wire), color = t.text3, fontSize = 12.sp,
                            modifier = Modifier.padding(end = 6.dp).clip(RoundedCornerShape(8.dp)).clickable {
                                val next = Effort.entries[(m.maxEffort.ordinal + 1) % Effort.entries.size]
                                AideApp.instance.settings.update { s -> s.copy(models = s.models.map { if (it == m) it.copy(maxEffort = next) else it }) }
                            }.padding(horizontal = 8.dp, vertical = 6.dp))
                    }) { on ->
                        AideApp.instance.settings.update { s -> s.copy(models = s.models.map { if (it == m) it.copy(enabled = on) else it }) }
                    }
                }
            }
            SettingsRow(tr("测试连接"), "›") {
                report = tr("测试中…")
                scope.launch { report = probeAll() }
            }
            if (report.isNotBlank()) Text(report, color = t.text2, fontSize = 12.sp, modifier = Modifier.padding(12.dp))
            SettingsRow(tr("添加服务"), if (adding) "×" else "+") { adding = !adding }
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
            SettingsChoice(tr("协议"), listOf(Wire.ANTHROPIC.name to "Anthropic", Wire.OPENAI_RESPONSES.name to "OpenAI Responses",
                Wire.OPENAI_CHAT.name to "OpenAI Chat"), wire.name) { wire = Wire.valueOf(it) }
            OutlinedTextField(name, { name = it }, label = { Text(tr("名字")) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(base, { base = it }, label = { Text(tr("服务地址")) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(key, { key = it }, label = { Text("API key") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(models, { models = it }, label = { Text(tr("模型（逗号分隔）")) }, modifier = Modifier.fillMaxWidth())
            SettingsRow(tr("保存"), "✓") {
                val ids = models.split(Regex("[,，;；\\s]+")).filter { it.isNotBlank() }
                if (base.isBlank() || key.isBlank() || ids.isEmpty()) return@SettingsRow
                val id = "s" + System.currentTimeMillis()
                AideApp.instance.secrets.put(SecretStore.serviceKey(id), key.trim())
                AideApp.instance.settings.update { s ->
                    s.copy(
                        services = s.services + Service(id, name.ifBlank { runCatching { URI(base.trim()).host }.getOrNull() ?: base }, wire, base.trim(),
                            bearer = wire == Wire.ANTHROPIC && !base.contains("anthropic.com")),
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
        SettingsSection(tr("路由表现")) {
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
        SettingsSection(tr("版本")) {
            SettingsRow(Updater.current, status) {
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
