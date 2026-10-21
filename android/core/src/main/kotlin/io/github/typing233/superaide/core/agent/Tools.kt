package io.github.typing233.superaide.core.agent

import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.core.llm.ToolCall
import io.github.typing233.superaide.core.llm.ToolOutput
import io.github.typing233.superaide.core.llm.ToolSpec
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

enum class Mode { ASK, ACT }

/** 工具真正的执行在 App 里（无障碍服务）；core 只定义名字、参数和进度文字。 */
interface ToolHost {
    suspend fun run(call: ToolCall, mode: Mode): ToolOutput
}

/** 工具定义。名字和写法沿用桌面版 cu/server.py，模型提示词基本不用改。 */
object Tools {
    private fun schema(s: String) = Json.parseToJsonElement(s).jsonObject

    val observe = ToolSpec(
        "observe_screen",
        "看手机屏幕：返回能操作的元素列表（带编号）和画好编号的截图。screenshot=false 只要文字列表（更快、更省）。",
        schema("""{"type":"object","properties":{"screenshot":{"type":"boolean","default":true}}}"""),
    )

    val find = ToolSpec(
        "find",
        "在最近一次观察的屏幕里按名字（或内容）找元素，包括已加载但滚出屏幕的。找到的会加上新编号，可以直接用来 act。",
        schema("""{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}"""),
    )

    val read = ToolSpec(
        "read",
        "逐字读文字：给 id 就读那个元素（和它里面的所有文字），不给就读整个屏幕。比看截图准，拼写以它为准。长的分页读。",
        schema(
            """{"type":"object","properties":{"id":{"type":"integer"},"start":{"type":"integer","default":0},
               "max_chars":{"type":"integer","default":8000}}}"""
        ),
    )

    val zoom = ToolSpec(
        "zoom",
        "放大最近一次截图里的一块区域（截图坐标），返回原始分辨率的图，看清小字和小图标。",
        schema(
            """{"type":"object","properties":{"x0":{"type":"integer"},"y0":{"type":"integer"},"x1":{"type":"integer"},
               "y1":{"type":"integer"}},"required":["x0","y0","x1","y1"]}"""
        ),
    )

    val apps = ToolSpec(
        "apps",
        "列出手机上能打开的 App（名字和包名）。query 可选，按名字筛选。",
        schema("""{"type":"object","properties":{"query":{"type":"string"}}}"""),
    )

    val point = ToolSpec(
        "point",
        "在用户屏幕上把要点的地方圈出来（可以一次圈几个，编号和你回答里的步骤对应）。目标用 id 或截图坐标框 x0,y0,x1,y1；label 是一句简短说明。",
        schema(
            """{"type":"object","properties":{"targets":{"type":"array","items":{"type":"object","properties":{
               "id":{"type":"integer"},"x0":{"type":"integer"},"y0":{"type":"integer"},"x1":{"type":"integer"},"y1":{"type":"integer"},
               "label":{"type":"string"}},"required":["label"]}},"seconds":{"type":"number","default":30}},"required":["targets"]}"""
        ),
    )

    val act = ToolSpec(
        "act",
        "按顺序执行一组动作（失败就停在那一步），默认执行完再观察一次并返回新的截图。\n" +
            "do 可以是：tap、long_press、double_tap、type（text；输入框里已经有字时必须说明：replace=true 先清空，append=true 接在后面，聊天框里用户没发的草稿不能动；enter=true 输完按回车/搜索）、" +
            "scroll（direction=up/down/left/right，amount 屏数）、swipe（x,y → to_x,to_y）、" +
            "back、home、recents、notifications、wait（seconds）、wait_for（text 出现，最多 seconds 秒）、" +
            "open_app（app：名字或包名）、open_url（url，也可以是 App 自带的链接）。\n" +
            "目标用 id（observe_screen 里的编号）或截图坐标 x、y。编号只在最近一次观察里有效。",
        schema(
            """{"type":"object","properties":{"actions":{"type":"array","items":{"type":"object","properties":{
               "do":{"type":"string","enum":["tap","long_press","double_tap","type","scroll","swipe","back","home","recents",
                     "notifications","wait","wait_for","open_app","open_url"]},
               "id":{"type":"integer"},"x":{"type":"integer"},"y":{"type":"integer"},"to_x":{"type":"integer"},"to_y":{"type":"integer"},
               "text":{"type":"string"},"replace":{"type":"boolean"},"append":{"type":"boolean"},"enter":{"type":"boolean"},
               "direction":{"type":"string","enum":["up","down","left","right"]},"amount":{"type":"number"},
               "seconds":{"type":"number"},"app":{"type":"string"},"url":{"type":"string"}},"required":["do"]}},
               "observe_after":{"type":"boolean","default":true}},"required":["actions"]}"""
        ),
    )

