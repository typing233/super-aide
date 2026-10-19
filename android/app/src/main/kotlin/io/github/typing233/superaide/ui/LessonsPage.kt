package io.github.typing233.superaide.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.typing233.superaide.core.experience.Lesson
import io.github.typing233.superaide.core.experience.Store
import io.github.typing233.superaide.core.i18n.tr

/**
 * 经验：踩过的坑总结出来的，碰到相似情况才会想起（平时不带）。左滑删除，几秒内能撤销。
 */
@Composable
fun LessonsPage(store: Store, onBack: () -> Unit) {
    val t = LocalTokens.current
    val lessons = remember { mutableStateListOf<Lesson>().apply { addAll(store.all().sortedByDescending { it.updated }) } }
    var removed by remember { mutableStateOf<Pair<Int, Lesson>?>(null) }
    // 撤销回来的换个 key：列表按 key 记着滑动状态，原 key 会让它停在"已滑走"
    val restores = remember { mutableStateMapOf<String, Int>() }
    SubPage(tr("经验"), onBack) {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(tr("走了弯路、被纠正或者你说「记住」的对话，结束后会总结成一条经验；碰到相似情况才会想起，平时不带。"),
                color = t.text3, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 4.dp))
            if (lessons.isEmpty()) Text(tr("还没有经验"), color = t.text3, fontSize = 14.sp, modifier = Modifier.padding(12.dp))
            LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(lessons, key = { "${it.id}#${restores[it.id] ?: 0}" }) { l ->
                    val state = rememberSwipeToDismissBoxState(confirmValueChange = { v ->
                        if (v == SwipeToDismissBoxValue.EndToStart && l in lessons) { // 可能连着回调两次
                            val index = lessons.indexOf(l)
                            store.remove(l.id)
                            lessons.remove(l)
                            removed = index to l
                        }
                        v == SwipeToDismissBoxValue.EndToStart
                    })
                    SwipeToDismissBox(state, enableDismissFromStartToEnd = false, backgroundContent = {
                        Box(Modifier.fillMaxSize().clip(RoundedCornerShape(12.dp)).background(t.err).padding(horizontal = 16.dp),
                            contentAlignment = Alignment.CenterEnd) { Text(tr("删除"), color = Color.White, fontSize = 14.sp) }
                    }) {
                        Column(
                            Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(cardBackground()).padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Text(l.title, color = t.text, fontSize = 15.sp)
                            Text(tr("适用：{when}", "when" to l.`when`), color = t.text2, fontSize = 13.sp)
                            Text(l.advice, color = t.text2, fontSize = 13.sp)
                            Text(when {
                                l.uses == 0 -> tr("还没想起过")
                                l.fails == 0 -> tr("想起过 {uses} 次", "uses" to l.uses)
                                else -> tr("想起过 {uses} 次，其中 {fails} 次没帮上", "uses" to l.uses, "fails" to l.fails)
                            }, color = t.text3, fontSize = 12.sp)
                        }
                    }
                }
            }
        }
        removed?.let { (index, l) ->
            UndoBar(tr("已删除"), key = l.id, onUndo = {
                store.restore(l)
                restores[l.id] = (restores[l.id] ?: 0) + 1
                lessons.add(index.coerceIn(0, lessons.size), l)
                removed = null
            }, onExpire = { if (removed?.second?.id == l.id) removed = null })
        }
    }
}
