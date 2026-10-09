"""自检：生效的小程序（evolve/apply.py）真跑一遍——真的 uv、真的进程、真的健康检查和回滚。

在临时目录里建一个虚拟环境，装一个假的小 super_aide（__main__ 只写健康报告然后待一会儿），不碰你装着的超级助手：
1. 装 v1 并"运行"它；让小程序换成 v2：应该等 v1 退出、换包、启动 v2、收到健康报告 → applied；
2. 再换一个起不来的 v3（__main__ 一启动就抛异常）：应该立刻回滚到 v2 → rolled_back，环境里还是 v2；
3. 换包期间持有 Local\\SuperAideApplying：wait_for_apply 会等它。

    uv run python spikes/p11_apply_check.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from super_aide.evolve import wheelfile  # noqa: E402
from super_aide.evolve.testenv import base_python, find_uv  # noqa: E402

MAIN_OK = '''import json, os, sys, time
nonce = os.environ.get("SUPER_AIDE_APPLY_NONCE", "")
if nonce:
    open(os.environ["AIDE_CHECK_HEALTH"], "w").write(json.dumps({"nonce": nonce, "version": "VERSION"}))
time.sleep(float(os.environ.get("AIDE_CHECK_LIFE", "20")))
'''
MAIN_BROKEN = 'raise SystemExit("v3 起不来")\n'

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(("  通过 " if ok else "  失败 ") + name + (f"：{detail}" if detail else ""))


def make_wheel(tmp: Path, version: str, main: str) -> Path:
    pkg = tmp / f"src-{version}" / "super_aide"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (pkg / "__main__.py").write_text(main.replace("VERSION", version), encoding="utf-8")
    info = tmp / f"info-{version}"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.4\nName: super-aide\nVersion: {version}\n", encoding="utf-8")
    return wheelfile.build(pkg, info, version, tmp / "wheels")


def installed_version(python: Path) -> str:
    out = subprocess.run([str(python), "-c", "import importlib.metadata as m; print(m.version('super-aide'))"],
                         capture_output=True, text=True)
    return out.stdout.strip()


def run_helper(tmp: Path, env_dir: Path, install: Path, fallback: Path, life: str = "20") -> dict:
    uv, uv_env = find_uv()
    scripts = env_dir / "Scripts"
    health = tmp / "health.json"
    health.unlink(missing_ok=True)
    app = subprocess.Popen([str(scripts / "pythonw.exe"), "-m", "super_aide"],
                           env={**dict(__import__("os").environ), "AIDE_CHECK_LIFE": "600",
                                "AIDE_CHECK_HEALTH": str(health)})
    import psutil

    proc = psutil.Process(app.pid)
    plan = {"job": "j", "action": "apply", "wait": [[app.pid, proc.create_time()]], "python": str(scripts / "python.exe"),
            "pythonw": str(scripts / "pythonw.exe"), "site": str(env_dir / "Lib" / "site-packages"), "uv": uv,
            "uv_env": {**uv_env, "AIDE_CHECK_HEALTH": str(health), "AIDE_CHECK_LIFE": life},
            "install": str(install), "fallback": str(fallback), "args": ["--evolved", "j"],
            "fallback_args": ["--evolve-failed", "j"], "home": str(tmp), "health": str(health), "nonce": "n-123",
            "result": str(tmp / "result.json"), "log": str(tmp / "apply.log"), "startup_log": str(tmp / "startup.log"),
            "health_timeout": 30, "settle": 2}
    (tmp / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    shutil.copy2(ROOT / "src" / "super_aide" / "evolve" / "apply.py", tmp / "apply.py")
    (tmp / "result.json").unlink(missing_ok=True)
    import os

    os.environ["AIDE_CHECK_HEALTH"], os.environ["AIDE_CHECK_LIFE"] = str(health), life
    helper = subprocess.Popen([str(base_python()), str(tmp / "apply.py"), str(tmp / "plan.json")])
    time.sleep(1.5)
    from super_aide.evolve import manager  # 换包期间：手动打开会等它（这里只看等不等，最多等 1 秒）

    t0 = time.time()
    manager.wait_for_apply(timeout_s=1)
    check("换包期间手动打开会等一等", time.time() - t0 >= 0.9, f"等了 {time.time() - t0:.1f} 秒")
    app.terminate()  # "超级助手退出了"
    helper.wait(timeout=180)
    return json.loads((tmp / "result.json").read_text(encoding="utf-8"))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="aide-apply-check-"))
    print(f"临时目录：{tmp}")
    uv, uv_env = find_uv()
    if not uv:
        print("没找到 uv")
        return 1
    env_dir = tmp / "env"
    subprocess.run([uv, "venv", "--python", str(base_python()), "--no-project", str(env_dir)], check=True,
                   capture_output=True)
    v1, v2, v3 = (make_wheel(tmp, "0.2.0", MAIN_OK), make_wheel(tmp, "0.2.0+aide.1", MAIN_OK),
                  make_wheel(tmp, "0.2.0+aide.2", MAIN_BROKEN))
    subprocess.run([uv, "pip", "install", "--python", str(env_dir / "Scripts" / "python.exe"), "--no-deps",
                    "--offline", str(v1)], check=True, capture_output=True, env={**dict(__import__("os").environ), **uv_env})
    python = env_dir / "Scripts" / "python.exe"
    check("装好了 v1", installed_version(python) == "0.2.0")

    print("1. 换成 v2")
    result = run_helper(tmp, env_dir, v2, v1)
    check("v2 生效（applied）", result.get("outcome") == "applied", json.dumps(result, ensure_ascii=False))
    check("环境里是 v2", installed_version(python) == "0.2.0+aide.1", installed_version(python))

    print("2. 换成起不来的 v3")
    result = run_helper(tmp, env_dir, v3, v2, life="5")
    check("v3 起不来就回滚（rolled_back）", result.get("outcome") == "rolled_back", result.get("detail", "")[:200])
    check("环境里回到了 v2", installed_version(python) == "0.2.0+aide.1", installed_version(python))
    check("回滚原因里有启动日志", "v3 起不来" in result.get("detail", ""))
    print((tmp / "apply.log").read_text(encoding="utf-8")[-1500:])
    passed = sum(ok for _, ok in results)
    print(f"\n{passed}/{len(results)} 通过")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
