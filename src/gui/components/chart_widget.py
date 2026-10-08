import os
import platform
import subprocess

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QMenu, QAction
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication

from src.services.analysis_service import AnalysisResult
from config.settings import Settings


class ChartWidget(QWidget):
    """图表组件 - 使用Settings配置优化"""

    # 添加点击信号
    chart_item_clicked = pyqtSignal(object)  # 传递 DisplayItem

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_result = None
        self.wedges = None
        #: 与 ``self.wedges`` 一一对应的条目；"其他"楔形为 ``None``（聚合项无真实路径，P0-6）。
        self.wedge_items = []
        self.is_dark_mode = False
        self.other_item = False
        self._setup_matplotlib()
        self.init_ui()
        self._preheat_fonts()

    def _setup_matplotlib(self):
        """设置matplotlib配置"""
        try:
            # 使用Settings中的字体配置
            plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
            plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
        except Exception:
            # 如果字体设置失败，使用默认设置
            pass

    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)

        # 图表标题
        self.chart_title = QLabel("磁盘使用情况")
        self.chart_title.setAlignment(Qt.AlignCenter)
        self.update_title_style()  # 使用统一的方法设置样式
        layout.addWidget(self.chart_title)

        # 创建matplotlib图形
        self.figure = Figure(figsize=(6, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)

        # 连接点击事件
        self.canvas.mpl_connect('button_press_event', self.on_chart_click)

        layout.addWidget(self.canvas)

        # 添加提示标签
        self.hint_label = QLabel("")
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setStyleSheet("color: #666; font-size: 12px; margin: 5px;")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

    def _preheat_fonts(self):
        """首帧字体缓存预热（O7）：构造时离屏绘制一次空图。

        matplotlib 首次渲染文本需要做字体度量并建缓存（实测 40~80ms），
        把这笔一次性开销移到应用启动时，消除用户首次进入目录的 UI 尖峰。
        """
        try:
            from matplotlib.backends.backend_agg import FigureCanvasAgg

            figure = Figure(figsize=(1, 1), dpi=100)
            FigureCanvasAgg(figure)
            ax = figure.add_subplot(111)
            ax.pie([1, 1], labels=["预热", "预热"], autopct="%1.1f%%")
            figure.canvas.draw()
        except Exception:
            pass  # 预热失败不影响功能

    def update_chart(self, analysis_result: AnalysisResult):
        """更新图表 - 使用Settings配置"""
        self.current_result = analysis_result
        self.wedge_items = []
        self.other_item = False
        self.figure.clear()
        ax = self.figure.add_subplot(111)

        # 设置背景色
        self._set_chart_background(ax)

        if not analysis_result.items:
            self._show_no_data_message(ax)
            self.hint_label.setText("")
            self.update_title_style()
            self.canvas.draw()
            return

        # 准备饼图数据（wedge 与 wedge_items 一一对应，P0-6）
        labels, sizes, colors = self._prepare_chart_data(analysis_result)

        # 绘制饼图
        if sum(sizes) > 0:
            self._draw_pie_chart(ax, labels, sizes, colors)
            self.update_chart_title(analysis_result)

            if self.other_item:
                self.hint_label.setText(
                    '💡 "其他"为占比小于 2% 的条目合计（Logical Size），无法直接进入'
                )
            else:
                self.hint_label.setText("")
        else:
            self._show_no_data_message(ax)
            self.hint_label.setText("")
            self.chart_title.setText("无数据可用")

        self.canvas.draw()

    def _set_chart_background(self, ax):
        """设置图表背景色"""
        if self.is_dark_mode:
            self.figure.patch.set_facecolor('#1a1a1a')
            ax.set_facecolor('#2d2d2d')
        else:
            self.figure.patch.set_facecolor('white')
            ax.set_facecolor('white')

    def _show_no_data_message(self, ax):
        """显示无数据消息"""
        text_color = 'white' if self.is_dark_mode else 'black'
        ax.text(0.5, 0.5, "无数据", ha='center', va='center',
                transform=ax.transAxes, color=text_color, fontsize=12)

    def show_loading(self, message: str = "计算中..."):
        """O9 预览态：图表区显示加载占位，不绘制「只有文件」的误导性饼图。

        正式结果到达后由 ``update_chart`` 覆盖。置空 ``current_result``，
        避免主题切换时用占位态误重绘旧饼图。
        """
        self.current_result = None
        self.wedges = None
        self.wedge_items = []
        self.other_item = False
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        self._set_chart_background(ax)
        text_color = 'white' if self.is_dark_mode else 'black'
        ax.text(0.5, 0.5, message, ha='center', va='center',
                transform=ax.transAxes, color=text_color, fontsize=12)
        ax.axis('off')
        self.chart_title.setText("目录大小计算中...")
        self.update_title_style()
        self.hint_label.setText("")
        self.canvas.draw()

    def _prepare_chart_data(self, analysis_result):
        """准备图表数据，并建立与 wedge 一一对应的 ``wedge_items``（P0-6）。

        * ``all_total`` 采用 ``analysis_result.total_size``（Logical Size，P0-5）。
        * 主项 = 占比 > 2% 的条目；``other = all_total - 主项合计``。
        * "其他"是聚合项，无真实路径，因此映射为 ``None``，不得指向任何真实 item。
        """
        labels = []
        sizes = []
        colors = []
        self.wedge_items = []
        self.other_item = False

        all_total = analysis_result.total_size
        if all_total <= 0:
            return labels, sizes, colors

        items = analysis_result.items[:Settings.MAX_DIRECTORY_ITEMS]
        main_items = [item for item in items if item.size / all_total * 100 > 2]

        for i, item in enumerate(main_items):
            label = f"{self.shorten_text(item.name, 8)}\n{self.format_size_short(item.size)}"
            labels.append(label)
            sizes.append(item.size)
            colors.append(self.get_color(i))
            self.wedge_items.append(item)

        main_total = sum(item.size for item in main_items)
        other_size = all_total - main_total
        if other_size > 0:
            self.other_item = True
            labels.append("其他")
            sizes.append(other_size)
            colors.append(self.get_color(len(main_items)))
            self.wedge_items.append(None)

        return labels, sizes, colors

    def _draw_pie_chart(self, ax, labels, sizes, colors):
        """绘制饼图"""
        text_color = 'white' if self.is_dark_mode else 'black'

        self.wedges, texts, autotexts = ax.pie(
            sizes,
            labels=labels,
            autopct='%1.1f%%',
            colors=colors,
            startangle=90,
            labeldistance=1.05,
            pctdistance=0.85,
            rotatelabels=True
        )

        # 设置文本样式
        for autotext in autotexts:
            autotext.set_color('white' if self.is_dark_mode else 'black')
            autotext.set_fontweight('bold')
            autotext.set_fontsize(8)

        for text in texts:
            text.set_fontsize(9)
            text.set_color(text_color)

        ax.axis('equal')

    def update_chart_title(self, analysis_result):
        """更新图表标题 - 使用更清晰的结构"""
        if analysis_result.result_type == "disk":
            self.chart_title.setText("🖥️ 磁盘使用情况")
        else:
            clean_path = analysis_result.path.rstrip('\\/')
            is_disk_root = (
                (len(clean_path) == 2 and clean_path[1] == ':') or
                clean_path == ''
            )

            if is_disk_root:
                disk_name = "/" if clean_path == '' else clean_path[0]
                self.chart_title.setText(f"磁盘 {disk_name} 使用情况")
            else:
                dir_name = os.path.basename(clean_path)
                self.chart_title.setText(f"目录使用情况: {dir_name}")

        self.update_title_style()

    def update_title_style(self):
        """更新标题样式 - 使用Settings中的颜色配置"""
        if self.is_dark_mode:
            self.chart_title.setStyleSheet("font-size: 14px; font-weight: bold; margin: 10px; color: #e9ecef;")
        else:
            self.chart_title.setStyleSheet("font-size: 14px; font-weight: bold; margin: 10px; color: #212529;")

    def on_chart_click(self, event):
        """处理饼图点击事件"""
        if event.button == 3:  # 右键
            self.show_chart_context_menu(event)
        elif event.button == 1:  # 左键
            self._handle_left_click(event)

    def _handle_left_click(self, event):
        """处理左键点击"""
        if not self.wedges:
            return

        index = self._get_clicked_wedge_index(event)
        if index == -1 or index >= len(self.wedge_items):
            return
        clicked_item = self.wedge_items[index]
        # "其他"楔形映射为 None，忽略；不可进入的项也忽略
        if clicked_item is not None and clicked_item.is_clickable:
            self.chart_item_clicked.emit(clicked_item)

    def show_chart_context_menu(self, event):
        """显示饼图的右键菜单"""
        if not self.wedges:
            return

        clicked_index = self._get_clicked_wedge_index(event)
        if clicked_index == -1 or clicked_index >= len(self.wedge_items):
            return

        clicked_item = self.wedge_items[clicked_index]
        # "其他"是聚合项，没有真实路径，不弹出菜单（P0-6）
        if clicked_item is None:
            return
        self._create_context_menu(event, clicked_item)

    def _get_clicked_wedge_index(self, event):
        """获取点击的饼图部分索引"""
        for i, wedge in enumerate(self.wedges):
            if wedge.contains_point([event.x, event.y]):
                return i
        return -1

    def _create_context_menu(self, event, clicked_item):
        """创建右键菜单"""
        menu = QMenu(self)

        # 添加"在文件浏览器中打开"选项
        open_action = QAction("在文件浏览器中打开", self)
        open_action.triggered.connect(lambda: self.open_in_explorer(clicked_item.path))
        menu.addAction(open_action)

        # 如果是目录，添加"进入目录"选项
        if clicked_item.item_type in ['disk', 'directory']:
            enter_action = QAction("进入目录", self)
            enter_action.triggered.connect(lambda: self.chart_item_clicked.emit(clicked_item))
            menu.addAction(enter_action)

        # 添加复制路径选项
        copy_path_action = QAction("复制路径", self)
        copy_path_action.triggered.connect(lambda: self.copy_path(clicked_item.path))
        menu.addAction(copy_path_action)

        # 显示菜单
        from PyQt5.QtCore import QPoint
        global_pos = self.canvas.mapToGlobal(QPoint(int(event.x), int(event.y)))
        menu.exec_(global_pos)

    def open_in_explorer(self, path):
        """在文件浏览器中打开 - 使用Settings中的平台配置"""
        try:
            system = platform.system()
            if system == "Windows":
                if os.path.isfile(path):
                    subprocess.run(f'explorer /select,"{path}"', shell=True)
                else:
                    subprocess.run(f'explorer "{path}"', shell=True)
            elif system == "Darwin":
                subprocess.run(['open', path])
            else:  # Linux/Unix
                subprocess.run(['xdg-open', path])
        except Exception as e:
            print(f"打开文件浏览器失败: {e}")

    def copy_path(self, path):
        """复制路径到剪贴板"""
        clipboard = QApplication.clipboard()
        clipboard.setText(path)

    def shorten_text(self, text, max_length):
        """缩短文本以避免重叠"""
        if len(text) > max_length:
            return text[:max_length - 3] + "..."
        return text

    def format_size_short(self, size_bytes):
        """格式化大小显示 - 使用Settings中的单位配置"""
        if size_bytes == 0:
            return "0B"

        for i, unit in enumerate(Settings.SIZE_UNITS):
            if size_bytes < 1024 ** (i + 1) or i == len(Settings.SIZE_UNITS) - 1:
                if i == 0:  # Bytes
                    return f"{size_bytes}{unit}"
                else:
                    size_value = size_bytes / (1024 ** i)
                    return f"{size_value:.1f}{unit}"

    def get_color(self, index):
        """获取颜色 - 使用Settings中的颜色配置"""
        return Settings.CHART_COLORS[index % len(Settings.CHART_COLORS)]

    def apply_theme(self, is_dark_mode):
        """应用主题"""
        self.is_dark_mode = is_dark_mode
        self.update_title_style()
        # 重新绘制当前图表
        if self.current_result:
            self.update_chart(self.current_result)
