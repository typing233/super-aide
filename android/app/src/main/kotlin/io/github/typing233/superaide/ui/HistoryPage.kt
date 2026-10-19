package io.github.typing233.superaide.ui

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.Text
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mikepenz.markdown.m3.Markdown
import com.mikepenz.markdown.m3.markdownColor
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.data.History
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 历史：搜索、左滑删除（几秒内能撤销）、点开看完整的问答。 */
@Composable
fun HistoryPage(history: History, onBack: () -> Unit) {
    val t = LocalTokens.current
    val entries = remember { history.purgeAll(); mutableStateListOf<History.Entry>().apply { addAll(history.list()) } }
    var query by rememberSaveable { mutableStateOf("") }
    var open by rememberSaveable { mutableStateOf<String?>(null) }
    var removed by remember { mutableStateOf<Pair<Int, History.Entry>?>(null) }
    // 撤销回来的换个 key：列表按 key 记着滑动状态，原 key 会让它停在"已滑走"
    val restores = remember { mutableStateMapOf<String, Int>() }
    val fmt = remember { SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()) }
    val shown = entries.filter { e ->
        query.isBlank() || e.turns.any { query.lowercase() in it.question.lowercase() || query.lowercase() in it.answer.lowercase() } ||
            query.lowercase() in e.app.lowercase()
    }
    SubPage(tr("历史"), onBack) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(cardBackground()).padding(12.dp)) {
                BasicTextField(query, { query = it }, singleLine = true, textStyle = TextStyle(color = t.text, fontSize = 15.sp),
                    cursorBrush = SolidColor(t.askA), modifier = Modifier.fillMaxWidth())
                if (query.isEmpty()) Text(tr("搜索问题和回答"), color = t.text3, fontSize = 15.sp)
            }
            if (shown.isEmpty()) Text(if (entries.isEmpty()) tr("还没有记录") else tr("没有找到"), color = t.text3, fontSize = 14.sp,
                modifier = Modifier.padding(12.dp))
            LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(shown, key = { "${it.id}#${restores[it.id] ?: 0}" }) { e ->
                    val state = rememberSwipeToDismissBoxState(confirmValueChange = { v ->
                        // 可能连着回调两次：已经删掉的不再处理（不然会把自己从回收站清掉，撤销不了）
                        if (v == SwipeToDismissBoxValue.EndToStart && e in entries) {
                            removed?.let { history.purge(it.second.id) } // 上一个撤销期没过的，直接删掉
                            val index = entries.indexOf(e)
                            history.delete(e.id)
                            entries.remove(e)
                            removed = index to e
                        }
                        v == SwipeToDismissBoxValue.EndToStart
                    })
                    SwipeToDismissBox(state, enableDismissFromStartToEnd = false, backgroundContent = {
                        Box(Modifier.fillMaxSize().clip(RoundedCornerShape(12.dp)).background(t.err).padding(horizontal = 16.dp),
                            contentAlignment = Alignment.CenterEnd) { Text(tr("删除"), color = androidx.compose.ui.graphics.Color.White, fontSize = 14.sp) }
                    }) {
                        EntryCard(e, open == e.id, fmt) { open = if (open == e.id) null else e.id }
                    }
                }
            }
        }
        removed?.let { (index, e) ->
            UndoBar(tr("已删除"), key = e.id, onUndo = {
                history.restore(e.id)
                restores[e.id] = (restores[e.id] ?: 0) + 1
                entries.add(index.coerceIn(0, entries.size), e)
                removed = null
            }, onExpire = {
                history.purge(e.id)
                if (removed?.second?.id == e.id) removed = null
            })
        }
    }
}

@Composable
private fun EntryCard(e: History.Entry, expanded: Boolean, fmt: SimpleDateFormat, onClick: () -> Unit) {
    val t = LocalTokens.current
    val first = e.turns.firstOrNull() ?: return
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(cardBackground()).clickable(onClick = onClick)
            .padding(12.dp).animateContentSize(),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(first.question.lineSequence().first(), color = t.text, fontSize = 15.sp, maxLines = if (expanded) 6 else 1,
            overflow = TextOverflow.Ellipsis)
        val mode = if (e.mode == "act") tr("做") else tr("问")
        Text(listOf(fmt.format(Date(e.time)), mode, e.app, "${first.model} · ${first.effort}").filter { it.isNotBlank() }.joinToString(" · ") +
            if (e.turns.any { !it.ok && !it.stopped }) " · ✗" else "", color = t.text3, fontSize = 12.sp)
        if (expanded) for ((i, turn) in e.turns.withIndex()) {
            if (i > 0) Text(turn.question, color = t.text2, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
            if (turn.answer.isNotBlank()) Markdown(content = turn.answer, colors = markdownColor(text = t.text))
            turn.error?.let { Text(it, color = t.err, fontSize = 13.sp) }
            if (turn.trace.isNotEmpty()) Text(turn.trace.joinToString("\n") { "· $it" }, color = t.text3, fontSize = 12.sp)
        }
    }
}
