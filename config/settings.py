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
    SCAN_TIMEOUT = 30  # 扫描超时时间(秒)

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
