"""Service 层单元测试（V2）。

覆盖（§24）：
    Cancellation —— cancel immediately / cancel mid-scan / restart after cancel
    Generation   —— scan A / scan B / A finishes after B 的旧结果丢弃
    P0-1         —— ERROR 状态走 error 信号，而不是呈现截断结果

本文件先覆盖 ``ScanWorker`` 的线程适配职责：进度转发、结果/错误信号、
以及取消令牌向扫描流水线的传递；随后覆盖 ``AnalysisService`` 的
取消 / generation 守卫（无需 Qt 事件循环，直接调用纯同步流水线）。
"""

from __future__ import annotations

import os

from src.core.aggregators import DirectoryAggregator
from src.core.filesystem import FileSystem
from src.core.scan_models import ScanResult, ScanStatistics, ScanStatus
from src.core.scanner import CancellationToken, DirectoryScanner
from src.gui.scan_worker import ScanWorker
from src.services.analysis_service import AnalysisResult, AnalysisService, DisplayItem
from src.services.directory_cache import DirectoryCache, cache_key


def make_result(status: ScanStatus = ScanStatus.COMPLETED) -> ScanResult:
    statistics = ScanStatistics(
        files_scanned=1,
        directories_scanned=0,
        bytes_scanned=10,
        errors=0,
        skipped=0,
        elapsed_seconds=0.01,
    )
    return ScanResult(
        root_path="root",
        total_size=10,
        file_count=1,
        directory_count=0,
        statistics=statistics,
        status=status,
        error_count=0,
    )


def test_worker_forwards_progress_and_result():
    progress_events = []
    results = []

    def job(cancel_token, report_progress, report_preview):
        report_progress(50, "halfway")
        return make_result()

    worker = ScanWorker(job)
    worker.progress_updated.connect(lambda percent, message: progress_events.append((percent, message)))
    worker.analysis_finished.connect(results.append)

    worker.run()

    assert progress_events == [(50, "halfway")]
    assert len(results) == 1
    assert results[0].status is ScanStatus.COMPLETED


def test_worker_emits_error_on_failure():
    errors = []

    def job(cancel_token, report_progress, report_preview):
        raise RuntimeError("boom")

    worker = ScanWorker(job)
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert len(errors) == 1
    assert "boom" in errors[0]


def test_worker_passes_cancel_token_to_job():
    seen = {}

    def job(cancel_token, report_progress, report_preview):
        seen["cancelled"] = cancel_token.is_cancelled()
        return make_result(ScanStatus.CANCELLED)

    worker = ScanWorker(job)
    worker.cancel()
    results = []
    worker.analysis_finished.connect(results.append)

    worker.run()

    assert seen["cancelled"] is True
    assert results[0].status is ScanStatus.CANCELLED


# ----------------------------------------------------------------------
# AnalysisService：cancel / generation（无需 Qt 事件循环）
# ----------------------------------------------------------------------
def analysis_result(root="root", status=ScanStatus.COMPLETED) -> AnalysisResult:
    return AnalysisResult(
        root_path=root, result_type="directory", total_size=0, items=[], status=status
    )


class CancelAfter(CancellationToken):
    """在第 ``limit`` 次取消检查之后开始返回取消。"""

    def __init__(self, limit: int) -> None:
        super().__init__()
        self._limit = limit
        self._seen = 0

    def is_cancelled(self) -> bool:
        self._seen += 1
        return super().is_cancelled() or self._seen > self._limit


def test_is_running_false_without_worker():
    assert AnalysisService().is_running() is False


def test_directory_pipeline_cancel_immediately(tmp_path):
    for index in range(5):
        (tmp_path / f"f{index}.txt").write_bytes(b"x")
    service = AnalysisService()
    token = CancellationToken()
    token.cancel()

    result = service._run_directory_scan(str(tmp_path), token, lambda percent, msg: None)

    assert isinstance(result, AnalysisResult)
    assert result.status is ScanStatus.CANCELLED
    assert result.result_type == "directory"


