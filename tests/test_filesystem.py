"""FileSystem 抽象单元测试（V2）。

覆盖：
    scandir / stat 行为、is_file / is_dir / is_symlink、
    file identity（hard link 去重）、disk usage、path normalize、
    平台分支（symlink）。
"""

from __future__ import annotations

import os

import pytest

from src.core.filesystem import FileSystem, StatFileIdentity
from src.core.scan_models import ItemType


@pytest.fixture()
def fs() -> FileSystem:
    return FileSystem()


def test_normalize_strips_trailing_separator(fs):
    raw = os.path.join("a", "b", "..", "c")
    assert fs.normalize(raw) == os.path.normpath(raw)


def test_scandir_and_classify(fs, tmp_path):
    (tmp_path / "file.txt").write_bytes(b"hello")
    (tmp_path / "sub").mkdir()

    kinds = {}
    with fs.scandir(str(tmp_path)) as iterator:
        for entry in iterator:
            kinds[entry.name] = fs.classify(entry)

    assert kinds == {"file.txt": ItemType.FILE, "sub": ItemType.DIRECTORY}


def test_path_based_helpers(fs, tmp_path):
    target = tmp_path / "data.bin"
    target.write_bytes(b"x")
    directory = tmp_path / "d"
    directory.mkdir()

    assert fs.is_file(str(target)) is True
    assert fs.is_dir(str(directory)) is True
    assert fs.is_symlink(str(target)) is False
    assert fs.stat(str(target)).st_size == 1


def test_identity_none_for_single_link(tmp_path):
    target = tmp_path / "single.txt"
    target.write_bytes(b"x")
    probing = FileSystem(probe_hard_links=True)
    stat_result = probing.stat(str(target))
    assert probing.identity(stat_result, path=str(target)) is None


def test_identity_dedups_hard_links(tmp_path):
    original = tmp_path / "original.txt"
    original.write_bytes(b"payload")
    link = tmp_path / "link.txt"
    try:
        os.link(str(original), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("文件系统不支持硬链接")

    probing = FileSystem(probe_hard_links=True)
    first = probing.identity(probing.stat(str(original)), path=str(original))
    second = probing.identity(probing.stat(str(link)), path=str(link))
    assert first is not None
    assert first == second
    assert hash(first) == hash(second)
    assert isinstance(first, StatFileIdentity)
    assert len({first, second}) == 1


def test_identity_not_probed_when_disabled(tmp_path):
    original = tmp_path / "a.bin"
    original.write_bytes(b"payload")
    link = tmp_path / "b.bin"
    try:
        os.link(str(original), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("文件系统不支持硬链接")

    # 关闭探测时，Windows 缓存 stat 无法提供 file index → 返回 None（保持快速路径）
    if os.name != "nt":
        pytest.skip("仅在 Windows 缓存 stat 场景下可观测")

    quiet = FileSystem(probe_hard_links=False)
    with quiet.scandir(str(tmp_path)) as iterator:
        direntry = next(entry for entry in iterator if entry.name == "a.bin")
        cached = quiet.stat(direntry)  # DirEntry → 使用缓存（Windows 上 st_ino == 0）
        assert quiet.identity(cached, path=direntry.path) is None


def test_is_hidden_dotfile(fs, tmp_path):
    hidden = tmp_path / ".secret"
    hidden.write_bytes(b"x")
    visible = tmp_path / "plain"
    visible.write_bytes(b"x")

    with fs.scandir(str(tmp_path)) as iterator:
        flags = {entry.name: fs.is_hidden(entry) for entry in iterator}

    assert flags[".secret"] is True
    assert flags["plain"] is False


def test_is_hidden_accepts_path_string(fs, tmp_path):
    """展示层按路径查询隐藏状态：点前缀在任意平台都算隐藏。"""
    dotfile = tmp_path / ".secret"
    dotfile.write_bytes(b"x")
    plain = tmp_path / "plain"
    plain.write_bytes(b"x")

    assert fs.is_hidden(str(dotfile)) is True
    assert fs.is_hidden(str(plain)) is False


def test_disk_usage_returns_positive_totals(fs, tmp_path):
    usage = fs.disk_usage(str(tmp_path))
    assert usage.total > 0
    assert 0 <= usage.used <= usage.total
    assert usage.free >= 0
