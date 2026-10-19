package io.github.typing233.superaide.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.typing233.superaide.data.SettingsStore
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.system.Apps

/**
 * 隐私名单：这些 App 的界面不读（截图涂黑、文字不采集），也不替你操作。默认是常见的密码管理器。
 */
@Composable
fun PrivacyPage(settings: SettingsStore, apps: Apps, onBack: () -> Unit) {
    val t = LocalTokens.current
    val s by settings.state.collectAsState()
    var adding by remember { mutableStateOf(false) }
    var query by remember { mutableStateOf("") }
    val installed = remember { apps.launchable() }
    SubPage(if (adding) tr("加到隐私名单") else tr("隐私名单"), onBack = { if (adding) adding = false else onBack() }) {
        if (!adding) Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(tr("这些 App 的界面不读、不截，也不替你操作。"), color = t.text3, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 4.dp))
            SettingsSection("") {
                for (pkg in s.blockedApps) {
                    Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 4.dp, top = 4.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(apps.label(pkg), color = t.text, fontSize = 15.sp)
                            Text(pkg, color = t.text3, fontSize = 12.sp)
                        }
                        Icon(Icons.Filled.Close, tr("移除"), tint = t.text3,
                            modifier = Modifier.size(40.dp).clip(CircleShape).clickable {
                                settings.update { it.copy(blockedApps = it.blockedApps - pkg) }
                            }.padding(10.dp))
                    }
                }
                SettingsRow(tr("添加 App"), "+") { adding = true; query = "" }
            }
        } else Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(cardBackground()).padding(12.dp)) {
                BasicTextField(query, { query = it }, singleLine = true, textStyle = TextStyle(color = t.text, fontSize = 15.sp),
                    cursorBrush = SolidColor(t.askA), modifier = Modifier.fillMaxWidth())
                if (query.isEmpty()) Text(tr("搜索 App"), color = t.text3, fontSize = 15.sp)
            }
            val shown = installed.filter { it.pkg !in s.blockedApps && (query.isBlank() || query.lowercase() in it.label.lowercase() || query.lowercase() in it.pkg) }
            LazyColumn(Modifier.fillMaxSize().clip(RoundedCornerShape(14.dp)).background(cardBackground())) {
                items(shown, key = { it.pkg }) { a ->
                    Column(Modifier.fillMaxWidth().clickable {
                        settings.update { it.copy(blockedApps = it.blockedApps + a.pkg) }
                        adding = false
                    }.padding(horizontal = 12.dp, vertical = 10.dp)) {
                        Text(a.label, color = t.text, fontSize = 15.sp)
                        Text(a.pkg, color = t.text3, fontSize = 12.sp)
                    }
                }
            }
        }
    }
}
