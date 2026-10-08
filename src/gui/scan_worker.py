"""Qt 后台工作适配器（V2）。

把纯 Python ``Scanner`` 放进 Qt 的后台工作环境，是 Core 与 PyQt 之间的
**唯一桥接层**（§9）：

    GUI Thread -> ScanWorker -> Pure Python Scanner

职责
----
QThread / worker lifecycle、signals、progress forwarding、cancel、finished、error。

关键约束
--------
* ``Scanner`` 不继承 ``QThread``；本模块是扫描链路中唯一允许依赖 PyQt 的代码。
* 正常流程禁止依赖 ``terminate()``；取消通过 cancel token 让 Scanner 自然退出（§12 P1-1）。
* 事件按 batch 转发，GUI 侧 100~250ms 节流刷新（§12 P1-4）。

组合方式
--------
本适配层**不负责**聚合与结果装配，只负责线程与信号。真正的扫描流水线由
composition 层（``AnalysisService``）以 ``job`` 回调注入：

::

    def job(cancel_token, report_progress, report_preview) -> ScanResult: ...

    worker = ScanWorker(job)
    worker.progress_updated.connect(...)
    worker.preview_ready.connect(...)
    worker.analysis_finished.connect(...)
    worker.start()
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt5.QtCore import QThread, pyqtSignal

from src.core.scan_models import CancelToken
from src.core.scanner import CancellationToken

#: 扫描流水线：接收取消令牌、进度回调与预览回调，返回任意结果对象
#: （V2 中由 ``AnalysisService`` 装配为 ``AnalysisResult``）。
#: ``report_preview`` 用于 O9：扫描开始前先产出一次快速预览首帧（可选）。
ScanJob = Callable[
    [CancelToken, Callable[[int, str], None], Callable[[object], None]], object
]


class ScanWorker(QThread):
    """在后台线程执行扫描流水线的 Qt 适配器。"""

    progress_updated = pyqtSignal(int, str)
    #: O9 预览首帧：扫描开始前由 job 通过 ``report_preview`` 上报（可选）。
    preview_ready = pyqtSignal(object)
    analysis_finished = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, job: ScanJob, parent: Optional[object] = None) -> None:
        super().__init__(parent)
        self._job = job
        self.cancel_token = CancellationToken()

    def cancel(self) -> None:
        """请求取消；Scanner 会在检查点自然退出。"""
        self.cancel_token.cancel()

    def run(self) -> None:
        try:
            result = self._job(
                self.cancel_token, self._report_progress, self._report_preview
            )
            self.analysis_finished.emit(result)
        except Exception as exc:  # 不向 GUI 抛出，转为错误信号
            self.error_occurred.emit(f"扫描失败: {exc}")

    def _report_progress(self, percent: int, message: str) -> None:
        self.progress_updated.emit(percent, message)

    def _report_preview(self, result: object) -> None:
        self.preview_ready.emit(result)