def test_directory_pipeline_cancel_mid_scan(tmp_path):
    # O4c：取消检查降频为每 256 条目一次（目录级检查保留）。
    # 树需超过 2×256 条目；token 在第 3 次检查（根 1 次 + 条目级 2 次）时开始取消。
    for index in range(600):
        (tmp_path / f"f{index}.txt").write_bytes(b"x")
    service = AnalysisService()

    result = service._run_directory_scan(str(tmp_path), CancelAfter(limit=2), lambda p, m: None)

    assert result.status is ScanStatus.CANCELLED


def test_directory_pipeline_completes_without_cancel(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"1234")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_bytes(b"56")
    service = AnalysisService()

    result = service._run_directory_scan(str(tmp_path), CancellationToken(), lambda p, m: None)

    assert result.status is ScanStatus.COMPLETED
    assert result.total_size == 6
    assert {item.name for item in result.items} == {"a.txt", "sub"}


def test_each_analysis_gets_new_generation(monkeypatch):
    """restart after cancel：每次分析分配唯一 generation（P1-3）。"""
    service = AnalysisService()
    generations = []
    monkeypatch.setattr(
        service, "_start_directory_scan", lambda path, gen: generations.append(gen)
    )

    service.analyze_directory("A")
    service.analyze_directory("B")
    service.analyze_directory("C")

    assert generations == [1, 2, 3]


def test_stale_generation_result_is_discarded(monkeypatch):
    """scan A / scan B：A 晚于 B 完成时，A 的结果必须被丢弃（P1-3）。"""
    service = AnalysisService()
    finished = []
    service.analysis_finished.connect(finished.append)

    started = []
    monkeypatch.setattr(
        service, "_start_directory_scan", lambda path, gen: started.append((path, gen))
    )

    service.analyze_directory("A")
    service.analyze_directory("B")
    (gen_a, gen_b) = started[0][1], started[1][1]
    assert gen_a != gen_b

    result_a = analysis_result("A")
    result_b = analysis_result("B")

    service._on_finished(gen_a, result_a)  # 旧 generation 晚到 → 丢弃
    assert finished == []

    service._on_finished(gen_b, result_b)  # 当前 generation → 呈现
    assert finished == [result_b]


def test_error_status_emits_error_not_finished():
    """P0-1：ERROR 不得呈现为「完成」，必须走 error 信号。"""
    service = AnalysisService()
    errors = []
    finished = []
    service.error_occurred.connect(errors.append)
    service.analysis_finished.connect(finished.append)
    service._generation = 1

    service._on_finished(1, analysis_result("C:/gone", ScanStatus.ERROR))

    assert finished == []
    assert len(errors) == 1
    assert "C:/gone" in errors[0]


def test_stale_error_is_discarded():
    service = AnalysisService()
    errors = []
    service.error_occurred.connect(errors.append)
    service._generation = 2

    service._on_error(1, "旧错误")

    assert errors == []


def test_progress_percent_uses_known_total():
    """分母已知时给出确定性百分比（V1 风格）；未知时回到 busy（-1）。"""
    assert AnalysisService._progress_percent(0, 1000) == 0
    assert AnalysisService._progress_percent(500, 1000) == 50
    # 估算偏小（hard link 重复计数 / 缓存过期）时封顶 99，不提前显示 100
    assert AnalysisService._progress_percent(3000, 1000) == 99
    # 分母未知 → busy 态
    assert AnalysisService._progress_percent(500, None) == -1
    assert AnalysisService._progress_percent(500, 0) == -1


def test_directory_pipeline_reports_determinate_progress(tmp_path, monkeypatch):
    """传入已知大小时上报确定性百分比，而不是 busy 的 -1。"""
    monkeypatch.setattr("src.services.analysis_service._PROGRESS_BATCH", 1)
    for index in range(4):
        (tmp_path / f"f{index}.bin").write_bytes(b"x" * 10)
    service = AnalysisService()
    percents = []

    service._run_directory_scan(
        str(tmp_path), CancellationToken(), lambda p, m: percents.append(p), 40
    )

    assert percents[0] == 0
    assert percents[-1] == 99
    assert percents == sorted(percents)


