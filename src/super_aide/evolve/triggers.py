"""什么情况触发自我改进、什么情况不算。

- 故障不算：网络、DNS、SSL、代理、认证、限流、服务过载、接口故障（Claude 的 api_error 结束时报错常常是空的，
  只看报错文字会把它当成能力失败）。路由的学习信号也用同一套判断。
- 按 Esc 停下：你选了"做错了 / 太慢或卡住了 / 没懂我的意思"，或者打字说了原因，才算助手的问题；
  不答、选"不是助手的问题"、写"改主意了""不用了"之类，不算。
- 问题指纹：同一类问题（同一种触发、同样的报错或根因）得到同一个短哈希。社区共建用它去重。
"""

from __future__ import annotations

import hashlib
import re

#: 和能力无关的失败（中英文、HTTP 状态码、常见的网络异常名）
INFRA_TEXT = re.compile(
    r"\b(401|403|407|408|429|500|502|503|504|520|522|524|529)\b"
    r"|timed? ?out|timeout|network|connection|connect(ion)? (refused|reset|aborted)|getaddrinfo|name resolution"
    r"|dns|ssl|certificate|proxy|eof occurred|rate.?limit|overloaded|service unavailable|bad gateway"
    r"|unauthori[sz]ed|forbidden|authentication|invalid (api )?key|api key|quota|insufficient|billing|credit balance"
    r"|网络|连接|超时|代理|认证|限流|过载|额度|余额|登录",
    re.IGNORECASE)
#: 汇报"没完成"的第一行是模型写的任务说明，里面常有"网络设置""代理"这样的词：只认明确的故障说法
REPORTED_INFRA = re.compile(r"\b(401|403|429)\b|timed? ?out|timeout|network error|connection (error|refused|reset)"
                            r"|rate.?limit|认证失败|被限流|连不上(服务|模型|接口)", re.IGNORECASE)
#: 这些结束原因本身就说明不是能力问题：你中途停止、接口出错、被中断
INFRA_REASONS = {"interrupted", "api_error", "aborted_streaming", "aborted_tools"}
INFRA_EXCEPTIONS = ("ConnectionError", "TimeoutError", "CLIConnectionError", "SSLError", "ProxyError",
                    "URLError", "gaierror", "RemoteDisconnected", "IncompleteRead", "ReadTimeout", "ConnectTimeout")

STOP_FAULTS = ("wrong", "slow", "misunderstood")
NOT_ASSISTANT = "not_assistant"
CHANGED_MIND = re.compile(r"改主意|不用了|不需要了|不要了|算了|我自己来|自己弄|搞错了|点错了|按错了|误触|没事了|不做了|先不"
                          r"|changed? my mind|never ?mind|no longer need|not needed|by mistake|my (mistake|bad)"
                          r"|wrong (key|button)|i'?ll do it myself",
                          re.IGNORECASE)


def is_infra(done: dict) -> bool:
    """这一轮没办成是不是和能力无关（网络、认证、限流、接口故障、你中途停止、环境没就绪）。"""
    if done.get("stopped") or done.get("hint"):
        return True
    if done.get("reason") in INFRA_REASONS:
        return True
    status = done.get("api_error_status")
    if isinstance(status, int) and status != 400 and status != 404:
        return True
    if any(name in str(done.get("exception", "")) for name in INFRA_EXCEPTIONS):
        return True
    error = str(done.get("error") or "")
    if done.get("reason") == "reported":
        return bool(REPORTED_INFRA.search(error))
    return bool(INFRA_TEXT.search(error))


def exception_is_infra(e: BaseException) -> bool:
    text = f"{type(e).__name__}: {e}"
    return any(name in text for name in INFRA_EXCEPTIONS) or bool(INFRA_TEXT.search(text))


def stop_counts(choice: str, text: str) -> bool:
    """按 Esc 停下后你给的原因，算不算助手的问题。"""
    if choice == NOT_ASSISTANT:
        return False
    text = (text or "").strip()
    if text and CHANGED_MIND.search(text):
        return False
    return choice in STOP_FAULTS or bool(text)


_NOISE = re.compile(r"[A-Za-z]:\\[^\s'\"]*|/[\w./-]+|0x[0-9a-f]+|\b[0-9a-f]{8,}\b|\d+|\s+", re.IGNORECASE)


def signature(kind: str, text: str) -> str:
    """问题指纹：去掉路径、数字、十六进制、空白之后的哈希。同一类问题、不同的具体路径和行号，指纹一样。"""
    normalized = _NOISE.sub(" ", (text or "").lower()).strip()
    return hashlib.sha1(f"{kind}|{normalized[:400]}".encode("utf-8")).hexdigest()[:12]
