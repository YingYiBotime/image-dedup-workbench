# 🔍 Image Dedup Workbench (图像智能查重与对比工作台 v4.0)

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6%20Qt-41CD52?style=flat-square&logo=qt&logoColor=white)](https://pypi.org/project/PySide6/)
[![OpenCV](https://img.shields.io/badge/Engine-OpenCV%20%2B%20SIFT-5C3EE8?style=flat-square&logo=opencv&logoColor=white)](https://opencv.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

一款专注于**高精度图像去重、跨分辨率缩放识别与像素级差异比对**的现代化桌面生产力工作台（Studio Dark 暗色工作台）。支持**单文件夹内部查重**与**跨文件夹交叉比对**。

---

## 🌟 核心特性 (Features)

- 🎯 **四级递进视觉感知查重引擎 (4-Stage Perceptual & Geometric Engine)**：
  - **第一级（MD5 字节级精确校验）**：毫秒级锁定二进制完全一致的重复文件。
  - **第二级（多尺度空间网格 + 中心核心区 HSV 直方图 + 2D-DCT 频域感知哈希）**：抵抗边缘裁切与高达 **10 倍以上跨分辨率缩放**（如 `8018×3608` 原图 vs `777×387` 缩略图）。
  - **第三级（SIFT 1200 关键点 + RANSAC 单应性矩阵几何配准 + 对齐像素差 MAD）**：精准检出 **90% 长宽比拉伸变形**、局部加水印/换字、轻度调色变体，同时杜绝异图误报。
  - **第四级（防传递性链式膨胀图聚类）**：确保同一组内每张图片均为高置信度同源图像。
- 📂 **灵活扫描模式与范围控制 (Flexible Scan Scope)**：
  - 支持 **「单文件夹内部查重」** 与 **「跨文件夹交叉比对 (A ↔ B)」** 一键平滑切换。
  - **默认仅扫描当前顶层文件夹**（不含子文件夹），并在主界面与顶栏提供 **「包含子文件夹」** 可选开关，按需一键开启深度递归扫描。
  - 提供 **标准模式（均衡推荐）**、**严格模式（零误报·仅同图）**、**深度宽松（广覆盖·含重绘）** 三档实时灵敏度。
- 🖥️ **专业双视口审阅画布 (Studio Dark Dual-Viewport Canvas)**：
  - **双图同步缩放与平移 (Sync Zoom & Pan)**：鼠标滚轮无级缩放，左右视口毫秒级像素对齐联动。
  - **像素差异热图 (Diff Heatmap)** 与 **滑动卷帘对比 (Curtain Wipe)**：一秒定位细微修改、水印位置或色彩差异。
  - **全键盘流水线决断**：`1` 保留左图、`2` 保留右图、`Space` 加入白名单、`Delete` 自动废弃非推荐项、`Ctrl+Z` 100% 原路径无损撤销恢复。
- 🔄 **GitHub 云端秒级热更新 (RSA-2048 Signed OTA Hot-Patch)**：
  - 客户端启动时通过多路国内镜像（`ghfast` / `ghproxy` / `jsDelivr`）静默拉取 ~70KB 签名补丁包，经 SHA-256 与 RSA-2048 验签通过后热重载最新模块。

---

## 📊 查重检出能力实测 (Benchmark)

| 对比场景 | 样本特征差异 | 检出准确度 | 匹配判定类型 |
| :--- | :--- | :--- | :--- |
| **原图完全重复 / 改名备份** | 二进制一致或仅修改文件名 | **100% 检出** | `完全相同 (MD5)` |
| **10倍跨分辨率极端缩放** | `8018 × 3608` (29MP) vs `777 × 387` (0.3MP) | **100% 检出** | `像素级同款` |
| **长宽比拉伸 / 边缘裁切** | 宽高比变形 `90%` 或上下裁边 `10%` | **100% 检出** | `像素级同款 / 同款变体` |
| **CMYK 印刷图 / 超大 TIFF** | 特殊色彩空间及 >50MB 工业大图 | **自动转码兼容** | `全格式無缝支持` |

---

## 🚀 开发者源码运行 (Quick Start from Source)

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

## 🔄 GitHub 同步与热更新发布 (GitHub Sync & OTA)

本项目自带一键同步与热更新签名脚本 `sync_github.bat`：
- 修改任何代码或算法后，直接双击运行 `sync_github.bat`；
- 脚本将自动打包并签名生成最新 `ota_hotpatch.zip` 与 `version.json`，并推送到 GitHub 远程仓库 `main` 分支；
- 所有已安装绿色版 `.exe` 的用户下次打开软件时，将在 **1 秒内自动同步生效**。

---

## 📄 开源许可证 (License)

本项目基于 [MIT 许可证](LICENSE) 开源。
