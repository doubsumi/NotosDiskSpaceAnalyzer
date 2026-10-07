"""扫描数据模型（V2）。

本模块集中定义 Scanner 与消费者之间共享的数据模型，是 V2 的「事实契约」：

    ScanContext      —— 一次扫描的输入（root / scan options / cancel token）
    ItemType         —— 文件系统条目类型
    ScanEntry        —— Scanner 产出的单条事实
    ScanStatistics   —— 扫描过程的统计计数
    ScanStatus       —— 扫描结束状态
    ScanResult       —— 面向消费者的汇总结果

契约（必须由 scanner.py 保证）
------------------------------
1. Scanner 只产出文件系统事实，不包含任何统计策略。
2. ``yield`` 顺序为 DFS 前序：目录条目先于其子条目。
   因此聚合器可假定父目录已在表中，向父目录累计为 O(1) 查表，无需回溯路径字符串。
3. ``ScanContext`` 只承载输入状态；statistics / lifecycle 分别由
   ``ScanStatistics`` 与 ``ScanResult`` 表达，不重复塞进 context。
4. 未来引入并发时，应以独立的 ``ConcurrencyPolicy`` 表达，
   而不是向 ``ScanContext`` 追加 int 字段。

状态语义（ScanStatus）
----------------------
======= ==========================================================
COMPLETED  无 skipped、无 error
PARTIAL    遍历走完，但 ``statistics.skipped > 0`` 或 ``statistics.errors > 0``
CANCELLED  用户主动取消（cancel_token 触发）
TIMED_OUT  达到 ScanOptions 中的超时限制
ERROR      Scanner 无法完成（根路径不可访问、内部异常等）
======= ==========================================================

尺寸口径（P0-5）
----------------
* ``ScanEntry.size`` 为 **Logical Size**（对应 ``os.stat().st_size``）。
* ``ScanEntry.allocated_size`` 为 **Allocated Size** 预留字段，第一阶段保持
  ``None``，不为它增加额外系统调用；将来需要时再填充。
* UI 必须使用 "Logical Size" 名称，不得称为 "Actual Disk Usage"。

类型说明
--------
``CancelToken`` / ``FileIdentity`` 只声明接口形状，不绑定具体实现；
真正实现分别落在 ``scanner.py`` / ``filesystem.py``。
``FileIdentity`` 必须支持 ``__hash__`` 与 ``__eq__``，因为它会被放入 ``set``
用于 hard link 去重。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class CancelToken(Protocol):
    """取消令牌接口形状（实现见 ``scanner.CancellationToken``）。"""

    def is_cancelled(self) -> bool: ...

    def cancel(self) -> None: ...


@runtime_checkable
class FileIdentity(Protocol):
    """文件实体标识接口形状（实现见 ``filesystem.StatFileIdentity``）。

    同一物理文件（含 hard link）必须得到相等的 identity，
    并且可安全放入 ``set`` 做去重。
    """

    def __hash__(self) -> int: ...

    def __eq__(self, other: object) -> bool: ...


@dataclass
class ScanContext:
    """一次扫描的输入状态。

    * ``include_hidden`` 默认 ``True``（P0-2：不默认跳过隐藏目录）。
    * ``follow_symlinks`` 默认 ``False``（P0-3：防止 cycle / 重复遍历）。
    """

    root_path: str
    cancel_token: CancelToken
    include_hidden: bool = True
    follow_symlinks: bool = False


class ItemType(Enum):
    """文件系统条目类型。"""

    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"


@dataclass
class ScanEntry:
    """Scanner 产出的单条事实。

    ``size`` 为 Logical Size；``allocated_size`` 为预留字段（第一阶段为 None）。
    ``file_identity`` 仅在文件可能存在 hard link（``st_nlink > 1``）时填充，
    其余情况为 ``None``，从而避免为去重集合付出额外内存。
    """

    path: str
    name: str
    parent_path: str
    item_type: ItemType
    size: int
    modified_time: Optional[float]
    file_identity: Optional[FileIdentity]
    allocated_size: Optional[int] = None


@dataclass
class ScanStatistics:
    """扫描过程的原始计数（不含聚合策略）。

    * ``files_scanned`` / ``bytes_scanned`` 为**原始遍历计数**，
      包含 hard link 的重复出现（反映实际完成的工作量）。
    * 去重后的权威汇总（``total_size`` / ``file_count``）由 Aggregator 计算，
      最终写入 ``ScanResult``。
    * ``skipped`` 记录被策略排除的条目（如 ``include_hidden=False`` 时的隐藏项）。
    """

    files_scanned: int
    directories_scanned: int
    bytes_scanned: int
    errors: int
    skipped: int
    elapsed_seconds: float


class ScanStatus(Enum):
    """扫描结束状态（语义见模块 docstring）。"""

    COMPLETED = "completed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    ERROR = "error"


@dataclass
class ScanResult:
    """面向消费者的汇总结果。

    ``total_size`` / ``file_count`` / ``directory_count`` 来自 Aggregator（已去重）；
    ``statistics`` 保留扫描过程的原始计数，两者共同表达扫描的「完整性」。
    """

    root_path: str
    total_size: int
    file_count: int
    directory_count: int
    statistics: ScanStatistics
    status: ScanStatus
    error_count: int
