package io.github.typing233.superaide.a11y

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.os.Build
import android.text.InputType
import android.view.Display
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import android.view.inputmethod.EditorInfo
import io.github.typing233.superaide.AideApp
import io.github.typing233.superaide.BuildConfig
import io.github.typing233.superaide.core.screen.Notice
import io.github.typing233.superaide.diag.Diag
import io.github.typing233.superaide.run.Aide
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
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
        _running.value = true
        Diag.log("a11y.connected")
        runCatching { overlays.start(AideApp.instance.scope) }.onFailure { Diag.error("overlays", it) }
        AideApp.instance.scope.launch(Dispatchers.Default) { Ocr.warmUp() }
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
        if (instance === this) { instance = null; _running.value = false }
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

    /**
     * 用无障碍输入法（API 33+）往当前有焦点的输入框里写字。和输入法一样走输入连接，不靠界面节点：
     * 不让无障碍读界面的 App（微信）也能输入。没有获得焦点的输入框返回 null。
     */
    /** 有焦点的输入框：里面的字、是不是多行（聊天框、正文这类） */
    class Field(val text: String, val multiLine: Boolean)

    /** 当前有焦点的输入框（经无障碍输入法读，API 33+）；没有获得焦点的输入框返回 null */
    fun imeField(): Field? {
        if (Build.VERSION.SDK_INT < 33) return null
        val im = inputMethod ?: return null
        val ic = im.currentInputConnection ?: return null
        val type = im.currentInputEditorInfo?.inputType ?: 0
        val multi = type and (InputType.TYPE_TEXT_FLAG_MULTI_LINE or InputType.TYPE_TEXT_FLAG_IME_MULTI_LINE) != 0
        return Field(ic.getSurroundingText(10_000, 10_000, 0)?.text?.toString().orEmpty(), multi)
    }

    fun imeType(text: String, replace: Boolean, enter: Boolean): String? {
        if (Build.VERSION.SDK_INT < 33) return null
        val im = inputMethod ?: return null
        val ic = im.currentInputConnection ?: return null
        if (replace) ic.performContextMenuAction(android.R.id.selectAll)
        ic.commitText(text, 1, null)
        val now = ic.getSurroundingText(2000, 2000, 0)?.text?.toString()
        val warn = if (now != null && text !in now) "（填完读回来是「${now.take(60)}」，和要填的不一样，看一下）" else ""
        if (!enter) return "输入「${text.take(40)}」$warn"
        val info = im.currentInputEditorInfo
        val action = (info?.imeOptions ?: 0) and EditorInfo.IME_MASK_ACTION
        val multiLine = info != null && info.inputType and InputType.TYPE_TEXT_FLAG_MULTI_LINE != 0
        val noAction = info != null && info.imeOptions and EditorInfo.IME_FLAG_NO_ENTER_ACTION != 0
        if (multiLine || noAction || action == EditorInfo.IME_ACTION_NONE || action == EditorInfo.IME_ACTION_UNSPECIFIED) {
            // 多行输入框（聊天框常这样）回车是换行：不按，让模型去点发送按钮
            return "输入「${text.take(40)}」$warn（这个输入框回车是换行，没有按：要发送就点「发送」按钮）"
        }
        ic.performEditorAction(action)
        return "输入「${text.take(40)}」并回车$warn"
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

        private val _running = MutableStateFlow(false)
        /** 界面用：服务连上/断开时跟着变（装完、更新完系统要过一会儿才连上） */
        val running: StateFlow<Boolean> = _running
    }
}
