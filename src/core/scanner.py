"""纯 Python 目录扫描器（V2 最核心的文件）。

职责（§6）
----------
目录遍历、文件发现、目录发现、metadata 获取、取消检查、
扫描状态、扫描统计、异常分类捕获。

技术
----
``os.scandir`` + ``DirEntry`` + 迭代式 DFS；每个条目尽量只获取一次 metadata。

边界（重要）
------------
Scanner **不依赖 PyQt**，也**不知道** Aggregator / SearchService / GUI / ScanWorker。

    Scanner discovers facts. Consumers interpret facts.

预期 API
--------
::

    class DirectoryScanner:
        def scan(self, root_path: str, context: ScanContext) -> Iterator[ScanEntry]:
            ...

产出顺序契约（目录条目先于其子条目，即 DFS 前序）见 ``scan_models`` 模块 docstring。

统计与状态
----------
* ``ScanEntry`` 流是唯一的产出；扫描结束后可读取
  ``scanner.statistics`` / ``scanner.status`` / ``scanner.error_breakdown``。
* ``statistics`` 是**原始遍历计数**（含 hard link 重复），去重后的权威汇总由
  Aggregator 计算；两者最终由 composition 层（AnalysisService / ScanWorker）装配为
  ``ScanResult``。
* 目录条目不带 ``modified_time``（不为此多一次 ``stat``），文件条目带。
* ``include_hidden=False`` 时被排除的条目计入 ``skipped``。
* 根路径不可访问 → ``ScanStatus.ERROR``；cancel token 触发 → ``CANCELLED``；
  遍历完成但有 ``skipped`` / ``errors`` → ``PARTIAL``。
"""

from __future__ import annotations

import os
import stat as stat_module
import threading
import time
from typing import Iterator, Optional

from src.core.filesystem import FileSystem
from src.core.scan_models import (
    ItemType,
    ScanContext,
    ScanEntry,
    ScanResult,
    ScanStatistics,
    ScanStatus,
)

#: 记录被排除条目路径的上限：仅用于让 UI 说明「受影响目录」，
#: 无需全量，避免超大目录下无界增长。
_MAX_RECORDED_PATHS = 50


class CancellationToken:
    """``CancelToken`` 的具体实现，线程安全（Scanner / GUI 跨线程共享）。"""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