    val recall = ToolSpec(
        "recall",
        "查以前在相似问题上踩过的坑：碰到报错、卡住、或者准备做有风险的操作之前用。",
        schema("""{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}"""),
    )

    // ---- 和 Claude Code / Codex 一样的通用工具：联网、文件、跑代码（core/work/WorkTools.kt） ----

    val webSearch = ToolSpec(
        "web_search",
        "联网搜索（百度 + 必应）。返回标题、链接和摘要。新闻、天气、价格、版本号、政策、营业时间这类会变的信息，以及你拿不准的事实，先搜再答。" +
            "搜索词写得像人搜的那样（关键词，必要时带年份）。要看全文、核对细节用 web_fetch 打开链接。",
        schema("""{"type":"object","properties":{"query":{"type":"string"},"max_results":{"type":"integer","default":8}},"required":["query"]}"""),
    )

    val webFetch = ToolSpec(
        "web_fetch",
        "打开网址读正文：网页（要 JS 渲染的页面会用内置浏览器打开）、PDF、文本文件。返回标题、最终网址、正文（长的分页读，用 start 接着读）和正文里的链接。" +
            "PDF 等文件会存进工作区的 web/ 目录。",
        schema(
            """{"type":"object","properties":{"url":{"type":"string"},"start":{"type":"integer","default":0},
               "max_chars":{"type":"integer","default":10000}},"required":["url"]}"""
        ),
    )

    val files = ToolSpec(
        "files",
        "列出这段对话工作区里的文件：用户给的（inbox/）、你生成的（根目录）、网上下载的（web/）。",
        schema("""{"type":"object","properties":{}}"""),
    )

    val readFile = ToolSpec(
        "read_file",
        "读工作区里的文件：PDF、Word（docx）、Excel（xlsx）、PowerPoint（pptx）、各种文本和代码；图片会直接给你看，并附上图里认出来的字。长的分页读，用 start 接着读。",
        schema(
            """{"type":"object","properties":{"path":{"type":"string"},"start":{"type":"integer","default":0},
               "max_chars":{"type":"integer","default":10000}},"required":["path"]}"""
        ),
    )

    val writeFile = ToolSpec(
        "write_file",
        "在工作区里写文件。写好的文件显示在回答下面，用户点一下就能打开、分享或存到手机。按扩展名：\n" +
            "- .docx：content 写 Markdown（# 标题、- 列表、| 表格 |、**粗体**），转成 Word；\n" +
            "- .xlsx：content 写 CSV 或 Markdown 表格，第一行是表头；多张工作表时每张前面一行「## 表名」；= 开头的是公式；转成 Excel；\n" +
            "- .pdf：content 写 Markdown，排版成 PDF；\n" +
            "- 其他（.md .txt .csv .html .json .svg .ics …）原样写入，append=true 接在后面。\n" +
            "同名文件会被覆盖。inbox/ 里是用户的原件，不能改。",
        schema(
            """{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"},"append":{"type":"boolean","default":false}},
               "required":["path","content"]}"""
        ),
    )

