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
from concurrent.futures import ThreadPoolExecutor
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

#: Windows 平台常量（热循环内避免重复求值 os.name）。
_IS_WINDOWS = os.name == "nt"

# Windows FILE_ATTRIBUTE_HIDDEN（与 filesystem.py 同一口径）
_FILE_ATTRIBUTE_HIDDEN = 0x2


class CancellationToken:
    """``CancelToken`` 的具体实现，线程安全（Scanner / GUI 跨线程共享）。"""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


def _prefetch_list(scandir_fn, path: str) -> tuple:
    """线程池内执行：仅枚举一个目录，返回 ``(entry_list, exc_or_None)``（O2）。

    线程安全约束（O2-TS）：
    * 只依赖传入的 ``scandir`` 绑定方法与 ``path``，**不触碰** Scanner /
      Aggregator 的任何状态（TS1 单写者 / TS2 零共享可变状态）；
    * 返回的 ``DirEntry`` 列表对主线程**只读**——迭代器关闭后 DirEntry
      仍有效（Windows 元数据来自枚举缓存，读取无需再进线程）；
    * ``OSError`` 作为返回值交回**主线程**分类记录（TS6：异常不在线程内
      静默吞掉，也不改变 scanner 状态的归属线程）。
    """
    try:
        with scandir_fn(path) as iterator:
            return list(iterator), None
    except OSError as exc:
        return [], exc


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
        # O2：并发枚举预取状态（仅 scan() 运行期间非空，TS5 保证收尾清理）。
        self._enum_pool: Optional[ThreadPoolExecutor] = None
        self._pending: dict = {}
        self._max_in_flight = 0

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def scan(self, root_path: str, context: ScanContext) -> Iterator[ScanEntry]:
        """按 DFS 前序产出 ``ScanEntry``（全量模式，契约不变，惰性）。

        遍历 / 分类 / stat / 隐藏 / 符号链接解析 / 统计全部由共享核心
        ``_walk`` 完成；本方法只把每条目装配成 ``ScanEntry`` 并 yield。
        """
        walk = self._walk(root_path, context)
        try:
            for parent, batch in walk:
                for entry, item_type, stat_result, hidden, identity in batch:
                    if item_type is ItemType.FILE:
                        yield ScanEntry(
                            path=entry.path,
                            name=entry.name,
                            parent_path=parent,
                            item_type=ItemType.FILE,
                            size=stat_result.st_size,
                            modified_time=stat_result.st_mtime,
                            file_identity=identity,
                            is_hidden=hidden,
                        )
                    elif item_type is ItemType.DIRECTORY:
                        yield ScanEntry(
                            path=entry.path,
                            name=entry.name,
                            parent_path=parent,
                            item_type=ItemType.DIRECTORY,
                            size=0,
                            modified_time=None,
                            file_identity=None,
                            is_hidden=hidden,
                        )
                    else:  # SYMLINK（follow_symlinks=False，或 follow=True 的断链）
                        size, modified = self._link_metadata(entry)
                        yield ScanEntry(
                            path=entry.path,
                            name=entry.name,
                            parent_path=parent,
                            item_type=ItemType.SYMLINK,
                            size=size,
                            modified_time=modified,
                            file_identity=None,
                            is_hidden=hidden,
                        )
        finally:
            # 确保 close()（消费者提前终止）时 _walk 的收尾（关预取池、写统计）确定执行
            walk.close()

    # ------------------------------------------------------------------
    # 共享遍历核心（B2）
    # ------------------------------------------------------------------
    def _walk(self, root_path: str, context: ScanContext):
        """共享遍历核心：按 DFS 前序逐目录产出 ``(parent_path, batch)``。

        ``batch`` 为 ``[(entry, item_type, stat_result, hidden, identity), ...]``，
        每条目已完成分类 / stat / 隐藏判定 / 符号链接解析 / 跳过过滤；
        ``stat_result`` 仅对 FILE 条目非空，``identity`` 仅对 FILE 非空。

        统计与状态在生成器结束时写入 ``self.statistics`` / ``self.status``。
        ``scan()``（全量）与 ``AnalysisService`` 的快速扫描路径分别消费本核心：
        前者装配 ``ScanEntry``，后者直接把事实累加进 ``DirectoryAggregator``
        （不经 ScanEntry，消除逐条 yield 与对象构造，见 performance 计划 B2）。
        """
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

        # O4b：热循环内用到的绑定提前局部化（省 LOAD_ATTR 常数税）。
        # O4d 热路径例外：Scanner 只消费 fs.scandir 产出的 DirEntry，
        # 直接调用其方法以消除 PathLike 的 isinstance 分派；通用 PathLike
        # API 仍由 FileSystem 提供（测试 / 展示层 / 预览装配使用）。
        scandir = fs.scandir
        identity_of = fs.identity
        stat_entry = fs.stat_entry
        record_error = self._record_error
        skipped_paths = self.skipped_paths

        # 热路径优化：Windows 默认不探测 hard link（scandir 缓存的 st_ino 恒为 0），
        # ``identity`` 对每条目必返回 None——短路掉逐文件的函数调用与 getattr。
        # POSIX 即便 probe=False，st_ino 仍是真实值，仍需走 identity 做去重，故不短路。
        probe_hard_links = fs.probe_hard_links
        if _IS_WINDOWS and not probe_hard_links:
            identity_of = None

        start = time.perf_counter()
        files = directories = bytes_scanned = errors = skipped = 0
        entry_count = 0
        fatal = False
        cancelled = False
        traversal_complete = False
        stack = [root]

        # O2：目录枚举并发预取（默认关，TS8）。只并行「枚举」这一步，
        # 统计与分类仍由本线程单写（TS1）。
        if context.enable_parallel_enum:
            max_workers = min(4, (os.cpu_count() or 1) * 2)
            self._max_in_flight = 2 * max_workers  # TS3：有界在途
            self._enum_pool = ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix="notos-enum"
            )
        else:
            self._max_in_flight = 0
            self._enum_pool = None
        self._pending = {}
        pending = self._pending
        enum_pool = self._enum_pool
        max_in_flight = self._max_in_flight

        try:
            try:
                while stack:
                    if cancel.is_cancelled():
                        cancelled = True
                        break

                    current = stack.pop()
                    is_root = current == root

                    # O2 / TS4：按 DFS 顺序取回预取结果——pop 到哪条才取哪条，
                    # 前序契约不变；异常作为返回值在此分类记录（TS6）。
                    future = pending.pop(current, None)
                    if future is not None:
                        entry_list, enum_error = future.result()
                        if enum_error is not None:
                            errors += 1
                            self._record_error(type(enum_error).__name__, current)
                            if is_root:
                                fatal = True
                                break
                            continue
                    else:
                        try:
                            with scandir(current) as iterator:
                                entry_list = list(iterator)
                        except (PermissionError, FileNotFoundError, NotADirectoryError, OSError) as exc:
                            errors += 1
                            self._record_error(type(exc).__name__, current)
                            if is_root:
                                fatal = True
                                break
                            continue

                    child_dirs = []
                    child_append = child_dirs.append

                    # O2 / TS3+TS5：取回结果后立即批量提交子目录预取；
                    # 在途达上限或已取消时停止提交，剩余目录退回同步 scandir。
                    if enum_pool is not None:
                        for pentry in entry_list:
                            try:
                                if not pentry.is_dir(follow_symlinks=False):
                                    continue
                            except OSError:
                                continue
                            if len(pending) >= max_in_flight or cancel.is_cancelled():
                                break
                            pending[pentry.path] = enum_pool.submit(
                                _prefetch_list, scandir, pentry.path
                            )

                    batch = []
                    batch_append = batch.append
                    for entry in entry_list:
                        # O4c：取消检查降频为每 256 条目一次。
                        entry_count += 1
                        if not entry_count & 0xFF and cancel.is_cancelled():
                            cancelled = True
                            break

                        # O4a：内联 classify——目录判定在前，symlink 的
                        # is_dir(follow_symlinks=False) 恒为 False，顺序等价。
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                item_type = ItemType.DIRECTORY
                            elif entry.is_symlink():
                                item_type = ItemType.SYMLINK
                            else:
                                item_type = ItemType.FILE
                        except OSError as exc:
                            errors += 1
                            record_error(type(exc).__name__, entry.path)
                            continue

                        # O3：隐藏位在扫描期确定。FILE 的 stat 与隐藏位/大小共用
                        # 同一份 stat；目录 / symlink 在 Windows 上读枚举缓存。
                        name = entry.name
                        stat_result = None
                        if name.startswith("."):
                            hidden = True
                        elif item_type is ItemType.FILE and not follow_symlinks:
                            try:
                                stat_result = stat_entry(entry, follow_symlinks=False)
                            except OSError as exc:
                                errors += 1
                                record_error(type(exc).__name__, entry.path)
                                continue
                            if _IS_WINDOWS:
                                hidden = bool(
                                    stat_result.st_file_attributes & _FILE_ATTRIBUTE_HIDDEN
                                )
                            else:
                                hidden = bool(
                                    getattr(stat_result, "st_file_attributes", 0)
                                    & _FILE_ATTRIBUTE_HIDDEN
                                )
                        elif _IS_WINDOWS:
                            try:
                                stat_result = entry.stat(follow_symlinks=False)
                                hidden = bool(
                                    stat_result.st_file_attributes & _FILE_ATTRIBUTE_HIDDEN
                                )
                            except OSError:
                                hidden = False
                                stat_result = None
                        else:
                            hidden = False

                        if not include_hidden and hidden:
                            skipped += 1
                            if len(skipped_paths) < _MAX_RECORDED_PATHS:
                                skipped_paths.append(entry.path)
                            continue

                        # follow_symlinks=True 时解析符号链接：目录→DIR，文件→FILE，
                        # 断链保持 SYMLINK（记 BrokenLink + skipped）。
                        if item_type is ItemType.SYMLINK and follow_symlinks:
                            try:
                                target = stat_entry(entry, follow_symlinks=True)
                            except OSError:
                                record_error("BrokenLink", entry.path)
                                skipped += 1
                            else:
                                if stat_module.S_ISDIR(target.st_mode):
                                    item_type = ItemType.DIRECTORY
                                else:
                                    item_type = ItemType.FILE
                                    stat_result = target

                        identity = None
                        if item_type is ItemType.FILE:
                            if stat_result is None:
                                # dot 前缀文件、或 follow=True 的常规文件（POSIX）
                                try:
                                    stat_result = stat_entry(
                                        entry, follow_symlinks=follow_symlinks
                                    )
                                except OSError as exc:
                                    errors += 1
                                    record_error(type(exc).__name__, entry.path)
                                    continue
                            files += 1
                            bytes_scanned += stat_result.st_size
                            if identity_of is not None:
                                identity = identity_of(stat_result, entry.path)
                        elif item_type is ItemType.DIRECTORY:
                            directories += 1
                            child_append(entry.path)
                        # SYMLINK：不计数（未跟随）

                        batch_append((entry, item_type, stat_result, hidden, identity))

                    yield (current, batch)
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
            # O2 / TS5：无论正常结束、取消还是 close()，都要关闭预取池。
            if self._enum_pool is not None:
                self._enum_pool.shutdown(wait=False, cancel_futures=True)
                self._enum_pool = None
            self._pending = {}

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
