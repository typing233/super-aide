"""判断模型（decision/）的对比测试：同一批合成题，用正式代码里的题目问判断模型，和原来的做法（关键词、llmrouter 难度、
严格对经验）比准确率和耗时。换判断模型、改题目写法之后重跑。题目都是编的，不含真实用户数据。

判断模型的地址、密钥、模型读 ~/.super_aide/config.toml 的 [decision]，也可以用环境变量
DECISION_URL / DECISION_KEY / DECISION_MODEL 临时换一个。

    uv run --no-sync python -X utf8 spikes/p14_decision_bench.py [followup stop reask kind difficulty lesson]

2026-10-20 deepseek-flash-jev 的结果（括号里是原来的做法）：追问 26/27（12）、Esc 原因 17/17（14）、重问 12/12（7）、
任务类型 18/18（9）、难度：判低了的 5 → 1（判高了的 1 → 4，只是多想一会儿）、经验 33/34（27）；
耗时 p50 0.60 秒、p90 0.73 秒。题目是照着关键词的弱点写的，差距会显得比实际大。
用户的真实记录（77 次首问，只在本机跑）：原来的严格对法有 39 次带了经验、多半不相干（屏幕上开着 Claude Code 就想起
"查 Claude Code 面板全文"），复核后只剩 10 次左右、基本都对得上；p50 0.64～0.92 秒，网关忙时约 5% 超过 1.5 秒退回原来的做法。
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

from super_aide import config, paths
from super_aide.decision import Decider, checks
from super_aide.decision.client import HOT_S
from super_aide.engines.hub import _specifics
from super_aide.evolve import triggers
from super_aide.experience import recall
from super_aide.experience.embed import Embedder
from super_aide.experience.semantic import Semantic
from super_aide.experience.store import Store
from super_aide.router import policy
from super_aide.router.policy import Task, task_kind


def fu(q, a, follow):
    return q, a, follow


FOLLOWUP = [  # (上一轮问题, 上一轮回答, 追问, 是在说没答好？)
    (*fu("pip 装 torch 很慢怎么办", "换清华镜像：pip install -i https://pypi.tuna.tsinghua.edu.cn/simple torch", "照你说的换了，还是卡在 Collecting 不动"), True),
    (*fu("帮我把这两列合并", "在 C1 输入 =A1&B1 然后下拉", "不对，我要的是把两列的内容合并到一列里并且中间加空格"), True),
    (*fu("怎么关闭 Edge 的新标签页新闻", "打开设置 → 高级设置 → 关闭资讯", "你说的那个“高级设置”菜单根本找不到"), True),
    (*fu("这个报错怎么解决", "缺少 requests，运行 pip install requests", "还是报同样的错"), True),
    (*fu("电脑没声音怎么办", "重启 Windows Audio 服务", "重启了也没变化"), True),
    (*fu("How do I fix this error?", "Run npm install again to restore the missing module.", "nope, same error"), True),
    (*fu("Why is the Save button disabled?", "You need to fill in the required Name field first.", "That didn't help, the button is still greyed out"), True),
    (*fu("怎么让 Word 自动生成目录", "引用 → 目录 → 自动目录", "没用"), True),
    (*fu("怎么合并单元格", "选中后点“合并后居中”", "你理解错了，我是想把两列的数据合并成一列"), True),
    (*fu("怎么开启远程桌面", "设置 → 系统 → 远程桌面 → 打开，然后在第三步选择网络级别身份验证", "按你的步骤做到第三步就没有那个选项了"), True),
    (*fu("怎么给这个脚本加执行权限", "运行 chmod +x run.sh", "执行完报 permission denied"), True),
    (*fu("vllm 怎么启动", "python -m vllm.entrypoints.openai.api_server --model 路径", "我输入的是这个：python3 -m vllm.entrypoints.openai.api_server --model /data/qwen，然后报 KeyError: 'qwen3'"), True),
    (*fu("Why does my build fail?", "Delete the cache folder and rebuild.", "still broken"), True),
    (*fu("这个函数是干嘛的", "它把列表去重后排序", "答非所问，我问的是第二个函数"), True),
    (*fu("怎么把这个服务设为开机启动", "用 sc config 服务名 start= auto", "好的，那怎么让它崩溃以后自动重启？"), False),
    (*fu("这个公式什么意思", "VLOOKUP 按第一列查找并返回第三列", "公式里的 $ 是什么意思"), False),
    (*fu("帮我解释一下这个表格的结构", "第一列是日期，第二到四列是各地区销售额，最后一行是合计", "第三行的合计算错了，你帮我看看是哪里出了问题"), False),
    (*fu("怎么清理 C 盘", "先用磁盘清理，勾选临时文件和系统更新清理", "不行的话还有别的办法吗？"), False),
    (*fu("怎么截长图", "用 Edge 的网页捕获 → 捕获整页", "可以了，谢谢！再问一下怎么撤销刚才的设置"), False),
    (*fu("怎么查看电脑配置", "运行 dxdiag", "为什么 Windows 更新老是失败了又重试"), False),
    (*fu("怎么在 Windows 上设置定时关机", "shutdown -s -t 3600", "那 Mac 上怎么做？"), False),
    (*fu("怎么装 Node", "去 nodejs.org 下载 LTS 安装包，一路下一步", "我照做了，现在呢？"), False),
    (*fu("Python 装哪个版本", "建议 3.12", "用一句话说：要装到哪个 Python？"), False),
    (*fu("How do I hide the taskbar?", "Settings → Personalization → Taskbar → Automatically hide", "Thanks, that worked. How do I undo it later?"), False),
    (*fu("What does this function do?", "It parses the config file and returns a dict.", "What does the 'wrong number of arguments' warning on line 12 mean?"), False),
    (*fu("帮我总结这篇文章", "文章讲了三点：……（约 600 字）", "能不能写得更简短一点"), False),
    (*fu("怎么重装显卡驱动", "先用 DDU 卸载旧驱动，再装新版", "如果还是不行我是不是要重装系统？"), False),
]

STOP = [  # (让它做的事, 停下的原因, 算助手的问题？)
    ("整理桌面上的文件", "你点错地方了，把我的文件删了", True), ("整理桌面上的文件", "我点错了，本来想按别的键", False),
    ("在 Excel 里做个透视表", "太慢了，半天没动", True), ("打开设置里的显示选项", "它一直在重复打开同一个菜单", True),
    ("帮我订一张明天的火车票", "不用了，会议马上开始了", False), ("把这个文档导出", "你理解错了，我要的是另存为 PDF", True),
    ("清理浏览器缓存", "先不做了，等下再说", False), ("帮我写邮件草稿", "它把我的邮件发出去了！我只是让它写草稿", True),
    ("把这个窗口里的表格复制出来", "搞错了，应该是另一个窗口，我刚才没说清楚", False),
    ("把这个窗口里的表格复制出来", "你搞错了，不是这个窗口", True), ("下载这个页面上的视频", "网太卡了", False),
    ("打开昨天那份合同", "打开的不是我要的那个文件", True), ("给项目建一个新的 git 分支", "我想起来这个已经做过了", False),
    ("Log in to the company portal", "stuck on the login page for a minute", True),
    ("Find the invoice email", "never mind, I found it myself", False),
    ("Fill in the registration form", "you typed into the wrong field", True),
    ("Rename the report file", "my bad, I gave the wrong file name", False),
]

REASK = [  # (上一次, 这一次, 屏幕一样？, 是重问？)
    ("把这个表格按日期排序", "按日期排一下序", True, True), ("新建 a.txt 内容是 1", "新建 b.txt 内容是 2", True, False),
    ("这个报错怎么解决", "这个报错到底怎么解决啊", True, True), ("翻译这段话", "翻译这段话", False, False),
    ("帮我把音量调小", "音量再调小一点", True, False), ("怎么关闭开机自启的 QQ", "QQ 开机自启怎么关", True, True),
    ("把第一段加粗", "把第二段加粗", True, False), ("下载这个页面上的 PDF", "下载这个页面上的 PDF", True, True),
    ("Summarize this page", "Give me a summary of this page", True, True), ("打开设置里的蓝牙", "打开设置里的 Wi-Fi", True, False),
    ("给张三发消息说我晚点到", "给李四发消息说我晚点到", True, False), ("这个图标是干什么的", "这个图标是做什么用的", True, True),
]

KIND = [  # (问题, 框选内容的类型, 可接受的类型)
    ("这句话英文怎么说：我们下周再讨论", "text", {"translation"}), ("帮我回一下这封邮件，委婉拒绝", "text", {"writing"}),
    ("这个报错啥意思", "error", {"error"}), ("这段代码是干嘛的", "code", {"code"}), ("这个选项勾上会怎样", "dialog", {"ui"}),
    ("电脑突然没声音了", "text", {"system"}), ("总结一下这篇文章", "text", {"general"}),
    ("What does this paragraph say in Chinese?", "foreign", {"translation"}), ("polish this paragraph for me", "text", {"writing"}),
    ("wifi 老掉线怎么办", "text", {"system"}), ("这个函数为什么返回 None", "code", {"code", "error"}),
    ("Excel 里怎么冻结首行", "text", {"ui"}), ("安装的时候提示 0x80070643", "error", {"error", "system"}),
    ("这个按钮灰的点不了是为什么", "dialog", {"ui"}), ("量子纠缠是什么", "text", {"general"}),
    ("把这段话改得正式一点", "text", {"writing"}), ("日语这句什么意思：お疲れ様です", "text", {"translation"}),
    ("PPT 怎么批量替换字体", "text", {"ui"}),
]
OLD_KIND = {v[1]: k for k, v in policy.ASK_KINDS.items()}  # 关键词分法的子类 → 判断模型的类型名

DEADLOCK = """import threading
a, b = threading.Lock(), threading.Lock()
def t1():
    with a:
        work()
        with b: commit()
