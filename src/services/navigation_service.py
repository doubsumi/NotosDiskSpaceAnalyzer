from typing import List


class NavigationService:
    """导航服务 - 修复版本"""

    def __init__(self):
        self.history: List[str] = []
        self.current_path: str = None

    def navigate_to(self, path: str):
        """导航到指定路径"""
        if self.current_path is not None:
            self.history.append(self.current_path)
        self.current_path = path

    def go_back(self) -> str:
        """返回上一级"""
        if self.history:
            self.current_path = self.history.pop()
            return self.current_path
        else:
            self.current_path = None
            return None

    def go_home(self):
        """返回首页"""
        self.history.clear()
        self.current_path = None

    def get_current_path_display(self) -> str:
        """获取当前路径显示文本"""
        if self.current_path is None:
            return "磁盘根目录"
        return f"当前路径: {self.current_path}"