def test_directory_pipeline_reports_busy_without_known_total(tmp_path):
    """没有已知大小时退回 percent=-1（GUI busy 态）。"""
    (tmp_path / "a.bin").write_bytes(b"x")
    service = AnalysisService()
    percents = []

    service._run_directory_scan(
        str(tmp_path), CancellationToken(), lambda p, m: percents.append(p)
    )

    assert percents == [-1]


class BlockedFileSystem(FileSystem):
    """对指定目录的 scandir 抛出 PermissionError，模拟无权限目录。"""

    def __init__(self, blocked) -> None:
        super().__init__()
        self._blocked = os.path.normpath(str(blocked))

    def scandir(self, path):
        if os.path.normpath(path) == self._blocked:
            raise PermissionError("access denied")
        return super().scandir(path)


def test_partial_result_carries_reason_and_affected_paths(tmp_path):
    """PARTIAL 结果要带上「原因 + 受影响目录」，供状态栏向用户解释（不静默截断）。"""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (tmp_path / "ok.bin").write_bytes(b"x")
    service = AnalysisService(BlockedFileSystem(blocked))

    result = service._run_directory_scan(
        str(tmp_path), CancellationToken(), lambda p, m: None
    )

    assert result.status is ScanStatus.PARTIAL
    assert result.skip_reason == "权限不足或文件被占用"
    assert result.affected_paths == ["blocked"]


def test_completed_result_has_no_skip_explanation(tmp_path):
    (tmp_path / "ok.bin").write_bytes(b"x")
    service = AnalysisService()

    result = service._run_directory_scan(
        str(tmp_path), CancellationToken(), lambda p, m: None
    )

    assert result.status is ScanStatus.COMPLETED
    assert result.skip_reason is None
    assert result.affected_paths == []


# ----------------------------------------------------------------------
# O8 / O9：会话级目录缓存与 Lazy 下钻
# ----------------------------------------------------------------------
def _register_result(service: AnalysisService, result: AnalysisResult) -> None:
    """模拟 worker 完成回调：把一次扫描结果送入 generation 守卫（含缓存回写）。"""
    service._on_finished(service._generation, result)


def _fingerprint(result: AnalysisResult):
    """逐字段对照指纹（statistics/scan 为缓存服务不保留的字段，不参与比较）。"""
    return (
        result.result_type,
        result.total_size,
        result.status,
        result.skip_reason,
        result.affected_paths,
        [
            (i.name, i.path, i.size, i.item_type, i.is_hidden, i.is_calculating,
             i.percentage)
            for i in result.items
        ],
    )