def t2():
    with b:
        flush()
        with a: commit()"""
RUST = """error[E0502]: cannot borrow `v` as mutable because it is also borrowed as immutable
3 |     let first = &v[0];
4 |     v.push(6);
5 |     println!("{}", first);"""
SQL = """SELECT o.id, c.name, SUM(i.price) FROM orders o JOIN customers c ON o.cid=c.id
JOIN items i ON i.oid=o.id WHERE DATE(o.created) = '2026-10-01' GROUP BY o.id, c.name ORDER BY 3 DESC"""
ARTICLE = "（一篇约 1500 字的新闻稿：某公司发布季度财报，营收同比增长 12%，利润率下降，管理层解释原因……）" * 3

DIFF = [  # (问题, 框选内容, 可接受的档)
    ("这个单词什么意思", "serendipity", {0}), ("帮我设计一个支持多机房的分布式限流方案", "", {2}),
    ("为什么这段代码偶尔会卡死", DEADLOCK, {1, 2}), ("这个报错怎么解决", "ModuleNotFoundError: No module named 'requests'", {0}),
    ("证明根号 2 是无理数", "", {1}), ("这个积分怎么算", "∫ x² eˣ dx", {1}), ("帮我看看这个 SQL 为什么慢", SQL, {1}),
    ("总结一下", ARTICLE, {0}), ("把这段话翻译成英文", "我们下周再讨论这个方案。", {0}),
    ("我们的服务 p99 延迟每天凌晨 3 点飙升，可能是什么原因，怎么排查", "", {2}), ("excel 怎么求和", "", {0}),
    ("这个报错怎么改", RUST, {1, 2}), ("帮我推导一下卡尔曼滤波的更新公式", "", {2}), ("电脑开机很慢怎么办", "", {0, 1}),
    ("写一个线程安全的 LRU 缓存，并分析复杂度", "", {1, 2}), ("今天几号", "", {0}),
    ("这个合同里有没有对我不利的条款", "（一份 3 页的租房合同全文……押金、违约金、提前退租条款……）", {1, 2}),
    ("为什么这两个数相加不等于 0.3", "0.1 + 0.2 = 0.30000000000000004", {0, 1}),
]

LESSONS = {
    "pip": ("pip 装包超时先查代理", "pip install 一直超时、卡住，或报代理、SSL 错误",
            ["pip install 超时", "Read timed out", "ProxyError", "SSLError", "装包很慢", "连接超时", "镜像源", "Collecting 卡住"],
            ["ReadTimeoutError", "ProxyError"]),
    "typo": ("No module named 先核对模块名拼写", "报 ModuleNotFoundError，而模块名和常见包名只差一两个字母",
             ["No module named", "ModuleNotFoundError", "找不到模块", "导入失败", "模块名拼写"], ["ModuleNotFoundError", "No module named"]),
    "excel": ("脚本改 Excel 先关受保护的视图", "用脚本改 Excel 文件时报 0x800A03EC，或文件处于受保护的视图",
              ["受保护的视图", "0x800A03EC", "只读", "Protected View", "黄色提示条"], ["0x800A03EC"]),
    "oom": ("内核挂掉先看显存内存", "训练时 Kernel died、CUDA out of memory",
            ["Kernel died", "CUDA out of memory", "显存不足", "内核重启", "batch size"], ["CUDA out of memory"]),
    "ps1": ("PowerShell 禁止运行脚本时改执行策略", "运行 .ps1 报禁止运行脚本、execution policy",
            ["禁止运行脚本", "execution policy", "执行策略", "ps1 无法运行", "running scripts is disabled"], ["running scripts is disabled"]),
    "git": ("git push 被拒先拉取再推", "push 被拒绝：rejected non-fast-forward，远程有新提交",
            ["push 被拒绝", "rejected", "non-fast-forward", "updates were rejected", "fetch first"], ["non-fast-forward"]),
    "port": ("端口被占用先查是哪个进程", "启动服务报 Address already in use、端口被占用",
             ["端口被占用", "Address already in use", "EADDRINUSE", "端口冲突", "bind failed"], ["EADDRINUSE", "Address already in use"]),
    "moji": ("中文乱码先确认文件编码", "打开文件中文显示成问号或乱码，文件编码不是 UTF-8",
             ["乱码", "中文显示问号", "文件编码", "GBK", "UTF-8", "mojibake"], ["UnicodeDecodeError"]),
}

LESSON_CASES = [  # (问题, 应想起的经验 或 None)
    ("下载依赖包的时候一直卡在 Collecting，最后提示连接失败", "pip"), ("安装 torch 半天装不上，老是 Read timed out", "pip"),
    ("导入的时候说没有这个库，可是我明明装过了", "typo"), ("用脚本改表格文件时报错说文档是只读的，上面有一条黄色提示条", "excel"),
    ("训练到一半笔记本的内核就重启了，显卡好像撑不住", "oom"), ("双击 ps1 文件没反应，提示不能运行脚本", "ps1"),
    ("推送代码时被拒绝了，说 updates were rejected because the remote contains work", "git"),
    ("启动服务报错说 8080 已经被别的程序用了", "port"), ("打开 csv 文件里面的汉字全是问号", "moji"),
    ("公司网络装包特别慢，十分钟都下不完", "pip"), ("显存不够了，跑到第二个 epoch 就挂", "oom"),
    ("Excel 打开导出的 csv 中文全是乱码", "moji"), ("npm start 说 3000 端口有人用了", "port"),
    ("pip install 报 No matching distribution found for torch==2.9.1", None), ("git pull 提示有合并冲突怎么办", None),
    ("localhost:3000 打不开，显示拒绝连接", None), ("运行 ps1 脚本提示找不到路径", None),
    ("CUDA error: device-side assert triggered", None), ("怎么把 pip 源换成清华的", None),
    ("这个 csv 用什么编码保存比较好", None), ("git push 之后怎么撤销", None),
    ("import numpy 报 No module named numpy，我确实还没装过 numpy", None),
    ("你好", None), ("今天天气怎么样", None), ("帮我把这段话翻译成英文", None), ("写一封请假邮件", None),
    ("Excel 怎么求和", None), ("python 怎么读取文件", None), ("git 怎么创建分支", None), ("端口是什么意思", None),
    ("pip 是什么", None), ("显卡型号怎么看", None), ("PowerShell 怎么打开", None), ("这段英文报错是什么意思", None),
]


class Counting(Decider):
    """记下每次的耗时和没答上的次数（正式代码判断不了时会悄悄退回原来的做法，测试里要看得见）。"""

    def __init__(self, cfg) -> None:
        super().__init__(cfg, log_path=Path(tempfile.gettempdir()) / "aide-decision-bench.jsonl")
        self.seconds: list[float] = []
        self.missed = 0

    def ready(self) -> bool:
        return self.configured()  # 测试里不歇

    def ask(self, *args, **kwargs):
        t = time.perf_counter()
        answers = super().ask(*args, **kwargs)
        self.seconds.append(time.perf_counter() - t)
        self.missed += answers is None
        return answers


def run(name: str, d: Counting) -> None:
    difficulty = policy._difficulty_fn(config.load().llmrouter_path) or policy._simple_difficulty
    rows: list[tuple[bool, bool, str]] = []  # (原来对不对, 现在对不对, 题目)
    if name == "followup":
        for q, a, follow, want in FOLLOWUP:
            old = bool(checks.NEGATIVE_FOLLOWUP.search(follow))
            rows.append((old == want, checks.negative_followup(d, q, a, follow) == want, follow))
    elif name == "stop":
        for task, why, want in STOP:
            rows.append((triggers.stop_counts("", why) == want, checks.stop_fault(d, task, "", why) == want, why))
    elif name == "reask":
        from difflib import SequenceMatcher
        for prev, new, same, want in REASK:
            old = SequenceMatcher(None, prev, new).ratio() >= 0.8 and _specifics(prev) == _specifics(new) and same
            rows.append((old == want, checks.reask(d, prev, new, same, old) == want, f"{prev} → {new}"))
    elif name == "kind":
        for q, ck, want in KIND:
            task = Task("ask", q, ck)
            u = checks.understand(d, task)
            rows.append((OLD_KIND.get(task_kind(task)[1]) in want, bool(u) and u.kind in want, q))
    elif name == "difficulty":
        for q, ctx, want in DIFF:
            score = difficulty(q)
            if ctx:
                score = max(score, difficulty(f"{q}\n\n{ctx}"))
            old = sum(score >= x for x in policy.BAND_LIMITS)
            u = checks.understand(d, Task("ask", q, "text", context=ctx))
            rows.append((old in want, bool(u) and max(old, u.band) in want, f"{q}（原来 {old}，判断模型 {u.band if u else '?'}）"))
    elif name == "lesson":
        store = Store(Path(tempfile.mkdtemp()) / "lessons.json")
        ids = {store.add(t, w, "（做法）", triggers=tr, errors=er).id: k for k, (t, w, tr, er) in LESSONS.items()}
        emb = Embedder(root=paths.MODELS)
        emb.ensure(wait=True)
        sem = Semantic(emb, store.path.with_name("vectors.json")) if emb.ready() else None
        for q, want in LESSON_CASES:
            situation = recall.Situation(question=q)
            strict = recall.recall(store, situation, semantic=sem)
            loose = recall.recall(store, situation, semantic=sem, limit=4, loose=True)
            u = checks.understand(d, Task("ask", q, "text"), loose)
            kept = (u.lessons or []) if u else strict

            def right(found):
                return [ids[x.id] for x in found][:1] == ([want] if want else [])
            rows.append((right(strict), right(kept), q))
    old, new = sum(r[0] for r in rows), sum(r[1] for r in rows)
    print(f"\n== {name}：原来 {old}/{len(rows)}，判断模型 {new}/{len(rows)}")
    for o, n, label in rows:
        if not (o and n):
            print(f"   {'✓' if o else '✗'} → {'✓' if n else '✗'}  {label[:70]}")


def main() -> int:
    cfg = config.load()
    cfg.decision_url = os.environ.get("DECISION_URL", cfg.decision_url)
    cfg.decision_key = os.environ.get("DECISION_KEY", cfg.decision_key)
    cfg.decision_model = os.environ.get("DECISION_MODEL", cfg.decision_model)
    d = Counting(cfg)
    if not d.configured():
        print("没配置判断模型：设置 → 判断模型，或者设环境变量 DECISION_URL / DECISION_KEY / DECISION_MODEL")
        return 1
    checks.HOT_S = 10.0  # 测准确率时不按提问路上的时限算（耗时另外看下面的 p50 / p90）
    for name in sys.argv[1:] or ["followup", "stop", "reask", "kind", "difficulty", "lesson"]:
        run(name, d)
    s = sorted(d.seconds)
    print(f"\n{cfg.decision_model}：{len(s)} 次，p50 {statistics.median(s):.2f}s，p90 {s[int(0.9 * len(s))]:.2f}s，"
          f"最慢 {s[-1]:.2f}s，没答上 {d.missed} 次（提问路上的时限是 {HOT_S:g} 秒）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
