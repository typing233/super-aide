package io.github.typing233.superaide.assist

import android.content.Context
import android.graphics.Bitmap
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import io.github.typing233.superaide.AideApp
import io.github.typing233.superaide.a11y.Shots
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.screen.Observation
import io.github.typing233.superaide.core.screen.Screen
import io.github.typing233.superaide.diag.Diag
import io.github.typing233.superaide.run.Aide
import io.github.typing233.superaide.ui.AideSurface
import io.github.typing233.superaide.ui.ComposeOwner
import android.service.voice.VoiceInteractionSession
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/**
 * 默认助手的会话窗口（长按电源键/手势，或者悬浮球、通知栏开关在已是默认助手时也走这里）。
 * 系统先把屏幕结构和截图交给我们（没开无障碍也能「问」），界面和透明 Activity 一样。
 */
class AideSession(context: Context) : VoiceInteractionSession(context) {
    private val owner = ComposeOwner()
    private var watch: Job? = null
    private var assist = CompletableDeferred<Aide.Capture>()
    private var screen: Screen? = null
    private var shot: ByteArray? = null
    private var got = 0

    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        window?.window?.setSoftInputMode(
            WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE or WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE
        )
        assist = CompletableDeferred()
        got = 0
        val mode = if (args?.getString(ARG_MODE) == Mode.ACT.name) Mode.ACT else Mode.ASK
        val via = args?.getString(ARG_VIA) ?: "assistant"
        if (args?.getBoolean(ARG_SUMMONED) != true) Aide.summon(context, mode, via, showHost = false, assist = assist)
        else Aide.attachAssist(assist)
        owner.resume()
        watch?.cancel()
        watch = AideApp.instance.scope.launch(Dispatchers.Main) {
            Aide.surface.collect { if (it == Aide.Surface.HIDDEN || it == Aide.Surface.PILL) hide() }
        }
    }

    override fun onHandleAssist(state: AssistState) {
        runCatching {
            val s = state.assistStructure ?: return@runCatching
            val m = context.resources.displayMetrics
            screen = AssistReader.read(s, m.widthPixels, m.heightPixels, AideApp.instance.settings.value.blockedApps.toSet())
        }.onFailure { Diag.error("session.assist", it) }
        arrived()
    }

    override fun onHandleScreenshot(screenshot: Bitmap?) {
        shot = screenshot?.let { runCatching { Shots.jpeg(Shots.scaled(it, Observation.scaleFor(it.width, it.height))) }.getOrNull() }
        arrived()
    }

    /** 结构和截图都到了（各一次）再交出去 */
    private fun arrived() {
        if (++got >= 2) assist.complete(Aide.Capture(screen, shot, source = "assist"))
    }

    override fun onCreateContentView(): View = owner.view(context) {
        AideSurface(onDismiss = { Aide.dismiss(); hide() })
    }

    override fun onBackPressed() {
        Aide.dismiss()
        hide()
    }

    override fun onHide() {
        watch?.cancel()
        if (!assist.isCompleted) assist.complete(Aide.Capture(screen, shot, source = "assist"))
        super.onHide()
    }

    override fun onDestroy() {
        owner.destroy()
        super.onDestroy()
    }

    companion object {
        const val ARG_MODE = "mode"
        const val ARG_VIA = "via"
        const val ARG_SUMMONED = "summoned"
    }
}
