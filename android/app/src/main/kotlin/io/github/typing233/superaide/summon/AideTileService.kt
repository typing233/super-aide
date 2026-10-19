package io.github.typing233.superaide.summon

import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.quicksettings.TileService
import io.github.typing233.superaide.assist.AideVoiceInteractionService
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.host.AssistActivity
import io.github.typing233.superaide.run.Aide

/** 通知栏快捷开关：是默认助手就开助手会话，否则开透明 Activity（得用 startActivityAndCollapse，后台不让直接开）。 */
class AideTileService : TileService() {
    override fun onClick() {
        if (AideVoiceInteractionService.active != null) {
            Aide.summon(this, Mode.ASK, "tile")
            return
        }
        Aide.summon(this, Mode.ASK, "tile", showHost = false)
        val intent = Intent(this, AssistActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= 34) {
            startActivityAndCollapse(PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE))
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(intent)
        }
    }
}
