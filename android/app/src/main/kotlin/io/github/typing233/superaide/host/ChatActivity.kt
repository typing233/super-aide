package io.github.typing233.superaide.host

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.IntentCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import io.github.typing233.superaide.MainActivity
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.i18n.I18n
import io.github.typing233.superaide.run.Aide
import io.github.typing233.superaide.run.TaskNotice
import io.github.typing233.superaide.ui.AideTheme
import io.github.typing233.superaide.ui.ChatPage
import kotlinx.coroutines.launch

/**
 * 全屏对话页。从卡片上的展开、「答好了」的通知、设置页、别的 App 的分享进来。
 * 「做」开始后它自己退到后面（让出屏幕给要操作的 App），进度在无障碍浮层的小条上。
 */
class ChatActivity : ComponentActivity() {
    private val pick = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris -> Aide.attach(this, uris) }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        I18n.lang = Aide.uiLang()
        if (savedInstanceState == null) shared(intent)
        setContent {
            AideTheme {
                ChatPage(
                    onBack = ::finish,
                    onAttach = { runCatching { pick.launch(arrayOf("*/*")) } },
                    onSettings = { startActivity(Intent(this, MainActivity::class.java)) },
                )
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                Aide.surface.collect { s ->
                    val c = Aide.card.value
                    if (s == Aide.Surface.PILL && c?.running == true && c.mode == Mode.ACT) moveTaskToBack(true)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        shared(intent)
    }

    override fun onStart() {
        super.onStart()
        Aide.chatOpen.value = true
        TaskNotice.clearDone(this)
    }

    override fun onStop() {
        Aide.chatOpen.value = false
        super.onStop()
    }

    /** 别的 App 分享来的：文件当附件（新开一段对话），文字放进输入框 */
    private fun shared(intent: Intent?) {
        if (intent == null) return
        val uris = when (intent.action) {
            Intent.ACTION_SEND -> listOfNotNull(IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java))
            Intent.ACTION_SEND_MULTIPLE -> IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java).orEmpty()
            else -> return
        }
        if (Aide.card.value?.running != true) Aide.newChat()
        if (uris.isNotEmpty()) Aide.attach(this, uris)
        val text = listOfNotNull(intent.getStringExtra(Intent.EXTRA_SUBJECT), intent.getStringExtra(Intent.EXTRA_TEXT))
            .filter { it.isNotBlank() }.distinct().joinToString("\n")
        if (text.isNotBlank()) Aide.draft.value = text
    }
}
