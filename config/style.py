class StyleManager:
    """样式管理类"""

    @staticmethod
    def get_main_style():
        """获取主样式表"""
        return """
            QMainWindow {
                background-color: #f5f5f5;
            }
            QWidget {
                font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
            }
            QPushButton {
                background-color: #2196F3;
                border: none;
                color: white;
                padding: 8px 16px;
                text-align: center;
                font-size: 14px;
                margin: 4px 2px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
            QListWidget {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #eee;
            }
            QListWidget::item:selected {
                background-color: #e3f2fd;
                color: #1976D2;
            }
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 4px;
                text-align: center;
                background-color: white;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
            QLabel {
                color: #333;
            }
            QSplitter::handle {
                background-color: #ddd;
            }
        """
