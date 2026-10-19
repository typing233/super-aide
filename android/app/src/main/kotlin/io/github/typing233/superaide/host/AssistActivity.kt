package io.github.typing233.superaide.host

import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.addCallback
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.run.Aide
import io.github.typing233.superaide.ui.AideSurface
import io.github.typing233.superaide.ui.AideTheme
import kotlinx.coroutines.launch

/**
 * 不是默认助手时的打字宿主：透明 Activity，浮在当前 App 上。点空白处或按返回收起。
 * 「做」开始后它自己退下（让出屏幕给要操作的 App），进度在无障碍浮层的小条上。
 */
class AssistActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        entered(intent)
        setContent { AideTheme { AideSurface(onDismiss = ::dismiss) } }
        onBackPressedDispatcher.addCallback(this) { dismiss() }
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                Aide.surface.collect { if (it == Aide.Surface.HIDDEN || it == Aide.Surface.PILL) finishQuietly() }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        entered(intent)
    }

    /**
     * 被系统的 ACTION_ASSIST（助手手势、助手键）或别人直接打开的：自己发起一次召唤。
     * 这时我们的窗口已经盖在 App 上了，系统就不给下面 App 的文字。先让窗口不接触摸（下面的 App 算回"能交互的窗口"），
     * 读完文字再恢复。
     */
    private fun entered(intent: Intent?) {
        if (intent?.action != Intent.ACTION_ASSIST && Aide.surface.value != Aide.Surface.HIDDEN) return
        val passive = WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        window.addFlags(passive)
        Aide.summon(this, Mode.ASK, if (intent?.action == Intent.ACTION_ASSIST) "assist-intent" else "activity", showHost = false)
        lifecycleScope.launch {
            Aide.awaitPreCapture()
            window.clearFlags(passive)
        }
    }

    private fun dismiss() {
        Aide.dismiss()
        finishQuietly()
    }

    private fun finishQuietly() {
        if (isFinishing) return
        finish()
        @Suppress("DEPRECATION")
        overridePendingTransition(0, 0)
    }
}
