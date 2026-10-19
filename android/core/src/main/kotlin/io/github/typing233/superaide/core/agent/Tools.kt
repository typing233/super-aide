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
            "do 可以是：tap、long_press、double_tap、type（text；replace=true 先清空；enter=true 输完按回车/搜索）、" +
            "scroll（direction=up/down/left/right，amount 屏数）、swipe（x,y → to_x,to_y）、" +
            "back、home、recents、notifications、wait（seconds）、wait_for（text 出现，最多 seconds 秒）、" +
            "open_app（app：名字或包名）、open_url（url，也可以是 App 自带的链接）。\n" +
            "目标用 id（observe_screen 里的编号）或截图坐标 x、y。编号只在最近一次观察里有效。",
        schema(
            """{"type":"object","properties":{"actions":{"type":"array","items":{"type":"object","properties":{
               "do":{"type":"string","enum":["tap","long_press","double_tap","type","scroll","swipe","back","home","recents",
                     "notifications","wait","wait_for","open_app","open_url"]},
               "id":{"type":"integer"},"x":{"type":"integer"},"y":{"type":"integer"},"to_x":{"type":"integer"},"to_y":{"type":"integer"},
               "text":{"type":"string"},"replace":{"type":"boolean"},"enter":{"type":"boolean"},
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

    fun forMode(mode: Mode, withRecall: Boolean = true): List<ToolSpec> =
        (if (mode == Mode.ACT) listOf(observe, act, find, read, zoom, apps, point) else listOf(observe, find, read, zoom, apps, point)) +
            (if (withRecall) listOf(recall) else emptyList())

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

    /** 看实时屏幕的工具：用过它们的问答不拿去后台对比 */
    fun looksAtScreen(name: String) = name in setOf("observe_screen", "find", "read", "zoom", "point", "act")
}
