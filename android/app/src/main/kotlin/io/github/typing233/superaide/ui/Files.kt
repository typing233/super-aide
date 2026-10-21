package io.github.typing233.superaide.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.typing233.superaide.core.files.Workspace
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.core.session.FileRef
import io.github.typing233.superaide.run.Aide
import io.github.typing233.superaide.work.FileActions
import java.io.File

/** 几个 material-icons-core 里没有的图标（Material Symbols 的路径） */
object AideIcons {
    private fun icon(name: String, path: String) = ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f)
        .addPath(addPathNodes(path), fill = SolidColor(Color.Black)).build()

    val attach = icon("attach", "M16.5,6v11.5c0,2.21 -1.79,4 -4,4s-4,-1.79 -4,-4V5c0,-1.38 1.12,-2.5 2.5,-2.5s2.5,1.12 2.5,2.5v10.5c0,0.55 -0.45,1 -1,1s-1,-0.45 -1,-1V6H10v9.5c0,1.38 1.12,2.5 2.5,2.5s2.5,-1.12 2.5,-2.5V5c0,-2.21 -1.79,-4 -4,-4S7,2.79 7,5v12.5c0,3.04 2.46,5.5 5.5,5.5s5.5,-2.46 5.5,-5.5V6h-1.5z")
    val download = icon("download", "M19,9h-4V3H9v6H5l7,7 7,-7zM5,18v2h14v-2H5z")
    val expand = icon("expand", "M21,11V3h-8l3.29,3.29l-10,10L3,13v8h8l-3.29,-3.29l10,-10L21,11z")
    val doc = icon("doc", "M14,2H6c-1.1,0 -1.99,0.9 -1.99,2L4,20c0,1.1 0.89,2 1.99,2H18c1.1,0 2,-0.9 2,-2V8l-6,-6zM16,18H8v-2h8v2zM16,14H8v-2h8v2zM13,9V3.5L18.5,9H13z")
    val newChat = icon("new", "M19,13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z")
}

/** 助手生成的文件：点一下打开，旁边是分享、存到手机 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun FileChips(files: List<FileRef>, modifier: Modifier = Modifier) {
    if (files.isEmpty()) return
    val t = LocalTokens.current
    val context = LocalContext.current
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (f in files) {
            val file = Aide.fileFor(f.path)
            val shape = RoundedCornerShape(12.dp)
            Row(
                Modifier.clip(shape).background(t.hover).border(1.dp, t.stroke, shape)
                    .clickable(enabled = file != null) { file?.let { FileActions.open(context, it) } }
                    .padding(start = 10.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Icon(AideIcons.doc, null, tint = t.accent(io.github.typing233.superaide.core.agent.Mode.ASK), modifier = Modifier.size(20.dp))
                Column(Modifier.weight(1f, fill = false).widthIn(max = 220.dp)) {
                    Text(f.name, color = t.text, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(if (file == null) tr("文件已清理") else Workspace.size(file.length()), color = t.text3, fontSize = 11.sp)
                }
                if (file != null) {
                    Icon(Icons.Filled.Share, tr("分享"), tint = t.text2,
                        modifier = Modifier.size(36.dp).clip(CircleShape).clickable { FileActions.share(context, file) }.padding(9.dp))
                    Icon(AideIcons.download, tr("存到手机"), tint = t.text2,
                        modifier = Modifier.size(36.dp).clip(CircleShape).clickable { FileActions.saveToDownloads(context, file) }.padding(8.dp))
                }
            }
        }
    }
}

/** 还没发出去的附件：每个一个小签，点 × 去掉 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun AttachmentChips(files: List<File>, onRemove: (File) -> Unit) {
    if (files.isEmpty()) return
    val t = LocalTokens.current
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (f in files) {
            Row(
                Modifier.clip(CircleShape).background(t.surface).border(1.dp, t.stroke, CircleShape).padding(start = 10.dp, end = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(f.name, color = t.text2, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.widthIn(max = 180.dp))
                Icon(Icons.Filled.Close, tr("去掉"), tint = t.text3,
                    modifier = Modifier.size(28.dp).clip(CircleShape).clickable { onRemove(f) }.padding(7.dp))
            }
        }
    }
}

/** 问题下面的附件名（已经发出去的） */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SentAttachments(names: List<String>) {
    if (names.isEmpty()) return
    val t = LocalTokens.current
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        for (n in names) Row(
            Modifier.clip(CircleShape).background(t.hover).padding(horizontal = 8.dp, vertical = 3.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Icon(AideIcons.attach, null, tint = t.text3, modifier = Modifier.size(12.dp))
            Text(n, color = t.text2, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.widthIn(max = 200.dp))
        }
    }
}
