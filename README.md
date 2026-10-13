# Image Dedup Workbench (图像智能查重与对比工作台 v4.0.7)

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6%20Qt-41CD52?style=flat-square&logo=qt&logoColor=white)](https://pypi.org/project/PySide6/)
[![OpenCV](https://img.shields.io/badge/Engine-OpenCV%20%2B%20SIFT-5C3EE8?style=flat-square&logo=opencv&logoColor=white)](https://opencv.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

一款专注于**商业级高精度图像去重、跨分辨率缩放识别与像素级差异比对**的现代化桌面生产力工作台（Studio Dark 现代中性暗色规范）。提供单文件直接运行的**免安装绿色便携版**，支持**单文件夹内部查重**与**跨文件夹交叉比对**。

---

## 核心特性 (Features)

- **四级递进视觉感知查重引擎 (4-Stage Perceptual & Geometric Engine)**：
  - **第一级（MD5 字节级校验）**：毫秒级锁定二进制完全一致的重复文件；
  - **第二级（多尺度空间色彩网格 + 2D-DCT 频域感知哈希）**：抵抗边缘裁切与高达 **10 倍以上跨分辨率缩放**（如 `8018×3608` 超大原图 vs `777×387` 缩略图）；
  - **第三级（SIFT 1200 关键点 + RANSAC 仿射几何配准 + 对齐像素差 MAD）**：精准检出 **90% 长宽比拉伸变形**、局部改字/加水印、轻度调色变体，同时杜绝异图误报；
  - **第四级（防传递性链式膨胀图聚类）**：保证同一相似组内每张图片均为高置信度同款变体。
- **灵活扫描范围与三档实时灵敏度 (Flexible Scan Scope & Sensitivity)**：
  - **扫描范围控制**：默认**仅扫描当前文件夹第一层顶层文件**；按需勾选 **「包含子文件夹」** 可开启全量嵌套目录递归扫描；
  - **三档灵敏度模式**：
    - **标准模式（推荐）**：兼顾原图与局部变体，精准识别同款改色、微调与局部换字；
    - **严格模式（仅限同图）**：仅检出画面高度一致的同款原图与缩放图，零误报；
    - **深度宽松（广覆盖）**：放宽匹配阈值，支持大幅改色、AI 图生图重绘与相似构图排查。
- **安全删除与永久保留白名单 (Safe Trash & Whitelist)**：
  - **保留白名单记忆**：同款变体图均有用时，按 `Space` 空格键加入白名单，组内图片 100% 完整保留在原文件夹，且下次扫描与极速复查时**永久免打扰记忆**；
  - **安全回收暂存区 (staging_trash)**：被淘汰的重复图片安全移入 `%LOCALAPPDATA%\TableclothDedupPro\staging_trash`，随时支持一键打开彻底清理；
  - **100% 原路径无损撤销**：删错时随时按 `Ctrl + Z`（支持连续撤销），原文件名与原文件夹路径毫秒级无损还原。
- **专业双视口审阅画布 (Studio Dark Dual-Viewport Canvas)**：
  - **双图联动缩放与平移**：滚轮平滑缩放，左右双视口毫秒级像素级对齐联动；
  - **差异热图 (Diff Heatmap) 与滑动卷帘对比 (Curtain Wipe)**：一秒看穿微调、水印、瑕疵与像素差异；
  - **纯键盘流水线决断**：`1` 仅留左图、`2` 仅留右图、`Space` 加入白名单、`Delete` 废弃重复项、`Ctrl+Z` 撤销、`F1` 打开使用指南与常见问题中心。

---

## 查重检出能力实测 (Benchmark)

| 对比场景 | 样本特征差异 | 检出准确度 | 匹配判定类型 |
| :--- | :--- | :--- | :--- |
| **原图完全重复 / 改名备份** | 二进制一致或仅修改文件名 | **100% 检出** | `完全相同 (MD5)` |
| **10倍跨分辨率极端缩放** | `8018 × 3608` (29MP) vs `777 × 387` (0.3MP) | **100% 检出** | `像素级同款` |
| **长宽比拉伸 / 局部裁切** | 宽高比变形 `90%` 或上下裁边 `10%` | **100% 检出** | `像素级同款 / 同款变体` |
| **换字 / 加水印 / 局部微调** | 主体相同、局部新增文字或水印徽标 | **精准锁定** | `同款变体图` |
| **CMYK 印刷图 / 超大 TIFF** | 特殊色彩空间及 >50MB 工业大图 | **自动转码兼容** | `全格式无缝支持` |

---

## 开发者源码运行 (Quick Start from Source)

### 1. 环境准备
确保已安装 Python 3.9+，并安装所需依赖：
```bash
pip install -r requirements.txt
```

### 2. 启动图形界面 (GUI)
- **Windows 用户**：直接双击运行项目根目录下的 `run.bat`。
- **命令行启动**：
```bash
python app.py
```

---

## 免安装绿色版使用说明 (Portable Build)

1. 双击运行 `dist_portable\图像智能查重工作台\图像智能查重工作台.exe`（或解压 `图像智能查重工作台_免安装绿色版_v4.0.7.zip`）；
2. 目标电脑无需安装 Python 或任何依赖环境，双击即可直接使用。

---

## 开源许可证 (License)

本项目基于 [MIT 许可证](LICENSE) 开源。
