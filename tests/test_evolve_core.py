"""自我改进的基础部件：什么算失败、补丁、打包、工作台、版本号、测试结果比对、任务落盘、选工具和模型。"""

from __future__ import annotations

import base64
import hashlib
import shutil
import zipfile
from pathlib import Path

import pytest

from super_aide import update
from super_aide.config import Config, EngineSettings, ModelEntry
from super_aide.evolve import agent, patching, triggers, wheelfile
from super_aide.evolve.agent import Choice
from super_aide.evolve.jobs import Job, Jobs
from super_aide.evolve.testenv import TestRun, compare, parse_junit
from super_aide.evolve.workshop import Installed, Workshop, restore_point


# ---------- 什么算失败 ----------

@pytest.mark.parametrize("done", [
    {"reason": "api_error", "error": ""},                       # Claude 的接口故障：报错常常是空的
    {"api_error_status": 529},
    {"api_error_status": 429, "error": "rate limited"},
    {"stopped": True, "ok": True},                              # 你按 Esc 停下的
    {"reason": "interrupted"},
    {"hint": "浏览器操作还没接通"},
    {"error": "Connection reset by peer"},
    {"exception": "CLIConnectionError: lost"},
    {"reason": "reported", "error": "Not done: network error while downloading"},
])
def test_outages_and_stops_are_not_capability_failures(done):
    assert triggers.is_infra(done)


@pytest.mark.parametrize("done", [
    {"reason": "reported", "error": "没完成：网络设置页面里找不到代理选项"},  # 任务说明里提到"网络""代理"不算故障
    {"reason": "error_during_execution", "error": "KeyError: 'foo'"},
    {"reason": "reported", "error": "没完成：需要管理员权限"},
    {"ok": False, "error": ""},
])
def test_real_failures_count(done):
    assert not triggers.is_infra(done)


def test_stop_reasons():
    assert triggers.stop_counts("wrong", "")
    assert triggers.stop_counts("", "点了半天没反应")
    assert not triggers.stop_counts("not_assistant", "做错了")
    assert not triggers.stop_counts("", "我改主意了，不用了")
    assert not triggers.stop_counts("slow", "changed my mind")
    assert not triggers.stop_counts("", "")


def test_signature_ignores_paths_and_numbers():
    a = triggers.signature("failure", r"KeyError at C:\Users\a\x.py line 12 0x7ff3")
    b = triggers.signature("failure", r"KeyError at C:\Users\b\y.py line 99 0x1a2b")
    assert a == b
    assert a != triggers.signature("stopped", r"KeyError at C:\Users\a\x.py line 12")


# ---------- 本地版本号 ----------

def test_local_versions_still_see_official_updates():
    assert update.parse("0.2.0+aide.3") == (0, 2, 0)
    assert update.is_newer("0.2.1", "0.2.0+aide.3")
    assert not update.is_newer("0.2.0", "0.2.0+aide.3")
    assert update.base_version("0.2.0+aide.3") == "0.2.0" and update.base_version("0.2.0") == "0.2.0"
    assert update.evolved_count("0.2.0+aide.3") == 3 and update.evolved_count("0.2.0") == 0


# ---------- 补丁 ----------

def tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="")
    return root


def read_tree(root: Path) -> dict[str, str]:
    return {rel: p.read_text(encoding="utf-8") for rel, p in patching.files(root).items()}


BEFORE = {"src/a.py": "".join(f"line {i}\n" for i in range(30)), "src/gone.py": "x = 1\n", "README.md": "hi\n"}
AFTER = {"src/a.py": BEFORE["src/a.py"].replace("line 10\n", "line ten\n").replace("line 25\n", ""),
         "src/new.py": "y = 2\n", "README.md": "hi\n"}


def test_diff_apply_and_reverse_round_trip(tmp_path):
    old, new = tree(tmp_path / "old", BEFORE), tree(tmp_path / "new", AFTER)
    patch = patching.diff_trees(old, new)
    assert sorted(patching.changed_paths(patch)) == ["src/a.py", "src/gone.py", "src/new.py"]
    target = tree(tmp_path / "target", BEFORE)
    patching.apply(patch, target)
    assert read_tree(target) == AFTER
    assert patching.applies(patch, target, reverse=True)  # 已经包含了这次改动
    assert not patching.applies(patch, target)
    patching.apply(patch, target, reverse=True)
    assert read_tree(target) == BEFORE


