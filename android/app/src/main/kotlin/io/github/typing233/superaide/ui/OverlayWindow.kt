package io.github.typing233.superaide.ui

import android.content.Context
import android.view.View
import android.view.WindowManager
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.ComposeView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.setViewTreeLifecycleOwner
import androidx.savedstate.SavedStateRegistry
import androidx.savedstate.SavedStateRegistryController
import androidx.savedstate.SavedStateRegistryOwner
import androidx.savedstate.setViewTreeSavedStateRegistryOwner

/**
 * 在 Activity 以外的窗口里用 Compose（无障碍浮层、默认助手的会话窗口）：
 * ComposeView 需要一个生命周期和状态保存的主人，这里自己当。
 */
class ComposeOwner : LifecycleOwner, SavedStateRegistryOwner {
    private val registry = LifecycleRegistry(this)
    private val saved = SavedStateRegistryController.create(this)
    override val lifecycle: Lifecycle get() = registry
    override val savedStateRegistry: SavedStateRegistry get() = saved.savedStateRegistry

    fun view(context: Context, content: @Composable () -> Unit): ComposeView {
        if (registry.currentState == Lifecycle.State.INITIALIZED) {
            saved.performRestore(null)
            registry.handleLifecycleEvent(Lifecycle.Event.ON_CREATE)
        }
        return ComposeView(context).apply {
            setViewTreeLifecycleOwner(this@ComposeOwner)
            setViewTreeSavedStateRegistryOwner(this@ComposeOwner)
            setContent { AideTheme(content) }
        }
    }

    fun resume() {
        registry.handleLifecycleEvent(Lifecycle.Event.ON_START)
        registry.handleLifecycleEvent(Lifecycle.Event.ON_RESUME)
    }

    fun destroy() {
        if (registry.currentState != Lifecycle.State.INITIALIZED) registry.handleLifecycleEvent(Lifecycle.Event.ON_DESTROY)
    }
}

/** 一个装着 Compose 的浮层窗口。 */
class OverlayWindow(private val context: Context, val params: WindowManager.LayoutParams, content: @Composable () -> Unit) {
    private val owner = ComposeOwner()
    private val wm = context.getSystemService(WindowManager::class.java)
    val view: View = owner.view(context, content)
    var shown = false
        private set

    fun show() {
        if (shown) return
        runCatching { wm.addView(view, params) }.onSuccess { shown = true; owner.resume() }
    }

    fun update() {
        if (shown) runCatching { wm.updateViewLayout(view, params) }
    }

    fun hide() {
        if (!shown) return
        runCatching { wm.removeView(view) }
        shown = false
    }

    fun destroy() {
        hide()
        owner.destroy()
    }
}
