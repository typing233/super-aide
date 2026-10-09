"""工作台：自我改进在这里改代码（~/.super_aide/evolve/work）。

工作台总是由"正在运行的版本"生成，不需要 git，也不需要联网：
- 已安装的 super_aide/ 放到 src/super_aide/；
- 源码包（wheel 里的 super_aide/_source/：pyproject、README、LICENSE、设计文档、测试）放到根目录；
- 老版本（0.1.2 及以前）没有源码包：下载同版本的 sdist（PyPI → 镜像 → GitHub Release），再用已安装的文件覆盖；
  开发时（可编辑安装）直接取仓库里的这些文件；都拿不到时只有代码，没有测试（只做导入检查）。
用已安装文件的指纹（RECORD 的哈希）判断工作台是不是最新的：装了新版本（官方更新、撤销、回滚）就重新生成。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import shutil
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from .. import __version__, paths, update
from . import patching, wheelfile

log = logging.getLogger(__name__)

KIT = "_source"
KIT_FILES = ("pyproject.toml", "README.md", "README.zh-CN.md", "LICENSE", "docs/design.md")
KIT_DIRS = ("tests",)
META = ".aide.json"
SDIST_INDEXES = ("https://mirrors.aliyun.com/pypi/simple", "https://pypi.tuna.tsinghua.edu.cn/simple")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".aide-tmp", ".pytest_cache")


@dataclass
class Installed:
    """正在运行的这一份超级助手。"""

    version: str
    pkg: Path                 # super_aide 包目录
    dist_info: Path | None    # super_aide-x.dist-info
    site: Path | None         # site-packages（换包时用）
    editable: bool            # 开发时的可编辑安装（包目录就是仓库里的 src/super_aide）
    fingerprint: str

    @property
    def repo(self) -> Path | None:
        """可编辑安装时，仓库的根目录。"""
        root = self.pkg.parent.parent
        return root if self.editable and (root / "pyproject.toml").exists() else None

    @classmethod
    def current(cls) -> Installed:
        pkg = Path(__file__).resolve().parent.parent
        try:
            dist = metadata.distribution("super-aide")
        except metadata.PackageNotFoundError:
            return cls(__version__, pkg, None, None, True, _tree_hash(pkg))
        info = getattr(dist, "_path", None)
        info = Path(info) if info else None
        editable = False
        try:
            direct = json.loads(dist.read_text("direct_url.json") or "{}")
            editable = bool(direct.get("dir_info", {}).get("editable"))
        except ValueError:
            pass
        record = dist.read_text("RECORD") or ""
        fp = _tree_hash(pkg) if editable or not record else hashlib.sha256(record.encode("utf-8")).hexdigest()[:16]
        site = info.parent if info else None
        return cls(dist.version, pkg, info, site, editable, fp)


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for rel, path in sorted(patching.files(root).items()):
        h.update(rel.encode("utf-8"))
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


class Workshop:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or paths.EVOLVE / "work"

    @property
    def src(self) -> Path:
        return self.root / "src" / "super_aide"

    def meta(self) -> dict:
        try:
            return json.loads((self.root / META).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def fresh(self, installed: Installed) -> bool:
        return self.src.exists() and self.meta().get("fp") == installed.fingerprint

    def has_tests(self) -> bool:
        return (self.root / "tests").is_dir() and (self.root / "pyproject.toml").exists()

    def ensure(self, installed: Installed, owner: str = "") -> str:
        """工作台和正在运行的版本一致、也没有被别的任务改过，就不动；否则重新生成。
        返回源码包从哪来：kit / repo / sdist / none。owner：接下来由哪个任务改它。"""
        dirty = self.meta().get("dirty", "")
        if self.fresh(installed) and dirty in ("", owner):
            self.mark(owner)
            return self.meta().get("source", "")
        tmp = self.root.with_name(self.root.name + ".new")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(installed.pkg, tmp / "src" / "super_aide", ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", KIT))
        source = self._kit(installed, tmp)
        (tmp / META).write_text(json.dumps({"fp": installed.fingerprint, "version": installed.version,
                                            "source": source, "built": time.time(), "dirty": owner}),
                                encoding="utf-8")
        shutil.rmtree(self.root, ignore_errors=True)
        tmp.replace(self.root)
        log.info("工作台已按 %s（%s）重新生成，源码包来自 %s", installed.version, installed.fingerprint, source)
        return source

    def _kit(self, installed: Installed, dest: Path) -> str:
        kit = installed.pkg / KIT
        if kit.is_dir():
            shutil.copytree(kit, dest, dirs_exist_ok=True, ignore=IGNORE)
            return "kit"
        if installed.repo is not None:
            _copy_kit(installed.repo, dest)
            return "repo"
        try:
            with tempfile.TemporaryDirectory(prefix="super-aide-sdist-") as tmp:
                root = fetch_sdist(update.base_version(installed.version), Path(tmp))
                _copy_kit(root, dest)
                return "sdist"
        except Exception as e:  # noqa: BLE001 - 拿不到就只有代码，没有测试
            log.warning("没拿到 %s 的源码包：%s", installed.version, e)
            return "none"

    def mark(self, owner: str) -> None:
        """记下工作台正被哪个任务改着（空 = 干净）。别的任务开始时发现它被改过，就重新生成。"""
        meta = self.meta()
        if meta and meta.get("dirty", "") != owner:
            meta["dirty"] = owner
            (self.root / META).write_text(json.dumps(meta), encoding="utf-8")

    def snapshot(self, dest: Path) -> None:
        """任务开始时的基准（diff、补丁、续上都靠它）。"""
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(self.root, dest, ignore=IGNORE)

    def restore(self, base: Path) -> None:
        """回到基准（放弃这次的改动），工作台又是干净的了。"""
        meta = self.meta()
        meta["dirty"] = ""
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.copytree(base, self.root, ignore=IGNORE)
        (self.root / META).write_text(json.dumps(meta), encoding="utf-8")

    def diff(self, base: Path) -> str:
        return patching.diff_trees(base, self.root)

    def kit_entries(self) -> dict[str, Path]:
        """打 wheel 时的源码包：工作台根目录下除了 src 以外的文件 → super_aide/_source/…"""
        out = {}
        for rel, path in patching.files(self.root).items():
            if not rel.startswith("src/"):
                out[f"super_aide/{KIT}/{rel}"] = path
        return out

    def build(self, installed: Installed, version: str, out_dir: Path) -> Path:
        if installed.dist_info is None:
            raise RuntimeError("找不到已安装的元数据（dist-info），没法打包")
        return wheelfile.build(self.src, installed.dist_info, version, out_dir, extra=self.kit_entries())


def restore_point(installed: Installed, out_dir: Path) -> Path:
    """用已安装的文件原样打一个 wheel：第一次生效前留着，回滚、撤销时装回去。"""
    target = out_dir / wheelfile.wheel_name(installed.version)
    if target.exists():
        return target
    if installed.dist_info is None:
        raise RuntimeError("找不到已安装的元数据（dist-info），没法留还原点")
    return wheelfile.build(installed.pkg, installed.dist_info, installed.version, out_dir)


def _copy_kit(root: Path, dest: Path) -> None:
    for name in KIT_FILES:
        if (root / name).is_file():
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, dest / name)
    for name in KIT_DIRS:
        if (root / name).is_dir():
            shutil.copytree(root / name, dest / name, dirs_exist_ok=True, ignore=IGNORE)


# ---------- 老版本：下载同版本的 sdist ----------

def _get(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"super-aide/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _sdist_sources(version: str) -> list[tuple[str, str]]:
    """(下载地址, sha256)：PyPI 的 JSON 接口、国内镜像的索引页（带 sha256），最后是 GitHub Release（不带）。"""
    name = f"super_aide-{version}.tar.gz"
    found: list[tuple[str, str]] = []
    try:
        data = json.loads(_get(f"https://pypi.org/pypi/{update.PACKAGE}/{version}/json", 15))
        found += [(u["url"], u["digests"]["sha256"]) for u in data.get("urls", []) if u.get("packagetype") == "sdist"]
    except Exception as e:  # noqa: BLE001
        log.info("PyPI 上没取到 sdist 信息：%s", e)
    for index in SDIST_INDEXES:
        try:
            page = _get(f"{index}/{update.PACKAGE}/", 15).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        m = re.search(rf'href="([^"]*?{re.escape(name)})#sha256=([0-9a-f]{{64}})"', page)
        if m:
            found.append((urllib.request.urljoin(f"{index}/{update.PACKAGE}/", m.group(1)), m.group(2)))
    repo = update.release_info().get("repo") or "typing233/super-aide"
    found.append((f"https://github.com/{repo}/releases/download/v{version}/{name}", ""))
    return found


def fetch_sdist(version: str, dest: Path) -> Path:
    """下载并解开同版本的 sdist，返回解开后的根目录。"""
    errors = []
    for url, sha in _sdist_sources(version):
        try:
            data = _get(url, 60)
            if sha and hashlib.sha256(data).hexdigest() != sha:
                raise ValueError("校验不通过")
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                tar.extractall(dest, filter="data")
            roots = [p for p in dest.iterdir() if p.is_dir()]
            if len(roots) == 1 and (roots[0] / "pyproject.toml").exists():
                return roots[0]
            raise ValueError("包里的结构不对")
        except Exception as e:  # noqa: BLE001 - 换下一个源
            errors.append(f"{url}: {e}")
    raise RuntimeError("; ".join(errors[-3:]) or "没有可用的下载源")
