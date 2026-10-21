package io.github.typing233.superaide.run

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import io.github.typing233.superaide.R
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.core.session.CardState
import io.github.typing233.superaide.diag.Diag
import io.github.typing233.superaide.host.ChatActivity

/**
 * 任务进行中的常驻通知（当前一步 + 停止按钮），和用户没在看时「答好了」的通知（点开就是对话页）。
 * 音量下键在有的系统上（MagicOS）到不了无障碍服务，进度小条又可能被要点的界面挡住：通知栏随时拉得下来，是最可靠的停止入口。
 * 进行中的通知同时是 [TaskService] 的前台通知：卡片收起、切到别的 App 以后，系统不会把任务冻住或杀掉。
 */
object TaskNotice {
    private const val CHANNEL = "task"
    private const val CHANNEL_DONE = "done"
    const val ID = 1
    private const val ID_DONE = 2
    private const val ACTION_STOP = "io.github.typing233.superaide.STOP"

    /** 问答开始后过这么久才给停止按钮（短的问答一闪而过，系统会推迟显示没有按钮的前台通知） */
    private const val STOP_AFTER_MS = 10_000L

    private var startedAt = 0L
    /** 上次通知的内容：回答一个字一个字出来时卡片一直在变，通知只在这一步变了时才更新 */
    private var shown = ""

    fun update(context: Context, c: CardState?) {
        val nm = context.getSystemService(NotificationManager::class.java)
        if (c == null || !c.running) {
            if (shown.isNotEmpty()) nm.cancel(ID)
            TaskService.stop(context)
            startedAt = 0L
            shown = ""
            return
        }
        if (startedAt == 0L) { startedAt = System.currentTimeMillis(); nm.cancel(ID_DONE) }
        if (!allowed(context)) return
        val key = "${c.mode}|${c.transient ?: c.steps.lastOrNull()}|${c.mode == Mode.ACT || System.currentTimeMillis() - startedAt > STOP_AFTER_MS}"
        if (key == shown) return
        shown = key
        ongoing(context, c)?.let { nm.notify(ID, it) }
    }

    /** 进行中的那条（前台服务启动时也用它） */
    fun ongoing(context: Context, c: CardState?): Notification? {
        if (c == null || !c.running) return null
        channels(context)
        val act = c.mode == Mode.ACT
        val b = Notification.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_tile)
            .setContentTitle(if (act) tr("超级助手正在操作") else tr("超级助手正在回答"))
            .setContentText(c.transient ?: c.steps.lastOrNull() ?: tr("正在思考…"))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(openChat(context))
        if (act || System.currentTimeMillis() - startedAt > STOP_AFTER_MS) {
            val stop = PendingIntent.getBroadcast(context, 0, Intent(ACTION_STOP).setClass(context, StopReceiver::class.java), PendingIntent.FLAG_IMMUTABLE)
            b.addAction(Notification.Action.Builder(null, tr("停止"), stop).build())
        }
        if (act) b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
        return b.build()
    }

    /** 问答答完了，用户没在看（卡片收起了、去了别的 App）：发一条「答好了」 */
    fun done(context: Context, c: CardState) {
        if (!allowed(context)) return
        channels(context)
        val title = when {
            c.stopped -> tr("已停止")
            !c.ok -> tr("没答完")
            c.files.isNotEmpty() -> tr("做好了：{name}", "name" to c.files.joinToString("、") { it.name })
            else -> tr("回答好了")
        }
        val text = c.summary().ifBlank { c.error ?: c.question }.take(120)
        val n = Notification.Builder(context, CHANNEL_DONE)
            .setSmallIcon(R.drawable.ic_tile)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(c.answer.take(400).ifBlank { text }))
            .setAutoCancel(true)
            .setContentIntent(openChat(context))
            .build()
        context.getSystemService(NotificationManager::class.java).notify(ID_DONE, n)
    }

    fun clearDone(context: Context) = context.getSystemService(NotificationManager::class.java).cancel(ID_DONE)

    private fun allowed(context: Context) =
        context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun openChat(context: Context): PendingIntent = PendingIntent.getActivity(
        context, 1, Intent(context, ChatActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun channels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, tr("正在进行的任务"), NotificationManager.IMPORTANCE_LOW).apply { setShowBadge(false) })
        }
        if (nm.getNotificationChannel(CHANNEL_DONE) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL_DONE, tr("任务完成"), NotificationManager.IMPORTANCE_DEFAULT))
        }
    }

    class StopReceiver : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == ACTION_STOP) Aide.stop()
        }
    }
}

/** 任务进行中的前台服务：只是让进程在后台也接着跑，通知内容由 [TaskNotice] 更新 */
class TaskService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val n = TaskNotice.ongoing(this, Aide.card.value)
        if (n == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        try {
            if (Build.VERSION.SDK_INT >= 34) startForeground(TaskNotice.ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
            else startForeground(TaskNotice.ID, n)
        } catch (e: Exception) {
            Diag.error("fgs.start", e)
            stopSelf()
        }
        return START_NOT_STICKY
    }

    companion object {
        @Volatile
        private var running = false

        /** 在界面还看得见的时候调（后台不让启动前台服务） */
        fun start(context: Context) {
            if (running) return
            runCatching { context.startForegroundService(Intent(context, TaskService::class.java)); running = true }
                .onFailure { Diag.error("fgs", it) }
        }

        fun stop(context: Context) {
            if (!running) return
            running = false
            runCatching { context.stopService(Intent(context, TaskService::class.java)) }
        }
    }
}
