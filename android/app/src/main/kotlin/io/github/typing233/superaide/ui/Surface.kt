package io.github.typing233.superaide.ui

import android.content.ClipData
import android.content.ClipboardManager
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ThumbUp
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mikepenz.markdown.m3.Markdown
import com.mikepenz.markdown.m3.markdownColor
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.core.session.CardState
import io.github.typing233.superaide.run.Aide

/**
 * 打字宿主里的整块界面：底部输入框，问过之后上面是回答卡片。点空白处收起。
 * 透明 Activity 和默认助手的会话窗口共用它。
 */
@Composable
fun AideSurface(onDismiss: () -> Unit) {
    val surface by Aide.surface.collectAsState()
    val card by Aide.card.collectAsState()
    val mode by Aide.mode.collectAsState()
    Box(
        Modifier.fillMaxSize().clickable(remember { MutableInteractionSource() }, indication = null) { onDismiss() },
        contentAlignment = Alignment.BottomCenter,
    ) {
        Column(
            Modifier.fillMaxWidth().statusBarsPadding().navigationBarsPadding().imePadding().padding(12.dp)
                .clickable(remember { MutableInteractionSource() }, indication = null) {},
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            val c = card
            if (surface == Aide.Surface.CARD && c != null) AnswerCard(c, Modifier.weight(1f, fill = false))
            InputBar(
                mode = if (surface == Aide.Surface.CARD && c != null) c.mode else mode,
                running = c?.running == true && surface == Aide.Surface.CARD,
                followup = surface == Aide.Surface.CARD && c != null,
                recent = surface == Aide.Surface.INPUT && Aide.hasRecent(),
            )
        }
    }
}

@Composable
fun InputBar(mode: Mode, running: Boolean, followup: Boolean, recent: Boolean) {
    val t = LocalTokens.current
    var text by rememberSaveable { mutableStateOf("") }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    val shape = RoundedCornerShape(Radius.input)
    val send = {
        if (text.isNotBlank() && !running) { Aide.submit(text); text = "" }
    }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        if (recent) Chip(tr("接着刚才的问")) { Aide.restore() }
        Row(
            Modifier.fillMaxWidth().shadow(12.dp, shape).clip(shape).background(t.surface).border(1.dp, t.stroke, shape).padding(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ModeChip(mode, enabled = !followup) { Aide.setMode(if (mode == Mode.ASK) Mode.ACT else Mode.ASK) }
            BasicTextField(
                value = text,
                onValueChange = { text = it },
                textStyle = TextStyle(color = t.text, fontSize = 16.sp),
                cursorBrush = SolidColor(t.accent(mode)),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { send() }),
                maxLines = 5,
                modifier = Modifier.weight(1f).padding(horizontal = 10.dp, vertical = 8.dp).focusRequester(focus),
                decorationBox = { inner ->
                    if (text.isEmpty()) Text(placeholder(mode, followup), color = t.text3, fontSize = 16.sp)
                    inner()
                },
            )
            if (running) RoundButton(t.err, onClick = Aide::stop) { Box(Modifier.size(10.dp).background(Color.White, RoundedCornerShape(2.dp))) }
            else RoundButton(null, mode, enabled = text.isNotBlank(), onClick = send) {
                Icon(Icons.AutoMirrored.Filled.Send, null, tint = Color.White, modifier = Modifier.size(16.dp))
            }
        }
    }
}

private fun placeholder(mode: Mode, followup: Boolean) = when {
    followup -> tr("接着问…")
    mode == Mode.ACT -> tr("让我做点什么…")
    else -> tr("问点什么…")
}

@Composable
private fun ModeChip(mode: Mode, enabled: Boolean, onClick: () -> Unit) {
    val t = LocalTokens.current
    Box(
        Modifier.clip(CircleShape).background(t.gradient(mode)).clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 7.dp),
    ) {
        Text(if (mode == Mode.ACT) tr("做") else tr("问"), color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
    }
}

