"""会话级目录缓存（O8）：DFS 只做一次，边界内命中一律零 DFS。

设计（docs/performance-optimization-plan.md O8，2026-10-08 决策）
----------------------------------------------------------------
* 硬约束：只要目标路径落在已扫描过的边界范围内，**不得再做 DFS**——
  不重扫、不补扫、不后台校验。扫描费力算出的目录表必须缓存并复用。
* 缓存模型：``dict[键 -> DirectoryStats]``（整张目录表合并自扫描完成后的
  聚合器，持有原对象、非额外副本）+ ``dict[键 -> RootRecord]``（已扫描根，
  按登记顺序）+ 每根元信息（status / skip_reason / affected_paths）。
* 覆盖判定：存在已扫描根 ``R`` 使 ``path == R`` 或 ``path`` 位于 ``R`` 之下
  （按「R + 分隔符」前缀判定，避免 ``C:\\a`` 误匹配 ``C:\\ab``）→ 命中。
* 写入（只增不减）：任何**遍历完成**的扫描（COMPLETED / PARTIAL）都把其
  整张目录表合并进缓存并登记该根；对根 ``R`` 重新扫描时删除登记在 ``R``
  之下的旧根（以新快照为准）。CANCELLED 的表不完整，**不登记**。
* 失效：``clear()``（服务关闭时）；不做 TTL（会话内快照语义）。
* 过期权衡（明确接受）：缓存值可能过期（扫描后磁盘变化）。顶层列表每次
  ``scandir`` 所以可见层始终新鲜，仅深层子树合计可能滞后；
  刷新手段 = 重新进入盘符根触发全量重扫。

线程约定
--------
仅主线程访问：``AnalysisService`` 的信号回调（worker finished / 命中服务）
都在 GUI 主线程执行，缓存无需加锁。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.core.aggregators import DirectoryAggregator, DirectoryStats
from src.core.scan_models import ScanStatus


def cache_key(path: str) -> str:
    """缓存键：Windows 大小写 / 分隔符不敏感。"""
    return os.path.normcase(os.path.normpath(path))


@dataclass
class RootRecord:
    """一个已扫描根的登记信息。"""

    path: str
    key: str
    status: ScanStatus
    skip_reason: Optional[str] = None
    affected_paths: List[str] = field(default_factory=list)


class DirectoryCache:
    """目录表缓存：覆盖判定 + O(1) 子树大小查表。"""

    def __init__(self, max_dirs: int = 2_000_000) -> None:
        self._stats: Dict[str, DirectoryStats] = {}
        self._roots: Dict[str, RootRecord] = {}  # dict 保持插入序（最早登记在前）
        self.max_dirs = max_dirs

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def find_covering_root(self, path: str) -> Optional[RootRecord]:
        """返回覆盖 ``path`` 的已扫描根；无覆盖时返回 ``None``（需走 O9）。"""
        key = cache_key(path)
        for root_key, record in self._roots.items():
            if key == root_key or key.startswith(root_key + os.sep):
                return record
        return None

    def stats_for(self, path: str) -> Optional[DirectoryStats]:
        """返回该路径的子树合计（finalize 后有效）；未缓存返回 ``None``。"""
        return self._stats.get(cache_key(path))

    def root_count(self) -> int:
        return len(self._roots)

    # ------------------------------------------------------------------
    # 写入 / 失效
    # ------------------------------------------------------------------
    def register(
        self,
        root_path: str,
        aggregator: DirectoryAggregator,
        status: ScanStatus,
        skip_reason: Optional[str] = None,
        affected_paths: Optional[List[str]] = None,
    ) -> None:
        """合并一次已完成扫描的整张目录表，并登记该根（只增不减）。"""
        root_key = cache_key(root_path)
        prefix = root_key + os.sep
        # 重扫根 R：删除登记在 R 之下的旧根（以新快照为准）
        for old_key in [k for k in self._roots if k.startswith(prefix)]:
            self._remove_root(old_key)
        # 聚合器键为原始路径，必须统一过 cache_key 才能与查询 / 逐出的键一致
        self._stats.update(
            {cache_key(path): stats for path, stats in aggregator.nodes.items()}
        )
        self._roots[root_key] = RootRecord(
            path=root_path,
            key=root_key,
            status=status,
            skip_reason=skip_reason,
            affected_paths=list(affected_paths or []),
        )
        self._evict_if_needed()

    def invalidate(self, path: str) -> bool:
        """使覆盖 ``path`` 的已扫描根失效（连同其整张目录表一起移除），
        返回是否确有移除（P1-1 刷新语义）。

        失效后再次进入 ``path`` 会走 O9（预览 + 全量重扫），从而得到一份
        新鲜快照；被移除的根之外的其他缓存不受影响。
        """
        record = self.find_covering_root(path)
        if record is None:
            return False
        self._remove_root(record.key)
        return True

    def clear(self) -> None:
        """服务关闭时清空（会话级缓存，退出即消失）。"""
        self._stats.clear()
        self._roots.clear()

    # ------------------------------------------------------------------
    def _remove_root(self, root_key: str) -> None:
        self._roots.pop(root_key, None)
        prefix = root_key + os.sep
        for key in [k for k in self._stats if k == root_key or k.startswith(prefix)]:
            del self._stats[key]

    def _evict_if_needed(self) -> None:
        """超过 ``max_dirs`` 时按「最早登记的扫描根」整体逐出。"""
        while len(self._stats) > self.max_dirs and self._roots:
            oldest = next(iter(self._roots))
            self._remove_root(oldest)
