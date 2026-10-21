package io.github.typing233.superaide.core.web

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.jsoup.Jsoup
import org.jsoup.nodes.Element
import java.net.URI
import java.net.URLDecoder
import java.net.URLEncoder
import java.util.Base64

/**
 * 搜索：不用 key，直接查百度和必应（大陆都能直接访问），两边的结果交错合并、去重。
 * 这里只管拼地址和解析结果页；网络请求、被要求验证时换浏览器打开，在 [WebAccess] 里。
 */
object Search {
    data class Hit(val title: String, val url: String, val snippet: String, val engine: String)

    /** backup 的只在前面几家都没搜到时才用 */
    enum class Engine(val label: String, val backup: Boolean = false) {
        BAIDU("百度"), BING("必应"), SO("360 搜索", backup = true);

        fun url(query: String): String {
            val q = URLEncoder.encode(query, "UTF-8")
            return when (this) {
                BAIDU -> "https://www.baidu.com/s?wd=$q"
                BING -> "https://www.bing.com/search?q=$q&setmkt=zh-CN"
                SO -> "https://m.so.com/s?q=$q"
            }
        }

        fun parse(html: String, base: String): List<Hit> = when (this) {
            BAIDU -> baidu(html, base)
            BING -> bing(html, base)
            SO -> so(html, base)
        }
    }

    /** 结果页是不是要人机验证 */
    fun blocked(html: String): Boolean = BLOCKED.any { html.contains(it) }

    private val BLOCKED = listOf("百度安全验证", "wappass.baidu.com/static/captcha", "安全验证 - 百度", "b_captcha", "/challenge/verify", "turing.captcha")

    fun baidu(html: String, base: String): List<Hit> {
        val doc = Jsoup.parse(html, base)
        return doc.select("div.c-result, div.result, div.c-container").mapNotNull { r ->
            if (r.parents().any { it.hasClass("c-result") || it.hasClass("c-container") }) return@mapNotNull null
            r.select("style, script").remove()
            val url = muOf(r) ?: r.select("a[href]").map { it.absUrl("href") }.firstOrNull { it.startsWith("http") } ?: return@mapNotNull null
            if (BAIDU_SKIP.any { url.contains(it) }) return@mapNotNull null
            val title = (r.selectFirst("h3, .c-title, [class*=title]")?.text() ?: r.selectFirst("a")?.text()).orEmpty().trim()
            val all = r.text().trim()
            if (title.isBlank() && all.length < 10) return@mapNotNull null
            val snippet = all.removePrefix(title).trim()
            Hit(title.ifBlank { all.take(40) }, url, snippet.take(SNIPPET), Engine.BAIDU.label)
        }
    }

    /** 百度的广告（baidu.php 跳转）和自家的推荐卡片（相关搜索、游戏中心这类）不算搜索结果 */
    private val BAIDU_SKIP = listOf("baidu.com/baidu.php", "recommend_list.baidu.com", "gamecenter.baidu.com", "baidu.com/s?", "baidu.com/from=")

    private fun muOf(r: Element): String? {
        val log = r.attr("data-log").ifBlank { return null }
        val mu = runCatching { Json.parseToJsonElement(log).jsonObject["mu"]?.jsonPrimitive?.contentOrNull }.getOrNull()
            ?: Regex("[\"']mu[\"']\\s*:\\s*[\"']([^\"']+)").find(log)?.groupValues?.get(1)
        return mu?.takeIf { it.startsWith("http") }
    }

    fun bing(html: String, base: String): List<Hit> {
        val doc = Jsoup.parse(html, base)
        return doc.select("li.b_algo").mapNotNull { r ->
            // 两种版式：<h2><a>标题</a></h2>，或者 <div class="b_algoheader"><a><h2>标题</h2></a></div>
            val a = r.selectFirst("h2 a[href]") ?: r.selectFirst(".b_algoheader a[href]") ?: r.selectFirst("a.tilk[href]") ?: return@mapNotNull null
            val url = unwrapBing(a.absUrl("href"))
            if (!url.startsWith("http")) return@mapNotNull null
            val title = (r.selectFirst("h2")?.text() ?: a.text()).trim()
            val snippet = (r.selectFirst(".b_caption p, p.b_lineclamp2, p.b_lineclamp3, p.b_lineclamp4, p") ?: r.selectFirst(".b_caption"))
                ?.text().orEmpty().trim()
            Hit(title, url, snippet.take(SNIPPET), Engine.BING.label)
        }
    }