def test_cache_hit_never_calls_scanner(tmp_path, monkeypatch):
    """O8 硬约束：边界内下钻 DirectoryScanner 一次都不被调用，且与现场扫描逐字段相等。

    ``analyze_directory`` 命中缓存后由 worker 线程调用 ``_build_from_cache`` 装配，
    这里直接断言该装配方法（同步）零 Scanner、且结果与现场扫描一致。
    """
    (tmp_path / "big.bin").write_bytes(b"x" * 100)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "f.bin").write_bytes(b"12345")

    service = AnalysisService()
    # 全量扫描根 → 经 _on_finished 登记进缓存
    fresh = service._run_directory_scan(str(tmp_path), CancellationToken(), lambda p, m: None)
    _register_result(service, fresh)
    # 现场扫描子树作为逐字段对照
    fresh_sub = service._run_directory_scan(str(sub), CancellationToken(), lambda p, m: None)

    counts = {"n": 0}

    class CountingScanner(DirectoryScanner):
        def __init__(self, *args, **kwargs):
            counts["n"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.services.analysis_service.DirectoryScanner", CountingScanner)

    cached = service._build_from_cache(str(sub))

    assert counts["n"] == 0  # 命中路径零 DFS
    assert cached is not None
    assert cached.root_path == str(sub)
    assert _fingerprint(cached) == _fingerprint(fresh_sub)


def test_out_of_boundary_serves_preview_then_formal(tmp_path, monkeypatch):
    """O9：边界外先预览（文件精确、目录「计算中」），正式结果落地后回写缓存。"""
    (tmp_path / "big.bin").write_bytes(b"x" * 100)
    d1 = tmp_path / "d1"
    d1.mkdir()
    (d1 / "f.bin").write_bytes(b"x" * 10)

    service = AnalysisService()

    # 第一段：预览首帧（worker 线程里由 _build_preview 产出）
    preview = service._build_preview(str(tmp_path))
    assert preview is not None
    assert preview.is_preview is True
    by_type = {i.item_type: i for i in preview.items}
    assert by_type["file"].size == 100
    assert by_type["directory"].size == 0
    assert by_type["directory"].is_calculating is True
    assert "计算中" in by_type["directory"].display_name
    assert preview.total_size == 100  # 与正式口径一致：total 只含文件

    # 第二段：后台补算完成 → 正式结果 + 回写缓存
    formal = service._run_directory_scan(
        str(tmp_path), CancellationToken(), lambda p, m: None
    )
    service._on_finished(service._generation, formal)
    assert service._cache.root_count() == 1
    assert formal.is_preview is False

    # 正式结果落地后：子孙下钻零 DFS 且大小正确
    counts = {"n": 0}

    class CountingScanner(DirectoryScanner):
        def __init__(self, *args, **kwargs):
            counts["n"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.services.analysis_service.DirectoryScanner", CountingScanner)
    cached = service._build_from_cache(str(d1))

    assert counts["n"] == 0
    assert cached is not None
    assert cached.total_size == 10
    assert cached.items[0].size == 10


def test_preview_not_suppressed_for_small_dir(tmp_path):
    """方案2：预览不再被子项数门槛抑制——小目录（< MAX_DIRECTORY_ITEMS）也照常产出。"""
    (tmp_path / "only.bin").write_bytes(b"x" * 10)
    service = AnalysisService()

    preview = service._build_preview(str(tmp_path))

    assert preview is not None
    assert preview.is_preview is True
    assert len(preview.items) == 1
    assert preview.items[0].name == "only.bin"
    assert preview.items[0].size == 10


def test_cancelled_scan_not_registered(tmp_path):
    """CANCELLED 的目录表不完整，不得登记进缓存（登记条件仅 COMPLETED / PARTIAL）。"""
    (tmp_path / "f.bin").write_bytes(b"x")
    service = AnalysisService()
    token = CancellationToken()
    token.cancel()
    result = service._run_directory_scan(str(tmp_path), token, lambda p, m: None)
    assert result.status is ScanStatus.CANCELLED

    _register_result(service, result)

    assert service._cache.root_count() == 0


def test_error_scan_not_registered(tmp_path):
    service = AnalysisService()
    result = service._run_directory_scan(
        str(tmp_path / "gone"), CancellationToken(), lambda p, m: None
    )
    assert result.status is ScanStatus.ERROR

    _register_result(service, result)

    assert service._cache.root_count() == 0


def test_cache_key_matches_across_separator_and_case():
    """缓存键对大小写 / 分隔符不敏感（Windows）；POSIX 保持 normpath 口径。"""
    if os.name == "nt":
        assert cache_key(r"C:\Windows\System32") == cache_key("c:/windows/system32")
    else:
        assert cache_key("/tmp/dir") == os.path.normpath("/tmp/dir")


def test_covering_root_prefix_is_separator_bounded(tmp_path):
    """前缀判定以分隔符为界：``R`` 不得误覆盖 ``Rx``。"""
    cache = DirectoryCache()
    cache.register(str(tmp_path), DirectoryAggregator(str(tmp_path)), ScanStatus.COMPLETED)

    sibling = tmp_path.parent / (tmp_path.name + "x")
    assert cache.find_covering_root(str(sibling)) is None
    assert cache.find_covering_root(str(tmp_path / "child")) is not None
    assert cache.find_covering_root(str(tmp_path)) is not None  # path == R 亦命中


def test_cache_eviction_removes_oldest_root():
    """超过 CACHE_MAX_DIRS 时按最早登记的扫描根整体逐出。"""
    cache = DirectoryCache(max_dirs=3)
    for name in ("R1", "R2", "R3", "R4"):
        cache.register(name, DirectoryAggregator(name), ScanStatus.COMPLETED)

    assert cache.find_covering_root("R1") is None
    assert cache.stats_for("R1") is None
    assert cache.find_covering_root("R4") is not None


def test_reregister_root_replaces_sub_roots():
    """对根 R 重新登记时，R 之下的旧根以新快照为准被移除（仍被 R 覆盖）。"""
    cache = DirectoryCache()
    cache.register("R", DirectoryAggregator("R"), ScanStatus.COMPLETED)
    cache.register("R/sub", DirectoryAggregator("R/sub"), ScanStatus.COMPLETED)
    assert cache.root_count() == 2

    cache.register("R", DirectoryAggregator("R"), ScanStatus.COMPLETED)

    assert cache.root_count() == 1
    assert cache.find_covering_root("R/sub") is not None  # 仍落在 R 边界内


def test_shutdown_clears_cache(tmp_path):
    service = AnalysisService()
    fresh = service._run_directory_scan(str(tmp_path), CancellationToken(), lambda p, m: None)
    _register_result(service, fresh)
    assert service._cache.root_count() == 1

    service.shutdown()

    assert service._cache.root_count() == 0


# ----------------------------------------------------------------------
# O6 —— 内存收敛
# ----------------------------------------------------------------------

def _totals_result(*pairs) -> AnalysisResult:
    """构造带 items 的目录结果，供 _remember_totals 的 LRU 测试使用。"""
    items = [
        DisplayItem(name=os.path.basename(path), path=path, size=size, item_type="file")
        for path, size in pairs
    ]
    return AnalysisResult(
        root_path="x",
        result_type="directory",
        total_size=0,
        items=items,
        status=ScanStatus.COMPLETED,
    )


def test_known_totals_lru_evicts_oldest(monkeypatch):
    """O6c：进度分母表 LRU 有界——超上限挤最旧；命中刷新新鲜度免于被挤。"""
    monkeypatch.setattr("src.services.analysis_service._KNOWN_TOTALS_MAX", 2)
    service = AnalysisService()

    service._remember_totals(_totals_result(("C:/a", 1), ("C:/b", 2)))
    service._known_total("C:/a")  # 刷新 a 的新鲜度 → 最旧变成 b
    service._remember_totals(_totals_result(("C:/c", 3)))

    totals = service._known_totals
    assert len(totals) == 2
    assert "C:/b" not in totals  # 最久未用的被挤出
    assert service._known_total("C:/a") == 1
    assert service._known_total("C:/c") == 3


def test_register_releases_aggregator_scratch(tmp_path):
    """O6b 接线：登记缓存后释放聚合器中间数据；子树合计保留供零 DFS 下钻。"""
    (tmp_path / "f.bin").write_bytes(b"x" * 10)
    service = AnalysisService()
    result = service._run_directory_scan(str(tmp_path), CancellationToken(), lambda p, m: None)
    assert result.aggregator is not None

    _register_result(service, result)

    aggregator = result.aggregator
    assert aggregator._released is True
    assert aggregator._children == {}
    assert all(node.own_size == 0 for node in aggregator.nodes.values())
    # 缓存里的子树合计不受释放影响
    assert service._cache.stats_for(str(tmp_path)).size == 10
