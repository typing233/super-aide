package io.github.typing233.superaide.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.typing233.superaide.core.i18n.tr
import kotlinx.coroutines.delay

/** 设置页的底色 */
@Composable
fun pageBackground(): Color = if (LocalTokens.current.dark) Color(0xFF111113) else Color(0xFFF5F5F7)

@Composable
fun cardBackground(): Color = if (LocalTokens.current.dark) Color(0xFF1C1C1F) else Color.White

/** 二级页面：左上角返回 + 标题，下面是内容 */
@Composable
fun SubPage(title: String, onBack: () -> Unit, content: @Composable () -> Unit) {
    val t = LocalTokens.current
    Column(Modifier.fillMaxSize().background(pageBackground()).safeDrawingPadding()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, tr("返回"), tint = t.text,
                modifier = Modifier.size(44.dp).clip(CircleShape).clickable(onClick = onBack).padding(10.dp))
            Text(title, color = t.text, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
        }
        Box(Modifier.weight(1f).padding(horizontal = 16.dp)) { content() }
    }
}

@Composable
fun SettingsSection(title: String, content: @Composable () -> Unit) {
    val t = LocalTokens.current
    Column {
        if (title.isNotEmpty()) Text(title, color = t.text2, fontSize = 13.sp, modifier = Modifier.padding(start = 4.dp, bottom = 6.dp))
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(cardBackground())) { content() }
    }
}

@Composable
fun SettingsRow(label: String, value: String, sub: String = "", onClick: () -> Unit) {
    val t = LocalTokens.current
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(label, color = t.text, fontSize = 15.sp)
            if (sub.isNotEmpty()) Text(sub, color = t.text3, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        Text(value, color = t.askA, fontSize = 15.sp, modifier = Modifier.padding(start = 8.dp))
    }
}

@Composable
fun SettingsToggle(label: String, on: Boolean, trailing: @Composable () -> Unit = {}, onChange: (Boolean) -> Unit) {
    val t = LocalTokens.current
    Row(
        Modifier.fillMaxWidth().clickable { onChange(!on) }.padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, color = t.text, fontSize = 15.sp, modifier = Modifier.weight(1f))
        trailing()
        Switch(on, onChange)
    }
}

@Composable
fun SettingsChoice(label: String, options: List<Pair<String, String>>, value: String, onPick: (String) -> Unit) {
    val t = LocalTokens.current
    Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
        Text(label, color = t.text2, fontSize = 13.sp)
        Spacer(Modifier.height(6.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for ((v, name) in options) Pill(name, v == value) { onPick(v) }
        }
    }
}

@Composable
fun Pill(text: String, selected: Boolean, onClick: () -> Unit) {
    val t = LocalTokens.current
    Text(text, color = if (selected) Color.White else t.text, fontSize = 14.sp,
        modifier = Modifier.clip(RoundedCornerShape(999.dp)).background(if (selected) t.askA else t.hover)
            .clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 6.dp))
}

/** 删掉以后底部的"已删除 · 撤销"，几秒后自己消失（消失时 onExpire：真正删掉） */
@Composable
fun UndoBar(message: String, onUndo: () -> Unit, onExpire: () -> Unit, key: Any) {
    val t = LocalTokens.current
    LaunchedEffect(key) {
        delay(5_000)
        onExpire()
    }
    Box(Modifier.fillMaxSize().navigationBarsPadding().padding(bottom = 12.dp), contentAlignment = Alignment.BottomCenter) {
        Row(
            Modifier.clip(RoundedCornerShape(12.dp)).background(if (t.dark) Color(0xFF2C2C30) else Color(0xFF2B2B2E))
                .padding(start = 16.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(message, color = Color.White, fontSize = 14.sp)
            Text(tr("撤销"), color = t.askA, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(start = 12.dp).clip(RoundedCornerShape(8.dp)).clickable(onClick = onUndo).padding(12.dp))
        }
    }
}
