import os
import math


class SizeCalculator:
    """大小计算器"""

    MAX_RECURSION_DEPTH = 100

    @staticmethod
    def calculate_directory_size(path: str, current_depth=0) -> int:
        """计算目录大小 - 递归方法"""
        if current_depth > SizeCalculator.MAX_RECURSION_DEPTH:
            return 0

        total = 0
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if not entry.name.startswith('.'):
                        if entry.is_file():
                            try:
                                total += entry.stat().st_size
                            except (OSError, PermissionError):
                                continue
                        elif entry.is_dir():
                            try:
                                total += SizeCalculator.calculate_directory_size(
                                    entry.path, current_depth + 1
                                )
                            except (OSError, PermissionError, RecursionError):
                                continue
        except (PermissionError, OSError, RecursionError):
            pass
        return total

    @staticmethod
    def calculate_directory_size_iterative(path: str) -> int:
        """迭代方式计算目录大小 - 修复实现"""
        total = 0
        stack = [path]

        while stack:
            current_path = stack.pop()
            try:
                with os.scandir(current_path) as it:
                    for entry in it:
                        try:
                            if entry.is_file():
                                total += entry.stat().st_size
                            elif entry.is_dir() and not entry.name.startswith('.'):
                                stack.append(entry.path)
                        except (OSError, PermissionError):
                            continue
            except (PermissionError, OSError):
                continue

        return total

    @staticmethod
    def format_size(size_bytes: int) -> str:
        """格式化大小显示"""
        if size_bytes == 0:
            return "0 B"

        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(size_bytes, 1024))) if size_bytes > 0 else 0
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2) if p > 0 else 0

        return f"{s} {size_names[i]}"
