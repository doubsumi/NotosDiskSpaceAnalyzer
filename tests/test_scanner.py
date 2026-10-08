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
              follow_symlinks=False, enable_parallel_enum=False):
    """执行一次完整扫描，返回 ``(entries, scanner)``。"""
    scanner = DirectoryScanner(filesystem=filesystem)
    context = ScanContext(
        root_path=str(root),
        cancel_token=cancel_token or CancellationToken(),
        include_hidden=include_hidden,
        follow_symlinks=follow_symlinks,
        enable_parallel_enum=enable_parallel_enum,
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
    """对指定文件抛出 FileNotFoundError，模拟扫描期间文件消失。

    O4d 后扫描热路径经由 ``stat_entry``（DirEntry 快速路径，无 PathLike
    分派）获取元数据，测试替身重写该方法作为缝合点。
    """

    def __init__(self, vanished: Path):
        super().__init__()
        self.vanished = os.path.normpath(str(vanished))

    def stat_entry(self, entry, follow_symlinks=False):
        path = entry if isinstance(entry, str) else entry.path
        if os.path.normpath(path) == self.vanished:
            raise FileNotFoundError("gone")
        return super().stat_entry(entry, follow_symlinks=follow_symlinks)


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
    # O4c：取消检查降频为每 256 条目一次（目录级检查保留）。
    # 树需超过 256 条目，条目级检查才会触发；token 在第 2 次检查
    # （根目录 1 次 + 条目级第 1 次）时开始返回取消。
    for index in range(300):
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
    assert len(entries) < 300  # 取消后未扫完


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


# ----------------------------------------------------------------------
# O2 —— 目录枚举并发（TS1~TS8；先写测试后实现）
# ----------------------------------------------------------------------

def make_wide_tree(root: Path) -> Path:
    """3 层 × 每层 4 目录 × 每目录 3 文件 + 隐藏文件，供并发/串行对比。"""
    roots = [root]
    for level in range(3):
        parents = roots
        roots = []
        for index, parent in enumerate(parents):
            for fanout in range(4):
                child = parent / f"d{level}_{index}_{fanout}"
                child.mkdir()
                roots.append(child)
            for file_index in range(3):
                (parent / f"f{level}_{index}_{file_index}.bin").write_bytes(b"x" * 8)
            (parent / f".hidden_{level}_{index}").write_bytes(b"h")
    return root


def test_parallel_enum_disabled_by_default():
    """TS8：ScanContext 默认关（可一键退回单线程）。"""
    context = ScanContext(root_path="root", cancel_token=CancellationToken())
    assert context.enable_parallel_enum is False


def test_parallel_enum_matches_serial_field_by_field(tmp_path):
    """TS4 / 验收(a)：并发开/关产出逐条目逐字段相等（含 DFS 前序顺序）。"""
    tree = make_wide_tree(tmp_path)

    serial_entries, serial_scanner = scan_tree(tree)
    par_entries, par_scanner = scan_tree(tree, enable_parallel_enum=True)

    serial_keys = [
        (e.path, e.parent_path, e.item_type, e.size, e.is_hidden, e.file_identity)
        for e in serial_entries
    ]
    par_keys = [
        (e.path, e.parent_path, e.item_type, e.size, e.is_hidden, e.file_identity)
        for e in par_entries
    ]
    assert par_keys == serial_keys  # 顺序 + 内容完全一致（前序契约不变）

    assert par_scanner.status is serial_scanner.status
    assert par_scanner.statistics.files_scanned == serial_scanner.statistics.files_scanned
    assert (
        par_scanner.statistics.directories_scanned
        == serial_scanner.statistics.directories_scanned
    )
    assert par_scanner.statistics.bytes_scanned == serial_scanner.statistics.bytes_scanned
    assert par_scanner.error_breakdown == serial_scanner.error_breakdown
    assert par_scanner.error_paths == serial_scanner.error_paths
    assert par_scanner.skipped_paths == serial_scanner.skipped_paths


def test_parallel_enum_records_permission_error_identically(tmp_path):
    """TS6：预取线程内的 OSError 作为返回值交回主线程，记录与串行路径一致。"""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "inside.txt").write_bytes(b"x")
    (tmp_path / "ok.txt").write_bytes(b"ok")
    fs = ForbiddenFileSystem(blocked)

    serial_entries, serial_scanner = scan_tree(tmp_path, filesystem=fs)
    par_entries, par_scanner = scan_tree(
        tmp_path, filesystem=fs, enable_parallel_enum=True
    )

    assert par_scanner.status is serial_scanner.status is ScanStatus.PARTIAL
    assert par_scanner.error_breakdown == serial_scanner.error_breakdown
    assert par_scanner.error_paths == serial_scanner.error_paths
    assert names(par_entries) == names(serial_entries)


