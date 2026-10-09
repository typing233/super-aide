"""本地向量模型：意思相近、字面不同的情况也能想起来（比如"下载依赖一直卡住"和"pip 装包超时"）。

完全离线运行（onnxruntime，不要显卡）。模型第一次需要时在后台下载到 ~/.super_aide/models/，
下载好之前照样按字面想起，不耽误使用。下载走系统代理，huggingface.co 不通时换 hf-mirror.com。
multilingual-e5 的分词用 sentencepiece，不用 tokenizers：词表一样、编号一样（实测），
tokenizers 把它 25 万词的 tokenizer.json 读进来要 262MB 内存，sentencepiece 只要 48MB。
"""

from __future__ import annotations

import logging
import os
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .. import paths

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Spec:
    files: dict[str, str]  # 本地文件名 → 仓库/路径
    pooling: str  # mean：所有词向量取平均；cls：取第一个
    tokenizer: str  # xlmr-spm：sentencepiece + XLM-R 的编号规则；hf：tokenizers 读 tokenizer.json
    query: str = ""  # 查询前面要加的话（有的模型这样训练的）
    passage: str = ""


MODELS = {
    "multilingual-e5-small": Spec({"model.onnx": "Xenova/multilingual-e5-small/onnx/model_int8.onnx",
                                   "sentencepiece.bpe.model": "intfloat/multilingual-e5-small/sentencepiece.bpe.model"},
                                  "mean", "xlmr-spm", "query: ", "passage: "),
    "multilingual-e5-base": Spec({"model.onnx": "Xenova/multilingual-e5-base/onnx/model_int8.onnx",
                                  "sentencepiece.bpe.model": "intfloat/multilingual-e5-base/sentencepiece.bpe.model"},
                                 "mean", "xlmr-spm", "query: ", "passage: "),
    "bge-small-zh-v1.5": Spec({"model.onnx": "Xenova/bge-small-zh-v1.5/onnx/model.onnx",
                               "tokenizer.json": "Xenova/bge-small-zh-v1.5/tokenizer.json"},
                              "cls", "hf", "为这个句子生成表示以用于检索相关文章：", ""),
}
DEFAULT = "multilingual-e5-small"
MIRRORS = ("https://huggingface.co", "https://hf-mirror.com")
MAX_TOKENS = 256


