package io.github.typing233.superaide.work

import android.annotation.SuppressLint
import android.content.Context
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import io.github.typing233.superaide.AideApp
import io.github.typing233.superaide.core.work.JsFiles
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
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/**
 * run_js 的沙箱：隐藏的 WebView 里开一个 Web Worker 跑模型写的代码。
 * 断网（屏蔽网络加载 + CSP），碰不到 DOM 和手机；超时就 terminate 掉 Worker（死循环也停得下来）。
 * 读写文件只能经 files.read / files.write，最后落到这段对话的工作区。
 */
object JsSandbox {
    private val lock = Mutex()
    private var view: WebView? = null
    private var ready: CompletableDeferred<Unit>? = null
    private var idle: Job? = null
    private val seq = AtomicInteger()
    private val runs = ConcurrentHashMap<Int, Run>()

    private class Run(val files: JsFiles) {
        val out = StringBuilder()
        val done = CompletableDeferred<Platform.Js>()
    }

    private const val MAX_OUTPUT = 100_000

    suspend fun run(context: Context, code: String, timeoutMs: Long, files: JsFiles): Platform.Js = lock.withLock {
        val id = seq.incrementAndGet()
        val run = Run(files)
        runs[id] = run
        try {
            withContext(Dispatchers.Main) {
                idle?.cancel()
                val wv = view ?: create(context.applicationContext).also { view = it }
                withTimeoutOrNull(10_000) { ready?.await() } ?: return@withContext run.done.complete(Platform.Js("", "沙箱没启动起来"))
                wv.evaluateJavascript("start($id, ${JsonPrimitive(code)}, $timeoutMs)", null)
            }
            // Worker 自己会在超时后停掉并回报；这里再多等一会儿兜底（页面本身卡住的情况）
            withTimeoutOrNull(timeoutMs + 5_000) { run.done.await() } ?: run.done.let {
                withContext(Dispatchers.Main) { destroy() }
                Platform.Js(run.out.toString(), "超时（${timeoutMs / 1000} 秒）还没跑完，已停止")
            }
        } finally {
            runs.remove(id)
            withContext(Dispatchers.Main) { scheduleDestroy() }
        }
    }

