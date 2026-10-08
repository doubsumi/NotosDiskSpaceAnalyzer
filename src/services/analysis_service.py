"""分析服务（V2 composition root，§8）。

职责
----
启动分析、停止分析、管理 generation、创建 scanner + aggregator、
启动 ``ScanWorker``、汇总结果为 ``AnalysisResult``。

数据流
------
::

    MainWindow
        │
        ▼
    AnalysisService ──(job 回调)──► ScanWorker ──► DirectoryScanner
        ▲                                             │ ScanEntry stream
        └──────────── AnalysisResult ◄── DirectoryAggregator

关键约束
--------
* Core 不依赖 PyQt；本模块只负责「组合」，线程与信号由 ``ScanWorker`` 承担（§9）。
* 每次分析分配唯一 ``generation``；旧 worker 的进度 / 结果即使晚到也不得更新 UI（§P2-F / §12 P1-3）。
* 取消通过 cancel token 让 Scanner 自然退出，不调用 ``terminate()``（§12 P1-1）。
* 不设置固定扫描超时（P0-1：禁止静默 30 秒截断），完整性由 ``ScanStatus`` 表达。
* 只装配当前真正被消费的 aggregator，不为「将来可能用到」付出遍历成本（§原则 3）。
"""

from __future__ import annotations

import math
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from config.settings import Settings
from src.core.aggregators import DirectoryAggregator
from src.core.filesystem import FileSystem
from src.core.scan_models import (
    ItemType,
    ScanContext,
    ScanEntry,
    ScanResult,
    ScanStatistics,
    ScanStatus,
)
from src.core.scanner import DirectoryScanner
from src.gui.scan_worker import ScanWorker
from src.services.directory_cache import DirectoryCache, cache_key

#: 扫描过程中向 GUI 转发进度的最小条目间隔（真正的节流在 GUI 侧，§22）。
_PROGRESS_BATCH = 2000

#: O6c：进度分母表（``_known_totals``）的 LRU 上限。大目录一层可达数万子项，
#: 全量记忆会随导航无界增长；LRU 保证「最近看过的目录」始终有确定性进度分母，
#: 最久未用的被挤出（下次进入退回 busy 态，无功能损失）。
_KNOWN_TOTALS_MAX = 50_000


@dataclass
class DisplayItem:
    """展示层条目：一个磁盘或当前目录的直接子项。

    ``size`` 为 **Logical Size**（P0-5）；磁盘项额外携带 ``total_size`` /
    ``used_size`` / ``free_size``。
    """

    name: str
    path: str
    size: int
    item_type: str  # 'disk' | 'directory' | 'file' | 'symlink'
    percentage: float = 0.0
    total_size: int = 0
    used_size: int = 0
    free_size: int = 0
    #: 文件管理器默认不显示的项目（P0-2：扫描包含隐藏项，但需向用户解释）。
    is_hidden: bool = False
    #: O9 预览：子树大小尚未算出（size=0，列表显示「计算中…」）。
    is_calculating: bool = False

    @property
    def is_clickable(self) -> bool:
        """仅磁盘与目录可进入。"""
        return self.item_type in ("disk", "directory")

    @property
    def formatted_size(self) -> str:
        return _format_size(self.size)

    @property
    def display_name(self) -> str:
        if self.item_type == "disk":
            used_percent = (self.used_size / self.total_size * 100) if self.total_size > 0 else 0.0
            return (
                f"{self.name} - 已用: {_format_size(self.used_size)} / "
                f"{_format_size(self.total_size)} ({used_percent:.1f}%)"
            )
        if self.item_type == "file":
            return f"📄 {self.name} - {self.formatted_size} ({self.percentage:.1f}%)"
        if self.item_type == "symlink":
            return f"🔗 {self.name} - {self.formatted_size} ({self.percentage:.1f}%)"
        if self.is_calculating:
            return f"📁 {self.name} - 计算中…"
        return f"📁 {self.name} - {self.formatted_size} ({self.percentage:.1f}%)"