class DirectoryScanner:
    """纯 Python、单线程、单次 traversal 的目录扫描器。"""

    def __init__(self, filesystem: Optional[FileSystem] = None) -> None:
        self.fs = filesystem or FileSystem()
        self.root_path: Optional[str] = None
        self.statistics: Optional[ScanStatistics] = None
        self.status: ScanStatus = ScanStatus.ERROR
        self.error_breakdown: dict = {}
        #: 因错误 / 策略被排除的条目路径，供 UI 解释「哪些目录受影响」。
        self.error_paths: list = []
        self.skipped_paths: list = []

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def scan(self, root_path: str, context: ScanContext) -> Iterator[ScanEntry]:
        """按 DFS 前序产出 ``ScanEntry``，并在结束时写入 statistics / status。"""
        fs = self.fs
        cancel = context.cancel_token
        include_hidden = context.include_hidden
        follow_symlinks = context.follow_symlinks

        root = fs.normalize(root_path) or root_path
        self.root_path = root
        self.error_breakdown = {}
        self.error_paths = []
        self.skipped_paths = []
        self.statistics = None

        start = time.perf_counter()
        files = directories = bytes_scanned = errors = skipped = 0
        fatal = False
        cancelled = False
        traversal_complete = False
        stack = [root]

        try:
            try:
                while stack:
                    if cancel.is_cancelled():
                        cancelled = True
                        break

                    current = stack.pop()
                    is_root = current == root

                    try:
                        with fs.scandir(current) as iterator:
                            entry_list = list(iterator)
                    except (PermissionError, FileNotFoundError, NotADirectoryError, OSError) as exc:
                        errors += 1
                        self._record_error(type(exc).__name__, current)
                        if is_root:
                            fatal = True
                            break
                        continue

                    child_dirs = []
                    for entry in entry_list:
                        if cancel.is_cancelled():
                            cancelled = True
                            break

                        try:
                            item_type = fs.classify(entry)
                        except OSError as exc:
                            errors += 1
                            self._record_error(type(exc).__name__, entry.path)
                            continue

                        if not include_hidden and fs.is_hidden(entry):
                            skipped += 1
                            if len(self.skipped_paths) < _MAX_RECORDED_PATHS:
                                self.skipped_paths.append(entry.path)
                            continue

                        if item_type is ItemType.SYMLINK:
                            if not follow_symlinks:
                                size, modified = self._link_metadata(entry)
                                yield ScanEntry(
                                    path=entry.path,
                                    name=entry.name,
                                    parent_path=current,
                                    item_type=ItemType.SYMLINK,
                                    size=size,
                                    modified_time=modified,
                                    file_identity=None,
                                )
                                continue
                            try:
                                target = fs.stat(entry, follow_symlinks=True)
                            except OSError:
                                self._record_error("BrokenLink", entry.path)
                                skipped += 1
                                size, modified = self._link_metadata(entry)
                                yield ScanEntry(
                                    path=entry.path,
                                    name=entry.name,
                                    parent_path=current,
                                    item_type=ItemType.SYMLINK,
                                    size=size,
                                    modified_time=modified,
                                    file_identity=None,
                                )
                                continue
                            if stat_module.S_ISDIR(target.st_mode):
                                item_type = ItemType.DIRECTORY
                            else:
                                item_type = ItemType.FILE

                        if item_type is ItemType.DIRECTORY:
                            yield ScanEntry(
                                path=entry.path,
                                name=entry.name,
                                parent_path=current,
                                item_type=ItemType.DIRECTORY,
                                size=0,
                                modified_time=None,
                                file_identity=None,
                            )
                            directories += 1
                            child_dirs.append(entry.path)
                            continue

                        try:
                            stat_result = fs.stat(entry, follow_symlinks=follow_symlinks)
                        except OSError as exc:
                            errors += 1
                            self._record_error(type(exc).__name__, entry.path)
                            continue

                        size = stat_result.st_size
                        files += 1
                        bytes_scanned += size
                        yield ScanEntry(
                            path=entry.path,
                            name=entry.name,
                            parent_path=current,
                            item_type=ItemType.FILE,
                            size=size,
                            modified_time=stat_result.st_mtime,
                            file_identity=fs.identity(stat_result, path=entry.path),
                        )

                    if cancelled:
                        break
                    # 反序入栈，保证同层仍按 scandir 顺序展开（DFS 前序契约不变）
                    stack.extend(reversed(child_dirs))

                traversal_complete = not (fatal or cancelled)
            except GeneratorExit:
                raise
            except Exception as exc:  # 内部异常：记录并结束，不向 GUI 抛出
                fatal = True
                errors += 1
                self._record_error(f"Unexpected:{type(exc).__name__}")
                traversal_complete = False
        finally:
            elapsed = time.perf_counter() - start
            if fatal:
                status = ScanStatus.ERROR
            elif cancelled or not traversal_complete:
                status = ScanStatus.CANCELLED
            elif errors or skipped:
                status = ScanStatus.PARTIAL
            else:
                status = ScanStatus.COMPLETED

            self.status = status
            self.statistics = ScanStatistics(
                files_scanned=files,
                directories_scanned=directories,
                bytes_scanned=bytes_scanned,
                errors=errors,
                skipped=skipped,
                elapsed_seconds=elapsed,
            )

    # ------------------------------------------------------------------
    # 装配 ScanResult（聚合数据由调用方注入；Scanner 本身不认识 Aggregator）
    # ------------------------------------------------------------------
    def build_result(
        self,
        root_path: Optional[str] = None,
        total_size: Optional[int] = None,
        file_count: Optional[int] = None,
        directory_count: Optional[int] = None,
    ) -> ScanResult:
        """用扫描计数装配 ``ScanResult``。

        当调用方（AnalysisService）传入聚合器的去重汇总时以聚合值为准，
        否则回退到扫描原始计数。
        """
        statistics = self.statistics or ScanStatistics(0, 0, 0, 0, 0, 0.0)
        return ScanResult(
            root_path=root_path if root_path is not None else (self.root_path or ""),
            total_size=statistics.bytes_scanned if total_size is None else total_size,
            file_count=statistics.files_scanned if file_count is None else file_count,
            directory_count=(
                statistics.directories_scanned if directory_count is None else directory_count
            ),
            statistics=statistics,
            status=self.status,
            error_count=statistics.errors,
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _record_error(self, category: str, path: Optional[str] = None) -> None:
        self.error_breakdown[category] = self.error_breakdown.get(category, 0) + 1
        if path is not None and len(self.error_paths) < _MAX_RECORDED_PATHS:
            self.error_paths.append(path)

    def _link_metadata(self, entry: "os.DirEntry[str]") -> tuple:
        """符号链接自身的元数据（lstat）；失败时退化为 ``(0, None)``。"""
        try:
            stat_result = self.fs.stat(entry, follow_symlinks=False)
        except OSError:
            return 0, None
        return stat_result.st_size, stat_result.st_mtime