    @SuppressLint("SetJavaScriptEnabled", "JavascriptInterface")
    private fun create(context: Context): WebView {
        val wv = WebView(context)
        wv.settings.apply {
            javaScriptEnabled = true
            blockNetworkLoads = true
            allowFileAccess = false
            allowContentAccess = false
            domStorageEnabled = false
        }
        val r = CompletableDeferred<Unit>()
        ready = r
        wv.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView, url: String) { r.complete(Unit) }
        }
        wv.addJavascriptInterface(Bridge(), "Aide")
        wv.loadDataWithBaseURL("https://sandbox.invalid/", PAGE, "text/html", "utf-8", null)
        return wv
    }

    /** 页面调回来的方法（在 WebView 的后台线程上） */
    private class Bridge {
        @JavascriptInterface
        fun log(id: Int, text: String) {
            val r = runs[id] ?: return
            synchronized(r.out) { if (r.out.length < MAX_OUTPUT) r.out.append(text).append('\n') }
        }

        @JavascriptInterface
        fun call(id: Int, callId: Int, op: String, args: String) {
            val r = runs[id] ?: return
            AideApp.instance.scope.launch {
                val a = runCatching { Json.parseToJsonElement(args).jsonArray.map { it.jsonPrimitive.content } }.getOrDefault(emptyList())
                val (value, error) = try {
                    when (op) {
                        "read" -> r.files.read(a.getOrElse(0) { "" }) to null
                        "write" -> r.files.write(a.getOrElse(0) { "" }, a.getOrElse(1) { "" }) to null
                        else -> null to "没有这个操作：$op"
                    }
                } catch (e: Exception) {
                    null to (e.message ?: e.toString())
                }
                withContext(Dispatchers.Main) {
                    view?.evaluateJavascript("reply($id, $callId, ${JsonPrimitive(value)}, ${JsonPrimitive(error)})", null)
                }
            }
        }

        @JavascriptInterface
        fun done(id: Int, json: String) {
            val r = runs[id] ?: return
            val o = runCatching { Json.parseToJsonElement(json).jsonObject }.getOrDefault(JsonObject(emptyMap()))
            val value = o["value"]?.jsonPrimitive?.contentOrNull
            val error = o["error"]?.jsonPrimitive?.contentOrNull
            val out = synchronized(r.out) {
                if (value != null) r.out.append("返回值：").append(value).append('\n')
                r.out.toString()
            }
            r.done.complete(Platform.Js(out, error))
        }
    }

    private fun destroy() {
        view?.destroy()
        view = null
        ready = null
    }

    private fun scheduleDestroy() {
        idle?.cancel()
        idle = AideApp.instance.scope.launch(Dispatchers.Main) {
            delay(60_000)
            destroy()
            Diag.log("jsbox", "destroyed")
        }
    }

    /** Worker 里跑的代码：console.* 回传，files.read / write 走主页面转给 App */
    private const val WORKER = """
const pending = new Map(); let seq = 0;
function call(op, args) {
  return new Promise((res, rej) => { const id = ++seq; pending.set(id, { res, rej }); postMessage({ t: 'call', id, op, args }); });
}
const files = { read: (p) => call('read', [String(p)]), write: (p, text) => call('write', [String(p), String(text)]) };
const fmt = (v) => { if (typeof v === 'string') return v; try { const s = JSON.stringify(v, null, 2); return s === undefined ? String(v) : s; } catch (e) { return String(v); } };
for (const k of ['log', 'info', 'warn', 'error', 'debug']) console[k] = (...a) => postMessage({ t: 'log', text: a.map(fmt).join(' ') });
self.fetch = undefined; self.XMLHttpRequest = undefined; self.WebSocket = undefined; self.importScripts = undefined;
onmessage = async (e) => {
  const m = e.data;
  if (m.t === 'reply') { const p = pending.get(m.id); pending.delete(m.id); if (!p) return; m.error ? p.rej(new Error(m.error)) : p.res(m.value); return; }
  if (m.t !== 'run') return;
  try {
    const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
    const v = await new AsyncFunction('files', m.code)(files);
    postMessage({ t: 'done', value: v === undefined ? null : fmt(v) });
  } catch (err) {
    postMessage({ t: 'done', error: String((err && err.stack) || err) });
  }
};
"""

    private const val PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob:; worker-src blob:">
</head><body><script id="w" type="text/plain">$WORKER</script><script>
const workers = {};
const src = URL.createObjectURL(new Blob([document.getElementById('w').textContent], { type: 'text/javascript' }));
function finish(id, msg) { const w = workers[id]; if (!w) return; delete workers[id]; clearTimeout(w.timer); w.terminate(); Aide.done(id, JSON.stringify(msg)); }
function start(id, code, timeout) {
  let w;
  try { w = new Worker(src); } catch (e) { Aide.done(id, JSON.stringify({ error: 'Worker 启动失败：' + e })); return; }
  workers[id] = w;
  w.timer = setTimeout(() => finish(id, { error: '超时（' + Math.round(timeout / 1000) + ' 秒）还没跑完，已停止' }), timeout);
  w.onmessage = (e) => {
    const m = e.data;
    if (m.t === 'log') Aide.log(id, m.text);
    else if (m.t === 'call') Aide.call(id, m.id, m.op, JSON.stringify(m.args));
    else if (m.t === 'done') finish(id, m);
  };
  w.onerror = (e) => { e.preventDefault(); finish(id, { error: e.message || String(e) }); };
  w.postMessage({ t: 'run', code });
}
function reply(id, callId, value, error) { const w = workers[id]; if (w) w.postMessage({ t: 'reply', id: callId, value, error }); }
</script></body></html>"""
}
