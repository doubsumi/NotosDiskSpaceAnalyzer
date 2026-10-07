"""SearchService 单元测试（V2）。

覆盖（§19 / §24）：
    当前目录即时搜索（``search_entries``）、Scanner 流式搜索（``iter_matches``）、
    匹配规则（大小写不敏感子串）、hidden 策略、取消、结果形状统一（不依赖 PyQt）。
"""

from __future__ import annotations

import os

from src.core.scan_models import ItemType, ScanContext, ScanEntry
from src.core.scanner import CancellationToken
from src.services.analysis_service import DisplayItem
from src.services.search_service import SearchService


def scan_entry(path, name, parent, size=1, item_type=ItemType.FILE):
    return ScanEntry(
        path=os.path.normpath(path),
        name=name,
        parent_path=parent,
        item_type=item_type,
        size=size,
        modified_time=0.0,
        file_identity=None,
    )


# ----------------------------------------------------------------------
# 匹配规则
# ----------------------------------------------------------------------
def test_matches_is_case_insensitive_substring():
    assert SearchService.matches("Report.PDF", "report") is True
    assert SearchService.matches("report.pdf", "PORT") is True
    assert SearchService.matches("report.pdf", "pdf") is True
    assert SearchService.matches("report.pdf", "xls") is False
    assert SearchService.matches("anything", "") is False


# ----------------------------------------------------------------------
# 当前目录搜索
# ----------------------------------------------------------------------
def test_search_entries_over_display_items():
    service = SearchService()
    items = [
        DisplayItem(name="Report.pdf", path="C:/a/Report.pdf", size=10, item_type="file"),
        DisplayItem(name="photos", path="C:/a/photos", size=20, item_type="directory"),
    ]

    results = service.search_entries(items, "report")

    assert len(results) == 1
    assert results[0].path == "C:/a/Report.pdf"
    assert results[0].item_type == "file"
    assert results[0].size == 10


def test_search_entries_over_scan_entries_normalizes_type():
    service = SearchService()
    entries = [
        scan_entry("C:/a/notes.txt", "notes.txt", "C:/a"),
        scan_entry("C:/a/notes_dir", "notes_dir", "C:/a", item_type=ItemType.DIRECTORY),
    ]

    results = service.search_entries(entries, "notes")

    assert {result.item_type for result in results} == {"file", "directory"}


def test_search_entries_empty_query_returns_nothing():
    service = SearchService()
    items = [DisplayItem(name="a", path="C:/a", size=1, item_type="file")]

    assert service.search_entries(items, "") == []
    assert service.search_entries(items, "   ") == []


# ----------------------------------------------------------------------
# 流式搜索
# ----------------------------------------------------------------------
def test_iter_matches_streams_only_hits(tmp_path):
    (tmp_path / "keep_me.txt").write_bytes(b"x")
    (tmp_path / "other.txt").write_bytes(b"y")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "keep_deep.txt").write_bytes(b"z")

    service = SearchService()
    results = list(service.iter_matches(str(tmp_path), "keep"))

    assert {result.name for result in results} == {"keep_me.txt", "keep_deep.txt"}
    assert all(result.item_type == "file" for result in results)
    assert all(result.path.endswith(".txt") for result in results)


def test_iter_matches_respects_hidden_policy(tmp_path):
    (tmp_path / ".hidden_target").write_bytes(b"x")
    (tmp_path / "target.txt").write_bytes(b"y")

    service = SearchService()

    visible = list(service.iter_matches(str(tmp_path), "target", include_hidden=False))
    assert [result.name for result in visible] == ["target.txt"]

    everything = list(service.iter_matches(str(tmp_path), "target"))
    assert len(everything) == 2  # P0-2：默认包含隐藏项


def test_iter_matches_is_cancellable(tmp_path):
    for index in range(10):
        (tmp_path / f"hit_{index}.txt").write_bytes(b"x")
    token = CancellationToken()
    token.cancel()

    service = SearchService()
    results = list(service.iter_matches(str(tmp_path), "hit", cancel_token=token))

    assert results == []


def test_iter_matches_empty_query_yields_nothing(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")

    service = SearchService()
    assert list(service.iter_matches(str(tmp_path), "")) == []


def test_iter_matches_does_not_touch_filesystem_for_empty_query(tmp_path):
    """空查询必须提前返回，不得触发目录扫描。"""

    class ExplodingScanner:
        def scan(self, root_path, context):
            raise AssertionError("不应发生扫描")

    service = SearchService(scanner=ExplodingScanner())
    assert list(service.iter_matches(str(tmp_path), "  ")) == []


def test_iter_matches_uses_supplied_scanner(tmp_path):
    captured = {}

    class RecordingScanner:
        def scan(self, root_path, context):
            captured["root"] = root_path
            captured["include_hidden"] = context.include_hidden
            captured["follow_symlinks"] = context.follow_symlinks
            return iter(())

    service = SearchService(scanner=RecordingScanner())
    list(service.iter_matches(str(tmp_path), "q"))

    assert captured == {
        "root": str(tmp_path),
        "include_hidden": True,
        "follow_symlinks": False,
    }


def test_scan_context_used_by_search_has_no_timeout(tmp_path):
    """搜索复用 Scanner 契约，因此同样不含静默超时（P0-1）。"""
    from dataclasses import fields

    assert "timeout" not in {field.name for field in fields(ScanContext)}
