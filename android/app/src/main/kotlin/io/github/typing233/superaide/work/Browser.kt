package io.github.typing233.superaide.work

import android.annotation.SuppressLint
import android.content.Context
import android.net.Uri
import android.view.View
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import io.github.typing233.superaide.AideApp
import io.github.typing233.superaide.core.web.Web
import io.github.typing233.superaide.core.work.Platform
import io.github.typing233.superaide.diag.Diag
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.io.ByteArrayInputStream
import java.net.InetAddress
import java.util.concurrent.ConcurrentHashMap

/**
 * 隐藏的浏览器：要靠 JS 才渲染得出来的网页、要求验证的搜索页，用它打开再取渲染完的 HTML。
 * 不显示、不加载图片；本机和局域网地址不让读。一分钟没用就销毁。WebView 只能在主线程上用。
 */
object Browser {
    private val lock = Mutex()
    private var view: WebView? = null
    private var idle: Job? = null
    private var loaded: CompletableDeferred<Unit>? = null

    suspend fun render(context: Context, url: String, timeoutMs: Long = 25_000): Platform.Rendered? = lock.withLock {
        val started = System.currentTimeMillis()
        val r = withContext(Dispatchers.Main) {
            idle?.cancel()
            val wv = view ?: create(context.applicationContext).also { view = it }
            try {
                withTimeoutOrNull(timeoutMs) {
                    val done = CompletableDeferred<Unit>()
                    loaded = done
                    wv.loadUrl(url)
                    // 有的页面一直在加载（长连接、广告）：等不到加载完也照样取已经渲染出来的内容
                    withTimeoutOrNull(LOAD_MS) { done.await() }
                    settle(wv)
                    val html = eval(wv, "document.documentElement.outerHTML") ?: return@withTimeoutOrNull null
                    Platform.Rendered(wv.url ?: url, html)
                }
            } catch (e: Exception) {
                Diag.error("browser", e)
                null
            } finally {
                runCatching { wv.stopLoading(); wv.loadUrl("about:blank") }
                scheduleDestroy()
            }
        }
        Diag.log("browser", "ms=${System.currentTimeMillis() - started} ok=${r != null} len=${r?.html?.length} host=${Uri.parse(url).host}")
        r
    }

    /** 等页面的字不再变（单页应用加载完还要再请求一轮数据）：连着两次一样就算好了，最多 5 秒 */
    private suspend fun settle(wv: WebView) {
        var last = -1
        var same = 0
        repeat(10) {
            val n = eval(wv, "document.body ? document.body.innerText.length : 0")?.toIntOrNull() ?: 0
            if (n == last && n > 0) { if (++same >= 2) return } else same = 0
            last = n
            delay(500)
        }
    }

    private const val LOAD_MS = 10_000L

    private suspend fun eval(wv: WebView, js: String): String? {
        val result = CompletableDeferred<String?>()
        wv.evaluateJavascript(js) { result.complete(it) }
        val raw = withTimeoutOrNull(5_000) { result.await() } ?: return null
        // 返回的是 JSON：字符串带引号和转义，数字是原样
        return runCatching { (Json.parseToJsonElement(raw) as? JsonPrimitive)?.contentOrNull }.getOrNull()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun create(context: Context): WebView {
        val wv = WebView(context)
        wv.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            loadsImagesAutomatically = false
            blockNetworkImage = true
            mediaPlaybackRequiresUserGesture = true
            allowFileAccess = false
            allowContentAccess = false
            setSupportMultipleWindows(false)
            javaScriptCanOpenWindowsAutomatically = false
            cacheMode = WebSettings.LOAD_DEFAULT
            // 带 wv 标记的 UA 有的网站当成内嵌页面，给的内容不全
            userAgentString = userAgentString.replace("; wv", "")
        }
        // 没挂到窗口上：给它一个手机屏幕大小，页面才会按手机版排版
        val dm = context.resources.displayMetrics
        wv.measure(View.MeasureSpec.makeMeasureSpec(dm.widthPixels, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(dm.heightPixels, View.MeasureSpec.EXACTLY))
        wv.layout(0, 0, dm.widthPixels, dm.heightPixels)
        wv.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView, url: String) {
                if (url != "about:blank") loaded?.complete(Unit)
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                // 跳到 App 自己的链接（weixin://、baiduboxapp:// 这类）不跟
                return request.url.scheme !in setOf("http", "https")
            }

            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                if (isLocal(request.url)) WebResourceResponse("text/plain", "utf-8", 403, "Forbidden", emptyMap(), ByteArrayInputStream(ByteArray(0)))
                else null
        }
        return wv
    }

    private val local = ConcurrentHashMap<String, Boolean>()

    /** 本机、局域网地址（这里在 WebView 的后台线程上，可以查 DNS） */
    private fun isLocal(uri: Uri): Boolean {
        if (uri.scheme == "about" || uri.scheme == "data" || uri.scheme == "blob") return false
        val host = uri.host ?: return true
        return local.getOrPut(host) {
            runCatching { InetAddress.getAllByName(host).let { all -> all.isNotEmpty() && all.all(Web::isPrivate) } }.getOrDefault(false)
        }
    }

    private fun scheduleDestroy() {
        idle?.cancel()
        idle = AideApp.instance.scope.launch(Dispatchers.Main) {
            delay(60_000)
            view?.destroy()
            view = null
        }
    }
}
