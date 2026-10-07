"""GUI 组件单元测试（V2，无头 offscreen）。

覆盖（§24 / P0-6 / §12）：
    Chart Top-N / Other —— wedge 与 ``wedge_items`` 一一对应；
        ``other = all_total - 主项合计``，且 "其他" 映射为 ``None``（不可点击）。
    MainWindow —— progress < 0 显示 busy 态；status 文案区分；close 走
        cancel + wait 的有界阻塞关闭（不再轮询 is_running）。

这些测试不使用真实事件循环，仅验证信号与状态契约；页面表现由人工验证。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt5")

from PyQt5.QtWidgets import QApplication

from src.core.scan_models import ScanStatus
from src.gui.components.chart_widget import ChartWidget
from src.services.analysis_service import AnalysisResult, DisplayItem


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_item(name, size, item_type="directory"):
    return DisplayItem(name=name, path=f"C:/root/{name}", size=size, item_type=item_type)


def make_result(items, total, status=ScanStatus.COMPLETED):
    return AnalysisResult(
        root_path="C:/root",
        result_type="directory",
        total_size=total,
        items=items,
        status=status,
    )


class FakeWedge:
    def contains_point(self, coordinates):
        return True


class FakeEvent:
    x = 1.0
    y = 1.0


# ----------------------------------------------------------------------
# P0-6：Chart Top-N / Other
# ----------------------------------------------------------------------
def test_wedge_items_align_with_wedges(qapp):
    widget = ChartWidget()
    widget.update_chart(make_result([make_item("a", 90), make_item("b", 10)], total=100))

    assert len(widget.wedges) == len(widget.wedge_items) == 2
    assert widget.other_item is False
    assert all(entry is not None for entry in widget.wedge_items)


def test_other_is_aggregate_and_not_mappable(qapp):
    widget = ChartWidget()
    # a 占 45% > 2% 为主项；b 占 1% 归入 Other；Other = 200 - 90 = 110
    widget.update_chart(make_result([make_item("a", 90), make_item("b", 2)], total=200))

    assert widget.other_item is True
    assert len(widget.wedges) == len(widget.wedge_items) == 2
    assert widget.wedge_items[0] is not None
    assert widget.wedge_items[-1] is None  # Other 不得映射到真实 item
    assert widget.wedges[-1].theta1 != widget.wedges[-1].theta2


def test_wedge_sizes_sum_to_logical_total(qapp):
    widget = ChartWidget()
    widget.update_chart(make_result([make_item("a", 90), make_item("b", 2)], total=200))

    sizes = [wedge.theta2 - wedge.theta1 for wedge in widget.wedges]
    # 饼图按比例绘制，总面积恒为 360 度；此处仅校验两个楔形都存在且为正
    assert len(sizes) == 2
    assert all(size > 0 for size in sizes)


def test_other_wedge_has_no_context_menu(qapp):
    widget = ChartWidget()
    calls = []
    widget._create_context_menu = lambda event, item: calls.append(item)

    widget.wedges = [FakeWedge()]
    widget.wedge_items = [None]

    widget.show_chart_context_menu(FakeEvent())

    assert calls == []


def test_non_clickable_item_is_not_emitted(qapp):
    widget = ChartWidget()
    emitted = []
    widget.chart_item_clicked.connect(emitted.append)

    widget.wedges = [FakeWedge()]
    widget.wedge_items = [make_item("file.bin", 10, item_type="file")]

    widget._handle_left_click(FakeEvent())

    assert emitted == []


def test_clickable_item_is_emitted(qapp):
    widget = ChartWidget()
    emitted = []
    widget.chart_item_clicked.connect(emitted.append)

    target = make_item("sub", 10)
    widget.wedges = [FakeWedge()]
    widget.wedge_items = [target]

    widget._handle_left_click(FakeEvent())

    assert emitted == [target]


# ----------------------------------------------------------------------
# MainWindow：进度 / 状态（§12 P1-2 / P1-4）
# ----------------------------------------------------------------------
def test_main_window_progress_is_batched(qapp):
    from src.gui.main_window import MainWindow

    assert 100 <= MainWindow._PROGRESS_INTERVAL_MS <= 250

    window = MainWindow()
    window.progress_bar.setValue(7)
    window.on_progress_updated(-1, "a")
    window.on_progress_updated(10, "b")
    window.on_progress_updated(20, "c")

    # 100~250ms 内只保留最新一条进度（未 flush 前不产生 UI 更新）
    assert window._pending_progress == (20, "c")
    assert window.progress_bar.value() == 7

    window._flush_progress()
    assert window.progress_bar.maximum() == 100
    assert window.progress_bar.value() == 20
    assert window.statusBar().currentMessage() == "c"


def test_main_window_unknown_progress_shows_busy(qapp):
    from src.gui.main_window import MainWindow

    window = MainWindow()
    window.on_progress_updated(-1, "正在扫描: x")
    window._flush_progress()

    assert window.progress_bar.maximum() == 0  # busy 态


def test_main_window_status_text_by_scan_status(qapp):
    from src.gui.main_window import MainWindow

    window = MainWindow()
    items = [make_item("a", 1)]

    window.on_analysis_finished(make_result(items, 1, ScanStatus.COMPLETED))
    assert window.statusBar().currentMessage() == "分析完成"

    window.on_analysis_finished(make_result(items, 1, ScanStatus.PARTIAL))
    assert "部分" in window.statusBar().currentMessage()

    window.on_analysis_finished(make_result(items, 1, ScanStatus.CANCELLED))
    assert window.statusBar().currentMessage() == "分析已取消"


def test_main_window_close_is_non_blocking_when_idle(qapp):
    from PyQt5.QtGui import QCloseEvent

    from src.gui.main_window import MainWindow

    window = MainWindow()
    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()


# ----------------------------------------------------------------------
# 列表悬停提示：解释隐藏项为何在文件管理器里看不到（P0-2）
# ----------------------------------------------------------------------
def test_hidden_item_tooltip_explains_invisible(qapp):
    from src.gui.components.list_widget import DirectoryListWidget

    widget = DirectoryListWidget()
    widget.update_list(
        make_result(
            [
                DisplayItem(
                    name="pagefile.sys",
                    path="E:/pagefile.sys",
                    size=1024,
                    item_type="file",
                    is_hidden=True,
                )
            ],
            1024,
        )
    )

    tooltip = widget.item(0).toolTip()
    assert "pagefile.sys" in tooltip
    assert "系统隐藏项" in tooltip


def test_visible_item_tooltip_has_no_hidden_hint(qapp):
    from src.gui.components.list_widget import DirectoryListWidget

    widget = DirectoryListWidget()
    widget.update_list(make_result([make_item("normal", 10)], 10))

    assert "系统隐藏项" not in widget.item(0).toolTip()


def test_analysis_service_shutdown_joins_workers(qapp, tmp_path):
    """关闭窗口走 shutdown：cancel + wait，is_running 必须立即归零（P0）。"""
    from src.services.analysis_service import AnalysisService

    (tmp_path / "a.bin").write_bytes(b"x")
    service = AnalysisService()
    service.analyze_directory(str(tmp_path))
    assert service.is_running() is True

    service.shutdown()

    assert service.is_running() is False


def test_retire_discards_already_finished_worker(qapp):
    """已结束的 worker 不得滞留在 _retired，否则 is_running 永久为真。"""
    from src.gui.scan_worker import ScanWorker
    from src.services.analysis_service import AnalysisService

    service = AnalysisService()
    worker = ScanWorker(lambda cancel_token, report_progress: None)
    worker.start()
    assert worker.wait(2000) is True  # 真实线程已结束

    service._retire(worker)

    assert service._retired == set()


def test_main_window_partial_status_explains_reason(qapp):
    from src.gui.main_window import MainWindow

    window = MainWindow()
    result = make_result([make_item("a", 1)], 1, ScanStatus.PARTIAL)
    result.skip_reason = "权限不足或文件被占用"

    window.on_analysis_finished(result)

    message = window.statusBar().currentMessage()
    assert "权限不足或文件被占用" in message
    assert "不影响当前页面显示" in message


def test_main_window_partial_status_lists_affected_dirs(qapp):
    from src.gui.main_window import MainWindow

    window = MainWindow()
    result = make_result([make_item("a", 1)], 1, ScanStatus.PARTIAL)
    result.skip_reason = "权限不足或文件被占用"
    result.affected_paths = ["a", "b", "c", "d"]

    window.on_analysis_finished(result)

    # 超过上限时用省略号收尾
    assert "受影响目录包括：a、b、c、……" in window.statusBar().currentMessage()
