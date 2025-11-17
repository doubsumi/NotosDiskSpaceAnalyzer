from dataclasses import dataclass
from typing import Dict, Any, List

from src.models.disk_item import DiskItem


@dataclass
class AnalysisResult:
    """分析结果数据模型"""
    items: List[DiskItem]
    total_size: int
    path: str
    result_type: str  # 'disk' or 'directory'

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'items': [item.__dict__ for item in self.items],
            'total_size': self.total_size,
            'path': self.path,
            'result_type': self.result_type
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnalysisResult':
        """从字典创建实例"""
        items = [DiskItem(**item_data) for item_data in data['items']]
        return cls(
            items=items,
            total_size=data['total_size'],
            path=data['path'],
            result_type=data['result_type']
        )
