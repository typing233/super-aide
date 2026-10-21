package io.github.typing233.superaide.run

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.Build
import io.github.typing233.superaide.AideApp
import io.github.typing233.superaide.BuildConfig
import io.github.typing233.superaide.a11y.AideAccessibilityService
import io.github.typing233.superaide.a11y.FullRead
import io.github.typing233.superaide.a11y.Ocr
import io.github.typing233.superaide.a11y.PhoneTools
import io.github.typing233.superaide.a11y.ScreenReader
import io.github.typing233.superaide.a11y.SelfHeal
import io.github.typing233.superaide.a11y.Shots
import io.github.typing233.superaide.assist.AideSession
import io.github.typing233.superaide.assist.AideVoiceInteractionService
import io.github.typing233.superaide.core.agent.Mode
import io.github.typing233.superaide.core.agent.ToolHost
import io.github.typing233.superaide.core.files.Workspace
import io.github.typing233.superaide.core.llm.ToolCall
import io.github.typing233.superaide.core.llm.ToolOutput
import io.github.typing233.superaide.core.work.WorkTools
import io.github.typing233.superaide.core.events.Event
import io.github.typing233.superaide.core.i18n.I18n
import io.github.typing233.superaide.core.i18n.tr
import io.github.typing233.superaide.core.llm.Part
import io.github.typing233.superaide.core.prompts.Prompts
import io.github.typing233.superaide.core.screen.EnvText
import io.github.typing233.superaide.core.screen.Observation
import io.github.typing233.superaide.core.screen.Opaque
import io.github.typing233.superaide.core.screen.partialLists
import io.github.typing233.superaide.core.screen.Screen
import io.github.typing233.superaide.core.session.CardState
import io.github.typing233.superaide.core.experience.Learn
import io.github.typing233.superaide.core.experience.Recall
import io.github.typing233.superaide.core.experience.Situation
import io.github.typing233.superaide.core.experience.Store
import io.github.typing233.superaide.core.router.Decision
import io.github.typing233.superaide.core.router.Task
import io.github.typing233.superaide.core.session.Session
import io.github.typing233.superaide.data.History
import io.github.typing233.superaide.diag.Diag
import io.github.typing233.superaide.host.AssistActivity
import io.github.typing233.superaide.host.ChatActivity
import io.github.typing233.superaide.system.Apps
import io.github.typing233.superaide.system.Device
import io.github.typing233.superaide.work.AndroidPlatform
import io.github.typing233.superaide.work.FileActions
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File

/**
 * 运行中的超级助手：召唤、抓屏、对话、停止、「让我来做」。界面（宿主和浮层）只订阅这里的状态。
 * 对应桌面版 shell/controller.py + engines/hub.py 的一部分。
 */
object Aide {
    /** 界面现在该显示什么 */
    enum class Surface { HIDDEN, INPUT, CARD, PILL }

    class Capture(val screen: Screen?, val shot: ByteArray?, val clipboard: String = "", val source: String = "a11y")

    private val app get() = AideApp.instance
    val apps by lazy { Apps(app) }
    val history by lazy { History(app) }

    private val _surface = MutableStateFlow(Surface.HIDDEN)
    val surface: StateFlow<Surface> = _surface
    private val _card = MutableStateFlow<CardState?>(null)
    /** 当前这段对话（null = 还没问） */
    val card: StateFlow<CardState?> = _card
    private val _mode = MutableStateFlow(Mode.ASK)
    /** 输入框当前的模式（左边的切换钮） */
    val mode: StateFlow<Mode> = _mode
    /** 设置页在前台：悬浮球先藏起来（免得挡住右边的开关） */
    val settingsOpen = MutableStateFlow(false)
    /** 对话页在前台（悬浮球也藏起来；答完不用再发通知） */
    val chatOpen = MutableStateFlow(false)
    private val _attachments = MutableStateFlow<List<File>>(emptyList())
    /** 还没发出去的附件（先拷在 cache/attach/ 里，发问时挪进这段对话的工作区） */
    val attachments: StateFlow<List<File>> = _attachments
    /** 分享进来的文字：对话页的输入框拿去当草稿 */
    val draft = MutableStateFlow<String?>(null)

