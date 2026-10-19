package io.github.typing233.superaide.a11y

import android.accessibilityservice.AccessibilityServiceInfo
import android.graphics.PixelFormat
import android.view.Gravity
import android.view.WindowManager
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import io.github.typing233.superaide.AideApp
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.run.Aide
import io.github.typing233.superaide.run.TaskNotice
import io.github.typing233.superaide.ui.LocalTokens
import io.github.typing233.superaide.ui.OverlayWindow
import io.github.typing233.superaide.ui.Pill
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 无障碍浮层里不需要打字的界面：进度小条（操作进行中 / 结果 / 收起的回答）和悬浮球。
 * 都不抢焦点；执行动作时小条临时不接触摸，免得挡住要点的地方。
 */
class Overlays(private val svc: AideAccessibilityService) {
    private var job: Job? = null
    private val density = svc.resources.displayMetrics.density

    private val pill = OverlayWindow(svc, params(Gravity.TOP or Gravity.CENTER_HORIZONTAL).apply { y = (28 * density).toInt() }) {
        val card by Aide.card.collectAsState()
        card?.let { c -> Pill(c, onTap = ::pillTapped) }
    }

    private val bubble = OverlayWindow(svc, params(Gravity.TOP or Gravity.START).apply {
        x = svc.resources.displayMetrics.widthPixels - (56 * density).toInt()
        y = (svc.resources.displayMetrics.heightPixels * 0.42f).toInt()
    }) { Bubble() }

    fun start(scope: CoroutineScope) {
        job = scope.launch(Dispatchers.Main) {
            combine(Aide.surface, AideApp.instance.settings.state, Aide.settingsOpen) { s, set, own -> s to (set.bubble && !own) }.collect { (surface, bubbleOn) ->
                if (surface == Aide.Surface.PILL) pill.show() else pill.hide()
                if (bubbleOn && surface == Aide.Surface.HIDDEN) bubble.show() else bubble.hide()
                keyFilter(Aide.card.value?.running == true && Aide.card.value?.mode == Mode.ACT && surface == Aide.Surface.PILL)
            }
        }
        scope.launch(Dispatchers.Main) {
            Aide.card.collect { c ->
                keyFilter(c?.running == true && c.mode == Mode.ACT)
                runCatching { TaskNotice.update(svc, c) }
            }
        }
    }

    fun stop() {
        job?.cancel()
        pill.destroy()
        bubble.destroy()
    }

    /** 派发手势的那一下：小条不接触摸（见 AideAccessibilityService.gesture） */
    suspend fun passThrough(on: Boolean) = withContext(Dispatchers.Main) {
        val f = WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        pill.params.flags = if (on) pill.params.flags or f else pill.params.flags and f.inv()
        pill.update()
    }

    private fun pillTapped() {
        val c = Aide.card.value ?: return
        if (c.running && c.mode == Mode.ACT) return // 正在操作：不能把卡片盖上去
        Aide.expand(svc)
    }

    /** 操作进行中才拦音量键（拦着会让系统按键变慢） */
    private var filtering = false
    private fun keyFilter(on: Boolean) {
        if (on == filtering) return
        filtering = on
        runCatching {
            val info = svc.serviceInfo
            info.flags = if (on) info.flags or AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS
            else info.flags and AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS.inv()
            svc.serviceInfo = info
        }
    }

    private fun params(gravity: Int) = WindowManager.LayoutParams(
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT,
    ).apply { this.gravity = gravity }

    /** 悬浮球：点一下问，长按直接做；能拖，松手贴边 */
    @androidx.compose.runtime.Composable
    private fun Bubble() {
        val t = LocalTokens.current
        Box(
            Modifier.size(44.dp).shadow(8.dp, CircleShape).clip(CircleShape).background(t.gradient(Mode.ASK))
                .border(2.dp, Color.White.copy(alpha = 0.8f), CircleShape).alpha(0.92f)
                .pointerInput(Unit) {
                    detectTapGestures(
                        onTap = { Aide.summon(svc, Mode.ASK, "bubble") },
                        onLongPress = { Aide.summon(svc, Mode.ACT, "bubble") },
                    )
                }
                .pointerInput(Unit) {
                    detectDragGestures(
                        onDragEnd = {
                            val w = svc.resources.displayMetrics.widthPixels
                            bubble.params.x = if (bubble.params.x + 22 * density < w / 2) 0 else w - (44 * density).toInt()
                            bubble.update()
                        },
                    ) { change, drag ->
                        change.consume()
                        bubble.params.x += drag.x.toInt()
                        bubble.params.y += drag.y.toInt()
                        bubble.update()
                    }
                },
        )
    }
}
