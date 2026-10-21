package io.github.typing233.superaide.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mikepenz.markdown.m3.Markdown
import com.mikepenz.markdown.m3.markdownColor
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.core.session.CardState
import io.github.typing233.superaide.core.session.Exchange
import io.github.typing233.superaide.run.Aide

/**
 * 全屏对话页：和召唤出来的卡片是同一段对话，长任务、长回答在这里看得全。
 * 在这里问的不读屏幕（屏幕上是我们自己）；能加文件，生成的文件就在回答下面。
 */
@Composable
fun ChatPage(onBack: () -> Unit, onAttach: () -> Unit, onSettings: () -> Unit) {
    val t = LocalTokens.current
    val card by Aide.card.collectAsState()
    val mode by Aide.mode.collectAsState()
    val c = card
    val list = rememberLazyListState()
    val count = (c?.earlier?.size ?: 0) + 1
    LaunchedEffect(count, c?.answer?.length, c?.steps?.size, c?.files?.size) {
        if (c != null) list.animateScrollToItem(count - 1, Int.MAX_VALUE / 2)
    }
    Column(Modifier.fillMaxSize().background(pageBackground()).safeDrawingPadding()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, tr("返回"), tint = t.text,
                modifier = Modifier.size(44.dp).clip(CircleShape).clickable(onClick = onBack).padding(10.dp))
            Column(Modifier.weight(1f)) {
                Text(tr("超级助手"), color = t.text, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                if (c != null && c.route.isNotBlank()) Text(c.route, color = t.text3, fontSize = 12.sp)
            }
            val canNew = c != null && !c.running
            Icon(AideIcons.newChat, tr("新对话"), tint = t.text2,
                modifier = Modifier.size(44.dp).alpha(if (canNew) 1f else 0.35f).clip(CircleShape).clickable(enabled = canNew) { Aide.newChat() }.padding(10.dp))
            Icon(Icons.Filled.Settings, tr("设置"), tint = t.text2,
                modifier = Modifier.size(44.dp).clip(CircleShape).clickable(onClick = onSettings).padding(11.dp))
        }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (c == null) Empty()
            else LazyColumn(state = list, contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                itemsIndexed(c.earlier) { _, e -> Turn(e) }
                item { Current(c) }
            }
        }
        Box(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
            InputBar(
                mode = c?.mode ?: mode,
                running = c?.running == true,
                followup = c != null,
                recent = false,
                chat = true,
                onAttach = onAttach,
                autoFocus = c == null,
            )
        }
    }
}

@Composable
private fun Question(text: String, attachments: List<String>) {
    val t = LocalTokens.current
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            text, color = t.text, fontSize = 15.sp,
            modifier = Modifier.widthIn(max = 300.dp).clip(RoundedCornerShape(16.dp, 16.dp, 4.dp, 16.dp)).background(t.hover)
                .padding(horizontal = 12.dp, vertical = 8.dp),
        )
        SentAttachments(attachments)
    }
}

/** 前面几轮：问题 + 完整的回答 + 生成的文件 */
@Composable
private fun Turn(e: Exchange) {
    val t = LocalTokens.current
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Question(e.question, e.attachments)
        if (e.answer.isNotBlank()) Markdown(content = e.answer, colors = markdownColor(text = t.text))
        FileChips(e.files)
    }
}

@Composable
private fun Current(c: CardState) {
    val t = LocalTokens.current
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (c.question.isNotBlank()) Question(c.question, c.attachments)
        Steps(c)
        if (c.answer.isNotBlank()) Markdown(content = c.answer, colors = markdownColor(text = t.text))
        else if (c.running) Pulse(c.transient ?: c.steps.lastOrNull() ?: tr("正在思考…"))
        FileChips(c.files)
        val err = c.error ?: c.reported
        if (c.done && !c.ok && !c.stopped && err != null) Text(err, color = t.err, fontSize = 14.sp)
        if (c.stopped) Text(tr("已停止"), color = t.text3, fontSize = 13.sp)
        if (c.done) Footer(c, chat = true)
        Spacer(Modifier.height(4.dp))
    }
}

/** 还没问：一句说明，几个能直接点的例子 */
@Composable
private fun Empty() {
    val t = LocalTokens.current
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        Text(tr("问点什么"), color = t.text, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
        Text(tr("能联网查、读你给的文件、写文档和表格、算账"), color = t.text3, fontSize = 14.sp, modifier = Modifier.padding(top = 6.dp, bottom = 18.dp))
        for (s in listOf(tr("今天有什么值得关注的科技新闻？"), tr("做一张这个月的记账表格"), tr("帮我查一下最近的天气，适合出门吗？"))) {
            Text(
                s, color = t.text2, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(vertical = 4.dp).clip(CircleShape).border(1.dp, t.stroke, CircleShape).clickable { Aide.draft.value = s }
                    .padding(horizontal = 14.dp, vertical = 8.dp),
            )
        }
    }
}
