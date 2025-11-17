from dataclasses import dataclass
from typing import Optional


@dataclass
class DiskItem:
    """磁盘项数据模型 - 支持文件和目录"""
    name: str
    path: str
    size: int
    item_type: str  # 'disk', 'directory', or 'file'
    percentage: float = 0.0
    parent_path: Optional[str] = None
    total_size: int = 0
    used_size: int = 0
    free_size: int = 0

    @property
    def formatted_size(self) -> str:
        """格式化大小显示"""
        return self._format_size(self.size)

    @property
    def display_name(self) -> str:
        """显示名称 - 支持文件类型"""
        if self.item_type == 'disk':
            used_percent = (self.used_size / self.total_size) * 100 if self.total_size > 0 else 0
            return f"{self.name} - 已用: {self._format_size(self.used_size)} / {self._format_size(self.total_size)} ({used_percent:.1f}%)"
        elif self.item_type == 'file':
            return f"📄 {self.name} - {self.formatted_size} ({self.percentage:.1f}%)"
        else:
            return f"📁 {self.name} - {self.formatted_size} ({self.percentage:.1f}%)"

    @property
    def is_clickable(self) -> bool:
        """是否可点击进入"""
        return self.item_type in ['disk', 'directory']

    def _format_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        import math

        if size_bytes == 0:
            return "0 B"

        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)

        return f"{s} {size_names[i]}"
