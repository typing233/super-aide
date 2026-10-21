package io.github.typing233.superaide.core.web

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.Dns
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.InetAddress
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit

/** 直接从手机联网取网页和文件（和模型服务无关，所有模型都能用）。 */
class Web(private val client: OkHttpClient = defaultClient) {
    class Response(val url: String, val status: Int, val type: String, val charset: String?, val bytes: ByteArray) {
        val ok get() = status in 200..299
        val isPdf get() = type.contains("pdf") || bytes.startsWith("%PDF")
        val isImage get() = type.startsWith("image/")
        val isHtml get() = type.contains("html") || type.contains("xhtml") ||
            (type.isBlank() || type.contains("octet-stream")) && String(bytes, 0, minOf(bytes.size, 512)).trimStart().startsWith("<")
        val isText get() = type.startsWith("text/") || type.contains("json") || type.contains("xml") || type.contains("javascript")
        /** 网址最后一段，存成文件时当文件名 */
        val fileName: String get() = url.toHttpUrlOrNull()?.pathSegments?.lastOrNull().orEmpty()

        private fun ByteArray.startsWith(s: String) = size >= s.length && s.indices.all { this[it] == s[it].code.toByte() }
    }

    class TooBig(val limit: Long) : IOException("文件太大（超过 ${limit / 1024 / 1024} MB）")

    suspend fun get(url: String, maxBytes: Long = MAX_BYTES): Response = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(url)
            .header("User-Agent", UA)
            .header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8")
            .header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
            .build()
        val call = client.newCall(request)
        val handle = currentCoroutineContext()[Job]?.invokeOnCompletion { call.cancel() }
        try {
            call.execute().use { r ->
                val body = r.body
                val type = body.contentType()
                val out = ByteArrayOutputStream()
                val buf = ByteArray(16 * 1024)
                body.byteStream().use { input ->
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        out.write(buf, 0, n)
                        if (out.size() > maxBytes) throw TooBig(maxBytes)
                    }
                }
                Response(r.request.url.toString(), r.code, type?.let { "${it.type}/${it.subtype}" }.orEmpty().lowercase(),
                    type?.charset()?.name(), out.toByteArray())
            }
        } catch (e: IOException) {
            currentCoroutineContext().ensureActive()
            throw e
        } finally {
            handle?.dispose()
        }
    }

    companion object {
        const val MAX_BYTES = 25L * 1024 * 1024
        /** 手机浏览器的 UA：不少网站给不认识的客户端返回空页或验证页 */
        const val UA = "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"

        /** 只读公网：本机、局域网地址不读（网页里的文字可能骗模型去读路由器后台这类） */
        val publicOnly = Dns { host ->
            val all = Dns.SYSTEM.lookup(host)
            val ok = all.filterNot(::isPrivate)
            if (ok.isEmpty()) throw UnknownHostException("$host 是本机或局域网地址，不能读")
            ok
        }

        fun isPrivate(a: InetAddress) = a.isLoopbackAddress || a.isSiteLocalAddress || a.isLinkLocalAddress || a.isAnyLocalAddress ||
            a.isMulticastAddress || a.address.let { b -> b.size == 16 && (b[0].toInt() and 0xfe) == 0xfc } // IPv6 ULA fc00::/7

        /** 像浏览器一样记住 Cookie（只在内存里）：每次都是"新访客"的话，搜索引擎更容易要求验证 */
        private val cookies = object : CookieJar {
            private val store = mutableMapOf<String, MutableMap<String, Cookie>>()

            override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) = synchronized(store) {
                for (c in cookies) store.getOrPut(c.domain) { mutableMapOf() }[c.name] = c
            }

            override fun loadForRequest(url: HttpUrl): List<Cookie> = synchronized(store) {
                val now = System.currentTimeMillis()
                store.values.flatMap { it.values }.filter { it.expiresAt > now && it.matches(url) }
            }
        }

        val defaultClient: OkHttpClient = OkHttpClient.Builder()
            .dns(publicOnly)
            .cookieJar(cookies)
            // 直接写 IP 的网址不经过 Dns：连上以后再看一次（跳转也算）
            .addNetworkInterceptor { chain ->
                val addr = chain.connection()?.route()?.socketAddress?.address
                if (addr != null && isPrivate(addr) && chain.connection()?.route()?.proxy?.type() == java.net.Proxy.Type.DIRECT) {
                    throw UnknownHostException("${chain.request().url.host} 是本机或局域网地址，不能读")
                }
                chain.proceed(chain.request())
            }
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .callTimeout(90, TimeUnit.SECONDS)
            .followRedirects(true)
            .build()

        /** 模型给的网址：补上 https://，只认 http / https */
        fun normalize(url: String): String? {
            val u = url.trim().let { if (Regex("^[A-Za-z][A-Za-z0-9+.-]*://").containsMatchIn(it)) it else "https://$it" }
            // 只认 http / https；中文、空格这类 toHttpUrlOrNull 会自己编码
            return u.toHttpUrlOrNull()?.toString()
        }
    }
}