    private var capture: Deferred<Capture>? = null
    private var session: Session? = null
    private var conversationId = ""
    private var conversationTime = 0L
    private var frontApp = ""
    private var job: Job? = null
    private var tools: PhoneTools? = null
    /** 这段对话的工作区和联网、文件、跑代码的工具 */
    private var work: WorkTools? = null
    private var lastActive = 0L
    /** 用户按了停止：工具每一步前都看它 */
    @Volatile
    private var stopRequested = false
    /** 路由和学习 */
    val routing by lazy { Routing(app) }
    /** 经验库：碰到相似情况才想起 */
    val experience by lazy { Store(java.io.File(app.filesDir, "experience/lessons.json")) }
    /** 这段对话里已经想起过的经验（不重复给）、这一轮给了哪几条、这一轮的情况 */
    private val seenLessons = mutableSetOf<String>()
    private var turnLessons = listOf<String>()
    private var situation = Situation()
    /** 这段对话里用户说过上一轮没答好（总结经验用） */
    private var negative = false
    private var learnJob: Job? = null
    /** 当前这一问（路由看的） */
    private var task: Task? = null
    /** 上一轮没办成或被说不对：下一轮追问换更强的配置 */
    private var escalateNext = false
    /** 上一段对话的第一问、时间和用的配置（很快又问一遍同样的问题 = 上次没答好） */
    private var lastQuestion = ""
    private var lastQuestionAt = 0L
    private var lastDecision: Decision? = null

    fun setMode(m: Mode) { _mode.value = m }
    fun hasRecent() = _card.value != null && System.currentTimeMillis() - lastActive < RECENT_MS

    /**
     * 召唤：先读屏幕上的文字，再把界面显示出来（界面一盖上去，下面 App 的文字系统就不给了）。
     * 读文字通常 20–200 毫秒，最多等 [PRE_CAPTURE_MS]。截图在界面出来以后补：API 34+ 只截那个 App 的窗口，
     * 我们的界面不会出现在上面；更老的系统在界面出来之前先截整屏。
     */
    fun summon(
        context: Context,
        mode: Mode,
        via: String,
        showHost: Boolean = true,
        assist: Deferred<Capture>? = null,
    ) {
        Diag.log("summon", "via=$via mode=$mode")
        I18n.lang = uiLang()
        runCatching { SelfHeal.ensure(app) }
        _mode.value = mode
        if (_card.value?.running == true) {
            _surface.value = if (_card.value?.mode == Mode.ACT) Surface.PILL else Surface.CARD
            if (_surface.value != Surface.PILL && showHost) openHost(context, mode, via)
            return
        }
        assistData = assist
        val pre = app.scope.async(Dispatchers.Default) { preCapture() }
        preRead = pre
        capture = app.scope.async { merge(finishCapture(pre.await())) }
        _surface.value = Surface.INPUT
        if (!showHost) return
        app.scope.launch(Dispatchers.Main) {
            withTimeoutOrNull(PRE_CAPTURE_MS) { pre.await() }
            openHost(context, mode, via)
        }
    }

    private var preRead: Deferred<Pre>? = null

    /** 等召唤时读屏幕文字那一步做完（最多 [PRE_CAPTURE_MS]）。宿主先出来的情况（系统直接打开的）用它 */
    suspend fun awaitPreCapture() {
        withTimeoutOrNull(PRE_CAPTURE_MS) { preRead?.await() }
    }

    /** 我们自己调 showSession 打开的默认助手会话：它拿到的屏幕结构和截图也并进来 */
    fun attachAssist(assist: Deferred<Capture>) {
        assistData = assist
    }

    private var assistData: Deferred<Capture>? = null

