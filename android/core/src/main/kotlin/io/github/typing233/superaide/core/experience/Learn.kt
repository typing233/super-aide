package io.github.typing233.superaide.core.experience

import io.github.typing233.superaide.core.redact.Redact
import io.github.typing233.superaide.core.session.TurnRecord
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/**
 * 从踩过的坑里总结经验（对应桌面版 experience/learn.py）。一段对话结束（最后一轮之后两分钟没追问），
 * 而且走了弯路的才总结：没办成、被纠正、一轮里绕了很久、用户说了"记住""以后别…"。顺利的不总结。
 */
object Learn {
    const val LEARN_DELAY_MS = 120_000L
    const val LONG_TURN_S = 120.0
    const val MANY_TOOLS = 12
    const val SIMILAR = 5
    private val REMEMBER = Regex("记住|以后|下次|别再|不要再|每次都")

    private const val PROMPT = """你在帮一个安卓手机助手积累"经验"。下面是它刚处理完的一次对话（{reason}）。
请判断里面有没有值得记住、以后遇到相似情况能少走弯路的经验。

好的经验：
- 可复用：换一台手机、换一个具体的页面或聊天，相似的情况下照样适用，不是这一次的流水账；
- 具体可执行：说清楚遇到什么情况、该怎么做或别怎么做，带上能一眼认出这种情况的特征（报错原文、App、网站、界面上的说法）；
- 是真正的坑或者捷径：助手判断错了、绕了远路、被用户纠正了、费了很大劲才找到办法，或者用户明确要求以后怎么做。
不要记：常识、这次碰巧的偶发问题（网络抖动、服务暂时不可用）、用户的隐私（人名、账号、聊天和文件的内容）。
原因要有记录支撑：记录里看不出确切原因时，不要猜一个原因写成经验，宁可不记。

库里已有的相似经验（可能为空）：
{similar}

和某条已有经验说的是同一件事，就用 update 把它改得更准、补上新的线索；是新的经验用 add；没有值得记的用 none。
只输出一个 JSON 对象，不要别的文字：
{"action": "none 或 add 或 update", "id": "update 时填已有经验的编号",
 "title": "一句话说清是什么坑，20 字以内（对话是英文的就用英文写，10 个词以内；它会显示给用户）",
 "when": "什么情况下适用，具体到能判断",
 "advice": "该怎么做、别怎么做，1～3 句",
 "triggers": ["能认出这种情况的问题特征：报错里固定的说法、症状的各种说法、界面上的说法，6～15 个，中英文同义词都写。不要写：报错、错误、问题、安装、软件这类太宽泛的词；App 名、网站名（写到 apps、domains 里）；这一次具体的名字"],
 "errors": ["报错里固定不变、最有辨识度的部分；没有就留空"],
 "apps": ["相关 App 的包名，比如 com.tencent.mm；和具体 App 无关就留空"],
 "domains": ["相关网站的域名；和网站无关就留空"],
 "why": "为什么值得记，一句话"}

这次对话：
{conversation}"""

    /** 这次对话值不值得总结，值得就返回原因（写进提示词） */
    fun worth(turns: List<TurnRecord>, negative: Boolean): String {
        if (negative) return "用户说上一轮没答好"
        if (turns.any { !it.ok && !it.stopped && it.error == null }) return "没办成"
        if (turns.any { !it.ok && !it.stopped && it.error != null && !it.error.contains(Regex("连不上|限流|认证|超时|服务")) }) return "没办成"
        for (t in turns) {
            if (REMEMBER.containsMatchIn(t.question)) return "用户要求以后照着做"
            if (t.ok && (t.seconds >= LONG_TURN_S || t.tools >= MANY_TOOLS)) return "绕了很久才办完"
        }
        return ""
    }

    /** 给模型看的对话经过：长的截断，统一打码 */
    fun describe(turns: List<TurnRecord>, situation: Situation, feedback: String = ""): String {
        val parts = turns.mapIndexed { i, t ->
            buildList {
                add("【第 ${i + 1} 轮】问题：${t.question}")
                if (i == 0) {
                    val where = listOf(situation.app, situation.title.takeIf { it.isNotEmpty() }?.let { "「$it」" }).filterNotNull()
                        .filter { it.isNotEmpty() }.joinToString("，")
                    if (where.isNotEmpty()) add("当时的前台：$where")
                    if (situation.errors.isNotEmpty()) add("屏幕上的报错行：\n${situation.errors.take(1000)}")
                }
                if (t.trace.isNotEmpty()) add("助手的步骤：" + t.trace.take(40).mapIndexed { n, s -> "${n + 1}. $s" }.joinToString("；"))
                add("回答：\n${t.answer.take(2000)}")
                add("结果：" + (if (t.ok) "办成了" else "没办成（${t.error ?: "原因不明"}）") + "；用时 ${t.seconds.toInt()} 秒，调用工具 ${t.tools} 次")
            }.joinToString("\n")
        } + listOfNotNull(feedback.takeIf { it.isNotBlank() }?.let { "用户事后的反馈：$it" })
        return Redact.apply(parts.joinToString("\n\n"))
    }

    fun prompt(reason: String, similar: List<Lesson>, conversation: String): String =
        PROMPT.replace("{reason}", reason)
            .replace("{similar}", similar.joinToString("\n") { "[${it.id}] ${it.title} / 适用：${it.`when`} / 做法：${it.advice}" }.ifEmpty { "（无）" })
            .replace("{conversation}", conversation)

    fun parse(text: String): JsonObject? {
        val start = text.indexOf('{')
        val end = text.lastIndexOf('}')
        if (start < 0 || end <= start) return null
        return runCatching { Json.parseToJsonElement(text.substring(start, end + 1)) as? JsonObject }.getOrNull()
    }

    /** 总结一次对话，写进经验库。返回做了什么（写日志用） */
    suspend fun learn(store: Store, turns: List<TurnRecord>, situation: Situation, reason: String, llm: suspend (String) -> String,
                      feedback: String = "", source: String = ""): String {
        val similar = Recall.recall(store, situation.copy(question = turns.joinToString("\n") { it.question }), limit = SIMILAR)
        val data = parse(llm(prompt(reason, similar, describe(turns, situation, feedback)))) ?: return "模型没给出能解析的结果"
        fun s(k: String) = (data[k] as? JsonPrimitive)?.contentOrNull.orEmpty()
        fun list(k: String) = (data[k] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull } ?: emptyList()
        val action = s("action").trim().lowercase()
        if (action == "update" && store.get(s("id")) != null) {
            val l = store.update(s("id"), s("title"), s("when"), s("advice"), source, list("triggers"), list("errors"), list("apps"), list("domains"))
            return if (l != null) "更新经验 ${l.id}：${l.title}" else "更新失败"
        }
        if (action in setOf("add", "update") && s("title").isNotBlank() && s("advice").isNotBlank()) {
            val l = store.add(s("title"), s("when"), s("advice"), source, list("triggers"), list("errors"), list("apps"), list("domains"))
            return "新经验 ${l.id}：${l.title}"
        }
        return "没有值得记的经验（${s("why").take(60)}）"
    }
}
