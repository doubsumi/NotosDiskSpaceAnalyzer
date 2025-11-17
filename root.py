import sys
import os
import platform
from pathlib import Path
from collections import defaultdict
import math

# GUI库
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QWidget, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QMessageBox, QProgressBar, QSplitter)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QPalette, QColor

# 图表库
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Patch


class DiskAnalyzer(QThread):
    """磁盘分析线程"""
    progress_updated = pyqtSignal(int)
    analysis_finished = pyqtSignal(dict)

    def __init__(self, path=None):
        super().__init__()
        self.path = path
        self.is_running = True

    def run(self):
        if self.path is None:
            # 分析所有磁盘
            result = self.analyze_disks()
        else:
            # 分析指定目录
            result = self.analyze_directory(self.path)
        self.analysis_finished.emit(result)

    def stop(self):
        self.is_running = False

    def analyze_disks(self):
        """分析所有磁盘"""
        disks = {}

        if platform.system() == "Windows":
            # Windows系统
            import string
            import ctypes
            drives = []
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append(letter + ":\\")
                bitmask >>= 1

            total_drives = len(drives)
            for i, drive in enumerate(drives):
                if not self.is_running:
                    break
                try:
                    total, used, free = self.get_disk_usage(drive)
                    disks[drive] = {
                        'total': total,
                        'used': used,
                        'free': free,
                        'type': 'disk'
                    }
                except OSError:
                    continue
                self.progress_updated.emit(int((i + 1) / total_drives * 100))
        else:
            # Linux系统
            import psutil
            partitions = psutil.disk_partitions()
            total_drives = len(partitions)
            for i, partition in enumerate(partitions):
                if not self.is_running:
                    break
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    disks[partition.mountpoint] = {
                        'total': usage.total,
                        'used': usage.used,
                        'free': usage.free,
                        'type': 'disk'
                    }
                except PermissionError:
                    continue
                self.progress_updated.emit(int((i + 1) / total_drives * 100))

        return disks

    def analyze_directory(self, path):
        """分析指定目录"""
        result = {}
        try:
            items = os.listdir(path)
            total_items = len(items)

            for i, item in enumerate(items):
                if not self.is_running:
                    break

                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    try:
                        size = self.get_folder_size(item_path)
                        result[item] = {
                            'path': item_path,
                            'size': size,
                            'type': 'directory'
                        }
                    except (PermissionError, OSError):
                        continue

                self.progress_updated.emit(int((i + 1) / total_items * 100))
        except PermissionError:
            pass

        return result

    def get_disk_usage(self, path):
        """获取磁盘使用情况"""
        import psutil
        usage = psutil.disk_usage(path)
        return usage.total, usage.used, usage.free

    def get_folder_size(self, path):
        """获取文件夹大小"""
        total = 0
        try:
            for entry in os.scandir(path):
                if entry.is_file():
                    total += entry.stat().st_size
                elif entry.is_dir():
                    total += self.get_folder_size(entry.path)
        except (PermissionError, OSError):
            pass
        return total


