import os
import psutil
from typing import List


class FileUtils:
    """文件操作工具类 - 修复版本"""

    @staticmethod
    def get_disk_usage(path: str) -> tuple:
        """获取磁盘使用情况"""
        try:
            usage = psutil.disk_usage(path)
            return usage.total, usage.used, usage.free
        except:
            # 备用方法
            return FileUtils.get_disk_usage_simple(path)

    @staticmethod
    def get_disk_usage_simple(path: str) -> tuple:
        """简单磁盘使用统计（备用方法）"""
        try:
            if not os.path.exists(path):
                return 0, 0, 0

            # 这是一个简化的实现，实际项目中可能需要更复杂的逻辑
            total = psutil.disk_usage(path).total
            used = psutil.disk_usage(path).used
            free = psutil.disk_usage(path).free
            return total, used, free
        except:
            return 0, 0, 0

    @staticmethod
    def list_directory(path: str) -> List[str]:
        """列出目录内容"""
        try:
            return os.listdir(path)
        except (PermissionError, FileNotFoundError):
            return []

    @staticmethod
    def is_accessible(path: str) -> bool:
        """检查路径是否可访问"""
        try:
            os.listdir(path)
            return True
        except (PermissionError, FileNotFoundError):
            return False

    @staticmethod
    def get_parent_path(path: str) -> str:
        """获取父路径"""
        return os.path.dirname(path) if path else ""
