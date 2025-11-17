import os
import platform
import subprocess

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSignal

from src.models.analysis_result import AnalysisResult
from config.settings import Settings


class ChartWidget(QWidget):
    """图表组件 - 修复饼图重叠和添加点击功能"""

    # 添加点击信号
    chart_item_clicked = pyqtSignal(object)  # 传递DiskItem

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_result = None
        self.wedges = None
        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)

        # 图表标题
        self.chart_title = QLabel("磁盘使用情况")
        self.chart_title.setAlignment(Qt.AlignCenter)
        self.chart_title.setStyleSheet("font-size: 14px; font-weight: bold; margin: 10px;")
        layout.addWidget(self.chart_title)

        # 创建matplotlib图形
        self.figure = Figure(figsize=(6, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)

        # 连接点击事件
        self.canvas.mpl_connect('button_press_event', self.on_chart_click)

        layout.addWidget(self.canvas)

    def update_chart(self, analysis_result: AnalysisResult):
        """更新图表 - 修复标题逻辑"""
        self.current_result = analysis_result
        self.figure.clear()
        ax = self.figure.add_subplot(111)

        if not analysis_result.items:
            ax.text(0.5, 0.5, "无数据", ha='center', va='center', transform=ax.transAxes)
            self.chart_title.setText("磁盘使用情况 - 无数据")
            self.canvas.draw()
            return

        # 准备饼图数据
        labels = []
        sizes = []
        colors = []

        # 只显示前8个最大的项目，避免重叠
        display_items = analysis_result.items[:8]

        for i, item in enumerate(display_items):
            # 缩短标签以避免重叠
            label = f"{self.shorten_text(item.name, 10)}\n{self.format_size_short(item.size)}"
            labels.append(label)
            sizes.append(item.size)
            colors.append(self.get_color(i))

        # 绘制饼图
        if sum(sizes) > 0:
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
                autotext.set_color('white')
                autotext.set_fontweight('bold')
                autotext.set_fontsize(8)

            for text in texts:
                text.set_fontsize(9)

            ax.axis('equal')

            # 修复：正确的标题逻辑
            if analysis_result.result_type == "disk":
                # 情况1：首页 - 显示所有磁盘汇总
                self.chart_title.setText("🖥️磁盘使用情况")
            else:  # 进入具体路径的分析
                # 清理路径
                clean_path = analysis_result.path.rstrip('\\/')

                # 判断是否是磁盘根目录
                is_disk_root = (
                    # Windows磁盘根目录：C:、D: 等
                    (len(clean_path) == 2 and clean_path[1] == ':') or
                    # Linux根目录：/
                    clean_path == ''
                )

                if is_disk_root:
                    # 情况2：磁盘根目录
                    if clean_path == '':
                        disk_name = "/"
                    else:
                        disk_name = clean_path[0]  # 提取磁盘字母 C: -> C
                    self.chart_title.setText(f"磁盘 {disk_name} 使用情况")
                else:
                    # 情况3：普通目录
                    dir_name = os.path.basename(clean_path)
                    self.chart_title.setText(f"目录使用情况: {dir_name}")
        else:
            ax.text(0.5, 0.5, "无数据", ha='center', va='center', transform=ax.transAxes)
            self.chart_title.setText("无数据可用")

        self.canvas.draw()

    def extract_directory_name(self, path: str) -> str:
        """提取目录名称"""
        if not path:
            return "未知目录"

        # 移除末尾的路径分隔符
        path = path.rstrip('\\/')

        # 分割路径并获取最后一部分
        if '\\' in path:  # Windows路径
            parts = path.split('\\')
        elif '/' in path:  # Linux路径
            parts = path.split('/')
        else:
            parts = [path]

        # 获取非空的最后一部分
        for part in reversed(parts):
            if part and part not in ['', '\\', '/']:
                return part

        # 如果都是空，返回根目录标识
        return "根目录"

    def on_chart_click(self, event):
        """处理饼图点击事件 - 支持右键菜单"""
        if event.button == 3:  # 右键
            self.show_chart_context_menu(event)
        elif event.button == 1:  # 左键
            if self.wedges and self.current_result:
                for i, wedge in enumerate(self.wedges):
                    if wedge.contains_point([event.x, event.y]):
                        # 找到对应的数据项
                        if i < len(self.current_result.items):
                            clicked_item = self.current_result.items[i]
                            # 只对可点击类型发出点击信号
                            if clicked_item.is_clickable:
                                self.chart_item_clicked.emit(clicked_item)
                        break

    def show_chart_context_menu(self, event):
        """显示饼图的右键菜单 - 简化版本"""
        if not self.wedges or not self.current_result:
            return

        # 找到点击的饼图部分
        clicked_index = -1
        for i, wedge in enumerate(self.wedges):
            if wedge.contains_point([event.x, event.y]):
                clicked_index = i
                break

        if clicked_index == -1 or clicked_index >= len(self.current_result.items):
            return

        clicked_item = self.current_result.items[clicked_index]

        # 创建右键菜单
        from PyQt5.QtWidgets import QMenu, QAction
        from PyQt5.QtCore import QPoint

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

        # 简化：直接在鼠标点击位置显示菜单
        # 将matplotlib事件坐标转换为Qt坐标
        global_pos = self.canvas.mapToGlobal(QPoint(int(event.x), int(event.y)))
        menu.exec_(global_pos)

    def open_in_explorer(self, path):
        """在文件浏览器中打开"""
        try:
            if platform.system() == "Windows":
                if os.path.isfile(path):
                    subprocess.run(f'explorer /select,"{path}"', shell=True)
                else:
                    subprocess.run(f'explorer "{path}"', shell=True)
            elif platform.system() == "Darwin":
                subprocess.run(['open', path])
            else:
                subprocess.run(['xdg-open', path])
        except Exception as e:
            print(f"打开文件浏览器失败: {e}")

    def copy_path(self, path):
        """复制路径到剪贴板"""
        from PyQt5.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(path)

    def shorten_text(self, text, max_length):
        """缩短文本以避免重叠"""
        if len(text) > max_length:
            return text[:max_length - 3] + "..."
        return text

    def format_size_short(self, size_bytes):
        """格式化大小显示 - 短版本"""
        if size_bytes == 0:
            return "0B"

        size_names = ["B", "K", "M", "G", "T"]
        i = int(max(0, min(len(size_names) - 1,
                           (len(str(size_bytes)) - 1) // 3)))
        p = 1024 ** i
        s = round(size_bytes / p, 1)

        return f"{s}{size_names[i]}"

    def get_color(self, index):
        """获取颜色"""
        colors = Settings.CHART_COLORS
        return colors[index % len(colors)]
