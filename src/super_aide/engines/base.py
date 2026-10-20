"""两个引擎共用的事件格式。界面只认这些事件，不关心背后是哪个引擎。"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import tr


@dataclass
class Event:
    #: route（路由结果）| status（一行状态）| new_message（新一段回答开始）| delta（正文增量）
    #: | retract（刚才那段是过程说明，从正文里撤掉）| done（这一轮结束）| error
    type: str
    text: str = ""
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"type": self.type, "text": self.text, **self.data}


def image_block(path: Path) -> dict:
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": media,
                                        "data": base64.b64encode(path.read_bytes()).decode()}}


def short(text: str, limit: int = 60) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


#: 操作模式的汇报约定第一行以「已完成：」或「没完成：」开头（英文回答是 Done: / Not done:，见 prompts.MODE_RULES）；
#: 后几个是没按约定时的常见说法
FAILED_STARTS = ("没完成", "未完成", "暂未", "未能", "没能", "无法完成",
                 "not done", "not completed", "couldn't", "could not", "unable to", "failed")


def reported_failure(text: str) -> str:
    """汇报说没办成时，返回它的第一行（界面上显示）；办成了或看不出来，返回空。"""
    first = next((line.strip(" *#>-\t") for line in text.strip().splitlines() if line.strip()), "")
    return first if first.lower().startswith(FAILED_STARTS) else ""


#: 这个模型用不了（服务不提供、没开通、中转没有它的渠道、账号类型不支持）：换一个模型就好，和能力无关
MODEL_UNAVAILABLE = re.compile(
    r"model[_ ]not[_ ]found|unknown[_ ]model|invalid[_ ]model|unsupported[_ ]model|model[_ ]not[_ ]supported"
    r"|model\W[^\n]{0,80}?\b(does not exist|not (found|supported|available|allowed|enabled)|is not (supported|available)"
    r"|unavailable|has been deprecated|no access)"
    r"|(do(es)?n'?t|do(es)? not) have access to (the |this )?model|(issue|problem) with the selected model"
    r"|not_found_error[^\n]{0,60}model|(no|unknown) (available )?(channels?|providers?|distributors?) (for|under|available)[^\n]{0,60}model"
    r"|无可用渠道|没有可用的?渠道|模型不存在|不支持(该|此|这个)?模型|模型[^\n]{0,20}(不可用|不存在|已下线|未开通|无权限)",
    re.IGNORECASE)
RATE_LIMITED = re.compile(r"\b429\b|rate.?limit|too many requests", re.IGNORECASE)
AUTH_FAILED = re.compile(r"\b(401|403)\b|unauthori[sz]ed|authentication|invalid (api )?key", re.IGNORECASE)
SERVICE_DOWN = re.compile(r"\b(500|502|503|504|520|522|524|529)\b|overloaded|service unavailable|bad gateway"
                          r"|internal server error", re.IGNORECASE)
TIMED_OUT = re.compile(r"timed? ?out|timeout", re.IGNORECASE)
NETWORK = re.compile(r"connection (error|refused|reset|aborted)|network error|getaddrinfo|name resolution"
                     r"|ssl|proxy error", re.IGNORECASE)


def friendly_text(msg: str) -> str:
    """引擎报上来的原始接口错误（常常是英文，比如 "exceeded retry limit, last status: 429 Too Many Requests"），
    换成给人看的一句话；认不出来的原样返回。"""
    if MODEL_UNAVAILABLE.search(msg):
        return tr("这个模型现在用不了（服务没提供或没开通），可以在设置里关掉它。")
    if RATE_LIMITED.search(msg):
        return tr("引擎被限流了，稍后再试。")
    if AUTH_FAILED.search(msg):
        return tr("引擎认证失败，请检查 Claude Code / Codex 的登录或服务地址配置。")
    if SERVICE_DOWN.search(msg):
        return tr("模型服务暂时不可用，稍后再试。")
    if TIMED_OUT.search(msg):
        return tr("引擎响应超时。")
    if NETWORK.search(msg):
        return tr("连不上模型服务，请检查网络或代理。")
    return msg


def service_reason(msg: str) -> str:
    """服务出错的简短说法（"被限流了"），用在"Codex 被限流了，换 Claude 接着做…"这行状态里。"""
    if MODEL_UNAVAILABLE.search(msg):
        return tr("用不了")
    if RATE_LIMITED.search(msg):
        return tr("被限流了")
    if AUTH_FAILED.search(msg):
        return tr("认证失败")
    if SERVICE_DOWN.search(msg):
        return tr("服务暂时不可用")
    if TIMED_OUT.search(msg):
        return tr("响应超时")
    if NETWORK.search(msg):
        return tr("连不上")
    return tr("出错了")


def friendly_error(e: BaseException) -> str:
    msg = str(e) or type(e).__name__
    lowered = msg.lower()
    if MODEL_UNAVAILABLE.search(msg):
        return friendly_text(msg)
    if "401" in msg or "unauthorized" in lowered or "auth" in lowered:
        return tr("引擎认证失败，请检查 Claude Code / Codex 的登录或服务地址配置。")
    if "429" in msg or "rate" in lowered:
        return tr("引擎被限流了，稍后再试。")
    if "timeout" in lowered or "timed out" in lowered:
        return tr("引擎响应超时。")
    return tr("引擎出错：{error}", error=short(msg, 120))
