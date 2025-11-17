import os
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QFileInfo


class IconLoader:
    """图标加载器"""

    @staticmethod
    def load_icon(icon_name, fallback_theme_icon=None):
        """
        加载图标

        Args:
            icon_name: 图标文件名
            fallback_theme_icon: 备用的主题图标名

        Returns:
            QIcon: 图标对象
        """
        # 首先尝试从资源文件加载
        resource_path = IconLoader.get_resource_path(f"icons/{icon_name}")
        if os.path.exists(resource_path):
            return QIcon(resource_path)

        # 其次尝试从主题加载
        if fallback_theme_icon:
            theme_icon = QIcon.fromTheme(fallback_theme_icon)
            if not theme_icon.isNull():
                return theme_icon

        # 最后返回空图标
        return QIcon()

    @staticmethod
    def get_resource_path(relative_path):
        """获取资源文件路径"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))
        return os.path.join(project_root, "resources", relative_path)

    @staticmethod
    def icon_exists(icon_path):
        """检查图标文件是否存在"""
        return QFileInfo(icon_path).exists()
    