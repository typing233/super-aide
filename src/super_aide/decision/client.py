"""判断模型（Jev 类）：给一段情况和几道带类型的题，几百毫秒返回带概率的答案，不写文字（设计 7.9 节）。

只用在原来靠关键词判断自然语言的地方（追问是不是说没答好、很快又问一遍、按 Esc 停下的原因、经验对不对得上、
路由看任务类型和难度）。可选：没配置、超时、出错时返回 None，调用方照原来的做法判断，不耽误回答。

接口是 TypeSafe 的 /v1/systemone：state（情况）+ questions（题目：noul 是/否、choice 多选一、score 打分）。
StartLux 这类兼容实现也认这个路径（有的服务叫 /v1/decisions，地址里写全了就照写的用）。
要不要先想一想：DeepSeek 一类认 effort（none/auto），StartLux 认 think_mode（never/auto），两个字段一起发，
不认识的服务会忽略（实测两边都忽略对方的字段）。
连接留着接着用：每次新建要多花一次 TLS 握手（实测 deepseek-flash-jev 0.59 → 0.30 秒）；召唤时先连上（warm）。
系统设了代理时走 urllib（它认代理），不复用连接。
"""

from __future__ import annotations

import http.client
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .. import paths
from ..config import Config
from ..i18n import tr

log = logging.getLogger(__name__)

#: 提问路上（首问、追问）最多等这么久，等不到就照原来的做法（实测 p50 约 0.3～0.7 秒）
HOT_S = 1.5
IDLE_S = 50          # 闲了这么久的连接不再用（服务端多半已经关了），重新连
#: 后台判断（重问、停下的原因）：不赶时间，可以让它先想一想
BACKGROUND_S = 20.0
FAIL_LIMIT = 2       # 连着失败这么多次……
BENCH_S = 300        # ……就先歇这么久，免得每次提问都白等
LOG_LIMIT = 2000     # 记录文件最多留这么多条


@dataclass
class Answer:
    type: str                     # noul | choice | score
    value: float | str | None     # noul：是的概率；choice：选中的那项；score：期望档位（可以落在两档之间）
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None


def endpoint(url: str) -> str:
    """地址里没写路径就补上 /v1/systemone；写了 /v1 补 /systemone；写全了照写的用。"""
    url = url.strip().rstrip("/")
    if url.endswith(("/systemone", "/decisions")):
        return url
    return f"{url}/systemone" if url.endswith("/v1") else f"{url}/v1/systemone"


def _proxied(parts) -> bool:
    """系统给这个地址设了代理（环境变量或 Windows 的代理设置）。"""
    proxies = urllib.request.getproxies()
    return bool(proxies.get(parts.scheme)) and not urllib.request.proxy_bypass(parts.hostname or "")


def parse(data: dict) -> dict[str, Answer]:
    out = {}
    for qid, a in (data.get("answers") or {}).items():
        kind = a.get("type", "")
        value = a.get(kind) if kind in ("noul", "choice", "score") else None
        probs = {str(k): float(v) for k, v in (a.get("probabilities") or {}).items()}
        conf = a.get("confidence")
        out[qid] = Answer(kind, value, probs, float(conf) if conf is not None else None)
    return out