    /** 无障碍读的文字更全（所有窗口、通知）；系统给的截图更干净（没有我们的界面） */
    private suspend fun merge(a: Capture): Capture {
        val s = assistData?.let { withTimeoutOrNull(1500) { it.await() } } ?: return a
        return Capture(a.screen ?: s.screen, s.shot ?: a.shot, a.clipboard, if (a.screen != null) "a11y" else "assist")
    }

    private fun openHost(context: Context, mode: Mode = _mode.value, via: String = "") {
        if (AideVoiceInteractionService.active != null) {
            val args = android.os.Bundle().apply {
                putString(AideSession.ARG_MODE, mode.name)
                putString(AideSession.ARG_VIA, via)
                putBoolean(AideSession.ARG_SUMMONED, true)
            }
            if (AideVoiceInteractionService.show(args)) return
        }
        context.startActivity(Intent(context, AssistActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    private class Pre(val read: ScreenReader.Result?, val shot: Bitmap?)

    /** 界面出来之前：读文字（老系统顺便截整屏） */
    private suspend fun preCapture(): Pre {
        val svc = AideAccessibilityService.instance ?: return Pre(null, null)
        val read = runCatching { svc.readScreen() }.getOrNull()
        val shot = if (Build.VERSION.SDK_INT < 34) runCatching { svc.screenshot() }.getOrNull() else null
        return Pre(read, shot)
    }

    /**
     * 界面出来以后：只截那个 App 的窗口（截不到再截整屏）。前台 App 不让无障碍读界面（微信）时，从这张截图里认字补上；
     * 界面出来以后才截的整屏上有我们自己的界面，不拿来认字。
     */
    private suspend fun finishCapture(pre: Pre): Capture = withContext(Dispatchers.Default) {
        val svc = AideAccessibilityService.instance ?: return@withContext Capture(null, null, source = "none")
        var read = pre.read
        val shot = runCatching {
            val front = read?.screen?.windows?.firstOrNull { it.type == "app" }
            val window = if (pre.shot == null && Build.VERSION.SDK_INT >= 34 && front != null) svc.screenshotOfWindow(front.id) else null
            val bmp = pre.shot ?: window ?: svc.screenshot()
            if (read != null && front != null && (pre.shot != null || window != null)) {
                read = Ocr.fill(read!!, bmp, fullScreen = pre.shot != null, dx = if (window != null) front.box.l else 0, dy = if (window != null) front.box.t else 0)
            }
            bmp?.let { Shots.jpeg(Shots.scaled(it, Observation.scaleFor(it.width, it.height))) }
        }.getOrNull()
        val screen = read?.screen
        Diag.log("capture", "ms=${pre.read?.ms} nodes=${screen?.windows?.sumOf { it.nodes.size }} shot=${shot?.size}" +
            (screen?.windows?.firstOrNull { it.opaque }?.let { " opaque=${it.pkg} ocr=${it.nodes.size}" } ?: ""))
        Capture(screen, shot)
    }

    /** 输入框里按了发送。fromChat = 在对话页里问的（不读屏幕：屏幕上是我们自己） */
    fun submit(text: String, fromChat: Boolean = false) {
        val question = text.trim().ifEmpty { if (fromChat && _attachments.value.isNotEmpty()) tr("看看这些文件") else return }
        val current = _card.value
        val followup = current != null && session != null && current.mode == _mode.value && !current.running &&
            (fromChat || hasRecent() && _surface.value == Surface.CARD)
        if (followup && Routing.NEGATIVE.containsMatchIn(question)) {
            routing.record(lastDecision, 0.0, "negative_followup")
            experience.failed(turnLessons)
            negative = true
            escalateNext = true
        }
        if (!followup && System.currentTimeMillis() - lastQuestionAt < REASK_MS && Routing.similar(question, lastQuestion) >= 0.8) {
            routing.record(lastDecision, 0.0, "reask")
        }
        if (!followup) newConversation(_mode.value)
        run(question, followup, fromChat = fromChat)
    }

    /** 「让我来做」：新开一段操作对话，带上刚才的问答 */
    fun handOff() {
        val c = _card.value ?: return
        _mode.value = Mode.ACT
        val q = Prompts.handOff(c.question, c.answer)
        newConversation(Mode.ACT, keepFiles = true)
        run(q, followup = false, display = tr("照刚才说的帮我做"))
    }

    /** keepFiles：「让我来做」接着用刚才问答的工作区（刚生成的文件还要用） */
    private fun newConversation(mode: Mode, keepFiles: Boolean = false) {
        job?.cancel()
        learnJob?.cancel()
        seenLessons.clear()
        turnLessons = emptyList()
        negative = false
        conversationTime = System.currentTimeMillis()
        conversationId = "c" + conversationTime
        val t = PhoneTools(apps, recall = ::recallTool, isStopped = { stopRequested })
        tools = t
        val w = work?.takeIf { keepFiles } ?: WorkTools(Workspace(File(app.filesDir, "work/$conversationId")), AndroidPlatform(app), onFile = { f ->
            // 网上下载的（web/）是给模型读的，不摆到回答下面
            if (!f.path.startsWith("${Workspace.WEB}/")) onEvent(Event.file(f.path, f.bytes))
        }, log = { event, detail -> Diag.log(event, detail) })
        work = w
        session = Session(
            mode = mode,
            tools = Hosts(w, t),
            pick = { exclude -> task?.let { routing.choices(it, exclude) } ?: emptyList() },
            sideline = routing::sideline,
            emit = ::onEvent,
            uiLang = ::uiLang,
        )
        escalateNext = false
        _card.value = CardState(mode)
    }

    /** 联网、文件、跑代码的归 WorkTools，看屏幕、操作手机的归 PhoneTools */
    private class Hosts(val work: WorkTools, val phone: PhoneTools) : ToolHost {
        override suspend fun run(call: ToolCall, mode: Mode): ToolOutput = work.run(call) ?: phone.run(call, mode)
    }

    /** 对话页的「新对话」：下一句不再当追问 */
    fun newChat() {
        if (_card.value?.running == true) return
        save()
        session = null
        _card.value = null
        if (_surface.value == Surface.CARD) _surface.value = Surface.HIDDEN
    }

    /** 在对话页里看这段对话（卡片上点了展开、通知点开） */
    fun openChat(context: Context) {
        tools?.clearMarks()
        if (_surface.value == Surface.CARD || _surface.value == Surface.INPUT) _surface.value = Surface.HIDDEN
        context.startActivity(Intent(context, ChatActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP))
    }

    /** 界面上显示的文件（相对这段对话的工作区） */
    fun fileFor(path: String): File? = runCatching { work?.workspace?.resolve(path) }.getOrNull()?.takeIf { it.isFile }

    /** 分享进来的、选好的文件：先放着，发问时一起发 */
    fun attach(context: Context, uris: List<android.net.Uri>) {
        if (uris.isEmpty()) return
        app.scope.launch(Dispatchers.IO) {
            val dir = File(app.cacheDir, "attach").apply { mkdirs() }
            val added = FileActions.import(context, uris, dir)
            _attachments.value = (_attachments.value + added).distinctBy { it.path }
        }
    }

    fun detach(f: File) {
        _attachments.value = _attachments.value - f
        f.delete()
    }

    /** 附件挪进工作区的 inbox/，返回相对路径 */
    private fun moveIn(w: WorkTools, files: List<File>): List<String> = files.mapNotNull { f ->
        if (!f.isFile) return@mapNotNull null
        val target = w.workspace.unique(Workspace.INBOX, f.name)
        if (!f.renameTo(target)) { f.copyTo(target, overwrite = true); f.delete() }
        w.workspace.relative(target)
    }

    /** 附件拼进首条消息：每个文件带上开头一段（一共最多 3 万字），图片直接附上 */
    private suspend fun describe(w: WorkTools, paths: List<String>): Pair<String, List<Part.Image>> {
        if (paths.isEmpty()) return "" to emptyList()
        val images = mutableListOf<Part.Image>()
        val sb = StringBuilder()
        var budget = 30_000
        for (p in paths) {
            if (budget < 1000) { sb.append("- ").append(p).append("（没带上内容，用 read_file 读）\n"); continue }
            val parts = runCatching { w.readFile(p, 0, minOf(12_000, budget)) }.getOrElse { listOf(Part.Text("文件：$p（读不了：${it.message}）")) }
            val text = parts.filterIsInstance<Part.Text>().joinToString("\n") { it.text }
            images += parts.filterIsInstance<Part.Image>()
            sb.append("<file path=\"").append(p).append("\">\n").append(text).append("\n</file>\n")
            budget -= text.length
        }
        if (images.isNotEmpty()) sb.append("（图片按顺序附在消息里，在屏幕截图后面。）\n")
        sb.append("（文件都在工作区的 inbox/ 里。只带了开头一部分的，用 read_file 加 start 接着读完再回答。）")
        return sb.toString() to images
    }

    /**
     * 「读完整页」：先把界面收起来（盖着的话读不到下面的 App），把列表翻到底读完再翻回去，
     * 然后带着完整的内容把刚才的问题再答一遍（作为同一段对话的追问）。
     */
    fun readFullPage(context: Context) {
        val c = _card.value ?: return
        val pkg = frontApp
        // 收成进度小条（不挡着下面的 App）：用户看得到在做什么，进程也不会被系统当成后台冻住
        _card.value = c.copy(fullPage = false, running = true, done = false, transient = tr("正在把这一页翻到底读一遍…"))
        _surface.value = Surface.PILL
        Diag.log("fullpage", "pkg=$pkg")
        app.scope.launch {
            delay(700)
            val svc = AideAccessibilityService.instance
            Diag.log("fullpage.read", "svc=${svc != null}")
            val result = svc?.let { FullRead.read(it, pkg, app.settings.value.blockedApps.toSet()) }
            _surface.value = Surface.CARD
            withContext(Dispatchers.Main) { openHost(context, Mode.ASK, "fullpage") }
            if (result == null || result.text.isBlank()) {
                _card.value = c.copy(fullPage = false, error = tr("没能翻完这一页：没找到能滚动的列表。"))
                return@launch
            }
            val env = (if (result.how.isNotEmpty()) "【屏幕上的文字】在「${apps.label(pkg)}」里翻页读到的全部内容${result.how}：\n"
            else "【屏幕上的文字】把「${apps.label(pkg)}」里的列表从当前位置往下翻了 ${result.pages} 屏读到的全部内容（逐字原文；" +
                "列表报告的总项数常把分隔线、分组标题也算进去，比实际条目多是正常的）：\n") + result.text.take(40_000)
            run("用户点了「读完整页」：环境里是翻页读到的全部内容。请根据完整内容重新回答刚才的问题：${c.question}",
                followup = true, display = tr("读完整页后重新回答"), envOverride = env)
        }
    }

    private fun run(question: String, followup: Boolean, display: String = question, envOverride: String? = null, fromChat: Boolean = false) {
        val s = session ?: return
        val w = work ?: return
        // 附件只在对话页里加、也只跟对话页里的提问一起发（召唤卡片上看不到它们）
        val files = if (fromChat) _attachments.value else emptyList()
        if (fromChat) _attachments.value = emptyList()
        val state = (_card.value ?: CardState(s.mode)).next(display, files.map { it.name })
        _card.value = state
        stopRequested = false
        lastActive = System.currentTimeMillis()
        // 对话页里问的：回答就在对话页上，不弹卡片
        _surface.value = if (s.mode == Mode.ACT) Surface.PILL else if (fromChat) Surface.HIDDEN else Surface.CARD
        // 界面还看得见的时候启动前台服务：收起卡片、切到别的 App 以后任务接着跑
        TaskService.start(app)
        TaskNotice.clearDone(app)
        job = app.scope.launch {
            try {
                // 读完整页时环境已经是翻完读到的全文，不再截一次（这时屏幕上大半是我们自己的卡片）；对话页里问的不读屏幕
                val cap = when {
                    envOverride != null || fromChat -> Capture(null, null, source = if (fromChat) "chat" else "fullpage")
                    followup -> withContext(Dispatchers.Default) { recapture() }
                    else -> capture?.await() ?: Capture(null, null)
                }
                frontApp = cap.screen?.windows?.firstOrNull { it.type == "app" }?.pkg ?: frontApp
                val extras = EnvText.Extras(apps::label, Device.line(app), cap.clipboard)
                val env = envOverride ?: cap.screen?.let { EnvText.render(it, extras) }
                    ?: EnvText.bare(System.currentTimeMillis(), extras,
                        if (fromChat) "（用户在超级助手自己的对话页里提问：没有别的 App 的屏幕。）" else "（没有读到屏幕：无障碍服务没开，或者是受保护的页面）")
                val (attached, attachedImages) = describe(w, withContext(Dispatchers.IO) { moveIn(w, files) })
                // 问答第一轮：列表只加载了一部分，答完给一个「读完整页」。不让无障碍读界面的 App 只认得出屏幕上看得到的字，也给
                val frontWindow = cap.screen?.windows?.firstOrNull { it.type == "app" }
                val lists = if (s.mode == Mode.ASK && !followup) frontWindow?.partialLists().orEmpty() else emptyList()
                val opaque = s.mode == Mode.ASK && !followup && frontWindow?.opaque == true && !frontWindow.blocked
                val partial = lists.isNotEmpty() || opaque
                val images = listOfNotNull(cap.shot?.let { Part.Image(it) })
                val notes = buildList {
                    if (cap.screen == null && envOverride == null && !fromChat) add("这次没能读取屏幕内容（无障碍服务没开）。需要看屏幕才能回答的，请让用户在设置里打开超级助手的无障碍权限。")
                }.toMutableList()
                lists.firstOrNull()?.let { (total, loaded) ->
                    notes += "屏幕上的列表只加载了一部分（列表报告共 $total 项，现在读到 $loaded 项；总数常把分隔线、分组标题这类没有文字的项也算进去）。用户要的是完整内容时，请用户点回答下面的「读完整页」，" +
                        "你会把列表翻到底读一遍再答；不要让用户自己去滑、再叫你一次。"
                }
                if (opaque && lists.isEmpty()) {
                    notes += "${apps.label(frontWindow!!.pkg)} 不让无障碍读界面，环境里的字是从截图里认出来的，只有屏幕上看得到的部分。" +
                        "用户要的是完整内容（整篇文章、更早的聊天记录）而屏幕上不全时，请用户点回答下面的「读完整页」，你会翻一遍读完再答；不要让用户自己去滑、再叫你一次。"
                }
                val t = routing.task(s.mode, question, frontApp, frontText(cap), errorLines(cap))
                task = t
                if (followup && escalateNext) {
                    escalateNext = false
                    routing.escalate(routing.decisionOf(s.choice))?.let { d ->
                        routing.choices(t, emptySet(), d).firstOrNull()?.let(s::switchTo)
                    }
                }
                situation = Situation(question, errors = errorLines(cap), app = frontApp,
                    title = cap.screen?.windows?.firstOrNull { it.type == "app" }?.title.orEmpty())
                val lessons = Recall.recall(experience, situation, exclude = seenLessons)
                turnLessons = lessons.map { it.id }
                seenLessons += turnLessons
                if (lessons.isNotEmpty()) Diag.log("recall", lessons.joinToString { it.title })
                val r = s.ask(question, env, images, notes, Recall.render(lessons), attached, attachedImages)
                if (partial) _card.value = _card.value?.copy(fullPage = true)
                learn(s, question, followup, r.tools, env)
            } catch (e: CancellationException) {
                withContext(NonCancellable) { onEvent(Event.done(mapOf("ok" to false, "stopped" to true, "reason" to "interrupted"))) }
            } catch (e: Exception) {
                Diag.error("turn", e)
                onEvent(Event.error(e.message ?: e.toString()))
                onEvent(Event.done(mapOf("ok" to false, "error" to (e.message ?: e.toString()))))
            } finally {
                withContext(NonCancellable) { save() }
            }
        }
    }

    /**
     * 追问时重新读一次屏幕文字（不把截图发出去：屏幕上现在可能是我们自己的卡片）。
     * 不让无障碍读界面的 App：API 34+ 只截它自己的窗口（卡片不在上面），认字补上。
     */
    private suspend fun recapture(): Capture {
        val svc = AideAccessibilityService.instance ?: return Capture(null, null)
        var read = runCatching { svc.readScreen() }.getOrNull() ?: return Capture(null, null)
        val front = read.screen.windows.firstOrNull { it.type == "app" }
        if (front != null && (front.opaque || front.pkg in Opaque.SCRAMBLERS) && Build.VERSION.SDK_INT >= 34) {
            val bmp = runCatching { svc.screenshotOfWindow(front.id) }.getOrNull()
            read = Ocr.fill(read, bmp, fullScreen = false, dx = front.box.l, dy = front.box.t)
        }
        return Capture(read.screen, null)
    }

    private fun onEvent(e: Event) {
        // 调试版把每一步记进日志（正式版不记：进度文字里可能有屏幕上的字）
        if (BuildConfig.DEBUG && e.type == "status" && e.data["transient"] != true) Diag.log("step", e.text)
        _card.value = (_card.value ?: CardState()).reduce(e)
        lastActive = System.currentTimeMillis()
        if (e.type == "done") {
            Diag.log("turn.done", e.data.toString())
            // 问答答完时用户没在看（卡片收起了、去了别的 App）：发一条通知，点开就是对话页
            val c = _card.value
            if (c != null && c.mode == Mode.ASK && !c.stopped && _surface.value != Surface.CARD && !chatOpen.value) runCatching { TaskNotice.done(app, c) }
            // 操作完成：进度条变成结果提示，过一会儿收起
            if (_card.value?.mode == Mode.ACT && _surface.value == Surface.PILL) app.scope.launch {
                delay(RESULT_MS)
                if (_surface.value == Surface.PILL && _card.value?.running == false) _surface.value = Surface.HIDDEN
            }
        }
    }

    /** 停止：当前这一步做完就停，1.5 秒还没停下就直接打断 */
    fun stop() {
        stopRequested = true
        session?.stop()
        val j = job ?: return
        app.scope.launch {
            delay(1500)
            if (j.isActive) j.cancel()
        }
    }

    fun feedback(v: Int) {
        _card.value = _card.value?.copy(rating = v)
        if (v != 0) routing.record(lastDecision, if (v > 0) 1.0 else 0.0, "feedback")
        if (v < 0) { escalateNext = true; negative = true; experience.failed(turnLessons); scheduleLearning() }
        save()
    }

    /** 这一轮的结果记给路由；第一轮校准耗时；问答答得好、没看实时屏幕的，空闲时拿去后台对比 */
    private fun learn(s: Session, question: String, followup: Boolean, tools: Int, env: String) {
        val rec = s.records.lastOrNull() ?: return
        val d = routing.decisionOf(s.choice) ?: return
        lastDecision = d
        if (!followup) { lastQuestion = question; lastQuestionAt = System.currentTimeMillis() }
        val infra = rec.error != null && rec.error != _card.value?.reported // 模型服务出错（网络、限流…），和能力无关
        when {
            rec.stopped || infra -> Unit
            rec.ok -> routing.record(d, 1.0, "status_ok")
            else -> { routing.record(d, 0.0, "status_fail"); escalateNext = true }
        }
        experience.used(turnLessons, if (rec.stopped || infra) null else rec.ok)
        scheduleLearning()
        if (!followup && rec.seconds > 0) routing.router.observe(d, rec.seconds)
        if (s.mode == Mode.ASK && rec.ok && !followup && tools == 0 && s.firstParts.isNotEmpty()) {
            val parts = s.firstParts
            app.scope.launch {
                routing.duel(d, question, parts, rec.answer, env, conversationTime) {
                    _card.value?.running != true && System.currentTimeMillis() - lastActive > 20_000
                }
            }
        }
    }

    /** 模型调 recall 工具：按它给的说法找经验 */
    private fun recallTool(query: String): String {
        val found = Recall.recall(experience, situation.copy(question = query), exclude = seenLessons)
        if (found.isEmpty()) return "没有相关的经验。"
        seenLessons += found.map { it.id }
        turnLessons = turnLessons + found.map { it.id }
        return "以前踩过的坑（只在和这次情况相符时参考）：\n" + Recall.render(found).joinToString("\n")
    }

    /** 对话结束（最后一轮之后两分钟没追问）再看值不值得总结经验 */
    private fun scheduleLearning() {
        val s = session ?: return
        learnJob?.cancel()
        learnJob = app.scope.launch {
            delay(Learn.LEARN_DELAY_MS)
            if (session !== s || _card.value?.running == true) return@launch
            val reason = Learn.worth(s.records, negative)
            if (reason.isEmpty()) return@launch
            val result = Learn.learn(experience, s.records.toList(), situation, reason,
                llm = { prompt -> routing.complete("你帮助手总结经验，只输出要求的 JSON。", prompt) ?: "" },
                feedback = if (negative) "用户说没答好" else "", source = conversationId)
            Diag.log("learn", result)
        }
    }

    /** 前台窗口的文字节选（路由判断难度用） */
    private fun frontText(cap: Capture): String =
        cap.screen?.windows?.firstOrNull { it.type == "app" }?.let { EnvText.windowText(it) }?.take(4000).orEmpty()

    /** 屏幕上的报错行 */
    private fun errorLines(cap: Capture): String =
        cap.screen?.windows?.flatMap { w -> w.nodes.map { it.text } }?.filter { ERROR_LINE.containsMatchIn(it) }
            ?.joinToString("\n")?.take(2000).orEmpty()

    /** 界面收起（点了空白处、按了返回） */
    fun dismiss() {
        tools?.clearMarks()
        val c = _card.value
        _surface.value = when {
            c?.running == true && c.mode == Mode.ACT -> Surface.PILL
            c?.running == true -> Surface.PILL // 问答还在答：收成小条，答完点开看
            else -> Surface.HIDDEN
        }
    }

    /** 输入框上的「接着刚才的问」：在当前宿主里把卡片恢复出来 */
    fun restore() {
        if (_card.value != null) _surface.value = Surface.CARD
    }

    /** 小条被点了：展开成卡片 */
    fun expand(context: Context) {
        _surface.value = Surface.CARD
        openHost(context, _card.value?.mode ?: _mode.value, "pill")
    }

    fun close() {
        tools?.clearMarks()
        _surface.value = Surface.HIDDEN
    }

    private fun save() {
        val s = session ?: return
        if (s.records.isEmpty()) return
        runCatching {
            history.save(conversationId, conversationTime, s.mode, apps.label(frontApp), s.records, _card.value?.rating ?: 0)
        }.onFailure { Diag.error("history.save", it) }
    }

    fun uiLang(): String = when (val l = app.settings.value.language) {
        "zh", "en" -> l
        else -> if (java.util.Locale.getDefault().language == "zh") "zh" else "en"
    }

    private const val RECENT_MS = 10 * 60_000L
    private const val REASK_MS = 10 * 60_000L
    private val ERROR_LINE = Regex("error|exception|failed|失败|错误|异常|出错", RegexOption.IGNORE_CASE)
    private const val PRE_CAPTURE_MS = 450L
    private const val RESULT_MS = 8_000L
}
