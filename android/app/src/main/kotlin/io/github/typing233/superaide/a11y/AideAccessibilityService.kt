package io.github.typing233.superaide.a11y

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.os.Build
import android.view.Display
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import io.github.typing233.superaide.AideApp
import io.github.typing233.superaide.BuildConfig
import io.github.typing233.superaide.core.screen.Notice
import io.github.typing233.superaide.diag.Diag
import io.github.typing233.superaide.run.Aide
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlin.coroutines.resume

/**
 * 读屏和操作都靠它。和 App 同一个进程：任何未捕获的异常都会让系统把服务标成"出错"并关掉，
 * 所以这里的回调都包在 runCatching 里。
 */
class AideAccessibilityService : AccessibilityService() {

    private val notices = ArrayDeque<Notice>()

    /** point 工具圈出的位置 */
    val marks by lazy { Marks(this) }

    /** 进度小条和悬浮球 */
    val overlays by lazy { Overlays(this) }

    override fun onServiceConnected() {
        instance = this
        Diag.log("a11y.connected")
        runCatching { overlays.start(AideApp.instance.scope) }.onFailure { Diag.error("overlays", it) }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent) {
        runCatching {
            if (event.eventType == AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED) {
                val text = event.text.joinToString(" ").trim()
                val pkg = event.packageName?.toString().orEmpty()
                if (text.isNotEmpty() && pkg != packageName) remember(Notice(System.currentTimeMillis(), pkg, text))
            }
        }
    }

    override fun onInterrupt() {}

    /** 操作进行中按音量下键 = 停止（按键过滤只在那时打开） */
    override fun onKeyEvent(event: KeyEvent): Boolean {
        if (BuildConfig.DEBUG && event.action == KeyEvent.ACTION_DOWN) Diag.log("a11y.key", "code=${event.keyCode}")
        if (event.keyCode == KeyEvent.KEYCODE_VOLUME_DOWN && Aide.card.value?.running == true) {
            if (event.action == KeyEvent.ACTION_DOWN) { Diag.log("stop.volume"); Aide.stop() }
            return true
        }
        return false
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        runCatching { marks.hide() }
        runCatching { overlays.stop() }
        Diag.log("a11y.destroyed")
        super.onDestroy()
    }

    @Synchronized
    private fun remember(n: Notice) {
        notices.addLast(n)
        val cutoff = System.currentTimeMillis() - NOTICE_TTL_MS
        while (notices.size > MAX_NOTICES || (notices.isNotEmpty() && notices.first().time < cutoff)) notices.removeFirst()
    }

    @Synchronized
    fun recentNotices(): List<Notice> = notices.toList()

    fun readScreen(): ScreenReader.Result {
        val metrics = resources.displayMetrics
        val blocked = AideApp.instance.settings.value.blockedApps.toSet()
        return ScreenReader(packageName, blocked).read(windows, metrics.widthPixels, metrics.heightPixels, recentNotices())
    }

    /** 截整屏（API 30+，系统限频约每秒 3 次）。失败返回 null。 */
    suspend fun screenshot(): Bitmap? = suspendCancellableCoroutine { cont ->
        takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
            override fun onSuccess(result: ScreenshotResult) {
                val buffer = result.hardwareBuffer
                val bitmap = runCatching {
                    Bitmap.wrapHardwareBuffer(buffer, result.colorSpace)?.copy(Bitmap.Config.ARGB_8888, false)
                }.getOrNull()
                buffer.close()
                if (cont.isActive) cont.resume(bitmap)
            }

            override fun onFailure(errorCode: Int) {
                Diag.log("a11y.screenshot.failed", "code=$errorCode")
                if (cont.isActive) cont.resume(null)
            }
        })
    }

    /**
     * 只截某个窗口（API 34+）：截的是那个 App 自己的画面，我们自己的界面不会出现在上面。
     * 截不了（旧系统、窗口受保护）返回 null，调用方再退回整屏截图。
     */
    suspend fun screenshotOfWindow(windowId: Int): Bitmap? {
        if (Build.VERSION.SDK_INT < 34 || windowId < 0) return null
        return suspendCancellableCoroutine { cont ->
            takeScreenshotOfWindow(windowId, mainExecutor, object : TakeScreenshotCallback {
                override fun onSuccess(result: ScreenshotResult) {
                    val buffer = result.hardwareBuffer
                    val bitmap = runCatching {
                        Bitmap.wrapHardwareBuffer(buffer, result.colorSpace)?.copy(Bitmap.Config.ARGB_8888, false)
                    }.getOrNull()
                    buffer.close()
                    if (cont.isActive) cont.resume(bitmap)
                }

                override fun onFailure(errorCode: Int) {
                    Diag.log("a11y.windowshot.failed", "code=$errorCode")
                    if (cont.isActive) cont.resume(null)
                }
            })
        }
    }

    /** 在屏幕坐标 (x, y) 上点一下（或按住 ms 毫秒）。 */
    suspend fun tap(x: Float, y: Float, ms: Long = 60): Boolean = gesture(
        GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(Path().apply { moveTo(x, y) }, 0, ms))
            .build()
    )

    /**
     * 派发手势。手势是模拟的触摸，落点上面要是有我们的浮层（进度小条）就会被它接走：
     * 只在手势进行的这一下（几十到几百毫秒）让浮层不接触摸，平时小条上的停止键一直点得到。
     */
    suspend fun gesture(g: GestureDescription): Boolean {
        overlays.passThrough(true)
        try {
            return dispatch(g)
        } finally {
            withContext(NonCancellable) { overlays.passThrough(false) }
        }
    }

    private suspend fun dispatch(g: GestureDescription): Boolean = suspendCancellableCoroutine { cont ->
        val accepted = dispatchGesture(g, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                if (cont.isActive) cont.resume(true)
            }

            override fun onCancelled(gestureDescription: GestureDescription?) {
                if (cont.isActive) cont.resume(false)
            }
        }, null)
        if (!accepted && cont.isActive) cont.resume(false)
    }

    companion object {
        private const val MAX_NOTICES = 30
        private const val NOTICE_TTL_MS = 3 * 60 * 60 * 1000L

        @Volatile
        var instance: AideAccessibilityService? = null
            private set
    }
}