@dataclass
class AnalysisResult:
    """一次分析面向 GUI 的汇总结果（§28 架构图中的 AnalysisResult）。

    ``items`` 为当前视图的直接子项（目录分析）或磁盘列表（磁盘总览），
    按大小降序排列；``status`` 表达扫描完整性（P0-1）。
    ``scan`` 保留底层 ``ScanResult``（原始遍历计数），供诊断与后续消费者使用。
    """

    root_path: str
    result_type: str  # 'disk' | 'directory'
    total_size: int
    items: List[DisplayItem] = field(default_factory=list)
    status: ScanStatus = ScanStatus.COMPLETED
    statistics: Optional[ScanStatistics] = None
    scan: Optional[ScanResult] = None
    #: 扫描为 PARTIAL 时的原因（如「权限不足或文件被占用」），供状态栏向用户解释。
    skip_reason: Optional[str] = None
    #: 受影响路径（相对扫描根），供状态栏列出「哪些目录受了影响」。
    affected_paths: List[str] = field(default_factory=list)
    #: O9：预览结果（文件精确、目录 size=0「计算中」）；正式结果随后同 generation 到达。
    #: 跳转时机由 GUI 侧的驻留计时器决定（方案2：限时驻留 + 双轨跳转），
    #: 服务侧不再用子项数门槛抑制预览。
    is_preview: bool = False
    #: O8：目录结果的聚合器（含整张目录表）；扫描完成后由服务回写缓存。
    aggregator: Optional[DirectoryAggregator] = None

    @property
    def path(self) -> str:
        """兼容既有 GUI 对 ``result.path`` 的访问。"""
        return self.root_path


def _format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    units = Settings.SIZE_UNITS
    index = int(math.floor(math.log(size_bytes, 1024)))
    index = min(index, len(units) - 1)
    value = round(size_bytes / math.pow(1024, index), 2)
    return f"{value} {units[index]}"


