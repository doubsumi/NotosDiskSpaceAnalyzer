"""搜索服务（V2）。

V2 不使用 SQLite / persistent index，搜索按需进行（§8 / §19）：

当前目录搜索
    对**当前已获取到**的条目（``AnalysisResult.items``）做即时、轻量匹配，
    不触碰文件系统。

全盘（或指定目录）搜索
    按需驱动 ``Scanner`` 做 streaming match，命中即流式返回 ``SearchResult``，
    不建立索引、不回放、不缓存。

RAM-only search index
    仅在**首次全盘搜索**时按需构建 session 级内存索引（退出即消失）。
    第一版**不建立**：只有 profile 证明「同一会话内反复全盘搜索」是真实场景时
    才引入，避免提前付出索引构建与一致性维护的成本。

约束
----
* 只存在内存，只在当前运行期间存在，退出程序立即消失。
* 不写 ``*.db`` / ``*.sqlite`` / cache / index 等任何持久化文件。
* **不依赖 PyQt**：搜索只消费 ``Scanner``，线程与展示由调用方决定
  （§P2-C：Scanner 不知道 Search，Search 也不知道 GUI）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional

from src.core.filesystem import FileSystem
from src.core.scan_models import ItemType, ScanContext
from src.core.scanner import CancellationToken, DirectoryScanner


@dataclass
class SearchResult:
    """一条搜索命中。

    ``item_type`` 统一为字符串（``'file' | 'directory' | 'symlink'``），
    这样来自 ``ScanEntry``（``ItemType`` 枚举）与来自展示层条目（字符串）
    的命中具有同一种形状，调用方无需分支。
    """

    name: str
    path: str
    item_type: str
    size: int


class SearchService:
    """按需搜索服务：当前目录即时匹配 + Scanner 流式匹配。"""

    def __init__(
        self,
        filesystem: Optional[FileSystem] = None,
        scanner: Optional[DirectoryScanner] = None,
    ) -> None:
        self._fs = filesystem or FileSystem()
        self._scanner = scanner

    # ------------------------------------------------------------------
    # 匹配规则
    # ------------------------------------------------------------------
    @staticmethod
    def matches(name: str, query: str) -> bool:
        """大小写不敏感的子串匹配（唯一的匹配策略，保持可预期）。"""
        return bool(query) and query.lower() in (name or "").lower()

    # ------------------------------------------------------------------
    # 当前目录搜索（即时、不触碰文件系统）
    # ------------------------------------------------------------------
    def search_entries(self, entries: Iterable[object], query: str) -> List[SearchResult]:
        """在已获取的条目里匹配 ``query``。

        ``entries`` 为鸭子类型：需要 ``name`` / ``path`` / ``size`` / ``item_type``
        （``DisplayItem`` 与 ``ScanEntry`` 都满足）。
        """
        normalized = (query or "").strip()
        if not normalized:
            return []
        return [
            self._to_result(entry)
            for entry in entries
            if self.matches(getattr(entry, "name", ""), normalized)
        ]

    # ------------------------------------------------------------------
    # 全盘 / 指定目录搜索（按需、流式）
    # ------------------------------------------------------------------
    def iter_matches(
        self,
        root_path: str,
        query: str,
        cancel_token: Optional[object] = None,
        include_hidden: bool = True,
        follow_symlinks: bool = False,
    ) -> Iterator[SearchResult]:
        """驱动 ``Scanner`` 流式搜索，命中即 ``yield``，可随时取消。

        参数默认值与扫描契约一致（P0-2 / P0-3）。
        """
        normalized = (query or "").strip()
        if not normalized:
            return

        scanner = self._scanner or DirectoryScanner(self._fs)
        context = ScanContext(
            root_path=root_path,
            cancel_token=cancel_token or CancellationToken(),
            include_hidden=include_hidden,
            follow_symlinks=follow_symlinks,
        )
        for entry in scanner.scan(root_path, context):
            if self.matches(entry.name, normalized):
                yield SearchResult(
                    name=entry.name,
                    path=entry.path,
                    item_type=entry.item_type.value,
                    size=entry.size,
                )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    @staticmethod
    def _to_result(entry: object) -> SearchResult:
        item_type = getattr(entry, "item_type", ItemType.FILE)
        return SearchResult(
            name=getattr(entry, "name", ""),
            path=getattr(entry, "path", ""),
            item_type=item_type.value if isinstance(item_type, ItemType) else str(item_type),
            size=int(getattr(entry, "size", 0) or 0),
        )
