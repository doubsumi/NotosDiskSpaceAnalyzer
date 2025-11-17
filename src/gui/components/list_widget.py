from PyQt5.QtWidgets import QListWidget, QListWidgetItem, QMenu, QAction
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QFont
import os
import platform
import subprocess


class DirectoryListWidget(QListWidget):
    """目录列表组件 - 修复右键菜单问题"""

    item_clicked = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        """设置UI"""
        self.setFont(QFont("Arial", 10))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def update_list(self, analysis_result):
        """更新列表"""
        self.clear()

        if not analysis_result.items:
            item = QListWidgetItem("无数据或目录为空")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.addItem(item)
            return

        for item in analysis_result.items:
            list_item = QListWidgetItem(item.display_name)
            list_item.setData(Qt.UserRole, item)

            # 根据类型设置不同的样式和提示
            if item.item_type == "disk":
                list_item.setToolTip(f"点击进入磁盘根目录")
            elif item.item_type == "directory":
                list_item.setToolTip(f"点击进入目录: {item.name}\n右键菜单可打开文件浏览器")
            else:  # file
                list_item.setToolTip(f"文件: {item.name}\n大小: {item.formatted_size}")
                # 文件不可点击进入
                if not item.is_clickable:
                    list_item.setFlags(list_item.flags() & ~Qt.ItemIsEnabled)
                    list_item.setForeground(Qt.gray)

            self.addItem(list_item)

    def mousePressEvent(self, event):
        """处理鼠标点击事件 - 修复右键问题"""
        # 如果是右键点击，不处理进入逻辑，让右键菜单显示
        if event.button() == Qt.RightButton:
            super().mousePressEvent(event)
            return

        # 左键点击：处理进入逻辑
        super().mousePressEvent(event)

        item = self.itemAt(event.pos())
        if item and item.isSelected():
            disk_item = item.data(Qt.UserRole)
            if disk_item and hasattr(disk_item, 'item_type') and disk_item.is_clickable:
                self.item_clicked.emit(disk_item)

    def show_context_menu(self, position):
        """显示右键菜单 - 支持目录和文件"""
        item = self.itemAt(position)
        if not item:
            return

        disk_item = item.data(Qt.UserRole)
        if not disk_item:
            return

        menu = QMenu(self)

        # 添加"在文件浏览器中打开"选项 - 支持目录和文件
        open_action = QAction("在文件浏览器中打开", self)
        open_action.triggered.connect(lambda: self.open_in_explorer(disk_item.path))
        menu.addAction(open_action)

        # 如果是目录，添加"进入目录"选项
        if disk_item.item_type in ['disk', 'directory']:
            enter_action = QAction("进入目录", self)
            enter_action.triggered.connect(lambda: self.enter_directory(disk_item))
            menu.addAction(enter_action)

        # 添加复制路径选项
        copy_path_action = QAction("复制路径", self)
        copy_path_action.triggered.connect(lambda: self.copy_path(disk_item.path))
        menu.addAction(copy_path_action)

        # 显示菜单
        menu.exec_(self.mapToGlobal(position))

    def enter_directory(self, disk_item):
        """进入目录"""
        self.item_clicked.emit(disk_item)

    def copy_path(self, path):
        """复制路径到剪贴板"""
        from PyQt5.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(path)

    def open_in_explorer(self, path):
        """在文件浏览器中打开"""
        try:
            if platform.system() == "Windows":
                if os.path.isfile(path):
                    # 文件：打开所在文件夹并选中文件
                    subprocess.run(f'explorer /select,"{path}"', shell=True)
                else:
                    # 目录：直接打开
                    subprocess.run(f'explorer "{path}"', shell=True)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(['open', path])
            else:  # Linux
                subprocess.run(['xdg-open', path])
        except Exception as e:
            print(f"打开文件浏览器失败: {e}")
