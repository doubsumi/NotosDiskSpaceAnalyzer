import os
import math
import time


class SizeCalculator:
    """大小计算器 - 简化版本，移除信号"""

    def __init__(self):
        self._is_running = True

    def stop_calculation(self):
        """停止计算"""
        self._is_running = False

    def calculate_directory_size_iterative(self, path: str, timeout=30) -> int:
        """迭代方式计算目录大小 - 简化版本"""
        self._is_running = True
        total = 0
        stack = [path]
        start_time = time.time()

        while stack and self._is_running:
            # 检查超时
            if time.time() - start_time > timeout:
                break

            current_path = stack.pop()

            try:
                with os.scandir(current_path) as it:
                    for entry in it:
                        if not self._is_running:
                            break

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
        """格式化文件大小"""
        if size_bytes == 0:
            return "0 B"

        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(size_bytes, 1024))) if size_bytes > 0 else 0
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2) if p > 0 else 0

        return f"{s} {size_names[i]}"
