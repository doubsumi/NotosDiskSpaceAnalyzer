import platform
from pathlib import Path


class Settings:
    """应用配置类"""

    # 应用信息
    APP_NAME = "Notos磁盘空间分析工具"
    APP_VERSION = "V1.1.1"
    ORGANIZATION = "NotosDiskSpaceAnalyzer"

    # 文件大小单位
    SIZE_UNITS = ["B", "KB", "MB", "GB", "TB"]

    # 图表配置
    CHART_COLORS = [
        '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
        '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9',
        '#F8C471', '#82E0AA', '#F1948A', '#85C1E9', '#D7BDE2',
        '#F9E79F', '#A9DFBF', '#F5B7B1', '#AED6F1', '#D2B4DE'
    ]

    # 分析配置
    MAX_DIRECTORY_ITEMS = 50  # 最大显示目录项数，小于2%已实际影响显示，所以最大50个

    # 列表流式渲染（O7）：不做截断，首屏 + 滚动增量热更新，任何一项都不丢弃。
    LIST_INITIAL_ITEMS = 200  # 首屏渲染条数
    LIST_PAGE_ITEMS = 200  # 滚动到尾部阈值时每批追加条数

    # 目录缓存（O8）：会话级目录表上限（约等于已扫描目录总数），
    # 超过时按「最早登记的扫描根」整体逐出；不做 TTL。
    CACHE_MAX_DIRS = 2_000_000

    # 结构性保证：图表只展示 Top-N（MAX_DIRECTORY_ITEMS），列表按大小降序，
    # 因此图表中出现的目录必然落在列表首屏之内（performance-optimization-plan.md O7）。
    assert LIST_INITIAL_ITEMS >= MAX_DIRECTORY_ITEMS

    @classmethod
    def get_platform_specific_settings(cls):
        """获取平台特定设置"""
        system = platform.system()
        if system == "Windows":
            return {
                "root_paths": ["C:\\", "D:\\", "E:\\", "F:\\"],
                "home_dir": Path.home()
            }
        else:  # Linux/Unix
            return {
                "root_paths": ["/", "/home", "/var", "/usr"],
                "home_dir": Path.home()
            }
