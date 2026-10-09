"""挑本地向量模型：意思相近、字面几乎不同的问题能不能对上那条经验，不相干的问题会不会被误认。

每条经验用"标题 + 适用情况 + 提示词"做向量；问题分两种：换了说法的（应该对上）、不相干的（应该对不上）。
看每个模型能不能用一个门槛把两种分开，以及速度。模型下载到临时目录。

    uv run --no-sync python -X utf8 spikes/p8_embed_bench.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from super_aide.experience.embed import MODELS, Embedder

LESSONS = {
    "pip": "pip 装包超时先查代理。pip install 一直超时、ProxyError、SSLError、Read timed out。代理 镜像源 清华源",
    "typo": "No module named 先核对模块名拼写。报 ModuleNotFoundError，或者后面的单元格报 NameError 变量未定义，模块名和常见包名只差一两个字母",
    "excel": "Excel 自动化先关掉受保护的视图。用脚本改 Excel 文件时报 0x800A03EC，或者文件处于受保护的视图",
    "oom": "Notebook 内核挂掉先看显存内存。训练时 Kernel died、CUDA out of memory，减小 batch size、清理显存",
    "ps1": "PowerShell 禁止运行脚本时改执行策略。运行 .ps1 报在此系统上禁止运行脚本、execution policy",
    "git": "git push 被拒绝先拉取再推。rejected non-fast-forward，远程有新提交，先 git pull --rebase",
    "port": "端口被占用先查是哪个进程。Address already in use、端口被占用，用 netstat 找到进程再决定",
    "mojibake": "中文乱码先确认文件编码。打开文件中文显示成问号或乱码，编码不是 UTF-8，GBK",
}
POSITIVE = [
    ("pip", "下载依赖包的时候一直卡在 Collecting，最后提示连接失败"),
    ("pip", "安装 torch 半天装不上，老是 Read timed out"),
    ("typo", "导入的时候说没有这个库，可是我明明装过了"),
    ("excel", "用脚本改表格文件时报错说文档是只读的，上面有一条黄色提示条"),
    ("oom", "训练到一半笔记本的内核就重启了，显卡好像撑不住"),
    ("ps1", "双击 ps1 文件没反应，提示不能运行脚本"),
    ("git", "推送代码时被拒绝了，说 updates were rejected because the remote contains work"),
    ("port", "启动服务报错说 8080 已经被别的程序用了"),
    ("mojibake", "打开 csv 文件里面的汉字全是问号"),
]
NEGATIVE = ["你好", "今天天气怎么样", "帮我把这段话翻译成英文", "写一封请假邮件", "这张图片里是什么", "怎么截图",
            "Excel 怎么求和", "python 怎么读取文件", "git 怎么创建分支", "端口是什么意思", "帮我总结一下这个网页",
            "这个函数是干什么的", "pip 是什么", "显卡型号怎么看", "怎么新建一个 Notebook", "PowerShell 怎么打开",
            "这段英文报错是什么意思", "帮我把代码格式化一下"]
#: 很泛的请求：问题和它们比和经验还像，就不算"碰到了相似的情况"
BACKGROUND = ["你好", "谢谢", "帮我翻译这段话", "帮我写一段文字", "这是什么意思", "解释一下这个", "这个怎么用",
              "帮我总结一下", "这是什么", "怎么操作", "介绍一下"]


def main() -> int:
    root = Path(tempfile.gettempdir()) / "aide-models"  # 下过一次就留着，反复跑不用再下
    names = ["multilingual-e5-small", "multilingual-e5-base"]
    keys = list(LESSONS)
    rows = []
    for name in names:
        emb = Embedder(name, root)
        emb.ensure(wait=True)
        if not emb.ready():
            print(f"{name}: 用不了（{emb.failed}）")
            continue
        lessons = emb.encode([LESSONS[k] for k in keys], "passage")
        back = emb.encode(BACKGROUND, "query")
        t = time.perf_counter()
        pos = emb.encode([q for _, q in POSITIVE], "query")
        neg = emb.encode(NEGATIVE, "query")
        per_query = (time.perf_counter() - t) / (len(POSITIVE) + len(NEGATIVE)) * 1000

        def features(q, sims):
            top = int(np.argmax(sims))
            others = np.delete(sims, top)
            return keys[top], sims[top], sims[top] - np.median(others), sims[top] - float((q @ back.T).max())

        P = [(want,) + features(q, s) for (want, _), q, s in zip(POSITIVE, pos, pos @ lessons.T)]
        N = [features(q, s) for q, s in zip(neg, neg @ lessons.T)]
        print(f"\n== {name}  （每句 {per_query:.0f}ms）")
        print("  换说法的：对上 / 相似度 / 比其它经验高 / 比泛泛的请求高")
        for (want, got, sim, med, bg), (_, q) in zip(P, POSITIVE):
            print(f"  {'✓' if got == want else '✗'} {sim:.3f} {med:+.3f} {bg:+.3f}  {q[:28]}")
        print("  不相干的：")
        for (got, sim, med, bg), q in zip(N, NEGATIVE):
            print(f"    {sim:.3f} {med:+.3f} {bg:+.3f}  {got:<8} {q}")
        for label, idx in (("相似度", 1), ("比其它经验高", 2), ("比泛泛的请求高", 3)):
            lo = min(p[idx + 1] for p in P if p[1] == p[0])
            hi = max(n[idx] for n in N)
            rows.append((name, label, lo, hi, lo - hi))
    print(f"\n{'模型':<24} {'判据':<10} {'换说法最低':>8} {'不相干最高':>8} {'间隔':>7}")
    for name, label, lo, hi, gap in rows:
        print(f"{name:<24} {label:<10} {lo:8.3f} {hi:8.3f} {gap:7.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
