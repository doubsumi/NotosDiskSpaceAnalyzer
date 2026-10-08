"""Aggregator 单元测试（V2）。

覆盖（§24）：
    directory total / extension statistics / Top-K / Other /
    file count / nested aggregation / hard link 去重
"""

from __future__ import annotations

import os

from src.core.aggregators import (
    NO_EXTENSION,
    DirectoryAggregator,
    FileTypeAggregator,
    TopKAggregator,
)
from src.core.filesystem import StatFileIdentity
from src.core.scan_models import ItemType, ScanContext, ScanEntry
from src.core.scanner import CancellationToken, DirectoryScanner

ROOT = os.path.normpath("C:\\root")


def file_entry(path, parent, size, identity=None):
    return ScanEntry(
        path=os.path.normpath(path),
        name=os.path.basename(path),
        parent_path=parent,
        item_type=ItemType.FILE,
        size=size,
        modified_time=0.0,
        file_identity=identity,
    )


def dir_entry(path, parent):
    return ScanEntry(
        path=os.path.normpath(path),
        name=os.path.basename(path),
        parent_path=parent,
        item_type=ItemType.DIRECTORY,
        size=0,
        modified_time=None,
        file_identity=None,
    )


def build_tree_entries():
    return [
        dir_entry(f"{ROOT}\\A", ROOT),
        file_entry(f"{ROOT}\\A\\a1.bin", f"{ROOT}\\A", 100),
        dir_entry(f"{ROOT}\\A\\B", f"{ROOT}\\A"),
        file_entry(f"{ROOT}\\A\\B\\b1.bin", f"{ROOT}\\A\\B", 50),
        file_entry(f"{ROOT}\\top.txt", ROOT, 10),
    ]


def test_directory_aggregation_nested_totals():
    aggregator = DirectoryAggregator(ROOT)
    for entry in build_tree_entries():
        aggregator.consume(entry)

    assert aggregator.total_size == 160
    assert aggregator.file_count == 3
    # directory_count 为子树内的目录总数（A、B）
    assert aggregator.directory_count == 2

    a = aggregator.stats_for(f"{ROOT}\\A")
    b = aggregator.stats_for(f"{ROOT}\\A\\B")
    assert a.size == 150
    assert a.file_count == 2
    assert a.directory_count == 1
    assert b.size == 50
    assert b.file_count == 1


def test_directory_children_sorted_by_size():
    aggregator = DirectoryAggregator(ROOT)
    for entry in build_tree_entries():
        aggregator.consume(entry)

    assert [node.path for node in aggregator.children_of(ROOT)] == [f"{ROOT}\\A"]
    assert [node.path for node in aggregator.children_of(f"{ROOT}\\A")] == [f"{ROOT}\\A\\B"]


def test_directory_aggregation_dedups_hard_links():
    shared = StatFileIdentity(7, 42)
    aggregator = DirectoryAggregator(ROOT)
    aggregator.consume(file_entry(f"{ROOT}\\x.bin", ROOT, 100, identity=shared))
    aggregator.consume(file_entry(f"{ROOT}\\y.bin", ROOT, 100, identity=shared))

    assert aggregator.total_size == 100
    assert aggregator.file_count == 1


def test_directory_incremental_finalize_is_stable():
    aggregator = DirectoryAggregator(ROOT)
    aggregator.consume(file_entry(f"{ROOT}\\a.bin", ROOT, 10))
    assert aggregator.total_size == 10
    aggregator.consume(file_entry(f"{ROOT}\\b.bin", ROOT, 5))
    # 二次 finalize 不得把之前的合计再累加一次
    assert aggregator.total_size == 15


def test_release_scratch_preserves_totals_and_blocks_consume():
    """O6b：release 后子树合计原样保留（缓存层继续可用），后续 consume 被忽略。"""
    aggregator = DirectoryAggregator(ROOT)
    for entry in build_tree_entries():
        aggregator.consume(entry)
    before = {
        path: (node.size, node.file_count, node.directory_count)
        for path, node in aggregator.nodes.items()
    }

    aggregator.release_scratch()

    after = {
        path: (node.size, node.file_count, node.directory_count)
        for path, node in aggregator.nodes.items()
    }
    assert after == before
    assert all(node.own_size == 0 for node in aggregator.nodes.values())
    assert aggregator._children == {}
    assert aggregator._identities == set()
    # release 后 consume 被忽略：合计不变
    aggregator.consume(file_entry(f"{ROOT}\\late.bin", ROOT, 999))
    assert aggregator.total_size == before[ROOT][0]


def test_file_type_statistics():
    aggregator = FileTypeAggregator()
    aggregator.consume(file_entry(f"{ROOT}\\a.JPG", ROOT, 300))
    aggregator.consume(file_entry(f"{ROOT}\\b.jpg", ROOT, 100))
    aggregator.consume(file_entry(f"{ROOT}\\readme", ROOT, 50))
    aggregator.consume(dir_entry(f"{ROOT}\\dir", ROOT))  # 目录不参与

    stats = {node.extension: node for node in aggregator.stats()}
    assert stats[".jpg"].count == 2
    assert stats[".jpg"].size == 400
    assert stats[NO_EXTENSION].count == 1
    assert aggregator.total_size == 450
    assert aggregator.total_count == 3


def test_top_k_and_other():
    aggregator = TopKAggregator(k=3)
    for index, size in enumerate([1, 2, 3, 4, 5]):
        aggregator.consume(file_entry(f"{ROOT}\\f{index}.bin", ROOT, size))

    top = aggregator.top()
    assert [entry.size for entry in top] == [5, 4, 3]
    assert aggregator.total_size == 15
    assert aggregator.top_size() == 12
    assert aggregator.other_size() == 3
    assert aggregator.other_count() == 2

    labelled = aggregator.top_with_other()
    assert labelled[-1][0] == "Other"
    assert labelled[-1][1] == 3
    assert labelled[-1][2] is None  # Other 不可点击


def test_top_k_without_other_when_fewer_files():
    aggregator = TopKAggregator(k=10)
    aggregator.consume(file_entry(f"{ROOT}\\only.bin", ROOT, 7))

    assert aggregator.other_count() == 0
    assert [label for label, _, _ in aggregator.top_with_other()] == ["only.bin"]


def test_aggregators_over_real_scan(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.dat").write_bytes(b"0" * 120)
    (tmp_path / "b.txt").write_bytes(b"0" * 30)

    scanner = DirectoryScanner()
    context = ScanContext(root_path=str(tmp_path), cancel_token=CancellationToken())
    root = os.path.normpath(str(tmp_path))

    directory = DirectoryAggregator(root)
    file_types = FileTypeAggregator()
    top_k = TopKAggregator(k=5)
    for entry in scanner.scan(str(tmp_path), context):
        directory.consume(entry)
        file_types.consume(entry)
        top_k.consume(entry)

    assert directory.total_size == 150
    assert directory.file_count == 2
    assert directory.directory_count == 1
    assert file_types.total_size == 150
    assert top_k.other_count() == 0
    assert [entry.name for entry in top_k.top()] == ["x.dat", "b.txt"]