class AnalysisService(QObject):
    """扫描链路的 composition root；对外仅暴露既有信号契约。"""

    analysis_started = pyqtSignal()
    analysis_finished = pyqtSignal(object)
    progress_updated = pyqtSignal(int, str)
    error_occurred = pyqtSignal(str)

    def __init__(self, filesystem: Optional[FileSystem] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._fs = filesystem or FileSystem()
        self._worker: Optional[ScanWorker] = None
        #: 已取消或已完成但线程尚未退出的 worker，保留引用直到线程真正结束，
        #: 避免 QThread 被提前析构（``QThread: Destroyed while thread is still running``）。
        self._retired: set = set()
        self._generation = 0
        self.last_result: Optional[AnalysisResult] = None
        #: path → 该路径上次已知的 Logical Size（仅存内存，退出即消失），
        #: 用于估算扫描进度分母，恢复 V1 的确定性进度条。
        # O6c：进度分母表，LRU 有界（见 _KNOWN_TOTALS_MAX），不再随导航无界增长。
        self._known_totals: OrderedDict = OrderedDict()
        #: O8 会话级目录缓存：边界内下钻零 DFS（仅主线程访问，无需加锁）。
        self._cache = DirectoryCache(max_dirs=Settings.CACHE_MAX_DIRS)

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    def analyze_disks(self) -> None:
        """分析所有磁盘（总览）。"""
        self._begin(None)

    def analyze_directory(self, path: str, silent: bool = False) -> None:
        """分析指定目录。

        ``silent=True`` 时不发 ``analysis_started``——GUI 留在原页面展示进度，
        跳转时机由 GUI 的驻留计时器决定（方案2：限时驻留 + 双轨跳转）。
        """
        self._begin(path, silent=silent)

    def refresh_directory(self, path: str, silent: bool = False) -> None:
        """刷新指定目录：使其子树缓存失效后重新分析（P1-1 刷新语义）。

        失效后 ``path`` 不再被任何已扫描根覆盖，从而强制走 O9（预览 + 全量
        重扫），得到一份新鲜快照；其他缓存不受影响。
        """
        root = self._fs.normalize(path) or path
        self._cache.invalidate(root)
        self.analyze_directory(root, silent=silent)

    def stop_analysis(self) -> None:
        """请求停止当前分析：取消 token + 自然退出，不阻塞、不 terminate。"""
        self._cancel_current()

    def is_running(self) -> bool:
        """是否有分析仍在进行（含已取消但尚未退出的 worker）。

        GUI 关闭窗口时用它做非阻塞轮询（§12 P1-2），不 sleep、不阻塞事件循环。
        """
        return self._worker is not None or bool(self._retired)

    # ------------------------------------------------------------------
    # 启动 / 取消
    # ------------------------------------------------------------------
    def _begin(self, path: Optional[str], silent: bool = False) -> None:
        self._cancel_current()
        self._generation += 1
        generation = self._generation
        if not silent:
            self.analysis_started.emit()

        if path is None:
            self._emit_disks(generation)
            return
        root = self._fs.normalize(path) or path
        if self._cache.find_covering_root(root) is not None:
            # O8 硬约束：落在已扫描边界内 → 零 DFS 直接服务（不重扫 / 不补扫）。
            self._serve_from_cache(root, generation)
            return
        # O9：边界外 → 预览 + 全量补算都由 worker 产出（P1-2：不阻塞 UI 线程）。
        self._start_directory_scan(root, generation)

    def _cancel_current(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        worker.cancel()
        self._retire(worker)

    def _retire_current(self) -> None:
        """释放当前 worker 的引用，但保证 QThread 真正结束前不被析构。

        正常完成 / 出错的 worker 同样要等 ``finished`` 信号后再释放，否则
        CPython 引用计数会在 ``analysis_finished`` 回调里立刻析构 QThread，
        而底层线程可能还在收尾，触发 ``QThread: Destroyed while thread is still running``。
        """
        worker = self._worker
        self._worker = None
        self._retire(worker)

    def _retire(self, worker) -> None:
        """把 worker 挂到 ``_retired`` 直到 ``finished`` 信号到达。

        必须先 connect 再检查 ``isFinished()``：``run()`` 结束与 ``finished``
        信号发出的时序不定，若信号已经发出后才 connect，这个连接永远不会被
        触发，worker 就会滞留在 ``_retired`` 中使 ``is_running()`` 永久为真。
        因此 connect 之后再用 ``isFinished()`` 兜底，确保不会有僵尸引用。
        """
        if worker is None:
            return
        self._retired.add(worker)
        worker.finished.connect(lambda w=worker: self._retired.discard(w))
        if worker.isFinished():
            self._retired.discard(worker)

    def shutdown(self, timeout_ms: int = 2000) -> None:
        """关闭窗口时调用：取消所有 worker 并等待线程真正退出。

        必须在主线程调用。与「轮询 is_running()」不同，这里是有界阻塞：
        cancel 后 Scanner 会在下一个检查点自然退出，通常几毫秒即返回；
        万一超时，最后兜底 ``terminate()``，保证关闭窗口一定能结束进程，
        且不会在线程仍在运行时析构 QThread。
        """
        workers = []
        if self._worker is not None:
            workers.append(self._worker)
        workers.extend(self._retired)
        self._worker = None
        self._retired.clear()

        # 让在途回调全部失效，关闭过程中不再更新 UI；O8 会话级缓存一并清空。
        self._generation += 1
        self._cache.clear()

        if not workers:
            return

        for worker in workers:
            worker.cancel()
        # 所有 worker 共享一个总预算，避免滞留 worker 逐个等待把关闭拖长。
        deadline = time.monotonic() + timeout_ms / 1000.0
        for worker in workers:
            if not worker.isRunning():
                continue
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms > 0:
                worker.wait(remaining_ms)
            if worker.isRunning():  # 最后兜底：不许有线程在退出时被析构
                worker.terminate()
                worker.wait(200)

    # ------------------------------------------------------------------
    # 磁盘总览
    # ------------------------------------------------------------------
    def _emit_disks(self, generation: int) -> None:
        try:
            mounts = self._fs.list_disks()
        except Exception as exc:  # 平台 / 权限异常统一转为错误信号
            self.error_occurred.emit(f"读取磁盘信息失败: {exc}")
            return

        total_used = sum(mount.used for mount in mounts)
        items: List[DisplayItem] = []
        for mount in mounts:
            item = DisplayItem(
                name=mount.name,
                path=mount.mountpoint,
                size=mount.used,
                item_type="disk",
                total_size=mount.total,
                used_size=mount.used,
                free_size=mount.free,
            )
            item.percentage = (mount.used / total_used * 100) if total_used else 0.0
            items.append(item)
        items.sort(key=lambda entry: entry.size, reverse=True)

        result = AnalysisResult(
            root_path="",
            result_type="disk",
            total_size=total_used,
            items=items,
            status=ScanStatus.COMPLETED,
        )
        if generation != self._generation:
            return
        self.last_result = result
        self._remember_totals(result)
        self.analysis_finished.emit(result)

    # ------------------------------------------------------------------
    # 目录扫描
    # ------------------------------------------------------------------
    def _start_directory_scan(self, path: str, generation: int) -> None:
        root = self._fs.normalize(path) or path
        # 进度分母取自上次已知的大小；取不到则为 None（GUI 显示 busy 态）。
        expected_total = self._known_total(path)

        def job(cancel_token, report_progress, report_preview):
            # O9 / 方案2：预览先于全量扫描，两者都在 worker 线程产出（P1-2）。
            preview = self._build_preview(root)
            if preview is not None and not cancel_token.is_cancelled():
                report_preview(preview)
            return self._run_directory_scan(root, cancel_token, report_progress, expected_total)

        worker = ScanWorker(job)
        worker.progress_updated.connect(
            lambda percent, message: self._on_progress(generation, percent, message)
        )
        worker.preview_ready.connect(
            lambda result: self._on_preview(generation, result)
        )
        worker.analysis_finished.connect(
            lambda result: self._on_finished(generation, result)
        )
        worker.error_occurred.connect(
            lambda message: self._on_error(generation, message)
        )
        self._worker = worker
        worker.start()

    # ------------------------------------------------------------------
    # O8 缓存命中 / O9 预览（下钻链路，均在 worker 线程装配，零 DFS）
    # ------------------------------------------------------------------
    def _serve_from_cache(self, root: str, generation: int) -> None:
        """O8 命中：一次 scandir 取顶层新鲜度 + 缓存表 O(1) 子树大小。

        装配在 worker 线程完成（P1-2：命中路径不阻塞 UI 线程）。只读访问
        ``_cache``：主线程在上一轮 ``_on_finished`` 之后不会再写缓存，安全。
        """

        def job(cancel_token, report_progress, report_preview):
            try:
                result = self._build_from_cache(root)
            except OSError:
                result = None
            if result is None:
                # 根已不可访问（被删除 / 权限变化）：与扫描失败同语义，不做重扫兜底。
                return AnalysisResult(
                    root_path=root,
                    result_type="directory",
                    total_size=0,
                    status=ScanStatus.ERROR,
                )
            return result

        worker = ScanWorker(job)
        worker.analysis_finished.connect(
            lambda result: self._on_finished(generation, result)
        )
        worker.error_occurred.connect(
            lambda message: self._on_error(generation, message)
        )
        self._worker = worker
        worker.start()

    def _build_from_cache(self, root: str) -> Optional[AnalysisResult]:
        """从缓存目录表组装结果：文件大小取自本次 scandir，目录大小 O(1) 查表。

        P2-3：仅当当前目录**就是**被扫描的根时，才沿用该根的状态 / 跳过原因 /
        受影响路径；子目录命中缓存时其自身扫描状态未被记录，按「快照视图」以
        ``COMPLETED`` 呈现，不再把覆盖根的整体 PARTIAL 状态误导到子目录上。
        """
        record = self._cache.find_covering_root(root)
        root_stats = self._cache.stats_for(root)
        if record is None or root_stats is None:
            return None
        items: List[DisplayItem] = []
        with self._fs.scandir(root) as iterator:
            for entry in iterator:
                items.append(self._display_item_from_entry(entry, preview=False))
        total = root_stats.size
        for item in items:
            item.percentage = (item.size / total * 100) if total else 0.0
        items.sort(key=lambda item: item.size, reverse=True)
        is_scan_root = record.key == cache_key(root)
        return AnalysisResult(
            root_path=root,
            result_type="directory",
            total_size=total,
            items=items,
            status=record.status if is_scan_root else ScanStatus.COMPLETED,
            skip_reason=record.skip_reason if is_scan_root else None,
            affected_paths=list(record.affected_paths) if is_scan_root else [],
        )

    def _build_preview(self, root: str) -> Optional[AnalysisResult]:
        """O9 预览：一次 scandir 产出首帧——文件精确、目录显示「计算中…」。

        在 worker 线程执行（P1-2）；失败返回 ``None``，正式扫描随后会给出
        ERROR 结果。不做子项数门槛抑制——跳转时机交给 GUI 的驻留计时器。
        """
        try:
            items: List[DisplayItem] = []
            with self._fs.scandir(root) as iterator:
                for entry in iterator:
                    items.append(self._display_item_from_entry(entry, preview=True))
        except OSError:
            return None
        # 与正式结果同口径：total 只含文件（符号链接不计入）。
        total = sum(item.size for item in items if item.item_type == "file")
        for item in items:
            item.percentage = (item.size / total * 100) if total else 0.0
        items.sort(key=lambda item: item.size, reverse=True)
        return AnalysisResult(
            root_path=root,
            result_type="directory",
            total_size=total,
            items=items,
            status=ScanStatus.COMPLETED,
            is_preview=True,
        )

    def _display_item_from_entry(self, entry, *, preview: bool) -> DisplayItem:
        """把一次 ``scandir`` 的 DirEntry 转为展示条目（O8 服务 / O9 预览共用）。

        文件 / 符号链接大小取自枚举缓存 stat（O3 同款，零 lstat）；目录大小
        O8 从缓存表 O(1) 查得，O9 预览置 0 并标记 ``is_calculating``。
        """
        item_type = self._fs.classify(entry)
        size = 0
        is_calculating = False
        if item_type is ItemType.DIRECTORY:
            if not preview:
                stats = self._cache.stats_for(entry.path)
                size = stats.size if stats is not None else 0
            else:
                is_calculating = True  # size 保持 0，列表显示「计算中…」
        else:
            try:
                size = self._fs.stat_entry(entry, follow_symlinks=False).st_size
            except OSError:
                size = 0  # 条目在枚举后消失：按 0 处理，正式扫描会记录该错误
        return DisplayItem(
            name=entry.name,
            path=entry.path,
            size=size,
            item_type=(
                "directory" if item_type is ItemType.DIRECTORY
                else "symlink" if item_type is ItemType.SYMLINK
                else "file"
            ),
            is_hidden=self._fs.is_hidden(entry),
            is_calculating=is_calculating,
        )

    def _run_directory_scan(
        self, root: str, cancel_token, report_progress, expected_total: Optional[int] = None
    ) -> AnalysisResult:
        """在 worker 线程内执行的纯扫描流水线（可在无 Qt 环境下直接调用）。

        ``expected_total`` 为该项的已知 Logical Size（来自上一次结果），作为进度
        分母以恢复 V1 的确定性进度条；为 None / 非正时退回 ``percent=-1``（busy 态）。
        """
        scanner = DirectoryScanner(self._fs)
        context = ScanContext(
            root_path=root,
            cancel_token=cancel_token,
            include_hidden=True,   # P0-2：默认不跳过隐藏项
            follow_symlinks=False,  # P0-3：不跟随链接，避免 cycle / 重复遍历
        )
        directory = DirectoryAggregator(root)

        denominator = expected_total if expected_total and expected_total > 0 else None
        report_progress(0 if denominator else -1, "正在扫描...")
        seen = 0
        scanned_bytes = 0
        root_children: List[ScanEntry] = []

        # 快速路径（B2）：直接消费 scanner 的共享遍历核心，把「事实」累加进
        # 聚合器，不经 ScanEntry / 逐条 yield——消除每条目的对象构造与生成器
        # 停机/恢复，盘级加载显著逼近 V1.1.1；仅对根的直接子项构造 ScanEntry
        # （供 _assemble_directory_result 展示，数量级小）。
        walk = scanner._walk(root, context)
        try:
            for parent, batch in walk:
                is_root = parent == root
                for entry, item_type, stat_result, hidden, identity in batch:
                    if item_type is ItemType.FILE:
                        directory.add_file(parent, stat_result.st_size, identity)
                        scanned_bytes += stat_result.st_size
                        if is_root:
                            root_children.append(
                                ScanEntry(
                                    path=entry.path, name=entry.name, parent_path=parent,
                                    item_type=ItemType.FILE, size=stat_result.st_size,
                                    modified_time=stat_result.st_mtime,
                                    file_identity=identity, is_hidden=hidden,
                                )
                            )
                    elif item_type is ItemType.DIRECTORY:
                        directory.add_directory(entry.path, parent)
                        if is_root:
                            root_children.append(
                                ScanEntry(
                                    path=entry.path, name=entry.name, parent_path=parent,
                                    item_type=ItemType.DIRECTORY, size=0,
                                    modified_time=None, file_identity=None, is_hidden=hidden,
                                )
                            )
                    else:  # SYMLINK（fast 路径只有 follow_symlinks=False）
                        if is_root:
                            size, modified = scanner._link_metadata(entry)
                            root_children.append(
                                ScanEntry(
                                    path=entry.path, name=entry.name, parent_path=parent,
                                    item_type=ItemType.SYMLINK, size=size,
                                    modified_time=modified, file_identity=None, is_hidden=hidden,
                                )
                            )
                    seen += 1
                    if seen % _PROGRESS_BATCH == 0:
                        report_progress(
                            self._progress_percent(scanned_bytes, denominator),
                            f"正在扫描: {entry.name}",
                        )
        finally:
            walk.close()

        scan = scanner.build_result(
            root_path=root,
            total_size=directory.total_size,
            file_count=directory.file_count,
            directory_count=directory.directory_count,
        )
        skip_reason, affected_paths = self._summarize_incomplete(root, scan, scanner)
        return self._assemble_directory_result(
            root, scan, directory, root_children, skip_reason, affected_paths
        )

    def _assemble_directory_result(
        self,
        root: str,
        scan: ScanResult,
        directory: DirectoryAggregator,
        root_children: List[ScanEntry],
        skip_reason: Optional[str] = None,
        affected_paths: Optional[List[str]] = None,
    ) -> AnalysisResult:
        total = directory.total_size
        items: List[DisplayItem] = []
        for entry in root_children:
            if entry.item_type is ItemType.DIRECTORY:
                stats = directory.stats_for(entry.path)
                size = stats.size if stats is not None else 0
                item_type = "directory"
            elif entry.item_type is ItemType.SYMLINK:
                size = entry.size
                item_type = "symlink"
            else:
                size = entry.size
                item_type = "file"
            items.append(
                DisplayItem(
                    name=entry.name,
                    path=entry.path,
                    size=size,
                    item_type=item_type,
                    # O3：隐藏位来自扫描期的枚举缓存，装配阶段零 syscall。
                    is_hidden=entry.is_hidden,
                )
            )

        for item in items:
            item.percentage = (item.size / total * 100) if total else 0.0
        items.sort(key=lambda entry: entry.size, reverse=True)

        return AnalysisResult(
            root_path=root,
            result_type="directory",
            total_size=total,
            items=items,
            status=scan.status,
            statistics=scan.statistics,
            scan=scan,
            skip_reason=skip_reason,
            affected_paths=affected_paths or [],
            aggregator=directory,  # O8：供 _on_finished 回写缓存（整张目录表）
        )

    @staticmethod
    def _summarize_incomplete(root: str, scan: ScanResult, scanner) -> tuple:
        """把「被跳过」翻译成给用户看的原因与受影响路径（P0-1：不静默截断）。

        只有 ``PARTIAL`` 才需要解释：``errors`` 表示条目无法访问，
        ``skipped`` 表示按扫描策略排除（如关闭隐藏项）。返回
        ``(reason, affected_paths)``，非 PARTIAL 时返回 ``(None, [])``。
        """
        statistics = scan.statistics
        if scan.status is not ScanStatus.PARTIAL or statistics is None:
            return None, []
        if statistics.errors:
            reason = "权限不足或文件被占用"
            raw_paths = scanner.error_paths
        else:
            reason = "扫描策略排除"
            raw_paths = scanner.skipped_paths
        return reason, AnalysisService._relative_paths(root, raw_paths)

    @staticmethod
    def _relative_paths(root: str, paths: List[str]) -> List[str]:
        """把绝对路径转成相对 ``root`` 的展示路径；去重并保持出现顺序。"""
        seen = set()
        result: List[str] = []
        for path in paths or []:
            try:
                relative = os.path.relpath(path, root)
            except ValueError:  # 跨盘符等无法求相对路径
                relative = path
            if relative in seen:
                continue
            seen.add(relative)
            result.append(relative)
        return result

    # ------------------------------------------------------------------
    # 进度分母（仅内存，退出即消失）
    # ------------------------------------------------------------------
    def _known_total(self, path: str) -> Optional[int]:
        """取该路径上次已知的大小作为进度分母；取不到返回 None。

        命中时 ``move_to_end`` 维护 LRU 新鲜度。
        """
        key = self._fs.normalize(path)
        size = self._known_totals.get(key)
        if size is not None:
            self._known_totals.move_to_end(key)
        return size

    def _remember_totals(self, result: AnalysisResult) -> None:
        """记住本次结果各项的大小，供下次进入该项时估算进度分母。

        进磁盘时记磁盘已用空间（``used_size``），进目录时记其 Logical Size。
        超过 ``_KNOWN_TOTALS_MAX`` 时按 LRU 从最旧端挤出（O6c）。
        """
        totals = self._known_totals
        for item in result.items:
            size = item.used_size if item.item_type == "disk" else item.size
            key = self._fs.normalize(item.path)
            if key in totals:
                totals.move_to_end(key)
            totals[key] = size
        while len(totals) > _KNOWN_TOTALS_MAX:
            totals.popitem(last=False)

    @staticmethod
    def _progress_percent(scanned_bytes: int, denominator: Optional[int]) -> int:
        """按「已扫描字节 / 已知大小」换算百分比；分母未知时返回 -1（busy 态）。

        封顶 99：已知大小可能偏小（缓存值过期、hard link 重复计数），
        避免在扫描真正结束前显示 100%；100% 由扫描结束时的 UI 复位表达。
        """
        if not denominator:
            return -1
        return min(99, int(scanned_bytes / denominator * 100))

    # ------------------------------------------------------------------
    # worker 回调（generation 守卫）
    # ------------------------------------------------------------------
    def _on_progress(self, generation: int, percent: int, message: str) -> None:
        if generation != self._generation:
            return
        self.progress_updated.emit(percent, message)

    def _on_preview(self, generation: int, result: AnalysisResult) -> None:
        """O9 预览首帧：直接转发给 GUI（由 GUI 的驻留计时器决定是否跳页）。

        不写缓存、不写 ``_remember_totals``（目录 size=0 会污染进度分母）、
        不 retire worker（全量扫描仍在进行）。
        """
        if generation != self._generation:
            return
        self.analysis_finished.emit(result)

    def _on_finished(self, generation: int, result: AnalysisResult) -> None:
        if generation != self._generation:
            return
        self._retire_current()
        if isinstance(result, AnalysisResult) and result.status is ScanStatus.ERROR:
            self.error_occurred.emit(f"无法完成分析: {result.root_path or '磁盘'}")
            return
        if (
            result.result_type == "directory"
            and result.aggregator is not None
            and result.status in (ScanStatus.COMPLETED, ScanStatus.PARTIAL)
        ):
            # O8 回写：整张目录表合并进缓存并登记该根 → 其子孙下钻全部零 DFS。
            # CANCELLED / ERROR 的表不完整，不登记。
            self._cache.register(
                result.root_path,
                result.aggregator,
                result.status,
                skip_reason=result.skip_reason,
                affected_paths=result.affected_paths,
            )
            # O6b：目录表已由缓存持有（_dirs 原样保留），释放扫描期中间数据。
            result.aggregator.release_scratch()
        self.last_result = result
        self._remember_totals(result)
        self.analysis_finished.emit(result)

    def _on_error(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self._retire_current()
        self.error_occurred.emit(message)
