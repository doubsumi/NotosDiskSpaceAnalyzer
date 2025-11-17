import os
import platform
import math
from pathlib import Path
from typing import Dict, List
from PyQt5.QtCore import QThread, pyqtSignal

from src.models.disk_item import DiskItem
from src.models.analysis_result import AnalysisResult
from src.core.file_utils import FileUtils
from src.core.size_calculator import SizeCalculator


class DiskAnalyzer(QThread):
    """磁盘分析器 - 修复版本，支持停止功能"""

    progress_updated = pyqtSignal(int, str)
    analysis_finished = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, path=None):
        super().__init__()
        self._is_running = True
        self._current_path = path
        self.size_calculator = SizeCalculator()  # 创建计算器实例

    def analyze_path(self, path: str = None):
        """分析指定路径"""
        if path is not None:
            self._current_path = path
        self._is_running = True
        self.size_calculator._is_running = True  # 重置计算器状态
        self.start()

    def run(self):
        """线程执行方法"""
        try:
            if not self._is_running:
                return

            if self._current_path is None:
                result = self._analyze_disks()
            else:
                result = self._analyze_directory(self._current_path)

            if self._is_running:
                self.analysis_finished.emit(result)

        except Exception as e:
            if self._is_running:
                self.error_occurred.emit(f"分析错误: {str(e)}")

    def stop_analysis(self):
        """停止分析"""
        self._is_running = False
        self.size_calculator.stop_calculation()  # 停止计算器
        if self.isRunning():
            self.wait(1000)

    def _analyze_disks(self) -> AnalysisResult:
        """分析所有磁盘"""
        disks = []

        if platform.system() == "Windows":
            disks = self._get_windows_disks()
        else:
            disks = self._get_linux_disks()

        # 计算总大小和百分比
        total_used = sum(disk.size for disk in disks)
        for disk in disks:
            if total_used > 0:
                disk.percentage = (disk.size / total_used) * 100

        return AnalysisResult(
            items=disks,
            total_size=total_used,
            path="",
            result_type="disk"
        )

    def _analyze_directory(self, path: str) -> AnalysisResult:
        """分析指定目录 - 支持停止功能"""
        items = []

        try:
            if not self._is_running:
                return AnalysisResult(items=[], total_size=0, path=path, result_type="directory")

            dir_items = FileUtils.list_directory(path)
            total_items = len(dir_items)

            for i, item_name in enumerate(dir_items):
                if not self._is_running:
                    break

                item_path = os.path.join(path, item_name)

                try:
                    if os.path.isdir(item_path):
                        # 使用计算器计算目录大小
                        size = self.size_calculator.calculate_directory_size_iterative(item_path)
                        item_type = "directory"
                    else:
                        size = os.path.getsize(item_path)
                        item_type = "file"

                    disk_item = DiskItem(
                        name=item_name,
                        path=item_path,
                        size=size,
                        item_type=item_type,
                        parent_path=path
                    )
                    items.append(disk_item)

                except (PermissionError, OSError, MemoryError) as e:
                    continue

                # 更新进度
                if total_items > 0:
                    progress = int((i + 1) / total_items * 100)
                    self.progress_updated.emit(progress, f"正在分析: {item_name}")

        except (PermissionError, MemoryError, OSError) as e:
            self.error_occurred.emit(f"无法访问目录: {path} - {str(e)}")

        # 按大小排序并计算百分比
        total_size = sum(item.size for item in items)
        items.sort(key=lambda x: x.size, reverse=True)

        for item in items:
            if total_size > 0:
                item.percentage = (item.size / total_size) * 100

        return AnalysisResult(
            items=items,
            total_size=total_size,
            path=path,
            result_type="directory"
        )

    def _get_windows_disks(self) -> List[DiskItem]:
        """获取Windows磁盘"""
        import string
        import ctypes

        disks = []
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()

        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drive = f"{letter}:\\"
                try:
                    import psutil
                    usage = psutil.disk_usage(drive)
                    disk_item = DiskItem(
                        name=drive,
                        path=drive,
                        size=usage.used,
                        item_type="disk",
                        total_size=usage.total,
                        used_size=usage.used,
                        free_size=usage.free
                    )
                    disks.append(disk_item)
                except (OSError, ImportError) as e:
                    continue
            bitmask >>= 1

        return disks

    def _get_linux_disks(self) -> List[DiskItem]:
        """获取Linux磁盘"""
        import psutil

        disks = []
        partitions = psutil.disk_partitions()

        for partition in partitions:
            try:
                if partition.fstype in ['squashfs', 'tmpfs', 'devtmpfs']:
                    continue

                usage = psutil.disk_usage(partition.mountpoint)
                disk_item = DiskItem(
                    name=partition.mountpoint,
                    path=partition.mountpoint,
                    size=usage.used,
                    item_type="disk",
                    total_size=usage.total,
                    used_size=usage.used,
                    free_size=usage.free
                )
                disks.append(disk_item)
            except (PermissionError, OSError):
                continue

        return disks
