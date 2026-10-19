package io.github.typing233.superaide.core.i18n

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * 和桌面版一样：中文原文就是键，英文从 en.json 里查（scripts/android/gen_strings.py 由桌面版的翻译表生成，再加上安卓特有的）。
 * 查不到就用中文。{name} 形式的占位符按参数替换。
 */
object I18n {
    @Volatile
    var lang: String = "zh"

    private val en: Map<String, String> by lazy {
        val text = I18n::class.java.getResourceAsStream("/i18n/en.json")?.bufferedReader(Charsets.UTF_8)?.readText()
            ?: return@lazy emptyMap()
        (Json.parseToJsonElement(text) as JsonObject).mapValues { it.value.jsonPrimitive.content }
    }

    fun tr(zh: String, vararg args: Pair<String, Any?>): String {
        var s = if (lang == "en") en[zh] ?: zh else zh
        for ((k, v) in args) s = s.replace("{$k}", v.toString())
        return s
    }
}

fun tr(zh: String, vararg args: Pair<String, Any?>) = I18n.tr(zh, *args)
