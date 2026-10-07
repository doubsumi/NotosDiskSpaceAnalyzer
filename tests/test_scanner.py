"""Scanner 单元测试（V2）。

覆盖场景（§24）：
    empty directory / single file / nested directory / hidden file /
    hidden directory / permission denied / file disappears during scan /
    symlink / hard link / Unicode path / spaces / very deep tree /
    zero byte file / cancellation
"""

from __future__ import annotations

import os
from dataclasses import fields
from pathlib import Path

import pytest

from config.settings import Settings
from src.core.filesystem import FileSystem
from src.core.scan_models import ItemType, ScanContext, ScanStatus
from src.core.scanner import CancellationToken, DirectoryScanner


def scan_tree(root, *, filesystem=None, cancel_token=None, include_hidden=True,
              follow_symlinks=False):
    """执行一次完整扫描，返回 ``(entries, scanner)``。"""
    scanner = DirectoryScanner(filesystem=filesystem)
    context = ScanContext(
        root_path=str(root),
        cancel_token=cancel_token or CancellationToken(),
        include_hidden=include_hidden,
        follow_symlinks=follow_symlinks,
    )
    return list(scanner.scan(str(root), context)), scanner


def names(entries):
    return sorted(entry.name for entry in entries)


class ForbiddenFileSystem(FileSystem):
    """对指定路径的 scandir 抛出 PermissionError。"""

    def __init__(self, forbidden: Path):
        super().__init__()
        self.forbidden = os.path.normpath(str(forbidden))

    def scandir(self, path):
        if os.path.normpath(path) == self.forbidden:
            raise PermissionError("access denied")
        return super().scandir(path)


class DisappearingFileSystem(FileSystem):
    """对指定文件抛出 FileNotFoundError，模拟扫描期间文件消失。"""

    def __init__(self, vanished: Path):
        super().__init__()
        self.vanished = os.path.normpath(str(vanished))

    def stat(self, entry, follow_symlinks=False):
        path = entry if isinstance(entry, str) else entry.path
        if os.path.normpath(path) == self.vanished:
            raise FileNotFoundError("gone")
        return super().stat(entry, follow_symlinks=follow_symlinks)


def test_empty_directory(tmp_path):
    entries, scanner = scan_tree(tmp_path)

    assert entries == []
    assert scanner.status is ScanStatus.COMPLETED
    assert scanner.statistics.files_scanned == 0
    assert scanner.statistics.directories_scanned == 0
    assert scanner.statistics.bytes_scanned == 0


def test_single_file(tmp_path):
    (tmp_path / "one.txt").write_bytes(b"12345")

    entries, scanner = scan_tree(tmp_path)

    assert names(entries) == ["one.txt"]
    assert entries[0].item_type is ItemType.FILE
    assert entries[0].size == 5
    assert entries[0].parent_path == os.path.normpath(str(tmp_path))
    assert scanner.statistics.files_scanned == 1
    assert scanner.statistics.bytes_scanned == 5
    assert scanner.status is ScanStatus.COMPLETED


def test_nested_directory(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "a" / "b" / "deep.txt").write_bytes(b"xyz")

    entries, scanner = scan_tree(tmp_path)

    assert names(entries) == ["a", "b", "deep.txt"]
    assert scanner.statistics.directories_scanned == 2
    assert scanner.statistics.files_scanned == 1
    assert scanner.statistics.bytes_scanned == 3


def test_dfs_preorder_parent_before_children(tmp_path):
    (tmp_path / "parent").mkdir()
    (tmp_path / "parent" / "child").mkdir()
    (tmp_path / "parent" / "child" / "leaf.txt").write_bytes(b"z")

    entries, _ = scan_tree(tmp_path)

    paths = [entry.path for entry in entries]
    parent = os.path.normpath(str(tmp_path / "parent"))
    child = os.path.normpath(str(tmp_path / "parent" / "child"))
    leaf = os.path.normpath(str(tmp_path / "parent" / "child" / "leaf.txt"))

    assert paths.index(parent) < paths.index(child) < paths.index(leaf)