def test_patch_tolerates_shifted_lines(tmp_path):
    patch = patching.diff_trees(tree(tmp_path / "old", BEFORE), tree(tmp_path / "new", AFTER))
    shifted = dict(BEFORE, **{"src/a.py": "# header\n" * 5 + BEFORE["src/a.py"]})
    target = tree(tmp_path / "target", shifted)
    patching.apply(patch, target)
    assert "line ten" in (target / "src/a.py").read_text(encoding="utf-8")


def test_change_already_merged_upstream_with_neighbours_edited(tmp_path):
    """本地改进合进主线以后，主线又改了旁边几行：反着套补丁对不上，但改动确实已经在里面了，不用再搬迁
    （2026-10-09：设置里隐藏"界面操作"那一行合进主线后，旁边加了"数据位置"，又起了一个搬迁任务）。"""
    patch = patching.diff_trees(tree(tmp_path / "old", BEFORE), tree(tmp_path / "new", AFTER))
    edited = dict(AFTER, **{"src/a.py": AFTER["src/a.py"].replace("line 9\n", "line 9 (edited upstream)\n")})
    target = tree(tmp_path / "target", edited)
    assert not patching.applies(patch, target, reverse=True)
    assert patching.included(patch, target)
    assert not patching.included(patch, tree(tmp_path / "before", BEFORE))  # 还没改的：不算已包含


def test_conflicting_patch_changes_nothing(tmp_path):
    patch = patching.diff_trees(tree(tmp_path / "old", BEFORE), tree(tmp_path / "new", AFTER))
    changed = dict(BEFORE, **{"src/a.py": BEFORE["src/a.py"].replace("line 10\n", "line X\n")})
    target = tree(tmp_path / "target", changed)
    with pytest.raises(patching.PatchError):
        patching.apply(patch, target)
    assert read_tree(target) == changed  # 一处套不上就一处也不改


def test_missing_trailing_newline(tmp_path):
    old = tree(tmp_path / "old", {"a.txt": "one\ntwo"})
    new = tree(tmp_path / "new", {"a.txt": "one\nTWO"})
    patch = patching.diff_trees(old, new)
    assert "No newline at end of file" in patch
    target = tree(tmp_path / "t", {"a.txt": "one\ntwo"})
    patching.apply(patch, target)
    assert (target / "a.txt").read_text(encoding="utf-8") == "one\nTWO"


# ---------- 工作台和打包 ----------

def fake_install(root: Path, version: str = "0.2.0", kit: bool = True) -> Installed:
    site = root / "site"
    pkg = site / "super_aide"
    tree(pkg, {"__init__.py": "VERSION = 1\n", "app.py": "def main():\n    return 0\n",
               "workspace/AGENTS.md": "rules\n", "__pycache__/app.cpython-312.pyc": "x"})
    if kit:
        tree(pkg / "_source", {"pyproject.toml": '[project]\nname = "super-aide"\n', "LICENSE": "MIT\n",
                               "tests/test_x.py": "def test_x():\n    assert True\n"})
    info = site / f"super_aide-{version}.dist-info"
    tree(info, {"METADATA": f"Metadata-Version: 2.4\nName: super-aide\nVersion: {version}\n"
                            "Requires-Dist: pyside6>=6.8\n\nlong description\n",
                "entry_points.txt": "[gui_scripts]\nsuper-aide = super_aide.app:main\n",
                "licenses/LICENSE": "MIT\n", "RECORD": "super_aide/__init__.py,,\n", "INSTALLER": "uv\n"})
    return Installed(version, pkg, info, site, False, f"fp-{version}")


def test_workshop_is_the_running_version_plus_its_source_kit(tmp_path):
    installed = fake_install(tmp_path)
    work = Workshop(tmp_path / "work")
    assert work.ensure(installed, "job1") == "kit"
    assert (work.src / "app.py").exists() and not (work.src / "_source").exists()
    assert not (work.src / "__pycache__").exists()
    assert (work.root / "tests" / "test_x.py").exists() and work.has_tests()
    assert work.fresh(installed) and work.meta()["dirty"] == "job1"


