from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from src.core.analyzer import DiskAnalyzer
from src.models.analysis_result import AnalysisResult


class AnalysisService(QObject):
    """分析服务 - 修复版本"""

    analysis_started = pyqtSignal()
    analysis_finished = pyqtSignal(object)
    progress_updated = pyqtSignal(int, str)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.analyzer = None

    def analyze_disks(self):
        """分析磁盘"""
        self._safe_stop_previous_analysis()
        self.analysis_started.emit()

        # 使用定时器延迟启动
        QTimer.singleShot(100, self._start_disk_analysis)

    def analyze_directory(self, path: str):
        """分析目录"""
        self._safe_stop_previous_analysis()
        self.analysis_started.emit()

        # 使用定时器延迟启动
        QTimer.singleShot(100, lambda: self._start_directory_analysis(path))

    def _start_disk_analysis(self):
        """开始磁盘分析"""
        try:
            self.analyzer = DiskAnalyzer()  # 不传递路径，表示分析磁盘
            self._connect_analyzer_signals()
            self.analyzer.analyze_path()  # 现在这个方法存在了
        except Exception as e:
            self.error_occurred.emit(f"启动磁盘分析失败: {str(e)}")

    def _start_directory_analysis(self, path: str):
        """开始目录分析"""
        try:
            self.analyzer = DiskAnalyzer(path)  # 传递路径，表示分析目录
            self._connect_analyzer_signals()
            self.analyzer.analyze_path(path)  # 现在这个方法存在了
        except Exception as e:
            self.error_occurred.emit(f"启动目录分析失败: {str(e)}")

    def _connect_analyzer_signals(self):
        """连接分析器信号"""
        if self.analyzer:
            self.analyzer.progress_updated.connect(self.progress_updated)
            self.analyzer.analysis_finished.connect(self.analysis_finished)
            self.analyzer.error_occurred.connect(self.error_occurred)

    def _safe_stop_previous_analysis(self):
        """安全停止之前的分析"""
        if self.analyzer:
            try:
                self.analyzer.stop_analysis()
                # 断开所有连接
                try:
                    self.analyzer.progress_updated.disconnect()
                    self.analyzer.analysis_finished.disconnect()
                    self.analyzer.error_occurred.disconnect()
                except:
                    pass

                if self.analyzer.isRunning():
                    self.analyzer.terminate()
                    self.analyzer.wait(2000)
            except:
                pass
            finally:
                self.analyzer = None

    def stop_analysis(self):
        """停止分析"""
        self._safe_stop_previous_analysis()
