from config.settings import Settings

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QPixmap, QPainter
from PyQt5.QtSvg import QSvgRenderer


class CustomTitleBar(QWidget):
    """使用SVG图标的专业标题栏"""

    theme_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.is_dark_mode = False
        self.init_ui()
        self.update_theme(False)

    def create_svg_icon(self, svg_content, color="#000000", size=12):
        """从SVG内容创建图标，支持颜色参数"""
        # 替换SVG中的currentColor为指定颜色
        colored_svg = svg_content.replace('currentColor', color)

        renderer = QSvgRenderer(colored_svg.encode())
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    def init_ui(self):
        """初始化UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 应用标题
        self.title_label = QLabel(Settings.APP_NAME+Settings.APP_VERSION)
        self.title_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        self.title_label.setAlignment(Qt.AlignVCenter)
        self.title_label.setStyleSheet("padding-left: 10px;")

        # 创建专业按钮
        self.minimize_btn = self.create_svg_button(self.get_minimize_night_svg(), "最小化")
        self.maximize_btn = self.create_svg_button(self.get_maximize_svg(), "最大化")
        self.close_btn = self.create_svg_button(self.get_close_night_svg(), "关闭")

        # 连接信号
        self.minimize_btn.clicked.connect(self.parent.showMinimized)
        self.maximize_btn.clicked.connect(self.toggle_maximize)
        self.close_btn.clicked.connect(self.parent.close)

        # 设置布局
        layout.addWidget(self.title_label)
        layout.addStretch()
        layout.addWidget(self.minimize_btn)
        layout.addWidget(self.maximize_btn)
        layout.addWidget(self.close_btn)

        self.setFixedHeight(35)

    def create_svg_button(self, svg_content, tooltip):
        """创建SVG按钮"""
        btn = QPushButton()
        btn.setToolTip(tooltip)
        btn.setFixedSize(45, 35)
        btn.setFocusPolicy(Qt.NoFocus)

        # 初始设置黑色图标，后续会在update_theme中更新
        icon = self.create_svg_icon(svg_content, "#000000")
        btn.setIcon(icon)
        btn.setIconSize(btn.size())

        return btn

    def get_minimize_night_svg(self):
        """最小化按钮SVG - 清晰的横线"""
        return """<svg t="1763454125316" class="icon" viewBox="0 0 1024 1024" version="1.1" 
        xmlns="http://www.w3.org/2000/svg" p-id="9411" width="32" height="32"><path d="M65.23884 456.152041 
        958.760137 456.152041l0 111.695918L65.23884 567.847959 65.23884 456.152041z" fill="#2c2c2c" 
        p-id="9412"></path></svg>"""

    def get_minimize_dark_svg(self):
        """最小化按钮SVG - 清晰的横线"""
        return """<svg t="1763454125316" class="icon" viewBox="0 0 1024 1024" version="1.1" 
        xmlns="http://www.w3.org/2000/svg" p-id="9411" width="32" height="32"><path d="M65.23884 456.152041 
        958.760137 456.152041l0 111.695918L65.23884 567.847959 65.23884 456.152041z" fill="#ffffff" 
        p-id="9412"></path></svg>"""

    def get_maximize_svg(self):
        """最大化按钮SVG - 单窗口"""
        return """
        <svg width="12" height="12" viewBox="0 0 12 12" xmlns="http://www.w3.org/2000/svg">
            <rect x="1.5" y="1.5" width="9" height="9" stroke="currentColor" stroke-width="1" fill="none"/>
        </svg>
        """

    def get_restore_night_svg(self):
        """还原按钮SVG"""
        return """<svg t="1763454008249" class="icon" viewBox="0 0 1024 1024" version="1.1" 
        xmlns="http://www.w3.org/2000/svg" p-id="8282" width="64" height="64"><path d="M256 
        0v256H0v768h768V768h256V0H256z m426.667 938.667H85.333V341.333h597.334v597.334z 
        m256-256H768V256H341.333V85.333h597.334v597.334z" p-id="8283" fill="#2c2c2c"></path></svg>"""

    def get_restore_dark_svg(self):
        """还原按钮SVG"""
        return """<svg t="1763454008249" class="icon" viewBox="0 0 1024 1024" version="1.1" 
        xmlns="http://www.w3.org/2000/svg" p-id="8282" width="64" height="64"><path d="M256 
        0v256H0v768h768V768h256V0H256z m426.667 938.667H85.333V341.333h597.334v597.334z 
        m256-256H768V256H341.333V85.333h597.334v597.334z" p-id="8283" fill="#ffffff"></path></svg>"""

    def get_close_night_svg(self):
        """关闭按钮SVG"""
        return """<svg t="1763453889539" class="icon" viewBox="0 0 1024 1024" version="1.1" 
        xmlns="http://www.w3.org/2000/svg" p-id="7132" width="32" height="32"><path d="M589.704 501.674L998.27 
        93.107c20.652-20.653 20.652-54.556 0-75.209l-2.237-2.237c-20.652-20.652-54.556-20.652-75.208 0L512.258 
        424.745 103.691 15.489c-20.652-20.652-54.556-20.652-75.208 0l-2.238 2.237c-21.168 20.652-21.168 54.556 0 
        75.208l408.568 408.74L26.245 910.24c-20.652 20.652-20.652 54.556 0 75.208l2.238 2.238c20.652 20.652 54.556 
        20.652 75.208 0l408.567-408.568 408.568 408.568c20.652 20.652 54.556 20.652 75.208 
        0l2.237-2.238c20.652-20.652 20.652-54.556 0-75.208L589.704 501.674z" fill="#2c2c2c" p-id="7133"></path></svg>"""

    def get_close_dark_svg(self):
        """关闭按钮SVG"""
        return """<svg t="1763453889539" class="icon" viewBox="0 0 1024 1024" version="1.1" 
        xmlns="http://www.w3.org/2000/svg" p-id="7132" width="32" height="32"><path d="M589.704 501.674L998.27 
        93.107c20.652-20.653 20.652-54.556 0-75.209l-2.237-2.237c-20.652-20.652-54.556-20.652-75.208 0L512.258 
        424.745 103.691 15.489c-20.652-20.652-54.556-20.652-75.208 0l-2.238 2.237c-21.168 20.652-21.168 54.556 0 
        75.208l408.568 408.74L26.245 910.24c-20.652 20.652-20.652 54.556 0 75.208l2.238 2.238c20.652 20.652 54.556 
        20.652 75.208 0l408.567-408.568 408.568 408.568c20.652 20.652 54.556 20.652 75.208 
        0l2.237-2.238c20.652-20.652 20.652-54.556 0-75.208L589.704 501.674z" fill="#ffffff" p-id="7133"></path></svg>"""

    def toggle_maximize(self):
        """切换最大化状态"""
        if self.parent.isMaximized():
            self.parent.showNormal()
            # 使用最大化图标
            if self.is_dark_mode:
                self.maximize_btn.setIcon(self.create_svg_icon(self.get_maximize_svg(), "#ffffff"))
            else:
                self.maximize_btn.setIcon(self.create_svg_icon(self.get_maximize_svg(), "#000000"))
            self.maximize_btn.setToolTip("最大化")
        else:
            self.parent.showMaximized()
            # 使用还原图标
            if self.is_dark_mode:
                self.maximize_btn.setIcon(self.create_svg_icon(self.get_restore_dark_svg(), "#ffffff"))
            else:
                self.maximize_btn.setIcon(self.create_svg_icon(self.get_restore_night_svg(), "#000000"))
            self.maximize_btn.setToolTip("向下还原")

    def update_theme(self, is_dark_mode):
        """更新主题样式 - 修复所有图标颜色问题"""
        self.is_dark_mode = is_dark_mode

        # 根据主题更新所有图标颜色
        icon_color = "#ffffff" if is_dark_mode else "#000000"

        if is_dark_mode:
            # 更新所有按钮图标颜色
            self.minimize_btn.setIcon(self.create_svg_icon(self.get_minimize_dark_svg(), icon_color))
            self.close_btn.setIcon(self.create_svg_icon(self.get_close_dark_svg(), icon_color))
        else:
            self.minimize_btn.setIcon(self.create_svg_icon(self.get_minimize_night_svg(), icon_color))
            self.close_btn.setIcon(self.create_svg_icon(self.get_close_night_svg(), icon_color))

        # 更新最大化/还原按钮图标
        if self.parent.isMaximized():
            if is_dark_mode:
                self.maximize_btn.setIcon(self.create_svg_icon(self.get_restore_dark_svg(), icon_color))
            else:
                self.maximize_btn.setIcon(self.create_svg_icon(self.get_restore_night_svg(), icon_color))
            self.maximize_btn.setToolTip("向下还原")
        else:
            self.maximize_btn.setIcon(self.create_svg_icon(self.get_maximize_svg(), icon_color))

        if is_dark_mode:
            # 深色主题
            self.setStyleSheet("""
                CustomTitleBar {
                    background-color: #2d2d30;
                    border-bottom: 1px solid #3e3e42;
                }
                QLabel {
                    color: #ffffff;
                    background-color: transparent;
                    padding: 0px;
                    margin: 0px;
                }
                QPushButton {
                    background-color: transparent;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #3e3e42;
                }
                QPushButton:pressed {
                    background-color: #5a5a5a;
                }
                QPushButton#close_btn:hover {
                    background-color: #e81123;
                }
            """)
        else:
            # 浅色主题
            self.setStyleSheet("""
                CustomTitleBar {
                    background-color: #f6f6f6;
                    border-bottom: 1px solid #e5e5e5;
                }
                QLabel {
                    color: #000000;
                    background-color: transparent;
                    padding: 0px;
                    margin: 0px;
                }
                QPushButton {
                    background-color: transparent;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #e5e5e5;
                }
                QPushButton:pressed {
                    background-color: #cccccc;
                }
                QPushButton#close_btn:hover {
                    background-color: #e81123;
                }
            """)

        # 设置对象名
        self.close_btn.setObjectName("close_btn")

    def mouseDoubleClickEvent(self, event):
        """双击标题栏切换最大化"""
        if event.button() == Qt.LeftButton:
            self.toggle_maximize()

    def mousePressEvent(self, event):
        """鼠标按下事件 - 支持窗口拖动"""
        if event.button() == Qt.LeftButton:
            self.parent.windowHandle().startSystemMove()
