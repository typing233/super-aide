package io.github.typing233.superaide.assist

import android.os.Bundle
import android.service.voice.VoiceInteractionService
import android.service.voice.VoiceInteractionSession
import io.github.typing233.superaide.diag.Diag

/** 被选为默认数字助手后系统常驻绑定它；长按电源键/手势时系统直接开会话（AideSession）。 */
class AideVoiceInteractionService : VoiceInteractionService() {
    override fun onReady() {
        super.onReady()
        active = this
        Diag.log("assist.ready")
    }

    override fun onShutdown() {
        if (active === this) active = null
        super.onShutdown()
    }

    companion object {
        /** 当前是默认助手时不为空；悬浮球和通知栏开关也走它开会话，只有一个宿主 */
        @Volatile
        var active: AideVoiceInteractionService? = null
            private set

        fun show(args: Bundle = Bundle()): Boolean {
            val s = active ?: return false
            return runCatching {
                s.showSession(args, VoiceInteractionSession.SHOW_WITH_ASSIST or VoiceInteractionSession.SHOW_WITH_SCREENSHOT)
                true
            }.getOrDefault(false)
        }
    }
}