def test_hidden_included_by_default(tmp_path):
    (tmp_path / ".hidden_dir").mkdir()
    (tmp_path / ".hidden_dir" / ".hidden_file").write_bytes(b"h")

    entries, scanner = scan_tree(tmp_path, include_hidden=True)

    assert names(entries) == [".hidden_dir", ".hidden_file"]
    assert scanner.statistics.skipped == 0
    assert scanner.status is ScanStatus.COMPLETED


def test_hidden_excluded_when_disabled(tmp_path):
    (tmp_path / ".hidden_dir").mkdir()
    (tmp_path / ".hidden_dir" / ".hidden_file").write_bytes(b"h")
    (tmp_path / "visible.txt").write_bytes(b"v")

    entries, scanner = scan_tree(tmp_path, include_hidden=False)

    assert names(entries) == ["visible.txt"]
    assert scanner.statistics.skipped == 1
    assert scanner.status is ScanStatus.PARTIAL


def test_zero_byte_file(tmp_path):
    (tmp_path / "empty.bin").write_bytes(b"")

    entries, scanner = scan_tree(tmp_path)

    assert entries[0].size == 0
    assert scanner.statistics.bytes_scanned == 0
    assert scanner.status is ScanStatus.COMPLETED


def test_unicode_and_spaces(tmp_path):
    (tmp_path / "目录 带 空格").mkdir()
    (tmp_path / "目录 带 空格" / "文件 名.txt").write_bytes(b"abc")

    entries, scanner = scan_tree(tmp_path)

    assert set(names(entries)) == {"目录 带 空格", "文件 名.txt"}
    assert scanner.statistics.bytes_scanned == 3


def test_very_deep_tree(tmp_path):
    current = tmp_path
    for index in range(40):
        current = current / f"level{index}"
        current.mkdir()
    (current / "bottom.txt").write_bytes(b"deep")

    entries, scanner = scan_tree(tmp_path)

    assert scanner.statistics.directories_scanned == 40
    assert scanner.statistics.files_scanned == 1
    assert scanner.statistics.bytes_scanned == 4


