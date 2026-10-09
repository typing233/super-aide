"""经验的端到端自检（会真的调用模型，约 3 次，写临时目录，不碰真实的经验库）：

1. 一次走了弯路的对话（像 ModelScope 那次：把拼错的 modescope 当成缺包去装，被用户纠正）→ 总结出一条经验；
2. 换一个拼错的包名（transfomers）再遇到 → 想起这条经验；问"你好"、问不相干的 → 一条也不带；
3. 又一次相似的对话 → 更新那条经验，不重复加；
4. 可选 --codex：没有 Claude 时用 Codex 总结也能用。

    uv run --no-sync python -X utf8 spikes/p6_experience_check.py [--codex]
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

from super_aide import config
from super_aide.engines.claude import complete as claude_complete
from super_aide.experience import learn, recall, store
from super_aide.experience.recall import Situation

NOTEBOOK = ("# 导入模型和分词器\nfrom modescope import AutoModelForCausalLM, AutoTokenizer\n"
            "ModuleNotFoundError: No module named 'modescope'\ntokenizer\n"
            "NameError: name 'tokenizer' is not defined")
DETOUR = [
    {"question": "为什么运行tokenizer报错", "ok": True, "seconds": 260, "tools": 16,
     "situation": {"text": NOTEBOOK, "app": "msedge.exe", "title": "代码工作区 · 魔搭社区",
                   "url": "https://www.modelscope.cn/my/mynotebook/authorization"},
     "trace": ["正在看 代码工作区 · 魔搭社区…", "正在运行 pip show modelscope", "正在点击 [12] 新建单元格",
               "正在输入 %pip install modelscope", "正在点击 [15] 运行", "正在等待 Successfully installed",
               "正在点击 [3] 重启内核", "正在看 代码工作区 · 魔搭社区…"],
     "answer": "tokenizer 没定义是因为第一个单元格导入失败：环境里没有 modelscope 包。我已经帮你装好了 modelscope 并重启了内核，"
               "重新从第一个单元格开始运行即可。"},
    {"question": "不对，还是报错。你看清楚，代码里写的是 modescope，拼错了", "ok": True, "seconds": 25, "tools": 1,
     "situation": {"text": NOTEBOOK, "app": "msedge.exe", "url": "https://www.modelscope.cn/my/mynotebook/authorization"},
     "trace": ["正在读 代码工作区 · 魔搭社区 的文字"],
     "answer": "你说得对，是拼写错误：modescope 应为 modelscope。把第一个单元格里的 from modescope 改成 from modelscope，"
               "重新运行这一格，后面的 tokenizer 就有定义了。"},
]
SIMILAR_AGAIN = [
    {"question": "这个 import 报错怎么回事", "ok": True, "seconds": 200, "tools": 14,
     "situation": {"text": "from transfomers import AutoModel\nModuleNotFoundError: No module named 'transfomers'",
                   "app": "Code.exe", "title": "train.ipynb - Visual Studio Code"},
     "trace": ["正在运行 pip install transfomers", "正在运行 pip install transformers"],
     "answer": "装了 transformers 之后还是不行，原来代码里把 transformers 拼成了 transfomers。改正拼写后可以导入。"},
]
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


async def main(use_codex: bool) -> int:
    lib = store.Store(Path(tempfile.mkdtemp(prefix="aide-exp-")) / "lessons.json")
    model = config.load().engine("claude").enabled_models()[0].id

    async def llm(prompt: str) -> str:
        return await asyncio.get_running_loop().run_in_executor(None, claude_complete, prompt, model)

    t = time.perf_counter()
    reason = learn.worth_learning(DETOUR, negative=True)
    out = await learn.learn(lib, DETOUR, reason, llm, "说了“不对”", source="p6-1")
    lessons = lib.all()
    check("走了弯路的对话总结出一条经验", len(lessons) == 1, f"{out}（{time.perf_counter() - t:.1f}s）")
    if lessons:
        x = lessons[0]
        print(f"\n标题：{x.title}\n适用：{x.when}\n做法：{x.advice}\n提示词：{x.triggers}\n报错：{x.errors}\n"
              f"程序：{x.apps}\n网站：{x.domains}\n")
        check("经验说的是核对拼写，而不是装包", any(k in x.title + x.advice for k in ("拼写", "拼错", "核对")), x.advice)
        check("报错特征里有 ModuleNotFoundError", any("modulenotfound" in e.lower() for e in x.errors), str(x.errors))

    new_typo = Situation(question="为什么这里报错", text="from transfomers import AutoModel\n"
                         "ModuleNotFoundError: No module named 'transfomers'", app="Code.exe")
    found = recall.recall(lib, new_typo)
    check("换一个拼错的包再遇到：想起来了", bool(found), recall.render(found)[:120])
    check("问你好：一条也不带", recall.recall(lib, Situation(question="你好")) == [])
    unrelated = Situation(question="帮我把这段话翻译成英文", app="msedge.exe", url="https://www.modelscope.cn/models")
    check("同一个网站上问不相干的：一条也不带", recall.recall(lib, unrelated) == [])

    out = await learn.learn(lib, SIMILAR_AGAIN, learn.worth_learning(SIMILAR_AGAIN), llm, source="p6-2")
    check("相似的对话再来一次：更新而不是重复加", len(lib.all()) == 1, out)

    # 按意思想起：字面完全对不上的说法（本地向量模型，模型下载在临时目录，p8 跑过就有）
    from super_aide.experience.embed import Embedder
    from super_aide.experience.semantic import Semantic

    sem = Semantic(Embedder("multilingual-e5-small", Path(tempfile.gettempdir()) / "aide-models"),
                   lib.path.with_name("vectors.json"))
    sem.embedder.ensure(wait=True)
    paraphrase = Situation(question="导入的时候说没有这个库，可是我明明已经装过了")
    t = time.perf_counter()
    literal = recall.recall(lib, paraphrase)
    meant = recall.recall(lib, paraphrase, semantic=sem)
    check("换个说法（字面对不上）：按意思想起来了", not literal and bool(meant),
          f"字面 {len(literal)} 条，按意思 {len(meant)} 条（{(time.perf_counter() - t) * 1000:.0f}ms，含加载模型）")
    t = time.perf_counter()
    topic = recall.recall(lib, Situation(question="python 的模块和包是什么关系"), semantic=sem)
    check("同话题但不是碰到问题：不想起", topic == [], f"{(time.perf_counter() - t) * 1000:.0f}ms")

    if use_codex:
        from super_aide.engines.codex import CodexEngine

        cfg = config.load()
        engine = CodexEngine("", False, "ours")
        codex_model = cfg.engine("codex").enabled_models()[0].id
        lib2 = store.Store(Path(tempfile.mkdtemp(prefix="aide-exp-codex-")) / "lessons.json")
        t = time.perf_counter()
        try:
            out = await learn.learn(lib2, DETOUR, reason, lambda p: engine.complete(p, codex_model, learn.SCHEMA),
                                    "说了“不对”")
            check("没有 Claude 时用 Codex 总结", len(lib2.all()) == 1, f"{out}（{time.perf_counter() - t:.1f}s）")
        finally:
            await engine.close()

    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail[:150]}")
    passed = sum(r[1] for r in results)
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--codex" in sys.argv)))
