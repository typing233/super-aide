package io.github.typing233.superaide.debug

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.view.Gravity
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import io.github.typing233.superaide.AideApp
import io.github.typing233.superaide.a11y.AideAccessibilityService
import io.github.typing233.superaide.assist.AideVoiceInteractionService
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.config.ModelEntry
import io.github.typing233.superaide.core.config.Settings
import io.github.typing233.superaide.core.llm.Chats
import io.github.typing233.superaide.core.llm.Effort
import io.github.typing233.superaide.core.llm.ModelProbe
import io.github.typing233.superaide.core.llm.Service
import io.github.typing233.superaide.diag.Diag
import io.github.typing233.superaide.run.Aide
import io.github.typing233.superaide.secure.SecretStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.Serializable
import java.io.ByteArrayOutputStream
import java.io.File

/**
 * 调试命令（只在 debug/staging 版本）：
 *   adb shell am broadcast -a io.github.typing233.superaide.DEBUG -p <包名> --es cmd <命令> [--es arg <参数>]
 * 结果写进 files/debug/log.jsonl（Diag）。
 */
class DebugReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val cmd = intent.getStringExtra("cmd").orEmpty()
        val arg = intent.getStringExtra("arg").orEmpty()
        // 不用 goAsync 拖着：广播超过一分钟算 ANR，系统会杀进程（「做」常常要更久）。结果都写日志
        val show = intent.getStringExtra("show") == "1"
        AideApp.instance.scope.launch {
            try {
                Diag.log("debug.$cmd", arg)
                run(context, cmd, arg, show)
            } catch (e: Throwable) {
                Diag.error("debug.$cmd.failed", e)
            }
        }
    }

    private suspend fun run(context: Context, cmd: String, arg: String, show: Boolean) {
        val app = AideApp.instance
        when (cmd) {
            // 电脑上的 scripts/android/provision.py 先经 run-as 写好 files/provision.json，这里导入后删掉明文
            "provision" -> {
                val file = File(context.filesDir, "provision.json")
                val p = Settings.json.decodeFromString(Provision.serializer(), file.readText())
                file.delete()
                p.services.forEach { app.secrets.put(SecretStore.serviceKey(it.service.id), it.key) }
                app.settings.update { s ->
                    s.copy(services = p.services.map { it.service }, models = p.services.flatMap { it.models })
                }
                Diag.log("debug.provision.done", p.services.joinToString { "${it.service.name}:${it.models.size}" })
            }

            "dump" -> repeat(arg.toIntOrNull() ?: 3) { i ->
                val svc = AideAccessibilityService.instance ?: error("无障碍没开")
                val r = withContext(Dispatchers.Default) { svc.readScreen() }
                val nodes = r.screen.windows.sumOf { it.nodes.size }
                val chars = r.screen.windows.sumOf { w -> w.nodes.sumOf { it.text.length + it.desc.length } }
                Diag.log(
                    "debug.dump.result",
                    "run=$i ms=${r.ms} visited=${r.visited} kept=$nodes chars=$chars windows=" +
                        r.screen.windows.joinToString { "${it.pkg}/${it.type}/${it.nodes.size}" },
                )
                if (i == 0) File(context.filesDir, "debug/screen.json")
                    .writeText(Settings.json.encodeToString(io.github.typing233.superaide.core.screen.Screen.serializer(), r.screen))
            }

            "shot" -> repeat(arg.toIntOrNull() ?: 3) { i ->
                val svc = AideAccessibilityService.instance ?: error("无障碍没开")
                val t0 = System.nanoTime()
                val bmp = svc.screenshot()
                val ms = (System.nanoTime() - t0) / 1_000_000
                Diag.log("debug.shot.result", "run=$i ms=$ms size=${bmp?.width}x${bmp?.height}")
                if (bmp != null && i == 0) File(context.filesDir, "debug/shot.jpg").outputStream().use {
                    bmp.compress(Bitmap.CompressFormat.JPEG, 80, it)
                }
            }

            "tap" -> {
                val (x, y) = arg.split(",").map { it.trim().toFloat() }
                val ok = AideAccessibilityService.instance?.tap(x, y)
                Diag.log("debug.tap.result", "ok=$ok")
            }

            "session" -> Diag.log("debug.session.result", "shown=${AideVoiceInteractionService.show()}")

            // 端到端：召唤（不开界面，除非 show=1）→ 提问 → 等这一轮答完，把结果写进日志
            "ask", "act" -> {
                val mode = if (cmd == "act") Mode.ACT else Mode.ASK

                withContext(Dispatchers.Main) { Aide.summon(context, mode, "debug", showHost = show) }
                Aide.setMode(mode)
                Aide.submit(arg)
                val c = withTimeoutOrNull(5 * 60_000L) { Aide.card.first { it?.done == true && it.question == arg } }
                Diag.log(
                    "debug.$cmd.result",
                    "ok=${c?.ok} stopped=${c?.stopped} route=${c?.route} steps=${c?.steps} error=${c?.error ?: c?.reported}\n${c?.answer}",
                )
            }

            "stop" -> Aide.stop()

            // 点「读完整页」，等重新回答完
            "fullpage" -> {
                val offered = Aide.card.value?.fullPage
                withContext(Dispatchers.Main) { Aide.readFullPage(context) }
                val c = withTimeoutOrNull(5 * 60_000L) { Aide.card.first { it?.done == true && it.question.isNotBlank() && it.earlier.isNotEmpty() } }
                Diag.log("debug.fullpage.result", "offered=$offered ok=${c?.ok} error=${c?.error}\n${c?.answer}")
            }

            // 点「让我来做」，等这一轮操作做完
            "handoff" -> {
                val before = Aide.card.value?.question
                Aide.handOff()
                val c = withTimeoutOrNull(5 * 60_000L) { Aide.card.first { it?.done == true && it.question != before } }
                Diag.log("debug.handoff.result", "ok=${c?.ok} steps=${c?.steps} error=${c?.error ?: c?.reported}\n${c?.answer}")
            }

            // 单独开关按键过滤，看 onKeyEvent 收不收得到（音量下键停止）
            "keys" -> {
                val svc = AideAccessibilityService.instance ?: error("无障碍没开")
                val info = svc.serviceInfo
                val flag = android.accessibilityservice.AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS
                info.flags = if (arg == "off") info.flags and flag.inv() else info.flags or flag
                svc.serviceInfo = info
                Diag.log("debug.keys.result", "flags=${svc.serviceInfo.flags} caps=${svc.serviceInfo.capabilities}")
            }

            // 加一个（不存在的）模型排在最前面 / 删掉：验证模型用不了时换模型接着答。arg = 服务/模型，前面加 - 是删
            "model" -> {
                val remove = arg.startsWith("-")
                val (svc, id) = arg.removePrefix("-").split("/", limit = 2)
                app.settings.update { s ->
                    val rest = s.models.filterNot { it.service == svc && it.id == id }
                    s.copy(models = if (remove) rest else listOf(ModelEntry(svc, id)) + rest)
                }
                Diag.log("debug.model.result", app.settings.value.models.joinToString { it.id })
            }

            // 开关自己的默认助手服务组件（验证 MagicOS 上的退路）
            "vis" -> {
                val cn = android.content.ComponentName(context, AideVoiceInteractionService::class.java)
                val state = if (arg == "on") android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DEFAULT
                else android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DISABLED
                context.packageManager.setComponentEnabledSetting(cn, state, android.content.pm.PackageManager.DONT_KILL_APP)
                Diag.log("debug.vis.result", arg)
            }

            // 在无障碍浮层里放一个能获得焦点的输入框，看输入法表现（arg=hide 关掉）
            "overlay" -> withContext(Dispatchers.Main) {
                val svc = AideAccessibilityService.instance ?: error("无障碍没开")
                val wm = svc.getSystemService(WindowManager::class.java)
                overlay?.let { runCatching { wm.removeView(it) } }
                overlay = null
                if (arg == "hide") return@withContext
                val input = EditText(svc).apply { hint = "M0：输入法测试（无障碍浮层）"; setBackgroundColor(0xFFFFFFFF.toInt()) }
                val lp = WindowManager.LayoutParams(
                    WindowManager.LayoutParams.MATCH_PARENT,
                    WindowManager.LayoutParams.WRAP_CONTENT,
                    WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                    0,
                    PixelFormat.TRANSLUCENT,
                ).apply {
                    gravity = Gravity.BOTTOM
                    softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
                }
                wm.addView(input, lp)
                overlay = input
                input.viewTreeObserver.addOnGlobalLayoutListener {
                    val loc = IntArray(2).also(input::getLocationOnScreen)
                    Diag.log("debug.overlay.layout", "inputTop=${loc[1]}")
                }
                input.post {
                    input.requestFocus()
                    svc.getSystemService(InputMethodManager::class.java).showSoftInput(input, 0)
                }
            }

            "probe" -> {
                val s = app.settings.value
                for (m in s.models.filter { it.enabled && (arg.isEmpty() || it.id == arg) }) {
                    val service = s.service(m.service) ?: continue
                    val key = app.secrets.get(SecretStore.serviceKey(service.id)) ?: continue
                    val r = ModelProbe.run({ system, tools ->
                        Chats.open(service, key, m.id, Effort.LOW, system, tools, m.vision)
                    }, if (m.vision) redJpeg() else null)
                    Diag.log("debug.probe.result", "${service.name}/${m.id}: $r")
                }
            }

            else -> Diag.log("debug.unknown", cmd)
        }
    }

    private fun redJpeg(): ByteArray {
        val bmp = Bitmap.createBitmap(64, 64, Bitmap.Config.ARGB_8888).apply { eraseColor(android.graphics.Color.RED) }
        return ByteArrayOutputStream().also { bmp.compress(Bitmap.CompressFormat.JPEG, 90, it) }.toByteArray()
    }

    @Serializable
    private data class Provision(val services: List<ProvisionedService>)

    @Serializable
    private data class ProvisionedService(val service: Service, val key: String, val models: List<ModelEntry>)

    companion object {
        private var overlay: EditText? = null
    }
}
