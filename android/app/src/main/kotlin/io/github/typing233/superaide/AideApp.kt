package io.github.typing233.superaide

import android.app.Application
import io.github.typing233.superaide.a11y.SelfHeal
import io.github.typing233.superaide.assist.AssistantRoute
import io.github.typing233.superaide.core.llm.Chats
import io.github.typing233.superaide.data.SettingsStore
import io.github.typing233.superaide.diag.Diag
import io.github.typing233.superaide.secure.SecretStore
import io.github.typing233.superaide.update.Updater
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class AideApp : Application() {
    /**
     * 整个进程共用的协程作用域。所有异常都在这里兜住：
     * 无障碍服务和 App 同一个进程，崩一次系统就会把无障碍关掉。
     */
    val scope = CoroutineScope(
        SupervisorJob() + Dispatchers.Default +
            CoroutineExceptionHandler { _, e -> Diag.error("uncaught", e) }
    )

    lateinit var settings: SettingsStore
        private set
    lateinit var secrets: SecretStore
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        Diag.init(this)
        settings = SettingsStore(this)
        secrets = SecretStore(this)
        // 服务说某个模型不收图片：记下来，以后只给它文字
        Chats.onNoVision = { service, model ->
            Diag.log("model.novision", "$service/$model")
            settings.update { s -> s.copy(models = s.models.map { if (it.service == service && it.id == model) it.copy(vision = false) else it }) }
        }
        // 被强行停止过（清理后台、划掉最近任务）：无障碍被系统去掉了，有权限就加回去
        runCatching { SelfHeal.ensure(this) }
        // 系统绑定默认助手服务要一点时间：过几秒再看它绑上没有；顺便每天查一次更新
        scope.launch {
            delay(8_000)
            runCatching { AssistantRoute.adapt(this@AideApp) }
            if (!BuildConfig.DEBUG) runCatching { Updater.dailyCheck(this@AideApp) }
        }
    }

    companion object {
        lateinit var instance: AideApp
            private set
    }
}