def test_workshop_rebuilt_for_a_new_version_or_another_jobs_leftovers(tmp_path):
    installed = fake_install(tmp_path)
    work = Workshop(tmp_path / "work")
    work.ensure(installed, "job1")
    (work.src / "app.py").write_text("changed by job1\n", encoding="utf-8")
    work.ensure(installed, "job1")  # 同一个任务续上：改动还在
    assert (work.src / "app.py").read_text(encoding="utf-8") == "changed by job1\n"
    work.ensure(installed, "job2")  # 别的任务：从正在运行的版本重新生成
    assert "def main" in (work.src / "app.py").read_text(encoding="utf-8")
    newer = fake_install(tmp_path / "v2", "0.2.1")
    work.ensure(newer, "job2")
    assert work.meta()["version"] == "0.2.1"


def test_snapshot_diff_and_restore(tmp_path):
    installed = fake_install(tmp_path)
    work = Workshop(tmp_path / "work")
    work.ensure(installed, "job1")
    base = tmp_path / "base"
    work.snapshot(base)
    (work.src / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    diff = work.diff(base)
    assert "-    return 0" in diff and "+    return 1" in diff and ".aide.json" not in diff
    work.restore(base)
    assert "return 0" in (work.src / "app.py").read_text(encoding="utf-8")
    assert work.meta()["dirty"] == ""


def _record_ok(z: zipfile.ZipFile, info: str) -> bool:
    for line in z.read(f"{info}/RECORD").decode().splitlines():
        name, digest, size = line.split(",")
        if digest:
            data = z.read(name)
            expect = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            if digest != expect or int(size) != len(data):
                return False
    return True


def test_built_wheel_changes_only_the_version(tmp_path):
    installed = fake_install(tmp_path)
    work = Workshop(tmp_path / "work")
    work.ensure(installed, "job1")
    (work.src / "app.py").write_bytes(b"def main():\n    return 1\n")
    wheel = work.build(installed, "0.2.0+aide.1", tmp_path / "wheels")
    assert wheel.name == "super_aide-0.2.0+aide.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as z:
        names = set(z.namelist())
        info = "super_aide-0.2.0+aide.1.dist-info"
        meta = z.read(f"{info}/METADATA").decode()
        assert "Version: 0.2.0+aide.1" in meta and "Requires-Dist: pyside6>=6.8" in meta
        assert z.read(f"{info}/entry_points.txt") == (installed.dist_info / "entry_points.txt").read_bytes()
        assert "super_aide/app.py" in names and "super_aide/_source/tests/test_x.py" in names
        assert f"{info}/INSTALLER" not in names and not any("__pycache__" in n for n in names)
        assert z.read("super_aide/app.py") == b"def main():\n    return 1\n"
        assert _record_ok(z, info)


def test_restore_point_is_the_installed_files(tmp_path):
    installed = fake_install(tmp_path)
    wheel = restore_point(installed, tmp_path / "wheels")
    with zipfile.ZipFile(wheel) as z:
        assert z.read("super_aide/app.py") == (installed.pkg / "app.py").read_bytes()
        assert "super_aide/_source/LICENSE" in z.namelist()
    assert restore_point(installed, tmp_path / "wheels") == wheel  # 已经有了就不重打
    assert wheelfile.version_of(wheel) == "0.2.0"


# ---------- 测试结果 ----------

JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">
<testcase classname="tests.test_a" name="test_ok" file="tests/test_a.py" line="1"/>
<testcase classname="tests.test_a.TestThing" name="test_bad[x-1]" file="tests/test_a.py" line="5">
  <failure message="boom">boom</failure></testcase>
<testcase classname="tests.test_b" name="test_skip" file="tests/test_b.py" line="1"><skipped message="no node"/></testcase>
</testsuite></testsuites>"""


def test_junit_results_become_node_ids(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text(JUNIT, encoding="utf-8")
    run = parse_junit(path)
    assert run.passed == {"tests/test_a.py::test_ok"}
    assert run.failed == {"tests/test_a.py::TestThing::test_bad[x-1]"}
    assert run.skipped == {"tests/test_b.py::test_skip"}


def test_compare_with_baseline():
    baseline = TestRun(passed={"a", "b", "c"}, failed={"old"})
    assert compare(baseline, TestRun(passed={"a", "b", "c", "new"}, failed={"old"})) == []  # 基线就失败的不管
    problems = compare(baseline, TestRun(passed={"a", "new"}, failed={"b", "fresh"}))
    assert any("不见了" in p and "c" in p for p in problems)          # 删测试绕过
    assert any("现在失败" in p and "b" in p for p in problems)
    assert any("新加的测试没通过" in p and "fresh" in p for p in problems)
    assert compare(baseline, TestRun(crashed="收集测试出错")) == ["测试没跑起来：收集测试出错"]


# ---------- 任务落盘 ----------

def test_jobs_round_trip_and_order(tmp_path):
    jobs = Jobs(tmp_path)
    a = jobs.add(Job(id="a", kind="failure", created=1.0, conv="k1"))
    jobs.add(Job(id="b", kind="suggestion", created=2.0))
    assert jobs.open_for("k1") is a and jobs.next_queued() is a and jobs.active() is None
    jobs.update(a, status="running", phase="agent")
    assert jobs.active() is a and jobs.next_queued().id == "b"
    again = Jobs(tmp_path)
    assert again.get("a").phase == "agent" and again.get("b").status == "queued"
    jobs.update(a, status="done", applied=10.0)
    jobs.update(jobs.get("b"), status="done", applied=5.0)
    assert [j.id for j in jobs.applied_chain()] == ["b", "a"]
    (jobs.folder(a) / "evidence").mkdir(parents=True)
    (jobs.folder(a) / "change.patch").write_text("x", encoding="utf-8")
    jobs.drop_evidence(a)
    assert not (jobs.folder(a) / "evidence").exists() and (jobs.folder(a) / "change.patch").exists()


# ---------- 选工具和模型 ----------

CODEX_META = {"codex": {"gpt-6-astra": {"efforts": ["low", "medium", "high", "xhigh", "max"],
                                        "desc": "Frontier intelligence for the most demanding work"},
                        "gpt-6-luna": {"efforts": ["low", "high"], "desc": "Fast and affordable"}}}


def cfg_with(claude=("claude-opus-5-5",), codex=("gpt-6-astra",)) -> Config:
    return Config(claude=EngineSettings(models=[ModelEntry(m, True) for m in claude]),
                  codex=EngineSettings(models=[ModelEntry(m, True) for m in codex]))


def test_default_is_claude_code_opus_max():
    assert agent.choose({"claude", "codex"}, cfg_with(), {}, CODEX_META, {}) == Choice("claude", "claude-opus-5-5", "max")


def test_without_opus_picks_the_strongest_available():
    found = {"claude": ["claude-sonnet-5-5", "claude-haiku-5-5"], "codex": ["gpt-6-luna", "gpt-6-astra"]}
    # 服务不提供 Opus 5.5：旗舰的 Codex 比主力的 Claude 强
    assert agent.choose({"claude", "codex"}, cfg_with(), found, CODEX_META, {}) == Choice("codex", "gpt-6-astra", "max")
    # 没有 Codex：Claude 里最强的，最高档
    assert agent.choose({"claude"}, cfg_with(), found, CODEX_META, {}) == Choice("claude", "claude-sonnet-5-5", "max")


def test_claude_code_missing_or_opus_unavailable():
    assert agent.choose({"codex"}, cfg_with(), {}, CODEX_META, {}) == Choice("codex", "gpt-6-astra", "max")
    blocked = {"claude|claude-opus-5-5": 9e12}
    assert agent.choose({"claude", "codex"}, cfg_with(), {}, CODEX_META, blocked).engine == "codex"
    assert agent.choose(set(), cfg_with(), {}, CODEX_META, {}) is None  # 只有 DeepSeek Harness：这一版不支持


def test_effort_steps_down():
    assert Choice("claude", "m", "max").lower() == Choice("claude", "m", "xhigh")
    assert Choice("claude", "m", "low").lower() is None


@pytest.mark.parametrize("text,status,api,kind", [
    ("", 401, True, "auth"),
    ("model claude-opus-5-5 not found", None, True, "model"),
    ("invalid effort value", 400, True, "effort"),
    ("No conversation found with session ID: x", None, False, "missing"),
    ("", 529, True, "network"),
    ("ConnectionResetError: reset by peer", None, False, "network"),
    ("Invalid permission mode: auto", None, False, "permission_mode"),
    ("something odd", None, False, "other"),
])
def test_classify_outcomes(text, status, api, kind):
    assert agent.classify(text, status, api) == kind


def test_parse_json_fallbacks():
    assert agent.parse_json('{"action": "none"}') == {"action": "none"}
    assert agent.parse_json('好的。\n```json\n{"action": "changed"}\n```') == {"action": "changed"}
    assert agent.parse_json("没有结论") is None


def test_no_leftovers(tmp_path):
    shutil.rmtree(tmp_path, ignore_errors=True)