    val runJs = ToolSpec(
        "run_js",
        "在隔离的 JavaScript 沙箱里运行代码（不能联网，碰不到手机上别的东西）：精确计算、统计、处理表格数据、转换格式、生成文件内容。\n" +
            "代码在 async 函数里运行，可以 await；console.log 打印的内容和 return 的值会返回给你。\n" +
            "读写工作区：await files.read(path) 返回文字（docx / xlsx / pdf 返回抽出来的文字，xlsx 是 Markdown 表格）；" +
            "await files.write(path, text) 写文件（规则和 write_file 一样）。",
        schema(
            """{"type":"object","properties":{"code":{"type":"string"},"timeout_seconds":{"type":"integer","default":30}},"required":["code"]}"""
        ),
    )

    val work = listOf(webSearch, webFetch, files, readFile, writeFile, runJs)

    fun forMode(mode: Mode, withRecall: Boolean = true): List<ToolSpec> =
        (if (mode == Mode.ACT) listOf(observe, act, find, read, zoom, apps, point) else listOf(observe, find, read, zoom, apps, point)) +
            work + (if (withRecall) listOf(recall) else emptyList())

    /** 不碰屏幕、互不影响的工具：模型一次要调好几个时一起跑 */
    val parallel = setOf("web_search", "web_fetch", "files", "read_file", "recall")

    private val verbs = mapOf(
        "tap" to "正在点击", "long_press" to "正在长按", "double_tap" to "正在双击", "type" to "正在输入",
        "scroll" to "正在滚动", "swipe" to "正在滑动", "back" to "正在返回", "home" to "正在回到桌面",
        "recents" to "正在打开最近任务", "notifications" to "正在打开通知栏", "wait" to "正在等待",
    )

    /** 工具调用 → 界面上的一行进度 */
    fun status(call: ToolCall): String {
        val a: JsonObject = call.input ?: JsonObject(emptyMap())
        fun s(o: JsonObject, k: String) = o[k]?.jsonPrimitive?.contentOrNull.orEmpty()
        return when (call.name) {
            "observe_screen" -> tr("正在看屏幕…")
            "find" -> tr("正在找「{target}」…", "target" to s(a, "text"))
            "read" -> tr("正在读屏幕上的文字…")
            "zoom" -> tr("正在放大看细节…")
            "apps" -> tr("正在查看手机上的 App…")
            "point" -> tr("正在屏幕上圈出位置…")
            "recall" -> tr("正在回想以前的经验…")
            "web_search" -> tr("正在搜索「{target}」…", "target" to s(a, "query").take(40))
            "web_fetch" -> tr("正在读网页 {url}…", "url" to host(s(a, "url")))
            "files" -> tr("正在看工作区里的文件…")
            "read_file" -> tr("正在读「{target}」…", "target" to s(a, "path").substringAfterLast('/'))
            "write_file" -> tr("正在写「{target}」…", "target" to s(a, "path").substringAfterLast('/'))
            "run_js" -> tr("正在运行代码…")
            "act" -> {
                val actions = runCatching { a["actions"]!!.jsonArray.map { it.jsonObject } }.getOrDefault(emptyList())
                val first = actions.firstOrNull() ?: JsonObject(emptyMap())
                val text = when (val d = s(first, "do")) {
                    "open_app" -> tr("正在打开「{target}」", "target" to s(first, "app"))
                    "open_url" -> tr("正在打开 {url}", "url" to s(first, "url").take(50))
                    "wait_for" -> tr("正在等「{target}」出现", "target" to s(first, "text"))
                    else -> tr(verbs[d] ?: "正在操作手机")
                }
                if (actions.size <= 1) "$text…" else tr("{action}（共 {count} 步）…", "action" to text, "count" to actions.size)
            }
            else -> tr("正在操作手机…")
        }
    }

    /** 进度里只显示网址的域名（完整网址太长） */
    private fun host(url: String): String =
        url.substringAfter("://").substringBefore('/').substringBefore('?').removePrefix("www.").ifBlank { url.take(40) }

    /** 看实时屏幕的工具：用过它们的问答不拿去后台对比 */
    fun looksAtScreen(name: String) = name in setOf("observe_screen", "find", "read", "zoom", "point", "act")
}
