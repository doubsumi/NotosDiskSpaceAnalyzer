"""扫描结果聚合器（V2）。

集中统计逻辑。消费者按 ``consume(entry)`` 逐个消费 ``ScanEntry`` 流，把
「发现」与「计算」彻底分开：

    DirectoryAggregator  —— 目录总大小 / 文件数 / 目录数
                            利用 DFS 前序契约，向父目录累计为 O(1) 查表
    FileTypeAggregator   —— 扩展名 / 文件类型的计数与大小
    TopKAggregator       —— Top-K 最大文件，使用 Min-Heap，O(N log K)

组合方式（§6）
--------------
聚合器由 ``AnalysisService`` / ``ScanWorker`` 负责组合，**Scanner 不知道它们存在**：

::

    for entry in scanner.scan(root, context):
        directory_aggregator.consume(entry)
        file_type_aggregator.consume(entry)
        top_k_aggregator.consume(entry)

不要写成 ``Scanner(aggregators=[...])``，也不要让 Aggregator 挂在 Scanner 内部。

硬链接去重（P0-4）
------------------
``ScanEntry.file_identity`` 仅在文件可能存在 hard link（``st_nlink > 1``）时非空。
各聚合器各自持有一个 identity 集合，遇到非空 identity 且已出现过时跳过该条目，
从而避免同一物理文件被重复累计。

目录大小计算（§15）
-------------------
``consume`` 时只累加目录的**直接**文件（own_*），``finalize`` 时按
「DFS 前序的逆序」把子树合计自底向上汇总——逆序遍历保证父目录在子目录之后处理，
因此每层累计都是 O(1) 查表。
"""

from __future__ import annotations

import heapq
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.core.scan_models import ItemType, ScanEntry

NO_EXTENSION = "(none)"


@dataclass
class DirectoryStats:
    """单个目录的统计结果。

    ``size`` / ``file_count`` / ``directory_count`` 为**子树合计**（finalize 后有效）；
    ``own_*`` 为扫描期累加的内部字段（仅该目录的直接内容）。
    """

    path: str
    parent_path: Optional[str] = None
    size: int = 0
    file_count: int = 0
    directory_count: int = 0
    own_size: int = 0
    own_file_count: int = 0
    own_directory_count: int = 0


@dataclass
class FileTypeStats:
    """单个扩展名的统计结果。"""

    extension: str
    count: int = 0
    size: int = 0


class DirectoryAggregator:
    """目录级聚合：子树大小 / 文件数 / 目录数。"""

    def __init__(self, root_path: str) -> None:
        self.root_path = root_path
        self._dirs: Dict[str, DirectoryStats] = {}
        self._children: Dict[str, List[str]] = {}
        self._identities: set = set()
        self._finalized = False
        self._dirs[root_path] = DirectoryStats(path=root_path, parent_path=None)

    # ------------------------------------------------------------------
    def consume(self, entry: ScanEntry) -> None:
        if entry.item_type is ItemType.DIRECTORY:
            self._add_directory(entry.path, entry.parent_path)
        elif entry.item_type is ItemType.FILE:
            self._add_file(entry)

    # ------------------------------------------------------------------
    def finalize(self) -> None:
        """自底向上汇总子树合计（可重复调用，内部会先清零）。"""
        if self._finalized:
            return
        for node in self._dirs.values():
            node.size = 0
            node.file_count = 0
            node.directory_count = 0
        for node in reversed(list(self._dirs.values())):
            node.size += node.own_size
            node.file_count += node.own_file_count
            node.directory_count += node.own_directory_count
            if node.parent_path is None:
                continue
            parent = self._dirs.get(node.parent_path)
            if parent is not None:
                parent.size += node.size
                parent.file_count += node.file_count
                parent.directory_count += node.directory_count
        self._finalized = True

    # ------------------------------------------------------------------
    @property
    def root(self) -> DirectoryStats:
        self.finalize()
        return self._dirs[self.root_path]

    @property
    def total_size(self) -> int:
        return self.root.size

    @property
    def file_count(self) -> int:
        return self.root.file_count

    @property
    def directory_count(self) -> int:
        return self.root.directory_count

    def stats_for(self, path: str) -> Optional[DirectoryStats]:
        self.finalize()
        return self._dirs.get(path)

    def children_of(self, path: str) -> List[DirectoryStats]:
        """返回某目录的直接子目录，按大小降序（供图表 / 列表使用）。"""
        self.finalize()
        children = [self._dirs[p] for p in self._children.get(path, ()) if p in self._dirs]
        children.sort(key=lambda node: (-node.size, node.path))
        return children

    # ------------------------------------------------------------------
    def _add_directory(self, path: str, parent_path: Optional[str]) -> None:
        if path not in self._dirs:
            self._dirs[path] = DirectoryStats(path=path, parent_path=parent_path)
            if parent_path is not None:
                self._children.setdefault(parent_path, []).append(path)
        parent = self._dirs.get(parent_path) if parent_path is not None else None
        if parent is not None:
            parent.own_directory_count += 1
        self._finalized = False

    def _add_file(self, entry: ScanEntry) -> None:
        identity = entry.file_identity
        if identity is not None:
            if identity in self._identities:
                return
            self._identities.add(identity)
        parent = self._dirs.get(entry.parent_path)
        if parent is None:
            parent = DirectoryStats(path=entry.parent_path, parent_path=None)
            self._dirs[entry.parent_path] = parent
        parent.own_size += entry.size
        parent.own_file_count += 1
        self._finalized = False


