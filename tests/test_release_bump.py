"""合并 PR 后自动发版（.github/workflows/auto-release.yml）：这次发哪个版本、版本号怎么改。"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bump", ROOT / "scripts" / "release" / "bump.py")
bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump)


def test_patch_is_bumped_unless_the_pr_already_did():
    assert bump.plan("0.4.1", "v0.4.1") == "0.4.2"     # 平常：补丁号加一
    assert bump.plan("0.5.0", "v0.4.1") == "0.5.0"     # PR 自己改成了新版本：就发它
    assert bump.plan("0.4.9", "v0.4.10") == "0.4.11"   # 按数字比，不按字母
    assert bump.plan("0.4.0", "v0.0.0") == "0.4.0"     # 还没有标签


def test_versions_are_changed_in_both_files():
    pyproject = '[project]\nname = "super-aide"\nversion = "0.4.1"\n\n[tool.x]\nversion = "9"\n'
    assert bump.project_version(pyproject) == "0.4.1"
    changed = bump.set_project_version(pyproject, "0.4.2")
    assert 'version = "0.4.2"' in changed and 'version = "9"' in changed  # 只改 [project] 那一个
    lock = ('[[package]]\r\nname = "six"\r\nversion = "0.4.1"\r\n\r\n'
            '[[package]]\r\nname = "super-aide"\r\nversion = "0.4.1"\r\nsource = { editable = "." }\r\n')
    new = bump.set_lock_version(lock, "0.4.2")
    assert 'name = "six"\r\nversion = "0.4.1"' in new and 'name = "super-aide"\r\nversion = "0.4.2"' in new


def test_the_real_files_have_what_the_script_edits():
    version = bump.project_version((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert bump.LOCK_ENTRY.search(lock).group(2) == version  # 两边一致，脚本找得到要改的那一行