class Decider:
    """判断模型的客户端。设置里改了地址、密钥、模型，下一次调用就用新的（和其它部分拿着同一个配置对象）。"""

    def __init__(self, cfg: Config, log_path: Path | None = None) -> None:
        self.cfg = cfg
        self.log_path = log_path if log_path is not None else paths.ROUTER / "checks.jsonl"
        self._lock = threading.Lock()
        self._fails = 0
        self._benched = 0.0
        self._pool = ThreadPoolExecutor(4, thread_name_prefix="decide")
        self._idle: dict[tuple, list[tuple[http.client.HTTPConnection, float]]] = {}  # (协议, 主机, 端口) → 闲着的连接

    def configured(self) -> bool:
        return bool(self.cfg.decision_url.strip() and self.cfg.decision_model.strip())

    def ready(self) -> bool:
        return self.configured() and time.time() - self._benched > BENCH_S

    def ask(self, purpose: str, state: str, questions: dict, budget: float = HOT_S, think: bool = False,
            legacy=None) -> dict[str, Answer] | None:
        """问一次，最多等 budget 秒。判断不了（没配置、在歇、超时、出错）返回 None。
        purpose、legacy（原来的做法会怎么判）只用来记录，方便以后拿真实记录对比两种做法。"""
        if not self.ready():
            return None
        t = time.perf_counter()
        future = self._pool.submit(self._post, state, questions, budget, think)
        try:
            data = future.result(timeout=budget)
            answers = parse(data)
            missing = set(questions) - set(answers)
            if missing:
                raise ValueError(f"少了这几道题的答案：{', '.join(sorted(missing))}")
        except FutureTimeout:
            self._failed(purpose, f"超过 {budget:g} 秒")
            return None
        except Exception as e:  # noqa: BLE001 - 判断模型出任何问题都不能耽误回答
            self._failed(purpose, str(e) or type(e).__name__)
            return None
        with self._lock:
            self._fails = 0
        self._note(purpose, answers, time.perf_counter() - t, legacy)
        return answers

    def _post(self, state: str, questions: dict, budget: float, think: bool) -> dict:
        body = {"model": self.cfg.decision_model.strip(), "state": state, "questions": questions,
                "effort": "auto" if think else "none", "think_mode": "auto" if think else "never"}
        headers = {"Content-Type": "application/json"}
        if self.cfg.decision_key.strip():
            headers["Authorization"] = f"Bearer {self.cfg.decision_key.strip()}"
        url, data, timeout = endpoint(self.cfg.decision_url), json.dumps(body).encode("utf-8"), max(budget, 5.0)
        parts = urlsplit(url)
        if _proxied(parts):
            req = urllib.request.Request(url, data, headers)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                raise RuntimeError(f"HTTP {e.code}：{e.read()[:300].decode('utf-8', 'replace')}") from None
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        for attempt in range(2):
            conn, reused = self._take(parts, timeout)
            try:
                conn.request("POST", path, data, headers)
                resp = conn.getresponse()
                raw = resp.read()
            except (http.client.HTTPException, OSError):
                conn.close()
                if reused and attempt == 0:
                    continue  # 留着的连接已经被服务端关了：重新连一次
                raise
            if resp.will_close:
                conn.close()
            else:
                self._give_back(parts, conn)
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}：{raw[:300].decode('utf-8', 'replace')}")
            return json.loads(raw)
        raise RuntimeError("连不上")  # 走不到：第二次失败会在上面抛出

    def _take(self, parts, timeout: float) -> tuple[http.client.HTTPConnection, bool]:
        key = (parts.scheme, parts.hostname, parts.port)
        with self._lock:
            idle = self._idle.get(key, [])
            while idle:
                conn, since = idle.pop()
                if time.time() - since < IDLE_S:
                    conn.timeout = timeout
                    if conn.sock is not None:
                        conn.sock.settimeout(timeout)
                    return conn, True
                conn.close()
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        return cls(parts.hostname, parts.port, timeout=timeout), False

    def _give_back(self, parts, conn: http.client.HTTPConnection) -> None:
        with self._lock:
            self._idle.setdefault((parts.scheme, parts.hostname, parts.port), []).append((conn, time.time()))

    def warm(self) -> None:
        """你召唤了助手：先在后台连上判断模型（握手约 0.3 秒），打完问题时就不用再等这一下。"""
        if not self.ready():
            return
        parts = urlsplit(endpoint(self.cfg.decision_url))
        key = (parts.scheme, parts.hostname, parts.port)
        with self._lock:
            if any(time.time() - since < IDLE_S for _conn, since in self._idle.get(key, [])) or _proxied(parts):
                return

        def connect() -> None:
            conn, _reused = self._take(parts, 5.0)
            try:
                conn.connect()
            except OSError as e:
                log.debug("判断模型先连上失败：%s", e)
                conn.close()
                return
            self._give_back(parts, conn)

        self._pool.submit(connect)

    def _failed(self, purpose: str, why: str) -> None:
        with self._lock:
            self._fails += 1
            benched = self._fails >= FAIL_LIMIT
            if benched:
                self._fails, self._benched = 0, time.time()
        log.warning("判断模型没答上（%s）：%s%s", purpose, why[:200],
                    f"；先歇 {BENCH_S // 60} 分钟，这期间照原来的做法判断" if benched else "")

    def _note(self, purpose: str, answers: dict[str, Answer], seconds: float, legacy) -> None:
        """记一条：哪件事、多久、每道题的答案（不记情况原文：里面是屏幕内容）。"""
        row = {"t": round(time.time(), 1), "purpose": purpose, "model": self.cfg.decision_model, "ms": round(seconds * 1000),
               "answers": {k: {"value": a.value, "confidence": a.confidence} for k, a in answers.items()}}
        if legacy is not None:
            row["legacy"] = legacy
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            if self.log_path.stat().st_size > LOG_LIMIT * 400:
                lines = self.log_path.read_text(encoding="utf-8").splitlines()[-LOG_LIMIT // 2:]
                self.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as e:
            log.debug("判断记录没写进去：%s", e)

    def test(self) -> dict:
        """设置里的"测试"：问一道很简单的题，返回 {"ok": 答对了没有, "ms": 耗时} 或 {"error": 原因}。"""
        if not self.configured():
            return {"error": tr("没填地址或模型")}
        t = time.perf_counter()
        try:
            data = self._post("用户说：电脑突然没声音了。",
                              {"q": {"type": "noul", "instructions": "用户碰到了问题"}}, 10.0, False)
            answer = parse(data).get("q")
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:300] or type(e).__name__}
        if answer is None or not isinstance(answer.value, (int, float)):
            return {"error": tr("返回的格式不对：不像 Jev 类判断模型")}
        with self._lock:
            self._fails, self._benched = 0, 0.0
        return {"ok": answer.value >= 0.5, "ms": round((time.perf_counter() - t) * 1000)}
