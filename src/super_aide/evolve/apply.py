"""生效：换上新打好的包、重启超级助手、确认它起得来，起不来就装回原来的版本。

这个文件独立运行（只用标准库）：超级助手先把它复制到 ~/.super_aide/evolve/apply.py，用基础 Python 的 pythonw 启动它，
再自己退出——运行环境里的文件正在被替换，不能用运行环境里的 Python 跑。

    pythonw apply.py <计划.json>

计划里有：要等退出的进程（pid 和启动时间）、运行环境的 python / pythonw / site-packages、uv、要装的 wheel、
起不来时装回的 wheel、启动参数、健康报告的位置和这次的随机数、结果和日志写到哪。
换包期间持有命名互斥体 Local\\SuperAideApplying：这时你手动打开超级助手，它会等换完再启动，不会抢走单实例锁。
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from ctypes import wintypes
from pathlib import Path

MUTEX = "Local\\SuperAideApplying"
SYNCHRONIZE, PROCESS_TERMINATE, PROCESS_QUERY_LIMITED_INFORMATION = 0x00100000, 0x0001, 0x1000
WAIT_OBJECT_0, WAIT_TIMEOUT = 0, 0x102
CREATE_NO_WINDOW, CREATE_NEW_PROCESS_GROUP, DETACHED_PROCESS = 0x08000000, 0x00000200, 0x00000008
EXIT_WAIT_S = 20
EPOCH_DIFF = 116444736000000000  # 1601-01-01 到 1970-01-01，单位 100ns

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None
_log_path: Path | None = None


class FILETIME(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


if kernel32 is not None:
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(FILETIME)] * 4
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]


def log(text: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}"
    if _log_path is not None:
        try:
            with _log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


# ---------- 进程 ----------

def _created(handle) -> float:
    c, e, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    if not kernel32.GetProcessTimes(handle, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
        return 0.0
    return ((c.high << 32 | c.low) - EPOCH_DIFF) / 1e7


def wait_exit(processes: list[list[float]], timeout: float = EXIT_WAIT_S) -> None:
    """等这些进程退出（pid 和启动时间都对上才算同一个进程）；超时就结束它们。不按程序路径杀：这个小程序自己也是 Python。"""
    deadline = time.time() + timeout
    for pid, created in processes:
        handle = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            continue
        try:
            if created and abs(_created(handle) - float(created)) > 2:
                continue  # pid 已经被别的进程复用了
            left = max(0, int((deadline - time.time()) * 1000))
            if kernel32.WaitForSingleObject(handle, left) == WAIT_TIMEOUT:
                log(f"进程 {pid} 没有按时退出，结束它")
                kernel32.TerminateProcess(handle, 1)
                kernel32.WaitForSingleObject(handle, 5000)
        finally:
            kernel32.CloseHandle(handle)


# ---------- 换包 ----------

def install(plan: dict, wheel: str) -> str:
    """换上 wheel：只换超级助手本身（不解析依赖、不联网）。成功返回空，失败返回原因。"""
    uv = plan.get("uv") or ""
    if uv and Path(uv).exists():
        cmd = [uv, "pip", "install", "--python", plan["python"], "--no-deps", "--reinstall-package", "super-aide",
               "--offline", "--link-mode", "copy", wheel]
        env = {**os.environ, **(plan.get("uv_env") or {})}
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                                    timeout=300, creationflags=CREATE_NO_WINDOW)
            log(f"uv：{result.returncode} {(result.stdout + result.stderr).strip()[-800:]}")
            if result.returncode == 0:
                return ""
        except (OSError, subprocess.SubprocessError) as e:
            log(f"uv 没跑起来：{e}")
    try:
        unpack(wheel, Path(plan["site"]))
        return ""
    except Exception as e:  # noqa: BLE001
        log(f"解包失败：{e}")
        return f"{type(e).__name__}: {e}"


def unpack(wheel: str, site: Path) -> None:
    """不用 uv 时自己装：按旧的 RECORD 删掉旧文件，解出新 wheel，写上 INSTALLER 和 RECORD。只动 super_aide 自己的文件。"""
    pkg = site / "super_aide"
    for info in site.glob("super_aide-*.dist-info"):
        shutil.rmtree(info, ignore_errors=True)
    shutil.rmtree(pkg, ignore_errors=True)
    with zipfile.ZipFile(wheel) as z:
        names = z.namelist()
        bad = [n for n in names if not (n.startswith("super_aide/") or n.startswith("super_aide-"))]
        if bad:
            raise ValueError(f"包里有不属于超级助手的文件：{bad[:3]}")
        z.extractall(site)
    info = next(site.glob("super_aide-*.dist-info"))
    (info / "INSTALLER").write_text("super-aide-evolve\n", encoding="utf-8")
    with (info / "RECORD").open("a", encoding="utf-8") as f:
        f.write(f"{info.name}/INSTALLER,,\n")
    log(f"已解包到 {site}")


# ---------- 启动和健康检查 ----------

def launch(plan: dict, args: list[str]) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_AGENT_SDK"))}
    env["SUPER_AIDE_APPLY_NONCE"] = plan["nonce"]
    env.setdefault("PYTHONIOENCODING", "utf-8")  # 起不来时的报错（中文）原样写进启动日志
    startup = Path(plan["startup_log"])
    startup.parent.mkdir(parents=True, exist_ok=True)
    err = startup.open("w", encoding="utf-8")
    log(f"启动：{plan['pythonw']} -m super_aide {' '.join(args)}")
    return subprocess.Popen([plan["pythonw"], "-m", "super_aide", *args], cwd=plan.get("home") or None, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                            creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS)


def healthy(plan: dict, proc: subprocess.Popen) -> bool:
    """新版本在限定时间内报告"启动好了"（随机数对得上），之后几秒还活着。进程提前退出就立刻算失败。"""
    deadline = time.time() + float(plan.get("health_timeout", 120))
    health = Path(plan["health"])
    while time.time() < deadline:
        if proc.poll() is not None:
            log(f"新版本提前退出了（{proc.returncode}）")
            return False
        try:
            if json.loads(health.read_text(encoding="utf-8")).get("nonce") == plan["nonce"]:
                time.sleep(float(plan.get("settle", 5)))
                alive = proc.poll() is None
                log("新版本启动正常" if alive else f"新版本报告启动后又退出了（{proc.returncode}）")
                return alive
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    log("等不到新版本的健康报告")
    return False


def tail(path: str, lines: int = 12) -> str:
    try:
        return "\n".join(Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def run(plan: dict) -> dict:
    wait_exit(plan.get("wait") or [])
    result = {"job": plan.get("job", ""), "action": plan.get("action", "apply"), "t": time.time()}
    problem = install(plan, plan["install"])
    if problem:
        # 没装上：旧版本可能已经被删了一半，装回原来的版本再打开
        result.update(outcome="install_failed", detail=problem)
        if plan.get("fallback"):
            install(plan, plan["fallback"])
        launch(plan, plan.get("fallback_args") or [])
        return result
    proc = launch(plan, plan.get("args") or [])
    if healthy(plan, proc):
        result["outcome"] = "applied"
        return result
    result.update(outcome="rolled_back", detail=tail(plan["startup_log"]))
    try:
        proc.kill()
    except OSError:
        pass
    if plan.get("fallback"):
        problem = install(plan, plan["fallback"])
        if problem:
            result["detail"] += f"\n装回原来的版本也失败了：{problem}"
    launch(plan, plan.get("fallback_args") or [])
    return result


def main(argv: list[str]) -> int:
    global _log_path
    plan = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    _log_path = Path(plan["log"])
    mutex = kernel32.CreateMutexW(None, True, MUTEX) if kernel32 else None
    try:
        log(f"开始：{plan.get('action')} {plan.get('job')} → {plan['install']}")
        result = run(plan)
    except Exception as e:  # noqa: BLE001 - 无论如何把结果写下来，超级助手下次启动时读
        result = {"job": plan.get("job", ""), "action": plan.get("action", "apply"), "outcome": "failed",
                  "detail": f"{type(e).__name__}: {e}", "t": time.time()}
        log(f"出错：{result['detail']}")
    finally:
        if mutex:
            kernel32.ReleaseMutex(mutex)
            kernel32.CloseHandle(mutex)
    Path(plan["result"]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    log(f"结束：{result.get('outcome')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