@Composable
private fun RoundButton(color: Color?, mode: Mode = Mode.ASK, enabled: Boolean = true, onClick: () -> Unit, content: @Composable () -> Unit) {
    val t = LocalTokens.current
    Box(
        Modifier.size(36.dp).clip(CircleShape)
            .then(if (color != null) Modifier.background(color) else Modifier.background(t.gradient(mode)))
            .alpha(if (enabled) 1f else 0.4f)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { content() }
}

@Composable
private fun Chip(label: String, onClick: () -> Unit) {
    val t = LocalTokens.current
    Text(
        label, color = t.text2, fontSize = 13.sp,
        modifier = Modifier.clip(CircleShape).background(t.surface).border(1.dp, t.stroke, CircleShape).clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    )
}

@Composable
fun AnswerCard(c: CardState, modifier: Modifier = Modifier) {
    val t = LocalTokens.current
    val shape = RoundedCornerShape(Radius.card)
    val maxH = (LocalConfiguration.current.screenHeightDp * 0.6f).dp
    val scroll = rememberScrollState()
    LaunchedEffect(c.answer.length, c.steps.size) { if (c.running) scroll.animateScrollTo(scroll.maxValue) }
    Column(
        modifier.fillMaxWidth().heightIn(max = maxH).shadow(16.dp, shape).clip(shape).background(t.surface).border(1.dp, t.stroke, shape)
            .padding(start = 16.dp, end = 8.dp, top = 8.dp, bottom = 12.dp).animateContentSize(),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(c.route, color = t.text3, fontSize = 12.sp, modifier = Modifier.weight(1f))
            Icon(Icons.Filled.Close, tr("关闭"), tint = t.text3,
                modifier = Modifier.size(32.dp).clip(CircleShape).clickable { Aide.close() }.padding(7.dp))
        }
        Column(Modifier.weight(1f, fill = false).verticalScroll(scroll).padding(end = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            for (e in c.earlier) {
                Text(e.question, color = t.text2, fontSize = 13.sp)
                Text(e.answer, color = t.text2, fontSize = 14.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
            if (c.question.isNotBlank()) Text(c.question, color = t.text2, fontSize = 13.sp)
            Steps(c)
            if (c.answer.isNotBlank()) {
                Markdown(content = c.answer, colors = markdownColor(text = t.text))
            } else if (c.running) {
                Pulse(c.transient ?: c.steps.lastOrNull() ?: tr("正在思考…"))
            }
            val err = c.error ?: c.reported
            if (c.done && !c.ok && !c.stopped && err != null) Text(err, color = t.err, fontSize = 14.sp)
            if (c.stopped) Text(tr("已停止"), color = t.text3, fontSize = 13.sp)
        }
        if (c.done) Footer(c)
    }
}

@Composable
private fun Steps(c: CardState) {
    if (c.steps.isEmpty()) return
    val t = LocalTokens.current
    var open by remember { mutableStateOf(false) }
    Column(Modifier.clip(RoundedCornerShape(8.dp)).clickable { open = !open }.padding(vertical = 2.dp)) {
        if (open) c.steps.forEach { Text("· $it", color = t.text3, fontSize = 13.sp) }
        else Text(
            if (c.running) c.steps.last() else tr("{count} 步", "count" to c.steps.size) + "  ›",
            color = t.text3, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
fun Pulse(text: String) {
    val t = LocalTokens.current
    val a by rememberInfiniteTransition(label = "pulse").animateFloat(0.35f, 1f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "a")
    Text(text, color = t.text2, fontSize = 14.sp, modifier = Modifier.alpha(a))
}

@Composable
private fun Footer(c: CardState) {
    val t = LocalTokens.current
    val context = LocalContext.current
    Row(Modifier.fillMaxWidth().padding(top = 8.dp, end = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Filled.ThumbUp, tr("有用"), tint = if (c.rating == 1) t.ok else t.text3,
            modifier = Modifier.size(32.dp).clip(CircleShape).clickable { Aide.feedback(if (c.rating == 1) 0 else 1) }.padding(7.dp))
        Icon(Icons.Filled.ThumbUp, tr("没用"), tint = if (c.rating == -1) t.err else t.text3,
            modifier = Modifier.size(32.dp).rotate(180f).clip(CircleShape).clickable { Aide.feedback(if (c.rating == -1) 0 else -1) }.padding(7.dp))
        Text(tr("复制"), color = t.text3, fontSize = 13.sp, modifier = Modifier.clip(CircleShape).clickable {
            context.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("answer", c.answer))
        }.padding(horizontal = 8.dp, vertical = 6.dp))
        Spacer(Modifier.weight(1f))
        if (c.fullPage && !c.handOff) Text(
            tr("读完整页"), color = t.accent(Mode.ASK), fontWeight = FontWeight.SemiBold, fontSize = 14.sp,
            modifier = Modifier.clip(CircleShape).background(t.hover).clickable { Aide.readFullPage(context) }
                .padding(horizontal = 14.dp, vertical = 8.dp),
        )
        if (c.handOff) Text(
            tr("让我来做"), color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 14.sp,
            modifier = Modifier.clip(CircleShape).background(t.gradient(Mode.ACT)).clickable { Aide.handOff() }
                .padding(horizontal = 14.dp, vertical = 8.dp),
        )
    }
}

/** 进度条 / 结果提示 / 收起后的小条（无障碍浮层里） */
@Composable
fun Pill(c: CardState, onTap: () -> Unit) {
    val t = LocalTokens.current
    val shape = RoundedCornerShape(Radius.pill)
    Row(
        Modifier.padding(8.dp).shadow(12.dp, shape).clip(shape).background(t.surface).border(1.dp, t.stroke, shape)
            .clickable(onClick = onTap).padding(start = 14.dp, end = 6.dp, top = 6.dp, bottom = 6.dp).widthIn(max = 320.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        val dot = when {
            c.running -> null
            c.ok -> t.ok
            else -> t.err
        }
        Box(Modifier.size(10.dp).clip(CircleShape).then(if (dot != null) Modifier.background(dot) else Modifier.background(t.gradient(c.mode))))
        val label = when {
            c.running -> c.transient ?: c.steps.lastOrNull() ?: tr("正在思考…")
            c.stopped -> tr("已停止")
            c.ok -> c.summary().ifBlank { tr("好了") }
            else -> c.reported ?: c.error ?: tr("没完成")
        }
        if (c.running) Pulse(label) else Text(label, color = t.text, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f, fill = false))
        if (c.running) Box(
            Modifier.size(30.dp).clip(CircleShape).background(t.hover).clickable(onClick = Aide::stop),
            contentAlignment = Alignment.Center,
        ) { Box(Modifier.size(9.dp).background(t.err, RoundedCornerShape(2.dp))) }
        else Spacer(Modifier.size(6.dp))
    }
}
