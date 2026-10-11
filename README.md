# NotosDiskSpaceAnalyzer 🖥️

[![Python 3.8+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-green.svg)](https://github.com/doubsumi/NotosDiskSpaceAnalyzer)
[![Version](https://img.shields.io/badge/Version-2.1.1-orange.svg)](https://github.com/doubsumi/NotosDiskSpaceAnalyzer/releases)
[![GitHub Issues](https://img.shields.io/github/issues/doubsumi/NotosDiskSpaceAnalyzer)](https://github.com/doubsumi/NotosDiskSpaceAnalyzer/issues)
[![GitHub Stars](https://img.shields.io/github/stars/doubsumi/NotosDiskSpaceAnalyzer)](https://github.com/doubsumi/NotosDiskSpaceAnalyzer/stargazers)

一个现代化的跨平台磁盘空间分析工具，提供直观的可视化界面来帮助您查看磁盘中各个目录和文件的占用空间大小。

![NotosDiskSpaceAnalyzer 主界面](https://raw.githubusercontent.com/doubsumi/my-project-assets/main/IMG-NotosDiskSpaceAnalyzer/1.png)
![NotosDiskSpaceAnalyzer 主界面_深色模式](https://raw.githubusercontent.com/doubsumi/my-project-assets/main/IMG-NotosDiskSpaceAnalyzer/Index.png)
*主界面展示 - 支持浅色/深色双主题*



## ✨ 功能特点

### 🎯 核心功能
- **跨平台支持** - 支持 Windows 和 Linux 系统
- **磁盘分析** - 快速扫描所有磁盘分区，显示使用情况
- **目录分析** - 深入分析指定目录，找出占用空间最大的文件和文件夹
- **实时进度** - 分析过程中实时显示进度条

### 📊 可视化展示
- **饼图统计** - 使用 matplotlib 生成美观的饼图，直观展示空间分配
- **交互式列表** - 点击即可进入子目录，支持返回和首页导航
- **色彩区分** - 自动为不同项目分配不同颜色，便于区分

## 🚀 快速开始

### 环境要求

- Python 3.10 或更高版本
- 支持的操作系统：Windows、Linux

### 安装步骤

1. **克隆项目**
   ```bash
   git clone https://github.com/doubsumi/NotosDiskSpaceAnalyzer.git
   cd NotosDiskSpaceAnalyzer
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

   或者手动安装：
   ```bash
   pip install PyQt5 psutil matplotlib
   ```

3. **运行程序**
   ```bash
   python main.py
   ```

### 📦 依赖说明

| 包名       | 版本   | 用途         |
| ---------- | ------ | ------------ |
| PyQt5      | ≥5.15  | 图形界面框架 |
| psutil     | ≥5.8.0 | 系统信息获取 |
| matplotlib | ≥3.3.0 | 数据可视化   |

## 📖 使用指南

### 基本操作

1. **启动分析**
   - 程序启动后自动分析所有磁盘分区
   - 点击列表中的磁盘可以进入该磁盘根目录

2. **目录导航**
   - 点击目录列表中的文件夹进入子目录
   - 使用"返回上级"按钮返回上一级目录
   - 使用"返回首页"按钮回到磁盘列表视图

3. **数据解读**
   - 饼图显示空间占用比例
   - 列表显示具体大小和百分比
   - 颜色区分不同的项目

### 高级功能

- **停止分析** - 在分析过程中可以随时停止（通过关闭窗口）
- **权限处理** - 自动跳过无权限访问的目录
- **进度跟踪** - 实时显示分析进度

## 🏗 项目结构

```tree
NotosDiskSpaceAnalyzer/
├── src/
│   ├── core/           # 核心分析引擎
│   │   ├── analyzer.py          # 磁盘分析器（支持停止功能）
│   │   ├── size_calculator.py   # 大小计算器（迭代优化）
│   │   └── file_utils.py        # 文件操作工具
│   ├── gui/           # 用户界面
│   │   ├── components/          # UI 组件（图表优化）
│   │   ├── utils/               # 界面工具
│   │   └── main_window.py       # 主窗口（主题支持）
│   ├── models/        # 数据模型
│   │   ├── disk_item.py         # 磁盘项模型
│   │   └── analysis_result.py   # 分析结果模型
│   └── services/      # 业务服务
│       ├── analysis_service.py   # 分析服务
│       └── navigation_service.py # 导航服务
├── config/            # 配置管理
│   ├── settings.py    # 应用设置（平台特定配置）
│   └── style.py       # 样式配置
└── tests/             # 测试用例
```

## 🔧 核心类说明

### DiskAnalyzer 类
- **功能**：后台磁盘分析线程
- **特性**：
  - 跨平台磁盘检测（Windows/Linux）
  - 递归目录大小计算
  - 进度信号发射
  - 可中断分析过程

### DiskSpaceAnalyzer 类
- **功能**：主窗口界面
- **特性**：
  - 现代化 UI 设计
  - 饼图数据可视化
  - 交互式目录导航
  - 历史记录管理

## 🤝 贡献指南

我们欢迎各种形式的贡献！请参考以下步骤：

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 开发环境设置

```bash
# 1. 克隆仓库
git clone https://github.com/doubsumi/NotosDiskSpaceAnalyzer.git

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows

# 3. 安装开发依赖
pip install -r requirements.txt
```

## 📄 许可证

本项目采用___许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🐛 问题反馈

如果您遇到任何问题或有改进建议，请通过以下方式反馈：

1. 在 [Issues](https://github.com/doubsumi/NotosDiskSpaceAnalyzer/issues) 页面提交问题
2. 描述问题的详细信息和复现步骤
3. 提供操作系统版本和 Python 版本信息

## 🌟 更新日志

### v1.1.1
- ✅ 基础磁盘分析功能
- ✅ 图形化界面
- ✅ 跨平台支持
- ✅ 目录大小统计

## 🙏 致谢

感谢以下开源项目：
- [PyQt5](https://www.riverbankcomputing.com/software/pyqt/) - 强大的 GUI 框架
- [psutil](https://github.com/giampaolo/psutil) - 跨平台系统信息库
- [matplotlib](https://matplotlib.org/) - 专业的数据可视化库

感谢 DeepSeek 提供主要的代码编写支持，生成readme和release note

---

**让磁盘空间管理变得简单直观！** 🎉

如果您觉得这个项目有用，请给个 ⭐ Star 支持一下！
