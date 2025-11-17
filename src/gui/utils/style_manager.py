class StyleManager:
    """样式管理器"""

    @staticmethod
    def get_main_style():
        """获取主样式表"""
        return """
            QMainWindow {
                background-color: #f8f9fa;
            }
            QWidget {
                font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
            }
            QPushButton {
                background-color: #007bff;
                border: none;
                color: white;
                padding: 8px 16px;
                text-align: center;
                font-size: 14px;
                margin: 4px 2px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
            QPushButton:disabled {
                background-color: #6c757d;
                color: #adb5bd;
            }
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
                background-color: #e9ecef;
            }
            QListWidget::item:selected {
                background-color: #007bff;
                color: white;
                border-radius: 2px;
            }
            QProgressBar {
                border: 1px solid #ced4da;
                border-radius: 4px;
                text-align: center;
                background-color: white;
                color: #495057;
            }
            QProgressBar::chunk {
                background-color: #28a745;
                border-radius: 3px;
            }
            QLabel {
                color: #212529;
            }
            QSplitter::handle {
                background-color: #dee2e6;
                width: 1px;
            }
            QSplitter::handle:hover {
                background-color: #adb5bd;
            }
        """

    @staticmethod
    def get_title_style():
        """获取标题样式"""
        return "font-size: 16px; font-weight: bold; color: #212529; margin: 10px;"

    @staticmethod
    def get_subtitle_style():
        """获取副标题样式"""
        return "font-size: 14px; color: #6c757d; margin: 5px;"
