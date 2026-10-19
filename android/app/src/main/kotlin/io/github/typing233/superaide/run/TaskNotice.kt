package io.github.typing233.superaide.run

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import io.github.typing233.superaide.R
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.core.session.CardState

/**
 * 「做」进行中的常驻通知：当前一步 + 停止按钮。
 * 音量下键在有的系统上（MagicOS）到不了无障碍服务，进度小条又可能被要点的界面挡住：通知栏随时拉得下来，是最可靠的停止入口。
 */
object TaskNotice {
    private const val CHANNEL = "task"
    private const val ID = 1
    private const val ACTION_STOP = "io.github.typing233.superaide.STOP"

    fun update(context: Context, c: CardState?) {
        val nm = context.getSystemService(NotificationManager::class.java)
        if (c == null || c.mode != Mode.ACT || !c.running) {
            nm.cancel(ID)
            return
        }
        if (context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        if (nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, tr("正在操作"), NotificationManager.IMPORTANCE_LOW).apply {
                setShowBadge(false)
            })
        }
        val stop = PendingIntent.getBroadcast(
            context, 0, Intent(ACTION_STOP).setClass(context, StopReceiver::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        val n = Notification.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_tile)
            .setContentTitle(tr("超级助手正在操作"))
            .setContentText(c.transient ?: c.steps.lastOrNull() ?: tr("正在思考…"))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .addAction(Notification.Action.Builder(null, tr("停止"), stop).build())
            .build()
        nm.notify(ID, n)
    }

    class StopReceiver : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == ACTION_STOP) Aide.stop()
        }
    }
}