def test_parallel_enum_permission_on_root_is_error(tmp_path):
    """TS6：根目录枚举失败（预取/同步同集合）→ ERROR，不向调用方抛异常。"""
    entries, scanner = scan_tree(
        tmp_path, filesystem=ForbiddenFileSystem(tmp_path), enable_parallel_enum=True
    )

    assert entries == []
    assert scanner.status is ScanStatus.ERROR
    assert scanner.statistics.errors == 1


def test_parallel_enum_cancel_is_clean(tmp_path):
    """TS5 / 验收(b)：扫描中途取消 → CANCELLED，池线程在 2s 内全部退出。"""
    import threading
    import time

    tree = make_wide_tree(tmp_path)
    for directory in tree.rglob("*"):
        if directory.is_dir():
            for index in range(40):
                (directory / f"bulk_{index}.txt").write_bytes(b"x" * 4)

    class CancelAfterNTicks(CancellationToken):
        def __init__(self, limit: int):
            super().__init__()
            self._seen = 0
            self._limit = limit

        def is_cancelled(self):
            self._seen += 1
            return super().is_cancelled() or self._seen > self._limit

    scanner = DirectoryScanner()
    context = ScanContext(
        root_path=str(tree),
        cancel_token=CancelAfterNTicks(limit=5),
        enable_parallel_enum=True,
    )
    entries = list(scanner.scan(str(tree), context))  # 触发 generator 收尾（finally）

    assert scanner.status is ScanStatus.CANCELLED
    assert len(entries) < 200

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        alive = [t for t in threading.enumerate() if t.name.startswith("notos-enum")]
        if not alive:
            break
        time.sleep(0.02)
    assert not [t for t in threading.enumerate() if t.name.startswith("notos-enum")]


def test_parallel_enum_bounded_in_flight(tmp_path):
    """TS3：预取在途数有界（≤ 2 × workers），不随树规模无限领先。"""
    tree = make_wide_tree(tmp_path)

    scanner = DirectoryScanner()
    context = ScanContext(
        root_path=str(tree),
        cancel_token=CancellationToken(),
        enable_parallel_enum=True,
    )
    iterator = scanner.scan(str(tree), context)
    next(iterator)  # 消费根目录的第一个条目 → 预取已开始
    try:
        assert scanner._enum_pool is not None
        assert len(scanner._pending) <= scanner._max_in_flight
        assert scanner._max_in_flight == 2 * scanner._enum_pool._max_workers
    finally:
        iterator.close()
    assert scanner._enum_pool is None  # 收尾后池已关闭


def test_parallel_enum_results_stable_over_real_tree():
    """验收(d) 前置：真实目录（System32）并发开跑通且状态稳定（PARTIAL 系错误集固定）。"""
    root = r"C:\Windows\System32"
    if not os.path.isdir(root):
        pytest.skip("仅 Windows 环境执行")

    serial_entries, serial_scanner = scan_tree(root)
    par_entries, par_scanner = scan_tree(root, enable_parallel_enum=True)

    assert par_scanner.status is serial_scanner.status
    assert (
        par_scanner.statistics.files_scanned == serial_scanner.statistics.files_scanned
    )
    assert (
        par_scanner.statistics.directories_scanned
        == serial_scanner.statistics.directories_scanned
    )
    assert par_scanner.statistics.bytes_scanned == serial_scanner.statistics.bytes_scanned
    assert len(par_entries) == len(serial_entries)


def test_scanner_never_imports_qt():
    """TS7：线程池只在 Core 层，Scanner 模块不得引入任何 Qt 符号。"""
    import src.core.scanner as scanner_module

    qt_symbols = [
        name
        for name in vars(scanner_module)
        if name.startswith(("PyQt", "Qt", "QObj")) or "QtCore" in name or "QtGui" in name
    ]
    assert qt_symbols == []