    fun so(html: String, base: String): List<Hit> {
        val doc = Jsoup.parse(html, base)
        return doc.select("div.res-list").mapNotNull { r ->
            if (r.parents().any { it.hasClass("res-list") }) return@mapNotNull null
            val h = r.selectFirst("h3.res-title, h3") ?: return@mapNotNull null
            val link = h.closest("a[href]") ?: r.selectFirst("a[href]") ?: return@mapNotNull null
            val url = r.attr("data-pcurl").takeIf { it.startsWith("http") } ?: unwrapSo(link.absUrl("href"))
            if (!url.startsWith("http") || url.contains("so.com/")) return@mapNotNull null
            val title = h.text().trim()
            val snippet = (r.selectFirst(".summary")?.text() ?: r.text().removePrefix(title)).trim()
            Hit(title, url, snippet.take(SNIPPET), Engine.SO.label)
        }
    }

    /** 360 的跳转链接 m.so.com/jump?u=<真实地址> */
    private fun unwrapSo(url: String): String {
        if (!url.contains("so.com/jump")) return url
        val u = url.substringAfter('?').split('&').firstOrNull { it.startsWith("u=") }?.removePrefix("u=") ?: return url
        return URLDecoder.decode(u, "UTF-8")
    }

    /** 必应有时给的是跳转链接（/ck/a?...&u=a1<base64>）：解出真实地址 */
    fun unwrapBing(url: String): String {
        val uri = runCatching { URI(url) }.getOrNull() ?: return url
        if (uri.host?.endsWith("bing.com") != true || uri.path != "/ck/a") return url
        val u = uri.rawQuery.orEmpty().split('&').firstOrNull { it.startsWith("u=") }?.removePrefix("u=") ?: return url
        val v = URLDecoder.decode(u, "UTF-8").removePrefix("a1")
        return runCatching { String(Base64.getUrlDecoder().decode(v.padEnd((v.length + 3) / 4 * 4, '='))) }.getOrDefault(url)
    }

    /** 几个搜索引擎的结果交错合并（各自的第 1 条、第 2 条…），同一个地址只留一次 */
    fun merge(lists: List<List<Hit>>, max: Int): List<Hit> {
        val seen = mutableSetOf<String>()
        val out = mutableListOf<Hit>()
        val longest = lists.maxOfOrNull { it.size } ?: 0
        for (i in 0 until longest) for (l in lists) {
            val h = l.getOrNull(i) ?: continue
            if (seen.add(key(h.url))) out += h
            if (out.size >= max) return out
        }
        return out
    }

    private fun key(url: String) = url.substringAfter("://").removePrefix("www.").removePrefix("m.").trimEnd('/').lowercase()

    fun render(query: String, hits: List<Hit>, engines: List<String>): String {
        if (hits.isEmpty()) return "搜索「$query」没有找到结果（${engines.joinToString("、")}）。换个说法再搜，或者直接用 web_fetch 打开你知道的网址。"
        return buildString {
            append("搜索「").append(query).append("」的结果（").append(engines.joinToString("、")).append("）：\n")
            hits.forEachIndexed { i, h ->
                append("\n").append(i + 1).append(". ").append(h.title).append("\n   ").append(h.url)
                if (h.snippet.isNotBlank()) append("\n   ").append(h.snippet)
            }
            append("\n\n（摘要可能过时或不全：关键的事实、数字、日期用 web_fetch 打开原文核对；回答里附上来源链接。）")
        }
    }

    private const val SNIPPET = 260
}
