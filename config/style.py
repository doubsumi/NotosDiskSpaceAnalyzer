class StyleManager:
    """样式管理器 - 统一背景色"""

    @staticmethod
    def get_main_style():
        """获取主样式表 - 统一背景色"""
        return """
            QMainWindow {
                background-color: white;
            }
            QWidget {
                font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
                background-color: white;
            }
            /* 导航按钮样式已在 navigation_bar.py 中单独设置 */
            QListWidget {
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                font-size: 12px;
                outline: none;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #e9ecef;
            }
            QListWidget::item:hover {
                background-color: #f8f9fa;
            }
            QListWidget::item:selected {
                background-color: #007bff;
                color: white;
                border-radius: 2px;
            }
            /* 进度条样式已在主题方法中单独设置 */
            QLabel {
                color: #212529;
                background-color: transparent;
            }
            QSplitter::handle {
                background-color: #dee2e6;
                width: 1px;
            }
            QSplitter::handle:hover {
                background-color: #adb5bd;
            }
        """
