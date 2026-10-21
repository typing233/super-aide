package io.github.typing233.superaide.core.work

import io.github.typing233.superaide.core.files.Workspace
import io.github.typing233.superaide.core.llm.Part
import io.github.typing233.superaide.core.llm.ToolCall
import io.github.typing233.superaide.core.web.Web
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okio.Buffer
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class WorkToolsTest {
    @get:Rule val tmp = TemporaryFolder()
    private val server = MockWebServer()
    private lateinit var ws: Workspace
    private val files = mutableListOf<String>()
    private val rendered = mutableListOf<String>()

    /** 假的手机能力：浏览器渲染出固定内容，PDF 读出固定文字 */
    private val platform = object : Platform {
        override suspend fun render(url: String): Platform.Rendered {
            rendered += url
            return Platform.Rendered(url, "<html><head><title>渲染后</title></head><body><article>${"<p>JS 渲染出来的正文。</p>".repeat(30)}</article></body></html>")
        }
        override suspend fun pdf(file: File) = Platform.Pdf(3, "PDF 第一页的字\nPDF 第二页的字")
        override suspend fun writePdf(markdown: String, file: File) = file.writeText("%PDF-fake $markdown")
    }

    private fun tools() = WorkTools(ws, platform, Web(OkHttpClient()), onFile = { files += it.path })

    private fun call(name: String, vararg args: Pair<String, Any>) =
        ToolCall("t", name, JsonObject(args.associate { (k, v) -> k to (if (v is Number) JsonPrimitive(v) else if (v is Boolean) JsonPrimitive(v) else JsonPrimitive(v.toString())) }), "{}")

    private fun text(parts: List<Part>?) = parts!!.filterIsInstance<Part.Text>().joinToString("\n") { it.text }

    @Before fun start() { server.start(); ws = Workspace(tmp.newFolder("c1")) }
    @After fun stop() = server.close()

    @Test fun fetchHtmlPagesThroughLongText() = runBlocking {
        val body = "<html><head><title>长文章</title></head><body><article>" + (1..400).joinToString("") { "<p>第${it}段内容。</p>" } + "</article></body></html>"
        server.enqueue(MockResponse.Builder().addHeader("Content-Type", "text/html; charset=utf-8").body(body).build())
        val t = tools()
        val url = server.url("/a").toString()
        val first = text(t.run(call("web_fetch", "url" to url, "max_chars" to 1000))?.parts)
        assertTrue(first.startsWith("网页：长文章"), first)
        assertTrue("第1段内容。" in first && "接着读：start=1000" in first)
        // 接着读不再请求网络
        val second = text(t.run(call("web_fetch", "url" to url, "start" to 1000, "max_chars" to 1000))?.parts)
        assertTrue("第 1001–2000 字" in second, second)
        assertEquals(1, server.requestCount)
        assertTrue(rendered.isEmpty())
    }

    @Test fun jsShellFallsBackToBrowser() = runBlocking {
        server.enqueue(MockResponse.Builder().addHeader("Content-Type", "text/html").body("<html><body><div id=root></div><script src=x.js></script></body></html>").build())
        val out = text(tools().run(call("web_fetch", "url" to server.url("/spa").toString()))?.parts)
        assertTrue("渲染后" in out && "JS 渲染出来的正文" in out && "内置浏览器" in out, out)
    }

    @Test fun pdfIsSavedAndRead() = runBlocking {
        server.enqueue(MockResponse.Builder().addHeader("Content-Type", "application/pdf").body(Buffer().writeUtf8("%PDF-1.7 fake")).build())
        val out = text(tools().run(call("web_fetch", "url" to server.url("/docs/报告.pdf").toString()))?.parts)
        assertTrue("web/报告.pdf" in out && "PDF，3 页" in out && "PDF 第二页的字" in out, out)
        assertEquals(listOf("web/报告.pdf"), files)
        assertTrue(ws.resolve("web/报告.pdf").isFile)
    }

    @Test fun writeAndReadOfficeFiles() = runBlocking {
        val t = tools()
        val w = text(t.run(call("write_file", "path" to "清单.xlsx", "content" to "名字,数量\n苹果,3"))?.parts)
        assertTrue("已生成 清单.xlsx" in w, w)
        val r = text(t.run(call("read_file", "path" to "清单.xlsx"))?.parts)
        assertTrue("Excel" in r && "| 苹果 | 3 |" in r, r)
        text(t.run(call("write_file", "path" to "报告.pdf", "content" to "# 标题"))?.parts)
        assertEquals(listOf("清单.xlsx", "报告.pdf"), files)
        val list = text(t.run(call("files"))?.parts)
        assertTrue("清单.xlsx" in list && "报告.pdf" in list && "生成的" in list, list)
    }

    @Test fun inboxIsReadOnlyAndPathsStayInside() = runBlocking {
        ws.unique(Workspace.INBOX, "原件.txt").writeText("用户的原件")
        val t = tools()
        assertTrue("不能改" in text(t.run(call("write_file", "path" to "inbox/原件.txt", "content" to "x"))?.parts))
        assertEquals("用户的原件", ws.resolve("inbox/原件.txt").readText())
        assertTrue("不在工作区里" in text(t.run(call("read_file", "path" to "../../etc/passwd"))?.parts))
        assertTrue("用户的原件" in text(t.run(call("read_file", "path" to "inbox/原件.txt"))?.parts))
        assertTrue("老版 Office" in text(t.run(call("read_file", "path" to "x.doc").also { ws.resolve("x.doc").writeText("?") })?.parts))
    }

    @Test fun localAddressesAreRefusedByDefault() = runBlocking {
        server.enqueue(MockResponse.Builder().body("secret").build())
        val out = text(WorkTools(ws, platform).run(call("web_fetch", "url" to server.url("/router").toString()))?.parts)
        assertTrue("局域网" in out, out)
        assertEquals(0, server.requestCount)
        assertFalse("secret" in out)
    }

    @Test fun unknownToolIsNotOurs() = runBlocking {
        assertEquals(null, tools().run(call("observe_screen")))
    }
}
