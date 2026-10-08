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


@dataclass(slots=True)
class DirectoryStats:
    """单个目录的统计结果。

    ``size`` / ``file_count`` / ``directory_count`` 为**子树合计**（finalize 后有效）；
    ``own_*`` 为扫描期累加的内部字段（仅该目录的直接内容）。

    O6a：``slots`` 去掉每实例 ``__dict__``——37.8k 目录实测省 ~30% 驻留
    （100 万目录 ≈ 350 MB → ~230 MB）。
    """

    path: str
    parent_path: Optional[str] = None
    size: int = 0
    file_count: int = 0
    directory_count: int = 0
    own_size: int = 0
    own_file_count: int = 0
    own_directory_count: int = 0


@dataclass(slots=True)
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
        # O5：父目录查表缓存。DFS 前序保证同一目录的文件条目连续出现，
        # 因此按 parent_path 记忆上一次命中的 DirectoryStats，命中率≈100%。
        # _dirs 中的对象只增不替换，缓存引用始终有效，无需失效逻辑。
        self._last_parent_path: Optional[str] = None
        self._last_parent_stats: Optional[DirectoryStats] = None
        # O6b：release_scratch() 置位后，中间数据已释放，consume 直接忽略
        # （正常流程中扫描结束后不会再有 consume；置位仅为防御误用）。
        self._released = False

    # ------------------------------------------------------------------
    def consume(self, entry: ScanEntry) -> None:
        if self._released:
            return
        if entry.item_type is ItemType.DIRECTORY:
            self.add_directory(entry.path, entry.parent_path)
        elif entry.item_type is ItemType.FILE:
            self.add_file(entry.parent_path, entry.size, entry.file_identity)

    # ------------------------------------------------------------------
    def add_file(self, parent_path: str, size: int, identity=None) -> None:
        """快速累加一个文件（不经 ``ScanEntry``，供扫描快速路径调用）。

        语义与 ``consume(ScanEntry(FILE))`` 完全一致，只是省去 ScanEntry
        构造；仅在扫描期间调用（``release_scratch`` 之后不再使用）。
        """
        if identity is not None:
            if identity in self._identities:
                return
            self._identities.add(identity)
        # O5：命中缓存时免一次路径哈希查表（DFS 前序下命中率≈100%）。
        if parent_path != self._last_parent_path:
            parent = self._dirs.get(parent_path)
            if parent is None:
                parent = DirectoryStats(path=parent_path, parent_path=None)
                self._dirs[parent_path] = parent
            self._last_parent_path = parent_path
            self._last_parent_stats = parent
        parent = self._last_parent_stats
        parent.own_size += size
        parent.own_file_count += 1
        self._finalized = False

    def add_directory(self, path: str, parent_path: Optional[str]) -> None:
        """快速累加一个目录（不经 ``ScanEntry``，供扫描快速路径调用）。

        语义与 ``consume(ScanEntry(DIRECTORY))`` 完全一致，省去 ScanEntry 构造。
        """
        if path not in self._dirs:
            self._dirs[path] = DirectoryStats(path=path, parent_path=parent_path)
            if parent_path is not None:
                self._children.setdefault(parent_path, []).append(path)
        # O5：父目录查表缓存同样适用于目录条目——DFS 前序下同父目录的
        # 子目录连续出现，命中时免一次路径哈希（与 add_file 共享缓存字段，
        # 缓存的永远是 _dirs[parent_path] 对象本身，语义不变）。
        if parent_path is not None:
            if parent_path != self._last_parent_path:
                parent = self._dirs.get(parent_path)
                self._last_parent_path = parent_path
                self._last_parent_stats = parent
            parent = self._last_parent_stats
            if parent is not None:
                parent.own_directory_count += 1
        self._finalized = False

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
    def release_scratch(self) -> None:
        """释放扫描期中间数据（O6b）：``own_*`` 清零、``_children`` / 去重集丢弃。

        仅在**结果装配完成且目录表已交由缓存 / 展示层持有**后调用——
        ``_dirs`` 本身（子树合计）原样保留，``finalize`` 结果不受影响。
        调用后不得再 ``consume``（防御：直接忽略）；``children_of`` 随之失效。
        不能并入 ``finalize``：``finalize → consume → finalize`` 的增量重算
        依赖 ``own_*`` 存活（有单测兜底）。
        """
        self._released = True
        self._children.clear()
        self._identities.clear()
        for node in self._dirs.values():
            node.own_size = 0
            node.own_file_count = 0
            node.own_directory_count = 0

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

    @property
    def nodes(self) -> Dict[str, DirectoryStats]:
        """整张目录表（键 = 原始路径，含根）。供 DirectoryCache 合并（O8）。

        调用即 finalize，保证每个节点为子树合计；返回聚合器内部字典本身
        （非副本），缓存直接持有这些 DirectoryStats 对象，不额外复制。
        """
        self.finalize()
        return self._dirs

    def stats_for(self, path: str) -> Optional[DirectoryStats]:
        self.finalize()
        return self._dirs.get(path)

    def children_of(self, path: str) -> List[DirectoryStats]:
        """返回某目录的直接子目录，按大小降序（供图表 / 列表使用）。"""
        self.finalize()
        children = [self._dirs[p] for p in self._children.get(path, ()) if p in self._dirs]
        children.sort(key=lambda node: (-node.size, node.path))
        return children


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
