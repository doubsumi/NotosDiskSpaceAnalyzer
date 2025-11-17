import sys
import os
import traceback
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QWidget, QLabel, QProgressBar, QSplitter, QMessageBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPalette, QColor  # 新增导入

from config.style import StyleManager
from src.services.analysis_service import AnalysisService
from src.services.navigation_service import NavigationService
from src.gui.components.navigation_bar import NavigationBar
from src.gui.components.chart_widget import ChartWidget
from src.gui.components.list_widget import DirectoryListWidget


class MainWindow(QMainWindow):
    """主窗口 - 支持标题栏主题统一"""

    def __init__(self):
        super().__init__()
        self.analysis_service = AnalysisService()
        self.navigation_service = NavigationService()
        self.is_analyzing = False
        self.is_dark_mode = False  # 新增：主题状态

        self.init_ui()
        self.connect_signals()

        # 延迟启动初始分析
        QTimer.singleShot(500, self.start_initial_analysis)

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("磁盘空间分析工具 v1.0")
        self.setGeometry(100, 100, 1200, 800)

        # 移除自定义窗口标志，使用系统默认标题栏
        # self.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint |
        #                    Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint |
        #                    Qt.WindowCloseButtonHint)

        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # 导航栏
        self.navigation_bar = NavigationBar()
        main_layout.addWidget(self.navigation_bar)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        main_layout.addWidget(self.progress_bar)

        # 内容区域
        content_splitter = QSplitter(Qt.Horizontal)

        # 图表组件
        self.chart_widget = ChartWidget()
        content_splitter.addWidget(self.chart_widget)

        # 列表组件
        self.list_widget = DirectoryListWidget()
        content_splitter.addWidget(self.list_widget)

        # 设置分割比例
        content_splitter.setStretchFactor(0, 2)
        content_splitter.setStretchFactor(1, 1)
        content_splitter.setSizes([700, 350])
        content_splitter.setMinimumHeight(500)

        main_layout.addWidget(content_splitter, 1)

        # 状态栏
        self.statusBar().showMessage("准备就绪")

        # 最后应用主题样式
        self.apply_light_theme()

    def apply_light_theme(self):
        """应用浅色主题"""
        self.is_dark_mode = False

        # 使用QSS设置标题栏样式（Windows系统支持）
        light_style = """
            QMainWindow {
                background-color: white;
                color: #212529;
            }
            QWidget {
                background-color: white;
                color: #212529;
                font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
            }
            /* 标题栏样式 */
            QMainWindow::title {
                background-color: white;
                color: #212529;
            }
            QListWidget {
                background-color: white;
                border: 1px solid #dee2e6;
                color: #212529;
                border-radius: 4px;
            }
            QListWidget::item {
                background-color: white;
                border-bottom: 1px solid #e9ecef;
            }
            QListWidget::item:hover {
                background-color: #f8f9fa;
            }
            QListWidget::item:selected {
                background-color: #007bff;
                color: white;
            }
            QLabel {
                color: #212529;
                background-color: transparent;
            }
        """
        self.setStyleSheet(StyleManager.get_main_style() + light_style)

        # 安全地更新图表主题
        if hasattr(self, 'chart_widget'):
            self.chart_widget.apply_theme(False)

    def apply_dark_theme(self):
        """应用暗黑主题"""
        self.is_dark_mode = True

        # 使用QSS设置标题栏样式
        dark_style = """
            QMainWindow {
                background-color: #1a1a1a;
                color: #e9ecef;
            }
            QWidget {
                background-color: #1a1a1a;
                color: #e9ecef;
                font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
            }
            /* 标题栏样式 */
            QMainWindow::title {
                background-color: #1a1a1a;
                color: #e9ecef;
            }
            QListWidget {
                background-color: #252525;
                border: 1px solid #404040;
                color: #e9ecef;
                border-radius: 4px;
            }
            QListWidget::item {
                background-color: #252525;
                border-bottom: 1px solid #404040;
            }
            QListWidget::item:hover {
                background-color: #323232;
            }
            QListWidget::item:selected {
                background-color: #0d6efd;
                color: white;
            }
            QLabel {
                color: #e9ecef;
                background-color: transparent;
            }
            QProgressBar {
                background-color: #252525;
                color: #e9ecef;
                border: 1px solid #404040;
            }
            QProgressBar::chunk {
                background-color: #198754;
            }
            QSplitter::handle {
                background-color: #404040;
            }
        """
        self.setStyleSheet(StyleManager.get_main_style() + dark_style)

        # 安全地更新图表主题
        if hasattr(self, 'chart_widget'):
            self.chart_widget.apply_theme(True)

    def on_theme_toggled(self, is_dark_mode):
        """主题切换处理"""
        if is_dark_mode:
            self.apply_dark_theme()
        else:
            self.apply_light_theme()

    def stop_analysis(self):
        """停止分析"""
        if self.is_analyzing:
            self.statusBar().showMessage("正在停止分析...")
            self.analysis_service.stop_analysis()
            self.is_analyzing = False
            self.progress_bar.setVisible(False)
            self.navigation_bar.set_stop_button_visible(False)
            self.statusBar().showMessage("分析已停止")

    def connect_signals(self):
        """连接信号槽"""
        # 导航信号
        self.navigation_bar.back_clicked.connect(self.go_back)
        self.navigation_bar.home_clicked.connect(self.go_home)
        self.navigation_bar.stop_clicked.connect(self.stop_analysis)
        self.navigation_bar.theme_toggled.connect(self.on_theme_toggled)  # 新增主题切换

        # 列表点击信号
        self.list_widget.item_clicked.connect(self.on_item_clicked)

        # 饼图点击信号
        self.chart_widget.chart_item_clicked.connect(self.on_item_clicked)

        # 分析服务信号
        self.analysis_service.analysis_started.connect(self.on_analysis_started)
        self.analysis_service.analysis_finished.connect(self.on_analysis_finished)
        self.analysis_service.progress_updated.connect(self.on_progress_updated)
        self.analysis_service.error_occurred.connect(self.on_error_occurred)

    def start_initial_analysis(self):
        """开始初始分析"""
        if not self.is_analyzing:
            self.analysis_service.analyze_disks()

    def on_analysis_started(self):
        """分析开始"""
        self.is_analyzing = True
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.navigation_bar.set_stop_button_visible(True)
        self.statusBar().showMessage("正在分析...")

    def on_analysis_finished(self, result):
        """分析完成"""
        self.is_analyzing = False
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        self.navigation_bar.set_stop_button_visible(False)

        try:
            self.chart_widget.update_chart(result)
            self.list_widget.update_list(result)
            self.navigation_bar.update_path_display(
                self.navigation_service.get_current_path_display()
            )

            is_at_root = self.navigation_service.current_path is None
            self.navigation_bar.set_navigation_buttons(not is_at_root)
            self.statusBar().showMessage("分析完成")
        except Exception as e:
            self.statusBar().showMessage(f"更新UI时出错: {str(e)}")

    def on_progress_updated(self, progress, current_item):
        """进度更新"""
        self.progress_bar.setValue(progress)
        self.statusBar().showMessage(f"正在分析: {current_item}")

    def on_error_occurred(self, error_message):
        """错误处理"""
        self.is_analyzing = False
        self.progress_bar.setVisible(False)
        QMessageBox.warning(self, "错误", error_message)
        self.statusBar().showMessage("分析出错")

    def on_item_clicked(self, disk_item):
        """处理项目点击"""
        try:
            if disk_item and hasattr(disk_item, 'path') and hasattr(disk_item, 'item_type'):
                if not self.is_analyzing:  # 确保没有正在进行的分析
                    self.navigation_service.navigate_to(disk_item.path)
                    self.analysis_service.analyze_directory(disk_item.path)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法分析目录: {str(e)}")

    def go_back(self):
        """返回上一级"""
        try:
            if not self.is_analyzing:
                previous_path = self.navigation_service.go_back()
                if previous_path is None:
                    self.analysis_service.analyze_disks()
                else:
                    self.analysis_service.analyze_directory(previous_path)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"导航失败: {str(e)}")

    def go_home(self):
        """返回首页"""
        try:
            if not self.is_analyzing:
                self.navigation_service.go_home()
                self.analysis_service.analyze_disks()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"返回首页失败: {str(e)}")

    def closeEvent(self, event):
        """关闭事件 - 确保安全退出"""
        self.analysis_service.stop_analysis()
        # 等待分析停止
        import time
        time.sleep(0.5)
        event.accept()


def main():
    """主函数"""
    try:
        # 设置异常处理
        def exception_hook(exctype, value, traceback_obj):
            """全局异常处理"""
            error_msg = ''.join(traceback.format_exception(exctype, value, traceback_obj))
            print(f"程序异常: {error_msg}")
            sys.__excepthook__(exctype, value, traceback_obj)

        sys.excepthook = exception_hook

        app = QApplication(sys.argv)
        app.setApplicationName("磁盘空间分析工具")
        app.setApplicationVersion("1.0.0")

        # 检查依赖
        try:
            import psutil
            import matplotlib
        except ImportError as e:
            QMessageBox.critical(None, "错误", f"缺少依赖库: {e}\n请安装: pip install psutil matplotlib")
            return 1

        window = MainWindow()
        window.show()

        return app.exec_()

    except Exception as e:
        print(f"程序启动失败: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
