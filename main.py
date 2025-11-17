#!/usr/bin/env python3
"""
磁盘空间分析工具 - 主程序入口
"""

import os
import sys

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from src.gui.main_window import main

if __name__ == "__main__":
    sys.exit(main())