def test_symlink_not_followed(tmp_path, tmp_path_factory):
    # 目标目录放在扫描范围之外，确保「未跟随」可被观测
    outside = tmp_path_factory.mktemp("outside")
    (outside / "target.txt").write_bytes(b"data")
    link = tmp_path / "link"
    try:
        os.symlink(str(outside), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("当前环境无法创建符号链接")

    entries, scanner = scan_tree(tmp_path, follow_symlinks=False)

    assert names(entries) == ["link"]
    assert entries[0].item_type is ItemType.SYMLINK
    assert scanner.statistics.files_scanned == 0  # 未跟随，target 不计入
    assert scanner.statistics.directories_scanned == 0


def test_hard_link_both_entries_yielded(tmp_path):
    original = tmp_path / "original.bin"
    original.write_bytes(b"1234567890")
    link = tmp_path / "link.bin"
    try:
        os.link(str(original), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("文件系统不支持硬链接")

    entries, scanner = scan_tree(tmp_path, filesystem=FileSystem(probe_hard_links=True))

    files = [entry for entry in entries if entry.item_type is ItemType.FILE]
    assert len(files) == 2
    identities = [entry.file_identity for entry in files]
    assert all(identity is not None for identity in identities)
    assert identities[0] == identities[1]
    # 原始计数包含两次出现（去重后的权威合计由 Aggregator 负责）
    assert scanner.statistics.bytes_scanned == 20


def test_permission_error_in_subdirectory(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "inside.txt").write_bytes(b"x")
    (tmp_path / "ok.txt").write_bytes(b"ok")

    entries, scanner = scan_tree(tmp_path, filesystem=ForbiddenFileSystem(blocked))

    assert "ok.txt" in names(entries)
    assert scanner.statistics.errors == 1
    assert scanner.error_breakdown == {"PermissionError": 1}
    assert scanner.status is ScanStatus.PARTIAL


def test_error_paths_record_blocked_directory(tmp_path):
    """被跳过的目录路径要记录下来，供 UI 说明「受影响目录」（不静默截断）。"""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "inside.txt").write_bytes(b"x")
    (tmp_path / "ok.txt").write_bytes(b"ok")

    _, scanner = scan_tree(tmp_path, filesystem=ForbiddenFileSystem(blocked))

    assert scanner.error_paths == [os.path.normpath(str(blocked))]


def test_permission_error_on_root_is_error(tmp_path):
    entries, scanner = scan_tree(tmp_path, filesystem=ForbiddenFileSystem(tmp_path))

    assert entries == []
    assert scanner.status is ScanStatus.ERROR
    assert scanner.statistics.errors == 1


def test_root_not_found_is_error(tmp_path):
    missing = tmp_path / "does_not_exist"

    entries, scanner = scan_tree(missing)

    assert entries == []
    assert scanner.status is ScanStatus.ERROR
    assert scanner.error_breakdown == {"FileNotFoundError": 1}


def test_file_disappears_during_scan(tmp_path):
    vanishing = tmp_path / "vanish.txt"
    vanishing.write_bytes(b"x")
    (tmp_path / "stable.txt").write_bytes(b"y")

    entries, scanner = scan_tree(tmp_path, filesystem=DisappearingFileSystem(vanishing))

    assert names(entries) == ["stable.txt"]
    assert scanner.statistics.errors == 1
    assert scanner.error_breakdown == {"FileNotFoundError": 1}
    assert scanner.status is ScanStatus.PARTIAL


def test_cancel_immediately(tmp_path):
    for index in range(5):
        (tmp_path / f"f{index}.txt").write_bytes(b"x")
    token = CancellationToken()
    token.cancel()

    entries, scanner = scan_tree(tmp_path, cancel_token=token)

    assert entries == []
    assert scanner.status is ScanStatus.CANCELLED


def test_cancel_mid_scan(tmp_path):
    for index in range(5):
        (tmp_path / f"f{index}.txt").write_bytes(b"x")

    class CancelAfterFirst(CancellationToken):
        def __init__(self, limit=1):
            super().__init__()
            self._seen = 0
            self._limit = limit

        def is_cancelled(self):
            self._seen += 1
            return super().is_cancelled() or self._seen > self._limit

    scanner = DirectoryScanner()
    context = ScanContext(
        root_path=str(tmp_path),
        cancel_token=CancelAfterFirst(limit=1),
    )
    entries = list(scanner.scan(str(tmp_path), context))

    assert scanner.status is ScanStatus.CANCELLED
    assert scanner.statistics is not None


def test_build_result_uses_statistics_when_no_aggregator(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"1234")

    _, scanner = scan_tree(tmp_path)
    result = scanner.build_result()

    assert result.root_path == os.path.normpath(str(tmp_path))
    assert result.total_size == 4
    assert result.file_count == 1
    assert result.error_count == 0
    assert result.status is ScanStatus.COMPLETED


def test_scan_context_defaults_enforce_p0_semantics():
    """P0-1 / P0-2 / P0-3：契约层默认值与「无超时」保证。"""
    context = ScanContext(root_path="root", cancel_token=CancellationToken())

    assert context.include_hidden is True   # P0-2：默认不跳过隐藏项
    assert context.follow_symlinks is False  # P0-3：默认不跟随链接
    # P0-1：扫描输入中不存在任何超时字段，禁止静默截断
    assert "timeout" not in {field.name for field in fields(ScanContext)}
    assert not hasattr(Settings, "SCAN_TIMEOUT")


def test_full_scan_is_not_truncated_by_time(tmp_path):
    """P0-1：遍历完整时状态必须是 COMPLETED，不存在「超时截断」路径。"""
    for index in range(30):
        (tmp_path / f"f{index}.bin").write_bytes(b"x")

    entries, scanner = scan_tree(tmp_path)

    assert len(entries) == 30
    assert scanner.status is ScanStatus.COMPLETED
