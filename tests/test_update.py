"""检查更新：版本号比较、几个来源依次问、发布信息、交给安装器。"""

from __future__ import annotations

import json

import pytest

from super_aide import update


def test_version_compare():
    assert update.parse("v0.2.0") == (0, 2, 0) and update.parse("0.2.0rc1") is None
    assert update.is_newer("0.2.0", "0.1.9") and update.is_newer("0.10.0", "0.9.0")
    assert update.is_newer("1.0.1", "1.0") and not update.is_newer("1.0", "1.0.0")
    assert not update.is_newer("0.2.0rc1", "0.1.0")  # 预发布版不提示


def fake_get(pages: dict):
    def get(url: str, timeout: float = 8) -> bytes:
        for prefix, body in pages.items():
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return body if isinstance(body, bytes) else json.dumps(body).encode()
        raise OSError(f"unreachable {url}")
    return get


def test_github_first_with_installer_url(monkeypatch):
    monkeypatch.setattr(update, "_get", fake_get({"https://api.github.com/repos/me/aide/releases/latest": {
        "tag_name": "v0.3.0", "html_url": "https://github.com/me/aide/releases/tag/v0.3.0",
        "assets": [{"name": "super_aide-0.3.0-py3-none-any.whl", "browser_download_url": "x"},
                   {"name": "SuperAideSetup.exe", "browser_download_url": "https://github.com/me/aide/s.exe"}]}}))
    release = update.latest("me/aide")
    assert (release.version, release.source, release.installer_url) == ("0.3.0", "GitHub",
                                                                           "https://github.com/me/aide/s.exe")


def test_falls_back_to_pypi_then_mirror(monkeypatch):
    monkeypatch.setattr(update, "_get", fake_get({"https://pypi.org/pypi/super-aide/json": {"info": {"version": "0.2.1"}}}))
    assert (update.latest("me/aide").version, update.latest("me/aide").source) == ("0.2.1", "PyPI")
    page = ('<a href="../../packages/a/super_aide-0.2.0-py3-none-any.whl#sha256=ab">super_aide-0.2.0-py3-none-any.whl</a>'
            '<a href="../../packages/b/super_aide-0.10.0-py3-none-any.whl#sha256=cd">super_aide-0.10.0-py3-none-any.whl</a>'
            '<a href="../../packages/c/super_aide-0.11.0rc1-py3-none-any.whl">x</a>').encode()
    monkeypatch.setattr(update, "_get", fake_get({update.MIRROR: page}))
    release = update.latest("me/aide")
    assert (release.version, release.source) == ("0.10.0", "阿里云镜像")


def test_nothing_reachable(monkeypatch):
    monkeypatch.setattr(update, "_get", fake_get({}))
    with pytest.raises(update.UpdateError):
        update.latest("")


def test_check_marks_source_builds_as_unmanaged(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "RELEASE_DIR", tmp_path)  # 没有 release.json：从源码装的
    monkeypatch.setattr(update, "__version__", "0.1.0")
    monkeypatch.setattr(update, "_get", fake_get({"https://pypi.org/pypi/super-aide/json": {"info": {"version": "0.2.0"}}}))
    result = update.check()
    assert result.newer and not result.managed and result.latest == "0.2.0"
    (tmp_path / "release.json").write_text(json.dumps({"repo": "me/aide", "version": "0.1.0"}), encoding="utf-8")
    assert update.check().managed


def test_start_update_needs_an_installer(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "installer_path", lambda: tmp_path / "missing.exe")
    with pytest.raises(update.UpdateError):
        update.start_update(None)
    started = []
    exe = tmp_path / "SuperAideSetup.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(update, "installer_path", lambda: exe)
    monkeypatch.setattr(update.subprocess, "Popen", lambda args, **kw: started.append(args))
    update.start_update(update.Release("0.2.0", "PyPI"))
    assert started[0][0] == str(exe) and started[0][1:3] == ["/update", "/pid"]
