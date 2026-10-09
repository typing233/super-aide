"""测试环境：在工作台上跑测试，和基线比。

- 一个很小的虚拟环境（~/.super_aide/evolve/tools/venv），用和运行环境同一个基础 Python：
  00-work.pth 指向工作台的 src（导入的是工作台里的代码），10-env.pth 接上运行环境的 site-packages（依赖不用再装）。
  测试里起的子进程（比如 MCP 服务器）也是这个 Python，同样导入工作台的代码——PYTHONPATH 传不到那些子进程里。
- pytest 锁定版本，--no-deps 装进来；它要的 packaging 用运行环境里的那份。第一次要联网（官方源 → 国内镜像）。
- 隔离（保护你的数据）：插件 aide_isolation 在收集测试之前把用户目录、AppData、临时目录指到沙盒，去掉模型服务的密钥，
  代理指到一个不通的端口。模型自己跑测试（python -m pytest）和流水线检查时都用它。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import sysconfig
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .. import paths

log = logging.getLogger(__name__)

#: pytest 和它的依赖（按 uv.lock 锁定）；packaging 用运行环境里的那份。运行环境里没有 pygments（实测：漏了它 pytest 导入不了）
PYTEST = ("pytest==9.1.1", "pluggy==1.6.0", "iniconfig==2.3.1", "colorama==0.4.6", "pygments==2.21.0")
INDEXES = ("", "https://mirrors.aliyun.com/pypi/simple", "https://pypi.tuna.tsinghua.edu.cn/simple")
TEST_TIMEOUT = 30 * 60
NO_WINDOW = 0x08000000

ISOLATION = '''"""超级助手自我改进的测试隔离：用户目录、AppData、临时目录指到沙盒，去掉模型服务的密钥，代理指到不通的端口。"""
import os
import tempfile

root = os.environ.get("AIDE_SANDBOX") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "aide-sandbox")
for name, sub in (("USERPROFILE", "home"), ("HOME", "home"), ("APPDATA", "appdata"),
                  ("LOCALAPPDATA", "localappdata"), ("TEMP", "temp"), ("TMP", "temp")):
    path = os.path.join(root, sub)
    os.makedirs(path, exist_ok=True)
    os.environ[name] = path
for name in list(os.environ):
    if name.startswith(("ANTHROPIC_", "OPENAI_", "CLAUDE_CODE_", "DEEPSEEK_", "SUPER_AIDE_CODEX_")):
        del os.environ[name]
for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ[name] = "http://127.0.0.1:9"
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
tempfile.tempdir = None
'''

IMPORT_CHECK = r'''
import importlib, pkgutil, sys, traceback
import super_aide
bad = []
for info in pkgutil.walk_packages(super_aide.__path__, "super_aide."):
    if info.name.endswith(".__main__") or "._source" in info.name:
        continue
    try:
        importlib.import_module(info.name)
    except BaseException as e:  # noqa: BLE001
        bad.append(f"{info.name}: {type(e).__name__}: {e}")
print("\n".join(bad))
sys.exit(1 if bad else 0)
'''


@dataclass
class TestRun:
    __test__ = False  # 不是 pytest 的测试类

    passed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    output: str = ""          # 最后一段输出（交给模型看）
    crashed: str = ""         # 没跑起来的原因（收集测试就出错、超时）

    @property
    def all(self) -> set[str]:
        return self.passed | self.failed | self.skipped

    def as_dict(self) -> dict:
        return {"passed": sorted(self.passed), "failed": sorted(self.failed), "skipped": sorted(self.skipped)}

    @classmethod
    def from_dict(cls, data: dict) -> TestRun:
        return cls(set(data.get("passed", [])), set(data.get("failed", [])), set(data.get("skipped", [])))


def base_python() -> Path:
    """运行环境背后的基础 Python（uv 管理的 CPython）。"""
    return Path(getattr(sys, "_base_executable", "") or sys.executable)


def env_site() -> Path:
    """运行环境的 site-packages。"""
    return Path(sysconfig.get_paths()["purelib"])


def find_uv() -> tuple[str, dict[str, str]]:
    """uv 在哪（安装器自带的、PATH 上的、默认位置），以及用它时要带的环境变量（安装器那份用自己的缓存）。"""
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    private = local / "Programs" / "Super Aide" / "uv.exe"
    if private.exists():
        return str(private), {"UV_CACHE_DIR": str(private.parent / "cache")}
    found = shutil.which("uv")
    if found:
        return found, {}
    for candidate in (Path.home() / ".local" / "bin" / "uv.exe", Path.home() / ".cargo" / "bin" / "uv.exe"):
        if candidate.exists():
            return str(candidate), {}
    return "", {}


def _run(cmd: list[str], cwd: Path | None = None, env: dict | None = None, timeout: float = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=NO_WINDOW)


class TestEnv:
    __test__ = False  # 不是 pytest 的测试类

    def __init__(self, work: Path, root: Path | None = None) -> None:
        self.work = work
        self.root = root or paths.EVOLVE / "tools" / "venv"
        self.sandbox = self.root.parent / "sandbox"

    @property
    def python(self) -> Path:
        return self.root / "Scripts" / "python.exe"

    @property
    def scripts(self) -> Path:
        return self.root / "Scripts"

    def _site(self) -> Path:
        return self.root / "Lib" / "site-packages"

    def ready(self) -> bool:
        """测试环境能用：pytest 真的导入得了（光看文件夹在不在不够，缺依赖时一样导入不了）。"""
        if not self.python.exists():
            return False
        try:
            return _run([str(self.python), "-c", "import pytest"], env=self.env(), timeout=60).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def ensure(self) -> None:
        """建好（或修好）测试环境。装 pytest 要联网：都失败时抛出最后的原因。"""
        uv, uv_env = find_uv()
        env = {**os.environ, **uv_env, "UV_HTTP_TIMEOUT": "60"}
        if not self.python.exists():
            if uv:
                _run([uv, "venv", "--python", str(base_python()), "--no-project", str(self.root)], env=env)
            if not self.python.exists():
                _run([str(base_python()), "-m", "venv", "--without-pip", str(self.root)])
            if not self.python.exists():
                raise RuntimeError("没能建测试环境")
        site = self._site()
        (site / "00-work.pth").write_text(str(self.work / "src") + "\n", encoding="utf-8")
        (site / "10-env.pth").write_text(f"import site; site.addsitedir({str(env_site())!r})\n", encoding="utf-8")
        (site / "aide_isolation.py").write_text(ISOLATION, encoding="utf-8")
        if self.ready():
            return
        last = ""
        for index in INDEXES:
            if uv:
                cmd = [uv, "pip", "install", "--python", str(self.python), "--no-deps", *PYTEST]
                if index:
                    cmd += ["--default-index", index]
            else:
                cmd = [str(base_python()), "-m", "pip", "install", "--target", str(site), "--no-deps", *PYTEST]
                if index:
                    cmd += ["-i", index]
            result = _run(cmd, env=env)
            if result.returncode == 0 and self.ready():
                return
            last = (result.stderr or result.stdout).strip().splitlines()[-1:] or [""]
            last = last[0]
        raise RuntimeError(f"装测试工具 pytest 失败：{last}")

    def env(self) -> dict[str, str]:
        """跑测试、跑代码时的环境变量（模型的会话也用这一份）。"""
        env = dict(os.environ)
        env.update(AIDE_SANDBOX=str(self.sandbox), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                   PYTEST_ADDOPTS="-p aide_isolation -p no:cacheprovider")
        env["PATH"] = str(self.scripts) + os.pathsep + env.get("PATH", "")
        for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            env.pop(name, None)
        return env

    def run(self, select: list[str] | None = None, timeout: float = TEST_TIMEOUT) -> TestRun:
        """跑测试（select 为空就跑全部），按 junit 结果分出通过、失败、跳过。"""
        if not (self.work / "tests").is_dir():
            return TestRun()
        report = self.sandbox / "junit.xml"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.unlink(missing_ok=True)
        cmd = [str(self.python), "-m", "pytest", "-q", "-o", "junit_family=xunit1", f"--junitxml={report}",
               *(select or ["tests"])]
        try:
            result = _run(cmd, cwd=self.work, env=self.env(), timeout=timeout)
        except subprocess.TimeoutExpired:
            return TestRun(crashed=f"测试跑了 {timeout // 60:.0f} 分钟还没完")
        output = (result.stdout + result.stderr)[-6000:]
        run = parse_junit(report) if report.exists() else TestRun()
        run.output = output
        if not run.all and result.returncode not in (0, 5):
            run.crashed = output[-1500:] or f"pytest 退出码 {result.returncode}"
        return run

    def import_check(self) -> list[str]:
        result = _run([str(self.python), "-c", IMPORT_CHECK], cwd=self.work, env=self.env(), timeout=300)
        return [line for line in result.stdout.splitlines() if line.strip()] if result.returncode else []

    def node_check(self, files: list[str]) -> list[str]:
        node = shutil.which("node")
        if not node:
            return []
        bad = []
        for rel in files:
            if rel.endswith(".js") and ".min." not in rel and (self.work / rel).exists():
                result = _run([node, "--check", str(self.work / rel)], timeout=60)
                if result.returncode:
                    bad.append(f"{rel}: {(result.stderr or result.stdout).strip()[-400:]}")
        return bad


def parse_junit(path: Path) -> TestRun:
    run = TestRun()
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return run
    for case in tree.iter("testcase"):
        node = _node_id(case.get("file", ""), case.get("classname", ""), case.get("name", ""))
        tags = {child.tag for child in case}
        if tags & {"failure", "error"}:
            run.failed.add(node)
        elif "skipped" in tags:
            run.skipped.add(node)
        else:
            run.passed.add(node)
    return run


def _node_id(file: str, classname: str, name: str) -> str:
    file = file.replace("\\", "/")
    module = file[:-3].replace("/", ".") if file.endswith(".py") else ""
    rest = classname[len(module) + 1:] if module and classname.startswith(module + ".") else ""
    return "::".join(x for x in (file or classname, rest, name) if x)


def compare(baseline: TestRun, now: TestRun) -> list[str]:
    """和基线比：基线通过的测试必须还在、还通过；新加的测试必须通过。返回问题（空 = 通过）。"""
    problems = []
    if now.crashed:
        return [f"测试没跑起来：{now.crashed}"]
    missing = sorted(baseline.passed - now.all)
    if missing:
        problems.append("这些原本通过的测试不见了（不要删测试或改名绕过）：" + "、".join(missing[:20]))
    regressed = sorted(baseline.passed & (now.failed | now.skipped))
    if regressed:
        problems.append("这些原本通过的测试现在失败或被跳过了：" + "、".join(regressed[:20]))
    fresh = sorted(now.failed - baseline.all)
    if fresh:
        problems.append("新加的测试没通过：" + "、".join(fresh[:20]))
    return problems
