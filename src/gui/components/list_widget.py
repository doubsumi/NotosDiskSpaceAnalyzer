from PyQt5.QtWidgets import QListWidget, QListWidgetItem, QMenu, QAction
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QFont
import os
import platform
import subprocess

from config.settings import Settings

#: 悬停提示补充：向用户解释为何在系统文件管理器里看不到该项目（P0-2：默认扫描隐藏项）。
HIDDEN_HINT = "\n系统隐藏项，通常为系统休眠/虚拟内存文件，资源管理器默认隐藏，不可操作，但占用实际内存"

#: 滚动追加触发阈值：距列表底部不足 3 屏时加载下一批（O7）。
_SCROLL_THRESHOLD_SCREENS = 3


class DirectoryListWidget(QListWidget):
    """目录列表组件（O7 流式渲染：首屏 + 滚动增量热更新，不截断）。

    渲染策略（docs/performance-optimization-plan.md O7）：
    * ``update_list`` 只渲染前 ``Settings.LIST_INITIAL_ITEMS`` 项，
      ``setUpdatesEnabled(False)`` 包住一次性提交 → 首屏 <10ms；
    * 滚动位置进入尾部阈值（距底 < 3 屏）时追加下一批
      ``Settings.LIST_PAGE_ITEMS``，每批只 ``addItems`` 新对象，
      不 clear、不重建已渲染项，顺序由 service 的降序结果保证；
    * ``QListWidgetItem`` 惰性构造：tooltip / 样式在追加该批时才计算；
    * 底部保留一行不可选中提示，随批次更新文本而非新增行。
    """

    item_clicked = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        #: 尚未渲染的数据源快照（DisplayItem 列表，已按大小降序）。
        self._source = []
        #: 已渲染的数据条数（不含底部提示行）。
        self._rendered = 0
        #: 底部状态提示行；全部渲染完成后移除。
        self._hint_item = None
        self.setup_ui()

    def setup_ui(self):
        """设置UI"""
        self.setFont(QFont("Arial", 10))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    # ------------------------------------------------------------------
    # 流式渲染
    # ------------------------------------------------------------------
    def update_list(self, analysis_result):
        """更新列表：只渲染首屏，其余随滚动增量追加（O7）。"""
        self.clear()
        self._hint_item = None
        self._source = list(analysis_result.items) if analysis_result else []
        self._rendered = 0

        if not self._source:
            item = QListWidgetItem("无数据或目录为空")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.addItem(item)
            return

        self._append_batch(Settings.LIST_INITIAL_ITEMS)
        self.scrollToTop()

    def _append_batch(self, count):
        """追加下一批未渲染项；只 addItems 新对象，不触碰已渲染项。"""
        batch = self._source[self._rendered : self._rendered + count]
        if not batch:
            return
        self.setUpdatesEnabled(False)
        try:
            start_row = self.count()
            self.addItems([item.display_name for item in batch])
            # 惰性构造：tooltip / 样式在该批追加时才计算
            for offset, item in enumerate(batch):
                self._configure_item(self.item(start_row + offset), item)
            self._rendered += len(batch)
            self._update_hint()
        finally:
            self.setUpdatesEnabled(True)

    def _configure_item(self, list_item, item):
        """配置单个 ``QListWidgetItem``（UserRole 数据 / tooltip / 不可点样式）。"""
        list_item.setData(Qt.UserRole, item)

        # 根据类型设置不同的提示
        if item.item_type == "disk":
            tooltip = "点击进入磁盘根目录"
        elif item.item_type == "directory":
            tooltip = f"点击进入目录: {item.name}\n右键菜单可打开文件浏览器"
        else:  # file
            tooltip = f"文件: {item.name}\n大小: {item.formatted_size}"
            # 文件不可点击进入
            if not item.is_clickable:
                list_item.setFlags(list_item.flags() & ~Qt.ItemIsEnabled)
                list_item.setForeground(Qt.gray)

        if item.is_hidden:
            tooltip += HIDDEN_HINT
        list_item.setToolTip(tooltip)

    def _update_hint(self):
        """维护底部提示行：随批次更新文本，全部渲染完成后移除。"""
        total = len(self._source)
        if self._rendered >= total:
            if self._hint_item is not None:
                self.takeItem(self.row(self._hint_item))
                self._hint_item = None
            return
        text = f"… 已显示 {self._rendered}/{total}，继续滚动加载"
        if self._hint_item is None:
            self._hint_item = QListWidgetItem(text)
            self._hint_item.setFlags(self._hint_item.flags() & ~Qt.ItemIsEnabled)
            self._hint_item.setForeground(Qt.gray)
            self.addItem(self._hint_item)
        else:
            self._hint_item.setText(text)

    def _on_scroll(self, _value):
        """滚动进入尾部阈值（距底 < 3 屏）时增量追加下一批。"""
        bar = self.verticalScrollBar()
        if bar.maximum() <= 0:
            return
        threshold = _SCROLL_THRESHOLD_SCREENS * max(1, self.viewport().height())
        if bar.maximum() - bar.value() < threshold:
            self._append_batch(Settings.LIST_PAGE_ITEMS)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
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
