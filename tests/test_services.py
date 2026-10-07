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

from src.core.filesystem import FileSystem
from src.core.scan_models import ScanResult, ScanStatistics, ScanStatus
from src.core.scanner import CancellationToken
from src.gui.scan_worker import ScanWorker
from src.services.analysis_service import AnalysisResult, AnalysisService


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

    def job(cancel_token, report_progress):
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

    def job(cancel_token, report_progress):
        raise RuntimeError("boom")

    worker = ScanWorker(job)
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert len(errors) == 1
    assert "boom" in errors[0]


def test_worker_passes_cancel_token_to_job():
    seen = {}

    def job(cancel_token, report_progress):
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
    for index in range(20):
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
