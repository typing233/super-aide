package io.github.typing233.superaide.core.llm

import io.github.typing233.superaide.core.i18n.tr

/**
 * 模型调用失败分类（对应桌面版 engines/base.py、hub.failure_kind）：
 * MODEL = 这个模型用不了（换一个模型），AUTH = 认证失败（换一个服务），SERVICE = 限流/过载/网络（暂时换走），
 * NONE = 和服务无关的错（比如请求本身有问题），不换。
 */
object Failure {
    enum class Kind { MODEL, AUTH, SERVICE, NONE }

    val MODEL_UNAVAILABLE = Regex(
        """model[_ ]not[_ ]found|unknown[_ ]model|invalid[_ ]model|unsupported[_ ]model|model[_ ]not[_ ]supported""" +
            """|model\W[^\n]{0,80}?\b(does not exist|not (found|supported|available|allowed|enabled)|is not (supported|available)""" +
            """|unavailable|has been deprecated|no access)""" +
            """|(do(es)?n'?t|do(es)? not) have access to (the |this )?model|(issue|problem) with the selected model""" +
            """|not_found_error[^\n]{0,60}model|(no|unknown) (available )?(channels?|providers?|distributors?) (for|under|available)[^\n]{0,60}model""" +
            """|无可用渠道|没有可用的?渠道|模型不存在|不支持(该|此|这个)?模型|模型[^\n]{0,20}(不可用|不存在|已下线|未开通|无权限)""",
        RegexOption.IGNORE_CASE,
    )
    private val RATE_LIMITED = Regex("""\b429\b|rate.?limit|too many requests""", RegexOption.IGNORE_CASE)
    private val AUTH_FAILED = Regex("""\b(401|403)\b|unauthori[sz]ed|authentication|invalid (api )?key""", RegexOption.IGNORE_CASE)
    private val SERVICE_DOWN = Regex(
        """\b(500|502|503|504|520|522|524|529)\b|overloaded|service unavailable|bad gateway|internal server error|auth_unavailable""",
        RegexOption.IGNORE_CASE,
    )
    private val TIMED_OUT = Regex("""timed? ?out|timeout""", RegexOption.IGNORE_CASE)
    private val NETWORK = Regex(
        """connection (error|refused|reset|aborted)|network error|getaddrinfo|name resolution|ssl|proxy error|unable to resolve host|failed to connect""",
        RegexOption.IGNORE_CASE,
    )

    fun kind(e: ModelError): Kind {
        val msg = "${e.type.orEmpty()} ${e.message.orEmpty()}"
        return when {
            e.status == 404 || MODEL_UNAVAILABLE.containsMatchIn(msg) -> Kind.MODEL
            e.status == 401 || e.status == 403 || (e.status == null && AUTH_FAILED.containsMatchIn(msg)) -> Kind.AUTH
            e.status == null -> Kind.SERVICE // 网络断了、流中途出错
            e.status == 408 || e.status == 409 || e.status == 425 || e.status == 429 || e.status >= 500 -> Kind.SERVICE
            RATE_LIMITED.containsMatchIn(msg) || SERVICE_DOWN.containsMatchIn(msg) -> Kind.SERVICE
            else -> Kind.NONE
        }
    }

    /** 给人看的一句话 */
    fun friendly(e: ModelError): String {
        val msg = "${e.status ?: ""} ${e.type.orEmpty()} ${e.message.orEmpty()}"
        return when {
            MODEL_UNAVAILABLE.containsMatchIn(msg) || e.status == 404 -> tr("这个模型现在用不了（服务没提供或没开通），可以在设置里关掉它。")
            e.status == 429 || RATE_LIMITED.containsMatchIn(msg) -> tr("模型服务限流了，稍后再试。")
            e.status == 401 || e.status == 403 || AUTH_FAILED.containsMatchIn(msg) -> tr("模型服务认证失败，请在设置里检查服务地址和 key。")
            (e.status ?: 0) >= 500 || SERVICE_DOWN.containsMatchIn(msg) -> tr("模型服务暂时不可用，稍后再试。")
            TIMED_OUT.containsMatchIn(msg) -> tr("模型服务响应超时。")
            e.status == null || NETWORK.containsMatchIn(msg) -> tr("连不上模型服务，请检查网络或代理。")
            else -> e.message?.take(300) ?: tr("出错了")
        }
    }

    /** "{模型} 被限流了，换 {另一个} 接着答…" 里的那几个字 */
    fun reason(e: ModelError): String {
        val msg = "${e.status ?: ""} ${e.type.orEmpty()} ${e.message.orEmpty()}"
        return when {
            MODEL_UNAVAILABLE.containsMatchIn(msg) || e.status == 404 -> tr("用不了")
            e.status == 429 || RATE_LIMITED.containsMatchIn(msg) -> tr("被限流了")
            e.status == 401 || e.status == 403 -> tr("认证失败")
            (e.status ?: 0) >= 500 || SERVICE_DOWN.containsMatchIn(msg) -> tr("服务暂时不可用")
            TIMED_OUT.containsMatchIn(msg) -> tr("响应超时")
            e.status == null -> tr("连不上")
            else -> tr("出错了")
        }
    }
}
