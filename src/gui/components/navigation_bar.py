from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QFont


class NavigationBar(QWidget):
    """导航栏组件 - 添加停止按钮"""

    back_clicked = pyqtSignal()
    home_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()  # 新增停止信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        layout = QHBoxLayout(self)

        # 路径显示
        self.path_label = QLabel("磁盘根目录")
        self.path_label.setFont(QFont("Arial", 10))
        self.path_label.setStyleSheet("color: #333; padding: 5px;")

        # 导航按钮
        self.back_button = QPushButton("返回上级")
        self.home_button = QPushButton("返回首页")
        self.stop_button = QPushButton("停止分析")  # 新增停止按钮

        # 设置按钮样式
        button_style = """
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """

        stop_button_style = """
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """

        self.back_button.setStyleSheet(button_style)
        self.home_button.setStyleSheet(button_style)
        self.stop_button.setStyleSheet(stop_button_style)

        # 初始状态
        self.back_button.setEnabled(False)
        self.home_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.stop_button.setVisible(False)  # 默认隐藏

        # 连接信号
        self.back_button.clicked.connect(self.back_clicked)
        self.home_button.clicked.connect(self.home_clicked)
        self.stop_button.clicked.connect(self.stop_clicked)

        # 布局
        layout.addWidget(self.path_label)
        layout.addStretch()
        layout.addWidget(self.stop_button)  # 添加停止按钮
        layout.addWidget(self.back_button)
        layout.addWidget(self.home_button)

    def update_path_display(self, path_text):
        """更新路径显示"""
        self.path_label.setText(path_text)

    def set_navigation_buttons(self, can_go_back):
        """设置导航按钮状态"""
        self.back_button.setEnabled(can_go_back)
        self.home_button.setEnabled(can_go_back)

    def set_stop_button_visible(self, visible):
        """设置停止按钮可见性"""
        self.stop_button.setVisible(visible)
        self.stop_button.setEnabled(visible)
