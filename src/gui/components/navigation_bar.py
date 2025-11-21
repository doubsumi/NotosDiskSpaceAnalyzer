from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush, QPainterPath
from PyQt5.QtCore import QRect, QPoint


class ThemeSwitch(QPushButton):
    """使用QPushButton实现的主题开关 - 更稳定"""

    theme_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(50, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)  # 设置为可切换状态
        self.setChecked(False)

        # 连接信号
        self.toggled.connect(self.theme_toggled)

    def paintEvent(self, event):
        """自定义绘制"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        checked = self.isChecked()

        # 绘制轨道
        track_rect = QRect(2, 2, self.width() - 4, self.height() - 4)
        track_radius = track_rect.height() // 2

        track_color = QColor('#007bff') if checked else QColor('#6c757d')
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(track_color))
        painter.drawRoundedRect(track_rect, track_radius, track_radius)

        # 绘制滑块
        thumb_size = track_rect.height() - 6
        thumb_x = track_rect.width() - thumb_size - 1 if checked else 3
        thumb_y = (self.height() - thumb_size) // 2

        thumb_rect = QRect(thumb_x, thumb_y, thumb_size, thumb_size)
        # thumb_color = QColor('#f8f9fa') if checked else QColor('#1a1a1a')

        # painter.setBrush(QBrush(thumb_color))
        # painter.setPen(QPen(QColor('#adb5bd'), 1))
        painter.drawEllipse(thumb_rect)

        # 绘制图标
        self.draw_icon(painter, thumb_rect, checked)

        painter.end()

    def draw_icon(self, painter, thumb_rect, checked):
        """绘制太阳/月亮图标 - 使用QPainterPath的精确月牙"""
        icon_size = int(thumb_rect.width())
        center_x = thumb_rect.center().x()
        center_y = thumb_rect.center().y()

        if checked:
            # 黑夜模式：使用QPainterPath创建月牙
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor('#959595')))  # 黄色填充

            # 创建月牙路径
            path = QPainterPath()

            # 外圆（主圆）
            outer_radius = int(icon_size * 0.6)
            outer_center = QPoint(center_x + 2, center_y + 1)
            path.addEllipse(outer_center, outer_radius, outer_radius)

            # 内圆（切割圆）- 稍小并向左偏移
            inner_radius = int(outer_radius)
            inner_center = QPoint(center_x - outer_radius // 2 - 3, center_y + 1)  # 向左偏移

            # 创建内圆路径并减去
            inner_path = QPainterPath()
            inner_path.addEllipse(inner_center, inner_radius, inner_radius)
            path = path.subtracted(inner_path)

            painter.drawPath(path)

        else:
            # 白昼模式：黄色太阳
            icon_rect = QRect(
                int(center_x - icon_size // 2 + 2),
                int(center_y - icon_size // 2 + 1),
                icon_size,
                icon_size
            )
            painter.setPen(QPen(QColor('#ffd43b'), 2))
            painter.setBrush(QBrush(QColor('#ffd43b')))
            painter.drawEllipse(icon_rect)


class NavigationBar(QWidget):
    """导航栏组件"""

    back_clicked = pyqtSignal()
    home_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    theme_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_dark_mode = False
        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        layout = QHBoxLayout(self)

        # 路径显示
        self.path_label = QLabel("磁盘根目录")
        self.path_label.setFont(QFont("Arial", 10))
        self.path_label.setStyleSheet("padding: 5px; background-color: transparent;")

        # 自定义主题开关
        self.theme_switch = ThemeSwitch()
        self.theme_switch.setChecked(False)
        self.theme_switch.setToolTip("点击切换白昼/黑夜模式")

        # 导航按钮
        self.back_button = QPushButton("返回上级")
        self.home_button = QPushButton("返回首页")
        self.stop_button = QPushButton("停止分析")

        # 设置按钮样式
        button_style = """
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 14px;
                width: 45px;
                height: 12px;
                font-size: 11px;
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
                padding: 8px 12px;
                border-radius: 14px;
                width: 45px;
                height: 12px;
                font-size: 11px;
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
        self.stop_button.setVisible(False)

        # 连接信号
        self.back_button.clicked.connect(self.back_clicked)
        self.home_button.clicked.connect(self.home_clicked)
        self.stop_button.clicked.connect(self.stop_clicked)
        self.theme_switch.theme_toggled.connect(self.on_theme_toggled)

        # 布局
        layout.addWidget(self.path_label)
        layout.addStretch()
        layout.addWidget(self.theme_switch)  # 使用优化后的开关
        layout.addWidget(self.stop_button)
        layout.addWidget(self.back_button)
        layout.addWidget(self.home_button)

    def on_theme_toggled(self, checked):
        """主题切换处理"""
        self.is_dark_mode = checked
        self.theme_toggled.emit(checked)

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
