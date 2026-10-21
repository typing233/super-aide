package io.github.typing233.superaide.core.web

import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.net.InetAddress
import java.util.Base64
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ReadableTest {
    // 放在 trimIndent 外面拼进去：不然 trimIndent 会把 pre 里的缩进当公共缩进去掉
    private val PRE = "<pre>line1\n  line2</pre>"

    @Test fun keepsStructureDropsChrome() {
        val html = """
            <html><head><title>测试页</title><style>.x{}</style><script>var a=1</script></head><body>
            <nav><a href="/home">首页</a><a href="/about">关于我们</a></nav>
            <article>
              <h1>大标题</h1>
              <p>第一段   有  多余空格。</p>
              <h2>小节</h2>
              <ul><li>苹果</li><li>香蕉 <a href="https://example.com/b">详情</a></li></ul>
              <table><tr><th>名字</th><th>价格</th></tr><tr><td>苹果</td><td>5</td></tr></table>
              <!--pre-->
              ${"<p>正文填充内容。</p>".repeat(40)}
            </article>
            <footer>版权所有</footer>
            </body></html>
        """.trimIndent().replace("<!--pre-->", PRE)
        val p = Readable.extract(html, "https://example.com/a")
        assertEquals("测试页", p.title)
        assertTrue("# 大标题" in p.text, p.text)
        assertTrue("## 小节" in p.text)
        assertTrue("第一段 有 多余空格。" in p.text)
        assertTrue("- 苹果" in p.text && "- 香蕉 详情" in p.text)
        assertTrue("| 名字 | 价格 |" in p.text && "| 苹果 | 5 |" in p.text)
        assertTrue("line1\n  line2" in p.text, "pre 里的缩进要保留：" + p.text.take(300))
        assertFalse("首页" in p.text || "版权所有" in p.text || "var a" in p.text)
        assertEquals(listOf("详情" to "https://example.com/b"), p.links)
    }

    @Test fun jsShellLooksEmpty() {
        val html = "<html><body><div id=app></div><script src=app.js></script></body></html>"
        assertTrue(Readable.looksEmpty(Readable.extract(html, "https://x.com").text))
    }

    @Test fun detectsCharsetFromMeta() {
        val html = "<html><head><meta charset=\"gbk\"><title>中文</title></head><body><p>你好，世界</p></body></html>"
        val doc = Readable.parse(html.toByteArray(charset("GBK")), null, "https://x.com")
        assertEquals("中文", doc.title())
        assertTrue("你好，世界" in Readable.extract(doc).text)
    }
}

class SearchTest {
    @Test fun parsesBaiduMobile() {
        val html = """
            <div class="c-result result" data-log='{"order":1,"mu":"https://ys.mihoyo.com/main/news"}'>
              <h3 class="c-title">原神官网 新闻</h3><div>7.1 版本「往冥府的安魂歌」上线</div>
              <div class="c-container"><a href="https://nested.example">嵌套的不算</a></div>
            </div>
            <div class="c-result result" data-log="{&quot;order&quot;:2,&quot;mu&quot;:&quot;https://m.ali213.net/tag/ysbbdq.html&quot;}">
              <div><span class="title-x">原神版本大全</span>历代版本列表</div>
            </div>
            <div class="c-result result" data-log='{"mu":"http://34689.recommend_list.baidu.com"}'><div>大家还在搜</div></div>
        """.trimIndent()
        val hits = Search.baidu(html, "https://www.baidu.com/s?wd=x")
        assertEquals(listOf("https://ys.mihoyo.com/main/news", "https://m.ali213.net/tag/ysbbdq.html"), hits.map { it.url })
        assertEquals("原神官网 新闻", hits[0].title)
        assertTrue("7.1 版本" in hits[0].snippet)
        assertEquals("原神版本大全", hits[1].title)
    }

    @Test fun parsesBingAndUnwrapsRedirects() {
        val real = "https://ys.mihoyo.com/main"
        val wrapped = "https://www.bing.com/ck/a?!&&p=abc&u=a1" + Base64.getUrlEncoder().withoutPadding().encodeToString(real.toByteArray()) + "&ntb=1"
        val html = """
            <ol id="b_results">
              <li class="b_algo"><h2><a href="$wrapped">《原神》官方网站</a></h2><div class="b_caption"><p>全新7.1版本上线</p></div></li>
              <li class="b_algo"><h2><a href="https://example.com/2">第二条</a></h2><p class="b_lineclamp3">摘要二</p></li>
            </ol>
        """.trimIndent()
        val hits = Search.bing(html, "https://cn.bing.com/search?q=x")
        assertEquals(listOf(real, "https://example.com/2"), hits.map { it.url })
        assertEquals("全新7.1版本上线", hits[0].snippet)
        assertEquals("摘要二", hits[1].snippet)
    }

    @Test fun mergeInterleavesAndDedupes() {
        val a = listOf(Search.Hit("a1", "https://www.x.com/1", "", "百度"), Search.Hit("a2", "https://y.com/", "", "百度"))
        val b = listOf(Search.Hit("b1", "https://m.x.com/1/", "", "必应"), Search.Hit("b2", "https://z.com", "", "必应"))
        assertEquals(listOf("a1", "a2", "b2"), Search.merge(listOf(a, b), 10).map { it.title })
        assertEquals(listOf("a1", "a2"), Search.merge(listOf(a, b), 2).map { it.title })
    }

    @Test fun blockedPages() {
        assertTrue(Search.blocked("<title>百度安全验证</title>"))
        assertFalse(Search.blocked("<title>原神 - 百度</title>"))
    }

    /** 真的去搜一次（要联网）：AIDE_LIVE_WEB=1 时才跑。被要求验证的引擎只打印出来，至少要有一家有结果 */
    @Test fun liveSearch() = runBlocking {
        assumeTrue(System.getenv("AIDE_LIVE_WEB") == "1")
        val web = Web()
        var any = false
        for (e in Search.Engine.entries) {
            val r = web.get(e.url("原神最新版本"))
            val page = String(r.bytes, Charsets.UTF_8)
            val hits = e.parse(page, r.url)
            println("${e.label}: ${hits.size} 条，blocked=${Search.blocked(page)} ${r.status} ${r.url.take(80)}")
            hits.take(3).forEach { println("  ${it.title} | ${it.url.take(100)} | ${it.snippet.take(60)}") }
            any = any || hits.isNotEmpty()
        }
        assertTrue(any, "一家都没搜到")
    }
}

class WebUrlTest {
    @Test fun normalize() {
        assertEquals("https://example.com/", Web.normalize("example.com"))
        assertEquals("http://a.com/x?q=%E4%B8%AD%E6%96%87", Web.normalize("http://a.com/x?q=中文"))
        assertNull(Web.normalize("file:///etc/passwd"))
        assertNull(Web.normalize("javascript:alert(1)"))
    }

    @Test fun privateAddresses() {
        assertTrue(Web.isPrivate(InetAddress.getByName("127.0.0.1")))
        assertTrue(Web.isPrivate(InetAddress.getByName("192.168.1.1")))
        assertTrue(Web.isPrivate(InetAddress.getByName("10.0.0.8")))
        assertTrue(Web.isPrivate(InetAddress.getByName("fd00::1")))
        assertFalse(Web.isPrivate(InetAddress.getByName("110.242.68.66")))
    }
}
