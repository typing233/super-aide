"""数据位置：记在 ~/.super_aide/location.json；换的时候先复制、记下新位置、重启后删掉旧的那份。"""

import json
from pathlib import Path

import pytest

from super_aide import paths, relocate


@pytest.fixture
def homes(tmp_path, monkeypatch):
    home = tmp_path / "home" / ".super_aide"
    (home / "sessions" / "20261009-200248-c19e").mkdir(parents=True)
    (home / "sessions" / "20261009-200248-c19e" / "screen.jpg").write_bytes(b"x" * 1000)
    (home / "logs").mkdir()
    (home / "logs" / "super_aide.log").write_text("log", encoding="utf-8")
    (home / "config.toml").write_text("", encoding="utf-8")
    monkeypatch.setattr(paths, "HOME", home)
    monkeypatch.setattr(paths, "DATA", home)
    monkeypatch.setattr(paths, "LOCATION", home / "location.json")
    return home


def test_data_root_follows_the_record(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "LOCATION", tmp_path / "location.json")
    monkeypatch.setattr(paths, "HOME", tmp_path / "home")
    assert paths._data_root() == tmp_path / "home"  # 没换过：和设置放在一起
    (tmp_path / "location.json").write_text(json.dumps({"data": str(tmp_path / "D")}), encoding="utf-8")
    assert paths._data_root() == tmp_path / "D"
    (tmp_path / "location.json").write_text(json.dumps({"data": "Q:\\nowhere\\SuperAide"}), encoding="utf-8")
    assert paths._data_root() == tmp_path / "home"  # 那个盘不在了（移动硬盘拔了）：回到默认位置
    (tmp_path / "location.json").write_text("{broken", encoding="utf-8")
    assert paths._data_root() == tmp_path / "home"


def test_target_keeps_a_drive_root_tidy(homes, tmp_path):
    busy = tmp_path / "D"
    (busy / "Games").mkdir(parents=True)
    assert relocate.target_for(busy) == busy / "SuperAide"  # 不把数据撒在一个有别的东西的文件夹里
    empty = tmp_path / "E"
    empty.mkdir()
    assert relocate.target_for(empty) == empty
    assert relocate.target_for(homes) == homes  # 搬回默认位置


def test_problems(homes, tmp_path):
    assert relocate.problem(homes, 10) == "数据已经在这里了"
    assert relocate.problem(homes / "sessions" / "x", 10).startswith("新位置和现在的数据文件夹")
    assert relocate.problem(tmp_path / "D" / "SuperAide", 10) == ""
    assert "空间不够" in relocate.problem(tmp_path / "D" / "SuperAide", 1 << 60)


def test_move_copies_then_switches_and_cleans_up_after_restart(homes, tmp_path, monkeypatch):
    target = tmp_path / "D" / "SuperAide"
    seen = []
    relocate.copy(target, lambda done, total: seen.append((done, total)))
    assert (target / "sessions" / "20261009-200248-c19e" / "screen.jpg").read_bytes() == b"x" * 1000
    assert (homes / "logs" / "super_aide.log").exists()  # 只是复制：出错的话旧的那份还在
    assert seen[-1][0] == seen[-1][1] == relocate.size(target)
    relocate.commit(target)
    record = json.loads(paths.LOCATION.read_text(encoding="utf-8"))
    assert Path(record["data"]) == target and Path(record["previous"]) == homes

    monkeypatch.setattr(paths, "DATA", target)  # 重启以后
    relocate.cleanup()
    assert not (homes / "sessions").exists() and not (homes / "logs").exists()
    assert (homes / "config.toml").exists()  # 设置和位置记录留在原地
    assert "previous" not in json.loads(paths.LOCATION.read_text(encoding="utf-8"))
    relocate.cleanup()  # 再起来一次：没什么要删的


def test_human_sizes():
    assert relocate.human(512) == "512 B"
    assert relocate.human(338 * 1024 * 1024) == "338 MB"
    assert relocate.human(3 * 1024 ** 3) == "3.0 GB"
