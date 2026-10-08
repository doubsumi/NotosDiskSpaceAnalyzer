"""轻量 FileSystem 抽象（V2）。

目标不是制造复杂的 interface hierarchy，而是把**真正需要的平台差异**
集中到一处，供 Scanner 复用：

    scandir / stat / is_file / is_dir / is_symlink
    file identity（供 hard link 去重）
    disk usage
    path normalize

约定
----
* 默认 ``follow_symlinks=False``（§11 P0-3），避免 cycle / 重复遍历 / 树意外膨胀。
* Windows 专属能力（junction / reparse point / hidden attribute）先在本文件内部
  做平台分支；只有当代码明显失控时才拆出 ``windows_filesystem.py``。
* ``FileIdentity`` 的具体实现（``StatFileIdentity``，提供 ``__hash__`` / ``__eq__``）
  落在本模块，用于在统计中避免同一物理文件实体被重复累计（§11 P0-4）。

hard link 检测的成本（重要）
---------------------------
* POSIX：``DirEntry.stat()`` 本身就是一次真实 ``stat`` 系统调用，``st_ino`` /
  ``st_nlink`` 可用，去重「免费」。
* Windows：``DirEntry.stat()`` 返回的是目录枚举的**缓存**（``st_ino`` / ``st_nlink``
  均为 0），要拿到 file index 必须再做一次 ``os.stat``。实测该调用约为缓存访问的
  260 倍（约 70k files/s 上限），逐文件调用会把整体吞吐拉回 V1 基线以下。
* 因此 ``probe_hard_links`` 默认值按平台选择：POSIX 为 ``True``，Windows 为
  ``False``。该取舍已由 STEP 16 benchmark 实测确认（见
  ``docs/performance-plan.md`` §8）：Windows 上开启探测使吞吐再降约 56%
  （56k → 24k files/s），因此**默认保持关闭**；需要严格 hard link 去重时可显式打开。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import List, NamedTuple, Optional, Union

from src.core.scan_models import FileIdentity, ItemType

PathLike = Union[str, "os.DirEntry[str]"]

# Windows FILE_ATTRIBUTE_HIDDEN
_FILE_ATTRIBUTE_HIDDEN = 0x2

#: 平台默认：POSIX 上 hard link 检测免费，Windows 上需要额外 os.stat。
_DEFAULT_PROBE_HARD_LINKS = os.name != "nt"


@dataclass(frozen=True)
class StatFileIdentity:
    """基于 ``(st_dev, st_ino)`` 的文件实体标识（FileIdentity 的具体实现）。

    frozen dataclass 自动提供 ``__hash__`` / ``__eq__``，可直接放入 ``set``。
    """

    device: int
    inode: int


class DiskUsage(NamedTuple):
    """磁盘使用情况（与 ``psutil.disk_usage`` 对齐的轻量结构）。"""

    total: int
    used: int
    free: int
    percent: float


class MountPoint(NamedTuple):
    """一个已挂载卷（Windows 为盘符，POSIX 为 mountpoint）。"""

    name: str
    mountpoint: str
    total: int
    used: int
    free: int
    percent: float


class FileSystem:
    """Scanner 与平台文件系统之间的轻量适配层。"""

    def __init__(self, probe_hard_links: Optional[bool] = None) -> None:
        #: 是否在缓存 stat 不提供 inode 时再做一次 ``os.stat`` 以完成 hard link 去重。
        self.probe_hard_links = (
            _DEFAULT_PROBE_HARD_LINKS if probe_hard_links is None else probe_hard_links
        )

    # ------------------------------------------------------------------
    # 遍历 / 元数据
    # ------------------------------------------------------------------
    def scandir(self, path: str) -> "os.ScandirIterator[str]":
        """返回 ``os.scandir`` 迭代器（调用方负责关闭，推荐 ``with``）。"""
        return os.scandir(path)

    def stat(self, entry: PathLike, follow_symlinks: bool = False) -> os.stat_result:
        """获取元数据；对 DirEntry 复用其缓存，避免重复系统调用。"""
        if isinstance(entry, str):
            if follow_symlinks:
                return os.stat(entry)
            return os.lstat(entry)
        return entry.stat(follow_symlinks=follow_symlinks)

    def stat_entry(
        self, entry: "os.DirEntry[str]", follow_symlinks: bool = False
    ) -> os.stat_result:
        """DirEntry 专用元数据快速路径（O4d：无 PathLike isinstance 分派）。

        与 :meth:`stat` 对 DirEntry 的行为完全一致；Scanner 热路径使用本方法，
        避免每条目一次的 ``isinstance`` 开销（热路径例外，见
        ``docs/performance-optimization-plan.md`` §5 O4d）。测试替身重写本方法
        即可拦截扫描期的元数据获取。
        """
        return entry.stat(follow_symlinks=follow_symlinks)

    def is_symlink(self, entry: PathLike) -> bool:
        if isinstance(entry, str):
            return os.path.islink(entry)
        return entry.is_symlink()

    def is_dir(self, entry: PathLike, follow_symlinks: bool = False) -> bool:
        if isinstance(entry, str):
            if follow_symlinks:
                return os.path.isdir(entry)
            return os.path.isdir(entry) and not os.path.islink(entry)
        return entry.is_dir(follow_symlinks=follow_symlinks)

    def is_file(self, entry: PathLike, follow_symlinks: bool = False) -> bool:
        if isinstance(entry, str):
            if follow_symlinks:
                return os.path.isfile(entry)
            return os.path.isfile(entry) and not os.path.islink(entry)
        return entry.is_file(follow_symlinks=follow_symlinks)

    def classify(self, entry: PathLike) -> ItemType:
        """判定条目类型。

        符号链接（含 Windows junction / reparse point）一律视为 ``SYMLINK``，
        不跟随目标；其余无法归类的特殊文件按叶子（``FILE``）处理。
        """
        if self.is_symlink(entry):
            return ItemType.SYMLINK
        if self.is_dir(entry, follow_symlinks=False):
            return ItemType.DIRECTORY
        return ItemType.FILE

    # ------------------------------------------------------------------
    # File identity（hard link 去重，P0-4）
    # ------------------------------------------------------------------
    def identity(
        self, stat_result: os.stat_result, path: Optional[str] = None
    ) -> Optional[FileIdentity]:
        """返回文件实体标识；仅在可能发生 hard link 重复时返回非空值。

        * ``st_nlink <= 1``：文件只有一个链接，不可能重复，返回 ``None``。
        * 缓存 stat 不提供 ``st_ino``（Windows）：仅当 ``probe_hard_links`` 打开且
          提供了 ``path`` 时，才补一次 ``os.stat`` 取回 file index。
        """
        inode = getattr(stat_result, "st_ino", 0) or 0
        if not inode:
            if not self.probe_hard_links or path is None:
                return None
            try:
                stat_result = os.stat(path)
            except OSError:
                return None
            inode = getattr(stat_result, "st_ino", 0) or 0
            if not inode:
                return None

        nlink = getattr(stat_result, "st_nlink", 1)
        if not nlink or nlink <= 1:
            return None
        return StatFileIdentity(getattr(stat_result, "st_dev", 0), inode)

    # ------------------------------------------------------------------
    # Hidden（P0-2：默认不跳过，仅在显式关闭时才需要判断）
    # ------------------------------------------------------------------
    def is_hidden(self, entry: PathLike) -> bool:
        """判断条目是否为隐藏项。

        POSIX：以 ``.`` 开头。Windows：``.`` 开头或带 FILE_ATTRIBUTE_HIDDEN
        （即文件管理器默认不显示的项目，如 ``pagefile.sys``）。

        接受 ``DirEntry`` 或路径字符串；后者需要额外一次 ``lstat``，
        仅供展示层对少量条目使用，不用于扫描热路径。
        """
        # 传入路径字符串时取最后一段，避免整条路径参与点前缀判断。
        name = os.path.basename(entry) if isinstance(entry, str) else entry.name
        if name.startswith("."):
            return True
        if os.name != "nt":
            return False
        try:
            if isinstance(entry, str):
                attributes = os.lstat(entry).st_file_attributes
            else:
                attributes = entry.stat(follow_symlinks=False).st_file_attributes
        except (OSError, AttributeError):
            return False
        return bool(attributes & _FILE_ATTRIBUTE_HIDDEN)

    # ------------------------------------------------------------------
    # 磁盘 / 路径
    # ------------------------------------------------------------------
    def normalize(self, path: str) -> str:
        """标准化路径（不解析符号链接，避免额外系统调用）。"""
        return os.path.normpath(path)

    def disk_usage(self, path: str) -> DiskUsage:
        """查询磁盘使用情况；优先 psutil，失败时回退到 ``shutil``。"""
        try:
            import psutil

            usage = psutil.disk_usage(path)
            return DiskUsage(usage.total, usage.used, usage.free, usage.percent)
        except Exception:
            usage = shutil.disk_usage(path)
            percent = (usage.used / usage.total * 100) if usage.total else 0.0
            return DiskUsage(usage.total, usage.used, usage.free, percent)

    def list_disks(self) -> List[MountPoint]:
        """枚举当前可用的本地卷（供磁盘总览使用）。"""
        return self._list_windows_disks() if os.name == "nt" else self._list_posix_disks()

    def _list_windows_disks(self) -> List[MountPoint]:
        import ctypes
        import string

        disks: List[MountPoint] = []
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drive = f"{letter}:\\"
                try:
                    usage = self.disk_usage(drive)
                except OSError:
                    pass
                else:
                    disks.append(
                        MountPoint(drive, drive, usage.total, usage.used, usage.free, usage.percent)
                    )
            bitmask >>= 1
        return disks

    def _list_posix_disks(self) -> List[MountPoint]:
        import psutil

        disks: List[MountPoint] = []
        for partition in psutil.disk_partitions():
            if partition.fstype in ("squashfs", "tmpfs", "devtmpfs"):
                continue
            try:
                usage = self.disk_usage(partition.mountpoint)
            except (PermissionError, OSError):
                continue
            disks.append(
                MountPoint(
                    partition.mountpoint,
                    partition.mountpoint,
                    usage.total,
                    usage.used,
                    usage.free,
                    usage.percent,
                )
            )
        return disks
