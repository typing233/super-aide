"""用判断模型判断的几件事。判断不了（没配置、超时、出错）时都退回原来的做法，结果和以前一样。

题目怎么写（实测见 spikes/p14_decision_bench.py，换模型时重跑）：
- 判断模型看不到题目和选项的键名，意思全写在说明里；选项的键用中性的名字，带褒贬的名字（yes/no 一类）
  会盖过说明的意思（arXiv 2609.26758）。
- 是/否题的概率落在 UNSURE 中间就是"说不准"：不当成任何信号（宁可不记，也不记错）。
- 只发判断需要的那一点：问题、上一轮的问答节选、框选内容的节选（已经去掉了密钥这类敏感串），不发整屏。

各件事和原来的做法比（合成题，见 spike）：追问 12→26/27；Esc 原因 14→17/17；重问 7→12/12；
问答的任务类型 9→18/18；难度判低了的 5→1；经验对不对得上 27→33/34。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ..evolve import triggers
from ..experience.store import Lesson
from ..router.policy import ASK_KINDS, Task
from .client import BACKGROUND_S, HOT_S, Decider

log = logging.getLogger(__name__)

UNSURE = (0.35, 0.65)
REASK_MIN = 0.7      # 记"上一次没答好"要的把握（权重 0.5 的信号，记错了会让路由白白加强）
LESSON_SECOND = 0.3  # 第二条经验也给的门槛（最多给两条）
KIND_MIN = 0.5       # 任务类型的把握低于这个就用原来的分法
QUESTION_LIMIT = 800
ANSWER_LIMIT = 1200
CONTEXT_LIMIT = 1500
ERRORS_LIMIT = 500

#: 原来的做法：追问里有这些说法就算"上一轮没答好"（判断模型用不了时用）
NEGATIVE_FOLLOWUP = re.compile(r"不对|错了|没用|不行|没解决|还是不|不是这样|没有用|不管用|失败了"
                               r"|\b(wrong|incorrect|not working|doesn'?t work|didn'?t work|still (not|broken|fail)|no luck)\b",
                               re.IGNORECASE)

KIND_CRITERIA = {
    "translation": "翻译：把屏幕上或用户给的文字翻成另一种语言，或者问某句外文是什么意思、某句话用外文怎么说",
    "writing": "写作：帮用户写、改写、润色、回复一段文字（邮件、消息、文案）",
    "error": "报错：解释或解决一个报错、异常、错误码",
    "code": "代码：解释、看懂、分析一段代码或它的行为",
    "ui": "界面：怎么在某个软件里操作、某个按钮或选项是什么意思",
    "system": "系统：Windows 系统、安装卸载、驱动、声音、网络、环境配置这类电脑问题",
    "general": "其他：知识问答、总结、分析、计算等",
}
DIFFICULTY = {
    "ask": ["一般：查一下、简单解释、短翻译、照着常规步骤就能做",
            "较难：要分析排查、多步推理、读懂一段代码或一串报错",
            "很难：复杂调试、深入的推理或数学推导、设计方案、需要反复验证"],
    "act": ["一般：一两步就能做完的常规操作，比如打开、新建、改一个设置",
            "较难：多步操作、要先找到东西、要在几个软件之间配合",
            "很难：复杂的排障、很长的流程、需要反复尝试和验证"],
}


def _cut(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _noul(decider: Decider, purpose: str, state: str, instructions: str, budget: float, think: bool,
          legacy) -> float | None:
    answers = decider.ask(purpose, state, {"q": {"type": "noul", "instructions": instructions}}, budget, think, legacy)
    value = answers["q"].value if answers else None
    return float(value) if isinstance(value, (int, float)) else None


# ---------- 首问：任务类型、难度、经验对不对得上（一次请求） ----------

@dataclass
class Understanding:
    kind: str = ""        # ASK_KINDS 里的一项；操作模式和说不准时为空
    band: int = -1        # 难度档 0～2；-1 = 没判断
    lessons: list[Lesson] | None = None  # 复核后留下的经验；None = 没复核（照原来的给）
    probabilities: dict = field(default_factory=dict)


def _task_state(task: Task, where: str = "") -> str:
    parts = [f"用户的问题：{_cut(task.question, QUESTION_LIMIT)}"]
    if where:  # 前台程序和窗口标题：经验常常和具体软件有关（实测：开着 PowerPoint 说"你帮我改一下"，不给它就认不出）
        parts.append(f"前台窗口：{_cut(where, 200)}")
    if task.context:
        parts.append(f"屏幕上框选的内容（节选）：\n{_cut(task.context, CONTEXT_LIMIT)}")
    if task.errors:
        parts.append(f"前台窗口里的报错（节选）：\n{_cut(task.errors, ERRORS_LIMIT)}")
    return "\n\n".join(parts)


def _lesson_question(candidates: list[Lesson]) -> dict:
    criteria = {str(i + 1): f"{x.title}（适用：{x.when}）" for i, x in enumerate(candidates)}
    criteria["none"] = "都不适用：不是这些经验说的那种情况"
    return {"type": "choice", "criteria": criteria,
            "instructions": "这次用户碰到的情况，适用下面哪一条以前总结的经验？只有确实是同一种情况才选；"
                            "只是同一个话题、原因不同、或者用户只是在问用法，选 none。"}


def _kept(answer, candidates: list[Lesson]) -> list[Lesson]:
    """选中的那条（不是 none）；第二像的那条概率也够高、而且比 none 高，也给。"""
    probs = answer.probabilities or {str(answer.value): 1.0}
    ranked = sorted(((p, k) for k, p in probs.items() if k != "none"), reverse=True)
    none = probs.get("none", 0.0)
    out = []
    for rank, (p, key) in enumerate(ranked[:2]):
        if not key.isdigit() or not 0 < int(key) <= len(candidates):
            continue
        if (rank == 0 and answer.value == key) or (rank == 1 and out and p >= LESSON_SECOND and p > none):
            out.append(candidates[int(key) - 1])
    return out


def understand(decider: Decider, task: Task, candidates: list[Lesson] = (), where: str = "",
               legacy=None) -> Understanding | None:
    """首问提交后：这是哪类任务、要想多深，以及初筛出来的经验里哪条真的对得上。判断不了返回 None。"""
    if not decider.ready():
        return None
    questions: dict = {"difficulty": {"type": "score", "instructions": "要做好这件事需要多深的思考？",
                                      "criteria": DIFFICULTY.get(task.mode, DIFFICULTY["ask"])}}
    if task.mode == "ask":
        questions["kind"] = {"type": "choice", "instructions": "用户向桌面助手提的这个问题属于哪一类？",
                             "criteria": KIND_CRITERIA}
    candidates = list(candidates)
    if candidates:
        questions["lesson"] = _lesson_question(candidates)
    answers = decider.ask("understand", _task_state(task, where), questions, HOT_S, legacy=legacy)
    if answers is None:
        return None
    out = Understanding()
    score = answers["difficulty"].value
    if isinstance(score, (int, float)):
        out.band = max(0, min(2, int(score + 0.5)))
    kind = answers.get("kind")
    if kind is not None and kind.value in ASK_KINDS and (kind.confidence is None or kind.confidence >= KIND_MIN):
        out.kind = str(kind.value)
    if candidates:
        out.lessons = _kept(answers["lesson"], candidates)
    out.probabilities = {k: a.probabilities for k, a in answers.items()}
    return out


def review(decider: Decider, task: Task, candidates: list[Lesson], purpose: str = "lessons",
           where: str = "") -> list[Lesson] | None:
    """只复核经验（追问时、做到一半工具报错时）：初筛出来的里哪条真的对得上。判断不了返回 None。"""
    if not candidates or not decider.ready():
        return None
    answers = decider.ask(purpose, _task_state(task, where), {"lesson": _lesson_question(candidates)}, HOT_S)
    return None if answers is None else _kept(answers["lesson"], candidates)


# ---------- 追问、重问、停下的原因 ----------

FOLLOWUP = ("用户接着说的话表明：助手上一轮的回答是错的、没解决问题、或者没理解用户的意思。"
            "（用户只是接着问新问题、追问细节、提出假设、说已经好了，都不算。）")
REASK = ("用户的新问题是在重复要求上一次那件事（多半是上一次没办好），"
         "而不是一件相似但不同的新事、也不是在上一次办成的基础上再进一步。")
STOP = ("用户中途停下的原因是助手做得不好（做错了、太慢或卡住了、没理解用户的意思），"
        "而不是用户自己改了主意、自己说错了、误触，或者网络等外部原因。")


def followup_state(previous_question: str, previous_answer: str, text: str) -> str:
    return (f"上一轮用户的问题：{_cut(previous_question, QUESTION_LIMIT)}\n"
            f"上一轮助手的回答（节选）：{_cut(previous_answer, ANSWER_LIMIT)}\n"
            f"用户接着说：{_cut(text, QUESTION_LIMIT)}")


def reask_state(previous: str, question: str, same_screen: bool) -> str:
    return (f"同一个程序里，几分钟内用户先后提了两次。\n上一次：{_cut(previous, QUESTION_LIMIT)}\n"
            f"这一次：{_cut(question, QUESTION_LIMIT)}\n"
            + ("两次提问时屏幕上的内容一样" if same_screen else "两次提问时屏幕上的内容不一样"))


def stop_state(task: str, text: str) -> str:
    return (f"用户让助手在电脑上替他操作：{_cut(task, QUESTION_LIMIT)}\n"
            f"操作进行到一半，用户按 Esc 停下，并写了原因：{_cut(text, QUESTION_LIMIT)}")


def negative_followup(decider: Decider, previous_question: str, previous_answer: str, text: str) -> bool:
    """追问是不是在说"上一轮没答好"（答错了、没解决、没理解意思）。"""
    legacy = bool(NEGATIVE_FOLLOWUP.search(text))
    if not previous_question or not decider.ready():
        return legacy
    p = _noul(decider, "followup", followup_state(previous_question, previous_answer, text), FOLLOWUP, HOT_S, False,
              legacy)
    return legacy if p is None else p >= UNSURE[1]


def reask(decider: Decider, previous: str, question: str, same_screen: bool, legacy: bool) -> bool:
    """很快又问了一次：是在重复要上一次那件事（多半没办好），还是一件相似的新事、或者在上次的基础上再进一步。"""
    if not decider.ready():
        return legacy
    p = _noul(decider, "reask", reask_state(previous, question, same_screen), REASK, BACKGROUND_S, True, legacy)
    return legacy if p is None else p >= REASK_MIN


def stop_fault(decider: Decider, task: str, choice: str, text: str) -> bool:
    """按 Esc 停下后你给的原因，算不算助手的问题。只选了原因、没打字的照原来的规则；打了字的交给判断模型。"""
    legacy = triggers.stop_counts(choice, text)
    text = (text or "").strip()
    if choice == triggers.NOT_ASSISTANT or not text or not decider.ready():
        return legacy
    p = _noul(decider, "stop", stop_state(task, text), STOP, BACKGROUND_S, True, legacy)
    return legacy if p is None else p >= 0.5
