package io.github.typing233.superaide.work

import android.content.ActivityNotFoundException
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.widget.Toast
import androidx.core.content.FileProvider
import io.github.typing233.superaide.core.files.Workspace
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.diag.Diag
import java.io.File

/** 文件进出：别的 App 给的文件拷进来；助手生成的文件打开、分享、存到「下载」。 */
object FileActions {
    private fun authority(context: Context) = "${context.packageName}.files"

    fun uri(context: Context, file: File): Uri = FileProvider.getUriForFile(context, authority(context), file)

    fun open(context: Context, file: File) {
        val intent = Intent(Intent.ACTION_VIEW).setDataAndType(uri(context, file), Workspace.mime(file.name))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            context.startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            toast(context, tr("手机上没有能打开它的 App，可以分享出去或存到手机"))
        }
    }

    fun share(context: Context, file: File) {
        val intent = Intent(Intent.ACTION_SEND).setType(Workspace.mime(file.name))
            .putExtra(Intent.EXTRA_STREAM, uri(context, file))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        context.startActivity(Intent.createChooser(intent, file.name).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    /** 存到「下载/超级助手」（不要存储权限：MediaStore 自己的文件） */
    fun saveToDownloads(context: Context, file: File) {
        val dir = Environment.DIRECTORY_DOWNLOADS + "/" + FOLDER
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, file.name)
            put(MediaStore.MediaColumns.MIME_TYPE, Workspace.mime(file.name))
            put(MediaStore.MediaColumns.RELATIVE_PATH, dir)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val resolver = context.contentResolver
        val ok = runCatching {
            val target = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: error("insert")
            resolver.openOutputStream(target)!!.use { out -> file.inputStream().use { it.copyTo(out) } }
            resolver.update(target, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null)
            // 重名时系统会自动改名（加 (1)），告诉用户真正的名字
            resolver.query(target, arrayOf(MediaStore.MediaColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0) else file.name
            } ?: file.name
        }.onFailure { Diag.error("save.downloads", it) }
        toast(context, ok.fold({ tr("已存到 下载/{folder}/{name}", "folder" to FOLDER, "name" to it) }, { tr("没存成：{error}", "error" to (it.message ?: it.toString())) }))
    }

    private val FOLDER get() = tr("超级助手")

    /** 在哪个线程上调都行 */
    fun toast(context: Context, text: String) {
        android.os.Handler(android.os.Looper.getMainLooper()).post { Toast.makeText(context.applicationContext, text, Toast.LENGTH_SHORT).show() }
    }

    /** 别的 App 给的文件（分享、选文件）拷到 dir 下；返回拷好的文件 */
    fun import(context: Context, uris: List<Uri>, dir: File): List<File> = uris.mapNotNull { uri ->
        runCatching {
            val (name, size) = describe(context, uri)
            if (size > MAX_IMPORT) {
                toast(context, tr("「{name}」太大了（超过 100 MB），没加进来", "name" to name))
                return@runCatching null
            }
            val ws = Workspace(dir)
            val f = ws.unique("", name)
            context.contentResolver.openInputStream(uri)!!.use { input -> f.outputStream().use { input.copyTo(it) } }
            f
        }.onFailure { Diag.error("import", it) }.getOrNull()
    }

    private const val MAX_IMPORT = 100L * 1024 * 1024

    /** 文件名（没有扩展名的按类型补上）和大小 */
    private fun describe(context: Context, uri: Uri): Pair<String, Long> {
        var name = uri.lastPathSegment?.substringAfterLast('/').orEmpty()
        var size = -1L
        runCatching {
            context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    c.getString(0)?.let { name = it }
                    if (!c.isNull(1)) size = c.getLong(1)
                }
            }
        }
        if (name.isBlank()) name = "file"
        if (!name.contains('.')) {
            val type = context.contentResolver.getType(uri).orEmpty()
            (Workspace.extFor(type) ?: android.webkit.MimeTypeMap.getSingleton().getExtensionFromMimeType(type))?.let { name = "$name.$it" }
        }
        return Workspace.safeName(name) to size
    }
}