class FileTypeAggregator:
    """按扩展名聚合的计数与大小。"""

    def __init__(self) -> None:
        self._types: Dict[str, FileTypeStats] = {}
        self._identities: set = set()
        self.total_size = 0
        self.total_count = 0

    def consume(self, entry: ScanEntry) -> None:
        if entry.item_type is not ItemType.FILE:
            return
        identity = entry.file_identity
        if identity is not None:
            if identity in self._identities:
                return
            self._identities.add(identity)

        extension = self.extension_of(entry.name)
        node = self._types.get(extension)
        if node is None:
            node = FileTypeStats(extension=extension)
            self._types[extension] = node
        node.count += 1
        node.size += entry.size
        self.total_size += entry.size
        self.total_count += 1

    def stats(self, limit: Optional[int] = None) -> List[FileTypeStats]:
        """按大小降序返回扩展名统计。"""
        ordered = sorted(self._types.values(), key=lambda node: (-node.size, node.extension))
        return ordered if limit is None else ordered[:limit]

    @staticmethod
    def extension_of(name: str) -> str:
        _, ext = os.path.splitext(name)
        return ext.lower() if ext else NO_EXTENSION


class TopKAggregator:
    """Top-K 最大文件（Min-Heap，O(N log K)），并同时给出 ``Other`` 聚合项。"""

    def __init__(self, k: int = 10) -> None:
        self.k = max(1, int(k))
        self._heap: List[Tuple[int, int, ScanEntry]] = []
        self._sequence = 0
        self._identities: set = set()
        self.total_size = 0
        self.total_count = 0

    def consume(self, entry: ScanEntry) -> None:
        if entry.item_type is not ItemType.FILE:
            return
        identity = entry.file_identity
        if identity is not None:
            if identity in self._identities:
                return
            self._identities.add(identity)

        self.total_size += entry.size
        self.total_count += 1

        record = (entry.size, self._sequence, entry)
        self._sequence += 1
        if len(self._heap) < self.k:
            heapq.heappush(self._heap, record)
        elif entry.size > self._heap[0][0]:
            heapq.heapreplace(self._heap, record)

    def top(self) -> List[ScanEntry]:
        """按大小降序返回 Top-K 文件条目。"""
        return [item[2] for item in sorted(self._heap, key=lambda item: item[0], reverse=True)]

    def top_size(self) -> int:
        return sum(item[0] for item in self._heap)

    def other_size(self) -> int:
        """``Other`` 合计 = 全部 - Top-K（P0-6）。"""
        return max(0, self.total_size - self.top_size())

    def other_count(self) -> int:
        return max(0, self.total_count - len(self._heap))

    def top_with_other(self) -> List[Tuple[str, int, Optional[ScanEntry]]]:
        """返回 ``(label, size, entry)`` 列表；``Other`` 的 entry 为 ``None``（不可点击）。"""
        items: List[Tuple[str, int, Optional[ScanEntry]]] = [
            (entry.name, entry.size, entry) for entry in self.top()
        ]
        if self.other_count() > 0:
            items.append(("Other", self.other_size(), None))
        return items