class DiskSpaceAnalyzer(QMainWindow):
    """磁盘空间分析器主窗口"""

    def __init__(self):
        super().__init__()
        self.current_path = None
        self.history = []
        self.analyzer = None
        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("磁盘空间分析工具")
        self.setGeometry(100, 100, 1200, 800)

        # 设置样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f0f0;
            }
            QWidget {
                font-family: Arial, sans-serif;
            }
            QPushButton {
                background-color: #4CAF50;
                border: none;
                color: white;
                padding: 8px 16px;
                text-align: center;
                text-decoration: none;
                font-size: 14px;
                margin: 4px 2px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
            QListWidget {
                background-color: white;
                border: 1px solid #cccccc;
                border-radius: 4px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #eeeeee;
            }
            QListWidget::item:selected {
                background-color: #e0e0e0;
            }
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
            }
        """)

        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout(central_widget)

        # 标题
        title_label = QLabel("磁盘空间分析工具")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        main_layout.addWidget(title_label)

        # 路径显示和导航按钮
        nav_layout = QHBoxLayout()
        self.path_label = QLabel("磁盘根目录")
        self.path_label.setFont(QFont("Arial", 10))

        self.back_button = QPushButton("返回上级")
        self.back_button.clicked.connect(self.go_back)
        self.back_button.setEnabled(False)

        self.home_button = QPushButton("返回首页")
        self.home_button.clicked.connect(self.go_home)
        self.home_button.setEnabled(False)

        nav_layout.addWidget(self.path_label)
        nav_layout.addStretch()
        nav_layout.addWidget(self.back_button)
        nav_layout.addWidget(self.home_button)
        main_layout.addLayout(nav_layout)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # 分割器 - 图表和列表
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # 左侧 - 饼图
        self.chart_widget = QWidget()
        chart_layout = QVBoxLayout(self.chart_widget)

        self.chart_title = QLabel("磁盘使用情况")
        self.chart_title.setAlignment(Qt.AlignCenter)
        self.chart_title.setFont(QFont("Arial", 12, QFont.Bold))
        chart_layout.addWidget(self.chart_title)

        # 创建matplotlib图形
        self.figure = Figure(figsize=(6, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        chart_layout.addWidget(self.canvas)

        splitter.addWidget(self.chart_widget)

        # 右侧 - 目录列表
        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self.on_item_clicked)
        splitter.addWidget(self.list_widget)

        # 设置分割器比例
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        # 状态栏
        self.statusBar().showMessage("准备就绪")

        # 开始分析磁盘
        self.analyze_disks()

    def analyze_disks(self):
        """分析磁盘"""
        self.statusBar().showMessage("正在分析磁盘...")
        self.progress_bar.setVisible(True)

        if self.analyzer and self.analyzer.isRunning():
            self.analyzer.stop()
            self.analyzer.wait()

        self.analyzer = DiskAnalyzer()
        self.analyzer.progress_updated.connect(self.update_progress)
        self.analyzer.analysis_finished.connect(self.on_disk_analysis_finished)
        self.analyzer.start()

    def analyze_directory(self, path):
        """分析目录"""
        self.statusBar().showMessage(f"正在分析目录: {path}")
        self.progress_bar.setVisible(True)

        if self.analyzer and self.analyzer.isRunning():
            self.analyzer.stop()
            self.analyzer.wait()

        self.analyzer = DiskAnalyzer(path)
        self.analyzer.progress_updated.connect(self.update_progress)
        self.analyzer.analysis_finished.connect(self.on_directory_analysis_finished)
        self.analyzer.start()

    def update_progress(self, value):
        """更新进度条"""
        self.progress_bar.setValue(value)

    def on_disk_analysis_finished(self, result):
        """磁盘分析完成"""
        self.progress_bar.setVisible(False)
        self.current_path = None
        self.history.clear()
        self.back_button.setEnabled(False)
        self.home_button.setEnabled(False)
        self.path_label.setText("磁盘根目录")
        self.display_disk_data(result)
        self.statusBar().showMessage("磁盘分析完成")

    def on_directory_analysis_finished(self, result):
        """目录分析完成"""
        self.progress_bar.setVisible(False)
        self.display_directory_data(result)
        self.statusBar().showMessage("目录分析完成")

    def display_disk_data(self, data):
        """显示磁盘数据"""
        if not data:
            QMessageBox.warning(self, "警告", "无法获取磁盘信息")
            return

        # 准备饼图数据
        labels = []
        sizes = []
        colors = []

        for path, info in data.items():
            labels.append(f"{path}\n({self.format_size(info['used'])})")
            sizes.append(info['used'])
            colors.append(self.get_color(len(colors)))

        # 绘制饼图
        self.figure.clear()
        ax = self.figure.add_subplot(111)

        if len(sizes) > 0:
            wedges, texts, autotexts = ax.pie(
                sizes, labels=labels, autopct='%1.1f%%',
                colors=colors, startangle=90
            )

            # 设置文本样式
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')

            ax.axis('equal')  # 确保饼图是圆形
            self.chart_title.setText("磁盘使用情况")
        else:
            ax.text(0.5, 0.5, "无数据", ha='center', va='center', transform=ax.transAxes)
            self.chart_title.setText("磁盘使用情况 - 无数据")

        self.canvas.draw()

        # 更新列表
        self.list_widget.clear()
        for path, info in data.items():
            used_percent = (info['used'] / info['total']) * 100 if info['total'] > 0 else 0
            item_text = f"{path} - 已用: {self.format_size(info['used'])} / {self.format_size(info['total'])} ({used_percent:.1f}%)"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, {'path': path, 'type': 'disk'})
            self.list_widget.addItem(item)

    def display_directory_data(self, data):
        """显示目录数据"""
        if not data:
            QMessageBox.information(self, "信息", "该目录为空或无法访问")
            return

        # 按大小排序
        sorted_data = sorted(data.items(), key=lambda x: x[1]['size'], reverse=True)

        # 准备饼图数据
        labels = []
        sizes = []
        colors = []

        for name, info in sorted_data[:10]:  # 只显示前10个最大的目录
            labels.append(f"{name}\n({self.format_size(info['size'])})")
            sizes.append(info['size'])
            colors.append(self.get_color(len(colors)))

        # 绘制饼图
        self.figure.clear()
        ax = self.figure.add_subplot(111)

        if len(sizes) > 0:
            wedges, texts, autotexts = ax.pie(
                sizes, labels=labels, autopct='%1.1f%%',
                colors=colors, startangle=90
            )

            # 设置文本样式
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')

            ax.axis('equal')  # 确保饼图是圆形
            self.chart_title.setText(f"目录使用情况: {os.path.basename(self.current_path)}")
        else:
            ax.text(0.5, 0.5, "无数据", ha='center', va='center', transform=ax.transAxes)
            self.chart_title.setText("目录使用情况 - 无数据")

        self.canvas.draw()

        # 更新列表
        self.list_widget.clear()
        total_size = sum(item[1]['size'] for item in sorted_data)

        for name, info in sorted_data:
            size_percent = (info['size'] / total_size) * 100 if total_size > 0 else 0
            item_text = f"{name} - {self.format_size(info['size'])} ({size_percent:.1f}%)"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, {'path': info['path'], 'type': 'directory', 'name': name})
            self.list_widget.addItem(item)

    def on_item_clicked(self, item):
        """处理列表项点击"""
        data = item.data(Qt.UserRole)
        if data['type'] == 'disk':
            # 点击磁盘，进入磁盘根目录
            self.history.append(self.current_path)
            self.current_path = data['path']
            self.path_label.setText(f"当前路径: {self.current_path}")
            self.analyze_directory(self.current_path)
            self.back_button.setEnabled(True)
            self.home_button.setEnabled(True)
        elif data['type'] == 'directory':
            # 点击目录，进入子目录
            self.history.append(self.current_path)
            self.current_path = data['path']
            self.path_label.setText(f"当前路径: {self.current_path}")
            self.analyze_directory(self.current_path)

    def go_back(self):
        """返回上一级目录"""
        if self.history:
            prev_path = self.history.pop()
            if prev_path is None:
                # 返回磁盘列表
                self.current_path = None
                self.path_label.setText("磁盘根目录")
                self.analyze_disks()
                if not self.history:
                    self.back_button.setEnabled(False)
                    self.home_button.setEnabled(False)
            else:
                # 返回上一级目录
                self.current_path = prev_path
                if self.current_path is None:
                    self.path_label.setText("磁盘根目录")
                    self.analyze_disks()
                else:
                    self.path_label.setText(f"当前路径: {self.current_path}")
                    self.analyze_directory(self.current_path)

    def go_home(self):
        """返回首页（磁盘列表）"""
        self.history.clear()
        self.current_path = None
        self.path_label.setText("磁盘根目录")
        self.analyze_disks()
        self.back_button.setEnabled(False)
        self.home_button.setEnabled(False)

    def get_color(self, index):
        """获取颜色"""
        colors = [
            '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
            '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9',
            '#F8C471', '#82E0AA', '#F1948A', '#85C1E9', '#D7BDE2',
            '#F9E79F', '#A9DFBF', '#F5B7B1', '#AED6F1', '#D2B4DE'
        ]
        return colors[index % len(colors)]

    def format_size(self, size_bytes):
        """格式化文件大小"""
        if size_bytes == 0:
            return "0 B"

        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)

        return f"{s} {size_names[i]}"


def main():
    app = QApplication(sys.argv)

    # 检查必要的库
    try:
        import psutil
    except ImportError:
        QMessageBox.critical(None, "错误", "请先安装psutil库: pip install psutil")
        sys.exit(1)

    try:
        import matplotlib
    except ImportError:
        QMessageBox.critical(None, "错误", "请先安装matplotlib库: pip install matplotlib")
        sys.exit(1)

    window = DiskSpaceAnalyzer()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
