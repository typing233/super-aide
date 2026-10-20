"""按意思想起：换了说法的能对上，同话题但不是碰到问题的不放行；向量存起来重启不用重算。模型用假的。"""

from __future__ import annotations

import numpy as np
import pytest

from super_aide.config import Config
from super_aide.decision import Decider
from super_aide.experience import recall, semantic, store
from super_aide.experience.recall import Situation

# 假的向量空间：[pip 话题, 拼写话题, 碰到问题, 泛泛的请求]
AXES = {"pip": 0, "依赖": 0, "拼写": 1, "模块": 1}


class FakeEmbedder:
    name = "fake"

    def __init__(self):
        self.passages = 0

    def ready(self):
        return True

    def encode(self, texts, kind="passage"):
        if kind == "passage":
            self.passages += len(texts)
        out = []
        for t in texts:
            v = np.zeros(4)
            if t in semantic.PROBLEM:
                v[2] = 1
            elif t in semantic.INFO:
                v[3] = 1
            else:
                for word, axis in AXES.items():
                    if word in t:
                        v[axis] = 1
                if any(w in t for w in ("失败", "卡住", "超时", "报错")):
                    v[2] = 0.3
                if any(w in t for w in ("是什么", "怎么用")):
                    v[3] = 0.3
            out.append(v / (np.linalg.norm(v) or 1))
        return np.array(out)


@pytest.fixture
def lib(tmp_path):
    s = store.Store(tmp_path / "lessons.json")
    s.add("pip 装包超时先查代理", "pip install 一直超时", "先查代理", triggers=["ProxyError", "清华源"])
    s.add("模块名先核对拼写", "ModuleNotFoundError", "核对拼写", triggers=["No module named", "拼写错误"])
    return s


def sem(lib, embedder=None):
    return semantic.Semantic(embedder or FakeEmbedder(), lib.path.with_name("vectors.json"))


def test_paraphrase_without_shared_words_is_recalled(lib):
    s = Situation(question="下载依赖一直卡住，最后连接失败")
    assert recall.recall(lib, s) == []  # 字面对不上
    assert [x.title for x in recall.recall(lib, s, semantic=sem(lib))] == ["pip 装包超时先查代理"]


def test_same_topic_but_not_a_problem_is_not_recalled(lib):
    assert recall.recall(lib, Situation(question="pip 是什么"), semantic=sem(lib)) == []
    assert recall.recall(lib, Situation(question="你好"), semantic=sem(lib)) == []


def test_meaning_only_adds_one_and_ranks_after_literal_matches(lib):
    lib.add("清华源配置", "pip 换源", "改 pip.ini", triggers=["清华源", "pip.ini"])
    s = Situation(question="依赖装不上一直超时，清华源和 ProxyError 都试过了")
    titles = [x.title for x in recall.recall(lib, s, semantic=sem(lib))]
    assert titles[0] == "pip 装包超时先查代理" and len(titles) <= recall.MAX_RECALL


def test_vectors_are_cached_and_reused(lib):
    first = FakeEmbedder()
    sem(lib, first).best(lib.all(), "依赖装不上，超时失败")
    assert first.passages == 2 and lib.path.with_name("vectors.json").exists()
    again = FakeEmbedder()
    sem(lib, again).best(lib.all(), "依赖装不上，超时失败")
    assert again.passages == 0  # 重启后直接用存下的向量
    lesson = lib.all()[0]
    lib.update(lesson.id, when="pip 下载依赖总是超时")
    third = FakeEmbedder()
    sem(lib, third).best(lib.all(), "依赖装不上，超时失败")
    assert third.passages == 1  # 只重算改过的那一条


def test_switching_models_recomputes(lib):
    sem(lib).best(lib.all(), "依赖装不上，超时失败")
    other = FakeEmbedder()
    other.name = "another-model"
    sem(lib, other).best(lib.all(), "依赖装不上，超时失败")
    assert other.passages == 2


def test_gist_keeps_question_and_errors_only():
    s = Situation(question="为什么", text="import torch\n" * 50 + "ModuleNotFoundError: No module named 'torch'")
    assert s.gist() == "为什么\nModuleNotFoundError: No module named 'torch'"


def test_idle_embedder_is_unloaded_and_reloaded_on_summon(monkeypatch, tmp_path):
    """向量模型占常驻内存的三成左右：闲了 10 分钟卸掉，召唤时在后台重新加载。"""
    import time as _time
    from types import SimpleNamespace

    from super_aide.engines import hub as hub_module
    from super_aide.engines.hub import EngineHub
    from super_aide.experience.embed import Embedder

    emb = Embedder(root=tmp_path)
    assert not emb.unload()                       # 没加载：没什么可卸的
    emb._session, emb._tokenizer = object(), object()
    with emb._lock:                               # 正在加载（别的线程拿着锁）：不等它
        assert not emb.unload()
    assert emb.unload() and not emb.loaded()

    loads = []
    semantic = SimpleNamespace(embedder=emb, ready=lambda: loads.append(1))
    hub = SimpleNamespace(semantic=semantic, conversations={}, _embed_used=0.0, decider=Decider(Config()))
    monkeypatch.setattr(emb, "downloaded", lambda: True)
    EngineHub.prewarm(hub)                        # 召唤了：在后台加载
    for _ in range(50):
        if loads:
            break
        _time.sleep(0.01)
    assert loads == [1] and _time.time() - hub._embed_used < 5

    emb._session, emb._tokenizer = object(), object()
    EngineHub.unload_idle(hub)                    # 刚用过：不卸
    assert emb.loaded()
    hub._embed_used = _time.time() - hub_module.EMBED_IDLE_S - 1
    hub.conversations = {"k": SimpleNamespace(busy=True)}
    EngineHub.unload_idle(hub)                    # 正在答：不卸
    assert emb.loaded()
    hub.conversations = {}
    EngineHub.unload_idle(hub)
    assert not emb.loaded()
