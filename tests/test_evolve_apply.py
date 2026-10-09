"""生效的小程序（换包、健康检查、回滚）、GitHub 设备码登录、社区共建（隐私扫描、套到主版本上）。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from super_aide.evolve import apply, community, github, patching
from super_aide.evolve.workshop import restore_point

from test_evolve_core import fake_install, tree


# ---------- 生效 ----------

def plan(tmp_path: Path, **extra) -> dict:
    return {"job": "j1", "action": "apply", "wait": [], "python": "py", "pythonw": "pyw", "site": str(tmp_path),
            "uv": "", "install": "new.whl", "fallback": "old.whl", "args": ["--evolved", "j1"],
            "fallback_args": ["--evolve-failed", "j1"], "home": str(tmp_path), "health": str(tmp_path / "h.json"),
            "nonce": "n1", "result": str(tmp_path / "r.json"), "log": str(tmp_path / "a.log"),
            "startup_log": str(tmp_path / "s.log"), "health_timeout": 2, "settle": 0, **extra}


class FakeProc:
    def __init__(self, exits: bool = False) -> None:
        self.returncode = 1 if exits else None

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.fixture
def helper(monkeypatch, tmp_path):
    record = SimpleNamespace(installs=[], launches=[], healthy=True, exits=False, fail_install=set())

    def fake_install(p, wheel):
        record.installs.append(wheel)
        return "坏了" if wheel in record.fail_install else ""

    def fake_launch(p, args):
        record.launches.append(args)
        if record.healthy and args and args[0] == "--evolved":
            Path(p["health"]).write_text(json.dumps({"nonce": p["nonce"]}), encoding="utf-8")
        return FakeProc(exits=record.exits and args[:1] == ["--evolved"])

    monkeypatch.setattr(apply, "install", fake_install)
    monkeypatch.setattr(apply, "launch", fake_launch)
    monkeypatch.setattr(apply.time, "sleep", lambda s: None)
    return record


def test_apply_success(helper, tmp_path):
    result = apply.run(plan(tmp_path))
    assert result["outcome"] == "applied" and helper.installs == ["new.whl"]
    assert helper.launches == [["--evolved", "j1"]]


def test_no_health_report_rolls_back(helper, tmp_path, monkeypatch):
    helper.healthy = False
    clock = iter(range(0, 1000, 1))
    monkeypatch.setattr(apply.time, "time", lambda: next(clock))
    result = apply.run(plan(tmp_path))
    assert result["outcome"] == "rolled_back"
    assert helper.installs == ["new.whl", "old.whl"] and helper.launches[-1] == ["--evolve-failed", "j1"]


def test_early_exit_rolls_back_immediately(helper, tmp_path):
    helper.exits, helper.healthy = True, False
    result = apply.run(plan(tmp_path))
    assert result["outcome"] == "rolled_back" and helper.installs[-1] == "old.whl"


def test_install_failure_restores_and_reopens(helper, tmp_path):
    helper.fail_install = {"new.whl"}
    result = apply.run(plan(tmp_path))
    assert result["outcome"] == "install_failed" and result["detail"] == "坏了"
    assert helper.installs == ["new.whl", "old.whl"] and helper.launches == [["--evolve-failed", "j1"]]


def test_unpack_replaces_only_super_aide(tmp_path):
    installed = fake_install(tmp_path / "inst")
    wheel = restore_point(installed, tmp_path / "wheels")
    site = tmp_path / "site2"
    tree(site, {"super_aide/old_only.py": "x\n", "super_aide-0.1.0.dist-info/METADATA": "old\n",
                "other_pkg/keep.py": "keep\n"})
    apply.unpack(str(wheel), site)
    assert not (site / "super_aide" / "old_only.py").exists() and (site / "super_aide" / "app.py").exists()
    assert (site / "other_pkg" / "keep.py").exists() and not (site / "super_aide-0.1.0.dist-info").exists()
    info = site / "super_aide-0.2.0.dist-info"
    assert (info / "INSTALLER").read_text(encoding="utf-8").strip() == "super-aide-evolve"


def test_unpack_refuses_foreign_files(tmp_path):
    bad = tmp_path / "bad.whl"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("super_aide/x.py", "x")
        z.writestr("evil/run.py", "x")
    with pytest.raises(ValueError):
        apply.unpack(str(bad), tmp_path / "site")


# ---------- GitHub 设备码登录 ----------

def test_device_flow_polls_until_authorized(monkeypatch):
    answers = iter([{"error": "authorization_pending"}, {"error": "slow_down", "interval": 10},
                    {"access_token": "gho_x"}])
    sent = []
    monkeypatch.setattr(github, "_form", lambda url, fields: sent.append(fields) or next(answers))
    waits = []
    code = github.DeviceCode("dc", "ABCD-1234", "https://github.com/login/device", 5, 9e12)
    assert github.device_poll(code, sleep=waits.append) == "gho_x"
    assert waits == [5, 5, 10] and sent[0]["client_id"] == github.CLIENT_ID and "client_secret" not in sent[0]


def test_device_flow_errors(monkeypatch):
    monkeypatch.setattr(github, "_form", lambda url, fields: {"error": "access_denied", "error_description": "拒绝了"})
    code = github.DeviceCode("dc", "ABCD-1234", "u", 5, 9e12)
    with pytest.raises(github.GitHubError, match="拒绝了"):
        github.device_poll(code, sleep=lambda s: None)
    expired = github.DeviceCode("dc", "ABCD-1234", "u", 5, 0)
    with pytest.raises(github.GitHubError):
        github.device_poll(expired, sleep=lambda s: None)


# ---------- 社区共建 ----------

def test_privacy_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPUTERNAME", "DESKTOP-ZHANG")
    monkeypatch.setattr(community.os.path, "expanduser", lambda p: r"C:\Users\zhangsan")
    patch = "\n".join([
        "+++ b/tests/test_x.py",
        "+PATH = r'C:\\Users\\zhangsan\\Desktop\\报表.xlsx'",
        "+HOST = 'DESKTOP-ZHANG'",
        "+MAIL = 'zhang@corp.cn'  # 安全的：noreply@example.com",
        "+PHONE = '13812345678'",
        "+KEY = 'sk-abcdefghijklmnopqrstuvwxyz123456'",
        "+TEXT = '王经理说下周三之前必须把合同发过去'",
    ])
    hits = community.privacy_scan(patch, ["王经理说下周三之前必须把合同发过去"])
    joined = "\n".join(hits)
    for word in ("用户目录", "计算机名", "zhang@corp.cn", "手机号", "令牌", "证据里的原文"):
        assert word in joined
    assert "example.com" not in joined
    assert community.privacy_scan("+x = 1\n+def test_ok():\n+    assert True\n", []) == []


def test_apply_upstream_and_compile_check(tmp_path):
    old = tree(tmp_path / "old", {"src/a.py": "".join(f"x{i} = {i}\n" for i in range(20))})
    new = tree(tmp_path / "new", {"src/a.py": "".join(f"x{i} = {i}\n" for i in range(20)).replace("x5 = 5", "x5 = 55"),
                                  "src/b.py": "y = 1\n"})
    patch = patching.diff_trees(old, new)
    upstream = {"src/a.py": "# 主版本多了一行\n" + "".join(f"x{i} = {i}\n" for i in range(20))}
    gh = SimpleNamespace(file_at=lambda repo, path, ref: upstream.get(path))
    files, failed = community.apply_upstream(gh, "o/r", "sha", patch)
    assert failed == [] and "x5 = 55" in files["src/a.py"] and files["src/b.py"] == "y = 1\n"
    upstream["src/a.py"] = "完全改写了\n"
    files, failed = community.apply_upstream(gh, "o/r", "sha", patch)
    assert failed == ["src/a.py"]  # 套不上的交给模型移植
    assert community.compile_check({"a.py": "def f(:\n", "b.txt": "x"}) and community.compile_check({"a.py": "x = 1\n"}) == []


def test_already_included_upstream(tmp_path):
    old = tree(tmp_path / "old", {"src/a.py": "x = 1\ny = 2\n", "src/gone.py": "z = 0\n"})
    new = tree(tmp_path / "new", {"src/a.py": "x = 1\ny = 3\n", "src/b.py": "w = 4\n"})
    patch = patching.diff_trees(old, new)
    merged = {"src/a.py": "x = 1\ny = 3\n", "src/b.py": "w = 4\n"}  # 主版本里已经合进去了
    gh = SimpleNamespace(file_at=lambda repo, path, ref: merged.get(path))
    assert community.already_included(gh, "o/r", "sha", patch)
    merged["src/a.py"] = "x = 1\ny = 2\n"  # 还没合
    assert not community.already_included(gh, "o/r", "sha", patch)


def test_pr_body_has_no_evidence():
    job = SimpleNamespace(result={"title_zh": "标题", "title_en": "Title", "summary_zh": "说明", "summary_en": "Summary",
                                  "tests": "test_x", "risk": "小"}, version="0.2.0+aide.1")
    body = community.pr_body(job, "claude · claude-opus-5-5 · max", "aide-sig:abc")
    assert "aide-sig:abc" in body and "标题" in body and "屏幕" not in body.split("Generated")[0].split("由超级助手")[0]