class Embedder:
    def __init__(self, name: str = DEFAULT, root: Path | None = None) -> None:
        self.name = name
        self.spec = MODELS[name]
        self.dir = (root or paths.HOME / "models") / name
        self._session = None
        self._tokenizer = None
        self._inputs: list[str] = []
        self._lock = threading.Lock()
        self._downloading = False
        self.failed = ""  # 下载或加载失败的原因（只记一次，不反复重试）

    # ---- 准备 ----

    def _files(self) -> dict[str, Path]:
        """仓库/路径 → 本地文件。"""
        return {remote: self.dir / local for local, remote in self.spec.files.items()}

    def downloaded(self) -> bool:
        return all(p.exists() for p in self._files().values())

    def ensure(self, wait: bool = False) -> None:
        """模型不在就去下载（默认在后台，不等）。"""
        if self.downloaded() or self._downloading or self.failed:
            return
        self._downloading = True
        thread = threading.Thread(target=self._download, name=f"download-{self.name}", daemon=True)
        thread.start()
        if wait:
            thread.join()

    def _download(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            for remote, local in self._files().items():
                if local.exists():
                    continue
                owner, name, path = remote.split("/", 2)
                for base in MIRRORS:
                    try:
                        t = time.perf_counter()
                        _fetch(f"{base}/{owner}/{name}/resolve/main/{path}", local)
                        log.info("下载了 %s/%s（%.1f MB，%.0f 秒）", self.name, remote,
                                 local.stat().st_size / 1e6, time.perf_counter() - t)
                        break
                    except Exception as e:  # noqa: BLE001 - 换一个地址再试
                        log.warning("从 %s 下载 %s 失败：%s", base, remote, e)
                else:
                    self.failed = f"下载 {remote} 失败"
                    return
        finally:
            self._downloading = False
        self._load()

    def _load(self) -> bool:
        if self._session is not None:
            return True
        if self.failed or not self.downloaded():
            return False
        with self._lock:
            if self._session is None:
                try:
                    import onnxruntime as ort

                    options = ort.SessionOptions()
                    options.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) // 2))
                    options.log_severity_level = 3
                    self._session = ort.InferenceSession(str(self.dir / "model.onnx"), options,
                                                         providers=["CPUExecutionProvider"])
                    self._inputs = [i.name for i in self._session.get_inputs()]
                    if self.spec.tokenizer == "xlmr-spm":
                        import sentencepiece

                        self._tokenizer = sentencepiece.SentencePieceProcessor(
                            model_file=str(self.dir / "sentencepiece.bpe.model"))
                    else:
                        from tokenizers import Tokenizer

                        tokenizer = Tokenizer.from_file(str(self.dir / "tokenizer.json"))
                        tokenizer.enable_truncation(MAX_TOKENS)
                        tokenizer.enable_padding()
                        self._tokenizer = tokenizer
                    log.info("向量模型已加载（%s）", self.name)
                except Exception as e:  # noqa: BLE001 - 没装好或者文件坏了：只是少了这项能力
                    self.failed = f"加载失败：{e}"
                    log.warning("向量模型 %s 加载失败：%s", self.name, e)
                    return False
        return True

    def ready(self) -> bool:
        return self._load()

    def loaded(self) -> bool:
        """已经加载好了（不会触发加载，不会卡住）。"""
        return self._session is not None

    # ---- 用 ----

    def encode(self, texts: list[str], kind: str = "passage"):
        """→ 每行一个单位长度的向量（numpy 数组）；模型还没好时返回 None。kind：query 或 passage。"""
        if not texts or not self._load():
            return None
        import numpy as np

        prefix = self.spec.query if kind == "query" else self.spec.passage
        ids, mask = self._tokenize([prefix + " ".join(t.split()) for t in texts])
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, {k: v for k, v in feed.items() if k in self._inputs})[0]
        if self.spec.pooling == "cls":
            vectors = hidden[:, 0]
        else:
            weights = mask[..., None].astype(hidden.dtype)
            vectors = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        return vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9, None)


    def _tokenize(self, texts: list[str]):
        import numpy as np

        if self.spec.tokenizer != "xlmr-spm":
            batch = self._tokenizer.encode_batch(texts)
            return (np.array([b.ids for b in batch], dtype=np.int64),
                    np.array([b.attention_mask for b in batch], dtype=np.int64))
        # XLM-R 的编号：sentencepiece 的编号 +1（fairseq 的偏移），未知词 3；前后加 <s>=0、</s>=2；补齐用 <pad>=1
        rows = [[0] + [i + 1 if i else 3 for i in self._tokenizer.encode(t, out_type=int)[:MAX_TOKENS - 2]] + [2]
                for t in texts]
        width = max(map(len, rows))
        ids = np.ones((len(rows), width), dtype=np.int64)
        mask = np.zeros((len(rows), width), dtype=np.int64)
        for r, row in enumerate(rows):
            ids[r, :len(row)] = row
            mask[r, :len(row)] = 1
        return ids, mask


def _fetch(url: str, target: Path) -> None:
    """下载到临时文件，完整了再改名（下到一半断了不会留下坏文件）。走系统代理。"""
    tmp = target.with_name(target.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "super-aide"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        with open(tmp, "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
    if total and tmp.stat().st_size != total:
        tmp.unlink(missing_ok=True)
        raise OSError(f"文件不完整（{tmp.stat().st_size}/{total}）")
    os.replace(tmp, target)
