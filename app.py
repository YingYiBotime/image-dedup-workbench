# -*- coding: utf-8 -*-
"""
印花图像查重工作台 v4.0 — Studio Dark Mode (app.py)
严格遵循工业级现代中性暗色规范 (Neutral Slate/Zinc) 与双阶段状态解耦架构 (Phase-Based Layout)：
- 底色体系：主背景 #18181b、卡片与面板 #202023、浮动工具栏 #27272a、1px 半透明描边 rgba(255,255,255,0.08)
- 零系统 Emoji：全量采用 QPainter 绘制的 16px/20px Lucide 风格线性矢量图标
- 阶段 1 (Import State)：48px 单行顶栏 + 对称双圆角拖拽卡 + 220×40px 居中主行动按钮「开始智能查重」
- 阶段 2 (Review Workbench)：
  * 左栏 (260px 可折叠)：双图微型缩略图卡片 + 相似度百分比 (99.4%) + 差异标签 + 搜索与排序
  * 中栏 (双视口画布)：顶部 #27272a 浮动胶囊条 [1:1 复位 | 联动缩放/平移 | 像素差异热图 | 滑动卷帘对比] + 并排/卷帘视口 + 底部决策按钮
  * 右栏 (240px 可折叠)：垂直对比文件名、分辨率、体积、格式、修改时间，自动高亮差异属性
  * 底栏 (40px 状态 Dock)：靠左进度指示 | 靠中紧凑翻页 [← 上一组] [下一组 →] | 靠右极弱暗灰快捷键提示
"""

import os
import sys
import json
import math
import runpy
import datetime
import subprocess
import importlib.abc
import importlib.util
from typing import List, Optional, Dict, Tuple


def _parse_ver_tuple(v: str) -> Tuple[int, ...]:
    clean = (v or "0.0.0").strip().lstrip("vV").split("-")[0]
    out = []
    for p in clean.split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


class _HotPatchMetaFinder(importlib.abc.MetaPathFinder):
    """优先于 PyInstaller FrozenImporter 拦截并加载本地热更新目录下的核心模块"""
    PATCHABLE_MODULES = {"core_infra", "engine", "generate_icon"}

    def __init__(self, hotpatch_dir: str):
        self.hotpatch_dir = hotpatch_dir

    def find_spec(self, fullname: str, path=None, target=None):
        if fullname in self.PATCHABLE_MODULES:
            cand = os.path.join(self.hotpatch_dir, f"{fullname}.py")
            if os.path.isfile(cand):
                return importlib.util.spec_from_file_location(fullname, cand)
        return None


def _bootstrap_hotpatch():
    """启动时检查 %LOCALAPPDATA%\\TableclothDedupPro\\hotpatch 下是否有更新的云端热补丁并无缝接管"""
    if getattr(sys, "_tdpro_hotpatch_bootstrapped", False):
        return
    builtin_version = "4.0.8"
    local_base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    hp_dir = os.path.join(local_base, "TableclothDedupPro", "hotpatch")
    hp_manifest = os.path.join(hp_dir, "hotpatch_manifest.json")
    hp_app_py = os.path.join(hp_dir, "app.py")

    if not (os.path.isfile(hp_manifest) and os.path.isfile(hp_app_py)):
        return
    try:
        with open(hp_manifest, "r", encoding="utf-8") as f:
            meta = json.load(f)
        hp_ver = str(meta.get("version", "")).strip()
        if _parse_ver_tuple(hp_ver) <= _parse_ver_tuple(builtin_version):
            return

        sys._tdpro_hotpatch_bootstrapped = True
        os.environ["TDPRO_ACTIVE_VERSION"] = hp_ver
        sys.meta_path.insert(0, _HotPatchMetaFinder(hp_dir))
        if hp_dir not in sys.path:
            sys.path.insert(0, hp_dir)
        runpy.run_path(hp_app_py, run_name="__main__")
        sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        # 若热补丁异常，自动回退至内置稳定版本，绝不闪退
        sys._tdpro_hotpatch_bootstrapped = False
        os.environ.pop("TDPRO_ACTIVE_VERSION", None)


_bootstrap_hotpatch()

import cv2
import numpy as np
from PySide6.QtCore import (
    Qt, QThread, Signal, QPointF, QRectF, QSize, QMimeData,
    QVariantAnimation, QEasingCurve, QTimer
)
from PySide6.QtGui import (
    QPixmap, QImage, QColor, QFont, QPainter, QPen, QBrush, QPainterPath,
    QKeySequence, QShortcut, QWheelEvent, QMouseEvent, QAction, QActionGroup, QIcon,
    QDragEnterEvent, QDragMoveEvent, QDragLeaveEvent, QDropEvent
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QProgressBar, QFrame, QScrollArea,
    QMenu, QToolButton, QStackedWidget, QSizePolicy, QWidgetAction,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QDialog, QTextBrowser,
    QAbstractItemView, QGridLayout
)

from engine import (
    DedupEngine, MatchGroup, ImageItem,
    read_cv2_image, compute_diff_visualization
)
from core_infra import (
    AppPaths, setup_rotating_logger, GlobalCrashHandler,
    SingleInstanceGuard, MachineFingerprint, APP_VERSION,
    AsymmetricLicenseManager, LicenseActivationDialog, AutoUpdateDialog,
    UpdateCheckWorker, UpdateDownloadWorker, build_github_ota_urls, restart_application
)
from generate_icon import render_studio_icon_qimage


# ==================== 1. Lucide 风格线性矢量图标引擎 (零 Emoji) ====================

class LucideIcon:
    """绘制 16px / 20px / 28px 现代细线条线性矢量图标 (1.5px 描边，无 Emoji)"""

    @staticmethod
    def pixmap(name: str, size: int = 16, color: str = "#a1a1aa", stroke_width: float = 1.5) -> QPixmap:
        dpr = 2.0
        px = QPixmap(int(size * dpr), int(size * dpr))
        px.setDevicePixelRatio(dpr)
        px.fill(Qt.transparent)

        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(color))
        pen.setWidthF(stroke_width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        s = float(size)
        m = s * 0.15
        w = s - 2 * m

        if name == "folder":
            path = QPainterPath()
            path.moveTo(m, m + w * 0.18)
            path.lineTo(m + w * 0.38, m + w * 0.18)
            path.lineTo(m + w * 0.50, m + w * 0.32)
            path.lineTo(m + w, m + w * 0.32)
            path.lineTo(m + w, m + w * 0.88)
            path.lineTo(m, m + w * 0.88)
            path.closeSubpath()
            p.drawPath(path)

        elif name == "folder-plus":
            path = QPainterPath()
            path.moveTo(m, m + w * 0.18)
            path.lineTo(m + w * 0.38, m + w * 0.18)
            path.lineTo(m + w * 0.50, m + w * 0.32)
            path.lineTo(m + w, m + w * 0.32)
            path.lineTo(m + w, m + w * 0.88)
            path.lineTo(m, m + w * 0.88)
            path.closeSubpath()
            p.drawPath(path)
            cx, cy = s * 0.5, m + w * 0.60
            r = w * 0.15
            p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
            p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))

        elif name == "search":
            r = w * 0.36
            cx, cy = m + r + w * 0.05, m + r + w * 0.05
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.drawLine(QPointF(cx + r * 0.72, cy + r * 0.72), QPointF(m + w * 0.92, m + w * 0.92))

        elif name == "panel-left":
            p.drawRoundedRect(QRectF(m, m + w * 0.08, w, w * 0.84), 2.0, 2.0)
            p.drawLine(QPointF(m + w * 0.34, m + w * 0.08), QPointF(m + w * 0.34, m + w * 0.92))

        elif name == "panel-right":
            p.drawRoundedRect(QRectF(m, m + w * 0.08, w, w * 0.84), 2.0, 2.0)
            p.drawLine(QPointF(m + w * 0.66, m + w * 0.08), QPointF(m + w * 0.66, m + w * 0.92))

        elif name == "maximize":
            # 1:1 四角取景框
            d = w * 0.26
            x0, y0, x1, y1 = m, m, m + w, m + w
            p.drawLine(QPointF(x0, y0 + d), QPointF(x0, y0))
            p.drawLine(QPointF(x0, y0), QPointF(x0 + d, y0))
            p.drawLine(QPointF(x1 - d, y0), QPointF(x1, y0))
            p.drawLine(QPointF(x1, y0), QPointF(x1, y0 + d))
            p.drawLine(QPointF(x0, y1 - d), QPointF(x0, y1))
            p.drawLine(QPointF(x0, y1), QPointF(x0 + d, y1))
            p.drawLine(QPointF(x1 - d, y1), QPointF(x1, y1))
            p.drawLine(QPointF(x1, y1), QPointF(x1, y1 - d))

        elif name == "link":
            p.drawRoundedRect(QRectF(m, s * 0.34, w * 0.56, s * 0.32), 3.0, 3.0)
            p.drawRoundedRect(QRectF(m + w * 0.44, s * 0.34, w * 0.56, s * 0.32), 3.0, 3.0)

        elif name == "layers":
            cx = s * 0.5
            top_y = m + w * 0.1
            mid_y = m + w * 0.35
            path = QPainterPath()
            path.moveTo(cx, top_y)
            path.lineTo(m + w, mid_y)
            path.lineTo(cx, m + w * 0.6)
            path.lineTo(m, mid_y)
            path.closeSubpath()
            p.drawPath(path)
            p.drawLine(QPointF(m, m + w * 0.58), QPointF(cx, m + w * 0.82))
            p.drawLine(QPointF(cx, m + w * 0.82), QPointF(m + w, m + w * 0.58))

        elif name == "columns":
            # 滑动卷帘对比图标
            p.drawRoundedRect(QRectF(m, m + w * 0.08, w, w * 0.84), 2.0, 2.0)
            p.drawLine(QPointF(s * 0.5, m), QPointF(s * 0.5, m + w))
            p.drawLine(QPointF(s * 0.36, s * 0.5), QPointF(s * 0.64, s * 0.5))

        elif name == "grid":
            # 2x2 网格平铺图标
            gap = w * 0.14
            cw = (w - gap) * 0.5
            p.drawRoundedRect(QRectF(m, m, cw, cw), 1.5, 1.5)
            p.drawRoundedRect(QRectF(m + cw + gap, m, cw, cw), 1.5, 1.5)
            p.drawRoundedRect(QRectF(m, m + cw + gap, cw, cw), 1.5, 1.5)
            p.drawRoundedRect(QRectF(m + cw + gap, m + cw + gap, cw, cw), 1.5, 1.5)

        elif name == "check":
            p.drawLine(QPointF(m + w * 0.12, s * 0.54), QPointF(m + w * 0.40, m + w * 0.82))
            p.drawLine(QPointF(m + w * 0.40, m + w * 0.82), QPointF(m + w * 0.88, m + w * 0.20))

        elif name == "trash":
            p.drawLine(QPointF(m + w * 0.1, m + w * 0.22), QPointF(m + w * 0.9, m + w * 0.22))
            p.drawLine(QPointF(m + w * 0.35, m + w * 0.22), QPointF(m + w * 0.35, m + w * 0.08))
            p.drawLine(QPointF(m + w * 0.35, m + w * 0.08), QPointF(m + w * 0.65, m + w * 0.08))
            p.drawLine(QPointF(m + w * 0.65, m + w * 0.08), QPointF(m + w * 0.65, m + w * 0.22))
            p.drawRoundedRect(QRectF(m + w * 0.20, m + w * 0.22, w * 0.60, w * 0.72), 1.5, 1.5)

        elif name == "chevron-left":
            p.drawLine(QPointF(s * 0.62, m + w * 0.15), QPointF(s * 0.34, s * 0.5))
            p.drawLine(QPointF(s * 0.34, s * 0.5), QPointF(s * 0.62, m + w * 0.85))

        elif name == "chevron-right":
            p.drawLine(QPointF(s * 0.38, m + w * 0.15), QPointF(s * 0.66, s * 0.5))
            p.drawLine(QPointF(s * 0.66, s * 0.5), QPointF(s * 0.38, m + w * 0.85))

        elif name == "help":
            r = w * 0.46
            cx, cy = s * 0.5, s * 0.5
            p.drawEllipse(QPointF(cx, cy), r, r)
            font = QFont("Segoe UI", int(size * 0.52), QFont.DemiBold)
            p.setFont(font)
            p.drawText(QRectF(0, 0, s, s), Qt.AlignCenter, "?")

        elif name == "sliders":
            y1, y2, y3 = m + w * 0.2, s * 0.5, m + w * 0.8
            p.drawLine(QPointF(m, y1), QPointF(m + w, y1))
            p.drawLine(QPointF(m, y2), QPointF(m + w, y2))
            p.drawLine(QPointF(m, y3), QPointF(m + w, y3))
            p.drawEllipse(QPointF(m + w * 0.3, y1), 2.0, 2.0)
            p.drawEllipse(QPointF(m + w * 0.7, y2), 2.0, 2.0)
            p.drawEllipse(QPointF(m + w * 0.4, y3), 2.0, 2.0)

        elif name == "refresh":
            r = w * 0.40
            p.drawArc(QRectF(s * 0.5 - r, s * 0.5 - r, 2 * r, 2 * r), 30 * 16, 290 * 16)
            p.drawLine(QPointF(s * 0.5 + r * 0.6, m + w * 0.1), QPointF(s * 0.5 + r, m + w * 0.32))
            p.drawLine(QPointF(s * 0.5 + r, m + w * 0.32), QPointF(s * 0.5 + r * 0.45, m + w * 0.36))

        elif name == "undo":
            p.drawLine(QPointF(m + w * 0.15, s * 0.42), QPointF(m + w * 0.38, m + w * 0.18))
            p.drawLine(QPointF(m + w * 0.15, s * 0.42), QPointF(m + w * 0.38, m + w * 0.64))
            p.drawLine(QPointF(m + w * 0.15, s * 0.42), QPointF(m + w * 0.75, s * 0.42))
            p.drawArc(QRectF(m + w * 0.45, s * 0.42, w * 0.4, w * 0.4), -90 * 16, 180 * 16)

        elif name == "arrow-left-right":
            y1, y2 = m + w * 0.30, m + w * 0.70
            p.drawLine(QPointF(m + w * 0.12, y1), QPointF(m + w * 0.88, y1))
            p.drawLine(QPointF(m + w * 0.66, y1 - w * 0.18), QPointF(m + w * 0.88, y1))
            p.drawLine(QPointF(m + w * 0.66, y1 + w * 0.18), QPointF(m + w * 0.88, y1))
            p.drawLine(QPointF(m + w * 0.88, y2), QPointF(m + w * 0.12, y2))
            p.drawLine(QPointF(m + w * 0.34, y2 - w * 0.18), QPointF(m + w * 0.12, y2))
            p.drawLine(QPointF(m + w * 0.34, y2 + w * 0.18), QPointF(m + w * 0.12, y2))

        p.end()
        return px

    @staticmethod
    def icon(name: str, size: int = 16, color: str = "#a1a1aa") -> QIcon:
        return QIcon(LucideIcon.pixmap(name, size, color))


# ==================== 2. 图像转换与辅助函数 ====================

def cv2_to_qpixmap(bgr_img: np.ndarray) -> QPixmap:
    if bgr_img is None:
        return QPixmap()
    rgb = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


def load_qpixmap_safe(filepath: str) -> QPixmap:
    bgr = read_cv2_image(filepath, grayscale=False)
    if bgr is None:
        return QPixmap()
    return cv2_to_qpixmap(bgr)


def make_dual_thumbnail_pixmap(path_a: str, path_b: str, w: int = 56, h: int = 32) -> QPixmap:
    """为左侧 260px 导航抽屉生成双图并排微型缩略图卡片"""
    dpr = 2.0
    canvas = QPixmap(int(w * dpr), int(h * dpr))
    canvas.setDevicePixelRatio(dpr)
    canvas.fill(QColor("#18181b"))

    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    half_w = (w - 2) // 2
    for idx, fp in enumerate((path_a, path_b)):
        x = idx * (half_w + 2)
        rect = QRectF(x, 0, half_w, h)
        bgr = read_cv2_image(fp, grayscale=False) if (fp and os.path.exists(fp)) else None
        if bgr is not None:
            thumb = cv2.resize(bgr, (half_w * 2, h * 2), interpolation=cv2.INTER_AREA)
            px = cv2_to_qpixmap(thumb)
            path_clip = QPainterPath()
            path_clip.addRoundedRect(rect, 3.0, 3.0)
            p.save()
            p.setClipPath(path_clip)
            p.drawPixmap(rect.toRect(), px)
            p.restore()
        else:
            p.fillRect(rect, QColor("#27272a"))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1.0))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 3.0, 3.0)

    p.end()
    return canvas


def extract_folders_from_mime(mime_data: QMimeData) -> List[str]:
    folders: List[str] = []
    seen = set()
    if mime_data.hasUrls():
        for url in mime_data.urls():
            local_path = url.toLocalFile()
            if not local_path:
                continue
            local_path = os.path.normpath(local_path)
            target_dir = local_path if os.path.isdir(local_path) else (
                os.path.dirname(local_path) if os.path.isfile(local_path) else None
            )
            if target_dir and os.path.isdir(target_dir):
                norm_key = os.path.normcase(os.path.abspath(target_dir))
                if norm_key not in seen:
                    seen.add(norm_key)
                    folders.append(target_dir)
    elif mime_data.hasText():
        raw = mime_data.text().strip().strip('"').strip("'")
        if os.path.isdir(raw):
            folders.append(os.path.normpath(raw))
        elif os.path.isfile(raw):
            folders.append(os.path.normpath(os.path.dirname(raw)))
    return folders


def shorten_path(path: str, max_chars: int = 26) -> str:
    if not path:
        return ""
    norm = os.path.normpath(path)
    if len(norm) <= max_chars:
        return norm
    parts = norm.split(os.sep)
    if len(parts) >= 2:
        tail = os.path.join(parts[-2], parts[-1])
        if len(tail) + 5 <= max_chars:
            return f"{parts[0]}\\...\\{tail}"
    return "..." + norm[-(max_chars - 3):]


# ==================== 3. 顶部 48px 单行工具栏组件 ====================

class SegmentedControl(QFrame):
    """
    分段控制器 (Segmented Control)：切换「单文件夹查重」与「跨文件夹交叉比对」
    配备 240ms OutCubic 丝滑滑动胶囊背景 + 描边微光过渡动画
    """
    modeChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setObjectName("SegCtrl")
        self.setStyleSheet("QFrame#SegCtrl { background: transparent; border: none; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        self.btn_single = QPushButton("单文件夹查重")
        self.btn_cross = QPushButton("跨文件夹交叉比对")
        self._is_cross = False
        self._slide_progress = 0.0  # 0.0 = 单文件夹, 1.0 = 跨文件夹
        self._glow_progress = 0.0   # 切换瞬间的描边呼吸高光

        for btn in (self.btn_single, self.btn_cross):
            btn.setFixedHeight(26)
            btn.setCursor(Qt.PointingHandCursor)
            layout.addWidget(btn)

        self._slide_anim = QVariantAnimation(self)
        self._slide_anim.setDuration(240)
        self._slide_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._slide_anim.valueChanged.connect(self._on_slide_step)

        self._glow_anim = QVariantAnimation(self)
        self._glow_anim.setDuration(420)
        self._glow_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._glow_anim.valueChanged.connect(self._on_glow_step)

        self.btn_single.clicked.connect(lambda: self.set_cross_mode(False))
        self.btn_cross.clicked.connect(lambda: self.set_cross_mode(True))
        self._refresh_style()

    @property
    def is_cross(self) -> bool:
        return self._is_cross

    def _on_slide_step(self, val):
        self._slide_progress = float(val)
        self.update()

    def _on_glow_step(self, val):
        self._glow_progress = float(val)
        self.update()

    def set_cross_mode(self, is_cross: bool, emit_signal: bool = True):
        if self._is_cross == is_cross:
            return
        self._is_cross = is_cross
        self._refresh_style()

        self._slide_anim.stop()
        self._slide_anim.setStartValue(self._slide_progress)
        self._slide_anim.setEndValue(1.0 if is_cross else 0.0)
        self._slide_anim.start()

        self._glow_anim.stop()
        self._glow_anim.setStartValue(1.0)
        self._glow_anim.setEndValue(0.0)
        self._glow_anim.start()

        if emit_signal:
            self.modeChanged.emit(self._is_cross)

    def _refresh_style(self):
        active_css = """
            QPushButton {
                background-color: transparent;
                color: #ffffff;
                font-size: 12px;
                font-weight: 600;
                border-radius: 4px;
                padding: 0 12px;
                border: none;
            }
        """
        idle_css = """
            QPushButton {
                background-color: transparent;
                color: #a1a1aa;
                font-size: 12px;
                font-weight: 400;
                border-radius: 4px;
                padding: 0 12px;
                border: none;
            }
            QPushButton:hover {
                color: #f4f4f5;
                background-color: rgba(255, 255, 255, 0.04);
            }
        """
        self.btn_single.setStyleSheet(idle_css if self._is_cross else active_css)
        self.btn_cross.setStyleSheet(active_css if self._is_cross else idle_css)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        outer = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        p.setBrush(QColor("#18181b"))

        # 外框描边随切换产生微光呼吸过渡
        g = self._glow_progress
        border_col = QColor(
            int(255 * (1 - g) + 59 * g),
            int(255 * (1 - g) + 130 * g),
            int(255 * (1 - g) + 246 * g),
            int(20 + 145 * g)
        )
        p.setPen(QPen(border_col, 1.0))
        p.drawRoundedRect(outer, 6.0, 6.0)

        # 计算平滑滑动的蓝色高亮胶囊位置与宽度
        r1 = self.btn_single.geometry()
        r2 = self.btn_cross.geometry()
        if r1.width() > 0 and r2.width() > 0:
            t = self._slide_progress
            x = r1.x() + (r2.x() - r1.x()) * t
            w = r1.width() + (r2.width() - r1.width()) * t
            pill_rect = QRectF(x, r1.y(), w, r1.height())

            p.setBrush(QColor("#2563eb"))
            p.setPen(QPen(QColor(255, 255, 255, int(35 + 45 * g)), 1.0))
            p.drawRoundedRect(pill_rect, 4.5, 4.5)

        p.end()


class CompactPathInput(QPushButton):
    """顶部紧凑路径输入框（支持拖入文件夹或点击浏览，配 16px 线性文件夹图标）"""
    pathSelected = Signal(int, str)
    multiplePathsDropped = Signal(list)

    def __init__(self, slot_index: int = 1, placeholder: str = "选择或拖入文件夹 1", parent=None):
        super().__init__(parent)
        self.slot_index = slot_index
        self.placeholder = placeholder
        self._path = ""

        self.setFixedHeight(32)
        self.setMinimumWidth(176)
        self.setMaximumWidth(256)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setIcon(LucideIcon.icon("folder", 15, "#71717a"))
        self.setIconSize(QSize(15, 15))
        self.clicked.connect(self._on_clicked)
        self._update_appearance()

    @property
    def path(self) -> str:
        return self._path

    def set_path(self, path: str):
        self._path = os.path.normpath(path) if path else ""
        self._update_appearance()

    def _update_appearance(self, drag_active: bool = False):
        if drag_active:
            self.setIcon(LucideIcon.icon("folder", 15, "#2563eb"))
            self.setStyleSheet("""
                QPushButton {
                    background-color: #202023;
                    border: 1px solid #2563eb;
                    border-radius: 6px;
                    color: #f4f4f5;
                    font-size: 12px;
                    padding: 0 10px;
                    text-align: left;
                }
            """)
            return

        if self._path and os.path.isdir(self._path):
            self.setIcon(LucideIcon.icon("folder", 15, "#a1a1aa"))
            self.setText(f" {shorten_path(self._path, 24)}")
            self.setToolTip(f"{self._path}\n点击更换目录，或直接拖入新文件夹")
            self.setStyleSheet("""
                QPushButton {
                    background-color: #18181b;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 6px;
                    color: #e4e4e7;
                    font-size: 12px;
                    padding: 0 10px;
                    text-align: left;
                }
                QPushButton:hover {
                    background-color: #27272a;
                    border-color: rgba(255, 255, 255, 0.16);
                }
            """)
        else:
            self.setIcon(LucideIcon.icon("folder", 15, "#71717a"))
            self.setText(f" {self.placeholder}")
            self.setToolTip("点击浏览文件夹，或直接拖入文件夹")
            self.setStyleSheet("""
                QPushButton {
                    background-color: #18181b;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 6px;
                    color: #71717a;
                    font-size: 12px;
                    padding: 0 10px;
                    text-align: left;
                }
                QPushButton:hover {
                    background-color: #27272a;
                    color: #a1a1aa;
                }
            """)

    def _on_clicked(self):
        start_dir = self._path if os.path.isdir(self._path) else os.path.expanduser("~\\Desktop")
        folder = QFileDialog.getExistingDirectory(self, f"选择文件夹 {self.slot_index}", start_dir)
        if folder:
            norm = os.path.normpath(folder)
            self.set_path(norm)
            self.pathSelected.emit(self.slot_index, norm)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if extract_folders_from_mime(event.mimeData()):
            event.acceptProposedAction()
            self._update_appearance(drag_active=True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if extract_folders_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._update_appearance(drag_active=False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self._update_appearance(drag_active=False)
        folders = extract_folders_from_mime(event.mimeData())
        if not folders:
            event.ignore()
            return
        event.acceptProposedAction()
        if len(folders) >= 2:
            self.multiplePathsDropped.emit(folders)
        else:
            self.set_path(folders[0])
            self.pathSelected.emit(self.slot_index, folders[0])


SENSITIVITY_SPECS = {
    "standard": {
        "short": "标准模式",
        "badge": "均衡推荐",
        "title": "标准模式（推荐）",
        "accent": "#3b82f6",
        "accent_rgb": (59, 130, 246),
        "desc": "兼顾原图与局部变体：精准检出完全相同、尺寸缩放压缩，以及加水印/换字、局部微调或局部调色的相似图片。",
        "detect_scope": "完全相同原图、不同分辨率缩放/有损压缩图、局部加水印或换字、边缘微调或局部调色的同源图片。",
        "ignore_scope": "构图完全不同的独立图片、仅背景色调相似但主体内容不同的图像。",
        "scene_logic": "综合多尺度空间直方图、边缘矩阵与 SIFT/RANSAC 几何内点校验，日常摄影图库、设计素材与电商图片去重首选。",
        "inline_hint": "当前灵敏度 [标准模式]：检出完全相同、尺寸压缩及水印/局部微调的相似图片",
    },
    "strict": {
        "short": "严格模式",
        "badge": "零误报 · 仅同图",
        "title": "严格模式（仅限同图）",
        "accent": "#10b981",
        "accent_rgb": (16, 185, 129),
        "desc": "仅限高度一致原图：只检出画面几乎一模一样的原图、格式转换与缩放压缩图，自动忽略换字或改色变体，零误报。",
        "detect_scope": "二进制完全相同文件、仅做过尺寸放大缩小、格式转换（PNG/JPG/WebP）或轻度重压缩的同一张图片。",
        "ignore_scope": "修改过文字、局部改过颜色、增减了局部元素的同系列衍生变体图（均不报警）。",
        "scene_logic": "采用高阈值结构与严苛几何内点一致性过滤，适合快速清理纯重复备份图片，确保零误删。",
        "inline_hint": "当前灵敏度 [严格模式]：仅检出画面高度一致的原图与缩放压缩图，忽略局部修改变体",
    },
    "deep": {
        "short": "深度宽松",
        "badge": "广覆盖 · 含重绘",
        "title": "深度宽松（广覆盖）",
        "accent": "#f59e0b",
        "accent_rgb": (245, 158, 11),
        "desc": "捕获大幅调色与重绘：放宽特征匹配阈值，将大幅换底色、AI图生图重绘变体及近似构图图片一并检出供人工排查。",
        "detect_scope": "包含标准模式全部范围，并额外捕获：大幅更换背景/色调、AI 图生图重绘变体、同构图连拍或衍生图片。",
        "ignore_scope": "仅过滤视觉结构与局部几何特征均完全无关的图片。",
        "scene_logic": "放宽局部特征匹配与色彩直方图容差，适合清查“AI 图生图衍生图”、连拍选片或近似素材深度复核。",
        "inline_hint": "当前灵敏度 [深度宽松]：放宽阈值，连同大幅调色、AI重绘及近似构图图片一并检出",
    },
}


def build_sensitivity_tooltip_html(key: str) -> str:
    """构建鼠标悬停时的完整模式逻辑富文本说明卡片"""
    spec = SENSITIVITY_SPECS.get(key, SENSITIVITY_SPECS["standard"])
    accent = spec["accent"]
    return (
        f"<div style='max-width: 440px; line-height: 1.45;'>"
        f"<div style='color: {accent}; font-weight: 600; font-size: 12px; margin-bottom: 4px;'>"
        f"● {spec['title']} — {spec['badge']}</div>"
        f"<div style='color: #e4e4e7; font-size: 12px; margin-bottom: 6px;'>{spec['desc']}</div>"
        f"<div style='color: #10b981; font-size: 11px; margin-bottom: 3px;'>"
        f"<b>✓ 检出范围：</b><span style='color: #d4d4d8;'>{spec['detect_scope']}</span></div>"
        f"<div style='color: #f59e0b; font-size: 11px; margin-bottom: 3px;'>"
        f"<b>✗ 自动忽略：</b><span style='color: #d4d4d8;'>{spec['ignore_scope']}</span></div>"
        f"<div style='color: #60a5fa; font-size: 11px;'>"
        f"<b>◎ 判别逻辑：</b><span style='color: #a1a1aa;'>{spec['scene_logic']}</span></div>"
        f"</div>"
    )


class SensitivitySelector(QToolButton):
    """
    带详尽图文说明卡片的灵敏度下拉选择器 (高度 32px)：
    - 点击展开 360px 宽的说明浮层，完整展示三种灵敏度的检出范围、忽略范围与适用场景；
    - 切换灵敏度时带有专属语义状态点与 420ms 描边呼吸微光动画。
    """
    sensitivityChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_key = "standard"
        self._pulse_val = 0.0
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)
        self.setPopupMode(QToolButton.InstantPopup)
        self.setIconSize(QSize(14, 14))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setStyleSheet("""
            QToolButton {
                background-color: transparent;
                border: none;
                border-radius: 6px;
                padding: 0 12px 0 22px;
                color: #e4e4e7;
                font-size: 12px;
                font-weight: 500;
            }
            QToolButton:hover {
                color: #ffffff;
            }
            QToolButton::menu-indicator { image: none; }
        """)

        self._pulse_anim = QVariantAnimation(self)
        self._pulse_anim.setDuration(450)
        self._pulse_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._pulse_anim.valueChanged.connect(self._on_pulse_step)

        self._menu = QMenu(self)
        self._menu.setStyleSheet("""
            QMenu {
                background-color: #202023;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 8px;
            }
        """)
        self.setMenu(self._menu)
        self._rebuild_menu()
        self._update_button_label()

    @property
    def current_key(self) -> str:
        return self._current_key

    def _on_pulse_step(self, val):
        self._pulse_val = float(val)
        self.update()

    def set_sensitivity(self, key: str, emit_signal: bool = True):
        if key not in SENSITIVITY_SPECS:
            return
        changed = (self._current_key != key)
        self._current_key = key
        self._update_button_label()
        self._rebuild_menu()

        self._pulse_anim.stop()
        self._pulse_anim.setStartValue(1.0)
        self._pulse_anim.setEndValue(0.0)
        self._pulse_anim.start()

        if changed and emit_signal:
            self.sensitivityChanged.emit(key)

    def _update_button_label(self):
        spec = SENSITIVITY_SPECS[self._current_key]
        self.setIcon(LucideIcon.icon("sliders", 14, spec["accent"]))
        self.setText(f" 灵敏度：{spec['short']} ▾")
        self.setToolTip(build_sensitivity_tooltip_html(self._current_key))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        spec = SENSITIVITY_SPECS[self._current_key]
        r, g, b = spec["accent_rgb"]
        pulse = self._pulse_val
        hovered = self.underMouse()

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)

        bg_base = QColor("#27272a") if hovered else QColor("#18181b")
        p.setBrush(bg_base)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(rect, 6.0, 6.0)

        if pulse > 0.01:
            p.setBrush(QColor(r, g, b, int(52 * pulse)))
            p.drawRoundedRect(rect, 6.0, 6.0)

        border_alpha = int(38 + 180 * pulse) if pulse > 0.01 else (48 if hovered else 24)
        border_col = QColor(r, g, b, border_alpha) if pulse > 0.01 else QColor(255, 255, 255, border_alpha)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(border_col, 1.2 if pulse > 0.15 else 1.0))
        p.drawRoundedRect(rect, 6.0, 6.0)

        # 左侧语义状态圆点与扩散光环
        dot_center = QPointF(12.0, self.height() / 2.0)
        if pulse > 0.05:
            halo_r = 3.0 + 4.5 * (1.0 - pulse)
            p.setBrush(QColor(r, g, b, int(95 * pulse)))
            p.setPen(Qt.NoPen)
            p.drawEllipse(dot_center, halo_r, halo_r)

        p.setBrush(QColor(r, g, b))
        p.setPen(Qt.NoPen)
        p.drawEllipse(dot_center, 3.0, 3.0)
        p.end()

        super().paintEvent(event)

    def _rebuild_menu(self):
        self._menu.clear()
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(4, 4, 4, 4)
        c_layout.setSpacing(6)

        hdr = QLabel("选择图像查重灵敏度（点击立即切换）")
        hdr.setStyleSheet("color: #71717a; font-size: 11px; font-weight: 600; padding: 2px 4px; border: none;")
        c_layout.addWidget(hdr)

        for key, spec in SENSITIVITY_SPECS.items():
            is_sel = (key == self._current_key)
            r, g, b = spec["accent_rgb"]
            accent_hex = spec["accent"]
            card = QFrame()
            card.setFixedWidth(368)
            card.setCursor(Qt.PointingHandCursor)
            border_col = accent_hex if is_sel else "rgba(255, 255, 255, 0.06)"
            bg_col = f"rgba({r}, {g}, {b}, 0.12)" if is_sel else "#18181b"
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {bg_col};
                    border: 1px solid {border_col};
                    border-radius: 6px;
                }}
                QFrame:hover {{
                    background-color: #27272a;
                    border-color: {accent_hex if is_sel else "rgba(255, 255, 255, 0.20)"};
                }}
            """)
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(12, 10, 12, 10)
            card_lay.setSpacing(4)

            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(6)

            dot_lbl = QLabel("●")
            dot_lbl.setStyleSheet(f"color: {accent_hex}; font-size: 10px; background: transparent; border: none;")
            title_row.addWidget(dot_lbl)

            lbl_t = QLabel(spec["title"])
            lbl_t.setStyleSheet(
                f"color: {accent_hex if is_sel else '#f4f4f5'}; font-size: 12px; font-weight: 600; background: transparent; border: none;"
            )
            title_row.addWidget(lbl_t)
            title_row.addStretch(1)

            badge_text = "当前使用" if is_sel else spec["badge"]
            lbl_chk = QLabel(badge_text)
            lbl_chk.setStyleSheet(
                f"color: {accent_hex if is_sel else '#71717a'}; "
                f"background-color: rgba({r}, {g}, {b}, {0.18 if is_sel else 0.08}); "
                f"padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; border: none;"
            )
            title_row.addWidget(lbl_chk)
            card_lay.addLayout(title_row)

            lbl_d = QLabel(spec["desc"])
            lbl_d.setWordWrap(True)
            lbl_d.setStyleSheet("color: #d4d4d8; font-size: 11px; line-height: 1.4; background: transparent; border: none;")
            card_lay.addWidget(lbl_d)

            lbl_det = QLabel(f"✓ 检出：{spec['detect_scope']}\n✗ 忽略：{spec['ignore_scope']}")
            lbl_det.setWordWrap(True)
            lbl_det.setStyleSheet("color: #71717a; font-size: 10px; line-height: 1.35; background: transparent; border: none;")
            card_lay.addWidget(lbl_det)

            def _make_click_handler(target_key: str):
                def _handler(event):
                    if event.button() == Qt.LeftButton:
                        self._menu.close()
                        self.set_sensitivity(target_key)
                return _handler

            card.mousePressEvent = _make_click_handler(key)
            c_layout.addWidget(card)

        act = QWidgetAction(self._menu)
        act.setDefaultWidget(container)
        self._menu.addAction(act)


class SensitivityInteractiveBar(QFrame):
    """
    导入态主按钮下方的交互式灵敏度切换与说明胶囊组件 (宽 600px，收起高 82px / 展开高 196px)：
    1. 完整显示不截断：加宽至 600px 并支持自动换行，核心说明一目了然，绝不截断文字；
    2. 悬停即看全貌：鼠标停留在文字上方时立即弹出富文本卡片，展示「检出范围 / 自动忽略 / 判别逻辑」；
    3. 点击展开详情：右上角配备 [展开详情 ▾] / [收起详情 ▴] 按钮（或直接点击文字区域），
       240ms 平滑展开三行完整逻辑拆解（✓ 检出范围、✗ 自动忽略、◎ 判别逻辑）。
    """
    sensitivitySelected = Signal(str)

    KEYS = ["standard", "strict", "deep"]
    COLLAPSED_H = 82
    EXPANDED_H = 196

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_key = "standard"
        self._prev_key = "standard"
        self._prev_rgb = SENSITIVITY_SPECS["standard"]["accent_rgb"]
        self._slide_idx = 0.0       # 0.0=standard, 1.0=strict, 2.0=deep
        self._text_anim_val = 1.0   # 0.0 -> 1.0 新旧文案滚轮交替进度
        self._pulse_val = 0.0       # 1.0 -> 0.0 边框语义色呼吸高光
        self._expanded = False
        self._expand_progress = 0.0  # 0.0 (收起) <-> 1.0 (展开)

        self.setFixedSize(600, self.COLLAPSED_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("SensInteractiveBar")
        self.setStyleSheet("QFrame#SensInteractiveBar { background: transparent; border: none; }")

        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(16, 8, 16, 8)
        main_lay.setSpacing(6)

        # 顶栏：左侧标签 + 三档分段快切按钮 + 右侧语义徽章 + [展开详情 ▾] 按钮
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        lbl_prefix = QLabel("灵敏度档位")
        lbl_prefix.setStyleSheet("color: #71717a; font-size: 11px; font-weight: 600; background: transparent; border: none;")
        top_row.addWidget(lbl_prefix)

        top_row.addSpacing(4)

        self._btns: Dict[str, QPushButton] = {}
        for k in self.KEYS:
            sp = SENSITIVITY_SPECS[k]
            btn = QPushButton(sp["short"])
            btn.setFixedHeight(22)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(build_sensitivity_tooltip_html(k))
            btn.clicked.connect(lambda checked=False, key=k: self._on_pill_clicked(key))
            self._btns[k] = btn
            top_row.addWidget(btn)

        top_row.addStretch(1)

        self.lbl_badge = QLabel()
        self.lbl_badge.setFixedHeight(20)
        top_row.addWidget(self.lbl_badge)

        self.btn_expand = QPushButton("展开详情 ▾")
        self.btn_expand.setFixedHeight(20)
        self.btn_expand.setCursor(Qt.PointingHandCursor)
        self.btn_expand.setToolTip("点击展开或收起当前灵敏度的完整检出范围、忽略规则与判别逻辑")
        self.btn_expand.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.04);
                color: #a1a1aa;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 4px;
                padding: 0 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #27272a;
                color: #f4f4f5;
                border-color: rgba(255, 255, 255, 0.18);
            }
        """)
        self.btn_expand.clicked.connect(self.toggle_expand)
        top_row.addWidget(self.btn_expand)

        main_lay.addLayout(top_row)
        main_lay.addStretch(1)

        # 动画控制器
        self._slide_anim = QVariantAnimation(self)
        self._slide_anim.setDuration(220)
        self._slide_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._slide_anim.valueChanged.connect(self._on_slide_step)

        self._text_anim = QVariantAnimation(self)
        self._text_anim.setDuration(240)
        self._text_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._text_anim.valueChanged.connect(self._on_text_step)

        self._pulse_anim = QVariantAnimation(self)
        self._pulse_anim.setDuration(460)
        self._pulse_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._pulse_anim.valueChanged.connect(self._on_pulse_step)

        self._expand_anim = QVariantAnimation(self)
        self._expand_anim.setDuration(240)
        self._expand_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._expand_anim.valueChanged.connect(self._on_expand_step)

        self._refresh_button_styles()

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    @property
    def text_summary(self) -> str:
        return SENSITIVITY_SPECS[self._current_key]["inline_hint"]

    def text(self) -> str:
        return self.text_summary

    def toggle_expand(self):
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool):
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self.btn_expand.setText("收起详情 ▴" if expanded else "展开详情 ▾")
        self._expand_anim.stop()
        self._expand_anim.setStartValue(self._expand_progress)
        self._expand_anim.setEndValue(1.0 if expanded else 0.0)
        self._expand_anim.start()

    def _on_expand_step(self, val):
        self._expand_progress = float(val)
        cur_h = int(self.COLLAPSED_H + (self.EXPANDED_H - self.COLLAPSED_H) * self._expand_progress)
        self.setFixedHeight(cur_h)
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        # 点击下方文字说明区域也可以直接展开/收起完整详情
        if event.button() == Qt.LeftButton and event.position().y() > 34:
            self.toggle_expand()
            event.accept()
            return
        super().mousePressEvent(event)

    def _on_pill_clicked(self, key: str):
        if key == self._current_key:
            return
        self.set_sensitivity(key, emit_signal=True)

    def set_sensitivity(self, key: str, emit_signal: bool = False):
        if key not in SENSITIVITY_SPECS:
            return
        target_idx = float(self.KEYS.index(key))
        changed = (key != self._current_key)
        if changed:
            self._prev_key = self._current_key
            self._prev_rgb = SENSITIVITY_SPECS[self._current_key]["accent_rgb"]

        self._current_key = key
        self._refresh_button_styles()

        if changed:
            self._slide_anim.stop()
            self._slide_anim.setStartValue(self._slide_idx)
            self._slide_anim.setEndValue(target_idx)
            self._slide_anim.start()

            self._text_anim.stop()
            self._text_anim.setStartValue(0.0)
            self._text_anim.setEndValue(1.0)
            self._text_anim.start()

            self._pulse_anim.stop()
            self._pulse_anim.setStartValue(1.0)
            self._pulse_anim.setEndValue(0.0)
            self._pulse_anim.start()

            self.update()

            if emit_signal:
                self.sensitivitySelected.emit(key)

    def _on_slide_step(self, val):
        self._slide_idx = float(val)
        self.update()

    def _on_text_step(self, val):
        self._text_anim_val = float(val)
        self.update()

    def _on_pulse_step(self, val):
        self._pulse_val = float(val)
        self.update()

    def _refresh_button_styles(self):
        spec = SENSITIVITY_SPECS[self._current_key]
        r, g, b = spec["accent_rgb"]
        accent_hex = spec["accent"]

        # 悬停在组件任意位置均弹出完整富文本逻辑卡片
        self.setToolTip(build_sensitivity_tooltip_html(self._current_key))

        self.lbl_badge.setText(f"● {spec['badge']}")
        self.lbl_badge.setStyleSheet(
            f"color: {accent_hex}; background-color: rgba({r}, {g}, {b}, 0.14); "
            f"border: 1px solid rgba({r}, {g}, {b}, 0.32); border-radius: 4px; "
            f"padding: 0 8px; font-size: 11px; font-weight: 600;"
        )

        for k, btn in self._btns.items():
            is_act = (k == self._current_key)
            if is_act:
                btn.setStyleSheet("""
                    QPushButton {
                        background: transparent;
                        color: #ffffff;
                        font-size: 11px;
                        font-weight: 600;
                        padding: 0 10px;
                        border: none;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background: transparent;
                        color: #a1a1aa;
                        font-size: 11px;
                        font-weight: 400;
                        padding: 0 10px;
                        border-radius: 4px;
                        border: none;
                    }
                    QPushButton:hover {
                        color: #f4f4f5;
                        background-color: rgba(255, 255, 255, 0.04);
                    }
                """)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        spec = SENSITIVITY_SPECS[self._current_key]
        prev_spec = SENSITIVITY_SPECS.get(self._prev_key, spec)
        tr, tg, tb = spec["accent_rgb"]
        pr, pg, pb = self._prev_rgb
        t_prog = self._text_anim_val

        # 实时插值当前过渡颜色
        r = int(pr + (tr - pr) * t_prog)
        g = int(pg + (tg - pg) * t_prog)
        b = int(pb + (tb - pb) * t_prog)
        pulse = self._pulse_val

        outer = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        p.setBrush(QColor("#202023"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(outer, 8.0, 8.0)

        if pulse > 0.01:
            p.setBrush(QColor(r, g, b, int(34 * pulse)))
            p.drawRoundedRect(outer, 8.0, 8.0)

        border_col = (
            QColor(r, g, b, int(50 + 175 * pulse))
            if pulse > 0.01
            else QColor(255, 255, 255, 24 if self._expand_progress > 0.1 else 20)
        )
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(border_col, 1.2 if pulse > 0.1 else 1.0))
        p.drawRoundedRect(outer, 8.0, 8.0)

        # 绘制顶部三档胶囊的平滑滑动指示背景
        idx_low = max(0, min(len(self.KEYS) - 1, int(self._slide_idx)))
        idx_high = max(0, min(len(self.KEYS) - 1, idx_low + 1))
        frac = self._slide_idx - idx_low

        b1 = self._btns[self.KEYS[idx_low]].geometry()
        b2 = self._btns[self.KEYS[idx_high]].geometry()
        if b1.width() > 0 and b2.width() > 0:
            px = b1.x() + (b2.x() - b1.x()) * frac
            pw = b1.width() + (b2.width() - b1.width()) * frac
            pill_rect = QRectF(px, b1.y(), pw, b1.height())

            p.setBrush(QColor(r, g, b, 62))
            p.setPen(QPen(QColor(r, g, b, 175), 1.0))
            p.drawRoundedRect(pill_rect, 4.0, 4.0)

        # 绘制核心一句话说明（600px 宽度 + TextWordWrap 确保完整显示不截断，支持滚轮切换过渡）
        p.setFont(QFont("Microsoft YaHei", 9))
        p.save()
        p.setClipRect(QRectF(14.0, 36.0, self.width() - 28.0, 38.0))

        if self._prev_key != self._current_key and t_prog < 0.99:
            p.setOpacity(max(0.0, (1.0 - t_prog) ** 1.4))
            p.setPen(QColor("#71717a"))
            out_rect = QRectF(16.0, 38.0 - 14.0 * t_prog, self.width() - 32.0, 34.0)
            p.drawText(out_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, prev_spec["desc"])

        p.setOpacity(max(0.05, t_prog))
        p.setPen(QColor("#e4e4e7" if pulse > 0.2 else "#b4b4bb"))
        in_rect = QRectF(16.0, 38.0 + (1.0 - t_prog) * 14.0, self.width() - 32.0, 34.0)
        p.drawText(in_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, spec["desc"])
        p.restore()

        # 绘制展开后的完整模式逻辑拆解区域 (✓ 检出范围 / ✗ 自动忽略 / ◎ 判别逻辑)
        if self._expand_progress > 0.02:
            p.save()
            p.setOpacity(self._expand_progress * max(0.15, t_prog))
            p.setClipRect(QRectF(12.0, 76.0, self.width() - 24.0, self.height() - 82.0))

            # 分隔细线
            p.setPen(QPen(QColor(255, 255, 255, 18), 1.0))
            p.drawLine(QPointF(16.0, 78.0), QPointF(self.width() - 16.0, 78.0))

            dy = (1.0 - t_prog) * 8.0
            rows = [
                ("✓ 检出范围：", spec["detect_scope"], QColor("#10b981"), QColor("#d4d4d8"), 84.0),
                ("✗ 自动忽略：", spec["ignore_scope"], QColor("#f59e0b"), QColor("#a1a1aa"), 118.0),
                ("◎ 判别逻辑：", spec["scene_logic"], QColor(r, g, b), QColor("#a1a1aa"), 152.0),
            ]
            label_w = 76.0
            content_w = self.width() - 32.0 - label_w

            for tag_text, body_text, tag_col, body_col, base_y in rows:
                ry = base_y + dy
                p.setFont(QFont("Microsoft YaHei", 8, QFont.DemiBold))
                p.setPen(tag_col)
                p.drawText(QRectF(16.0, ry, label_w, 30.0), Qt.AlignLeft | Qt.AlignTop, tag_text)

                p.setFont(QFont("Microsoft YaHei", 8))
                p.setPen(body_col)
                p.drawText(
                    QRectF(16.0 + label_w, ry, content_w, 32.0),
                    Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                    body_text
                )

            p.restore()

        p.end()


# ==================== 4. 阶段 1：准备与导入态对称圆角拖拽卡片与连接组件 ====================

class CrossConnectorBadge(QWidget):
    """
    跨文件夹交叉比对模式下的中央动态连接器 (宽 64px × 高 216px)：
    切换模式时伴随卡片展开执行 0° -> 180° 旋转与缩放过渡动画。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 216)
        self._progress = 0.0

    def set_progress(self, val: float):
        self._progress = max(0.0, min(1.0, float(val)))
        self.update()

    def paintEvent(self, event):
        if self._progress <= 0.02:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setOpacity(self._progress)

        cx, cy = self.width() / 2.0, self.height() / 2.0 - 6.0

        # 两侧虚线连接引导线
        dash_pen = QPen(QColor(59, 130, 246, int(110 * self._progress)), 1.2, Qt.DashLine)
        p.setPen(dash_pen)
        p.drawLine(QPointF(2.0, cy), QPointF(cx - 18.0, cy))
        p.drawLine(QPointF(cx + 18.0, cy), QPointF(self.width() - 2.0, cy))

        # 中央圆形徽章（带缩放与图标旋转过渡）
        scale = 0.55 + 0.45 * self._progress
        angle = (1.0 - self._progress) * -180.0

        p.save()
        p.translate(cx, cy)
        p.scale(scale, scale)
        p.rotate(angle)

        p.setBrush(QColor("#202023"))
        p.setPen(QPen(QColor(37, 99, 235, 160), 1.2))
        p.drawEllipse(QPointF(0, 0), 17.0, 17.0)

        icon_px = LucideIcon.pixmap("arrow-left-right", 16, "#3b82f6", 1.6)
        p.drawPixmap(QRectF(-8.0, -8.0, 16.0, 16.0).toRect(), icon_px)
        p.restore()

        # 底部微标签
        p.setFont(QFont("Microsoft YaHei", 8))
        p.setPen(QColor("#71717a"))
        p.drawText(QRectF(0, cy + 22.0, self.width(), 18.0), Qt.AlignCenter, "交叉比对")
        p.end()


class StudioDropCard(QFrame):
    """
    导入态对称圆角拖拽卡片 (320px × 216px, 背景 #202023, 极淡虚线描边)
    内含角色徽章、轻量线性矢量文件夹图标与简练文字：“拖入文件夹或点击浏览”
    支持模式切换时的描边微光呼吸脉冲动画 (trigger_mode_pulse)。
    """
    folderSelected = Signal(int, str)
    multipleFoldersDropped = Signal(list)

    def __init__(
        self,
        slot_index: int,
        title: str,
        subtitle: str = "拖入文件夹或点击浏览",
        role_badge: str = "单文件夹内部查重",
        parent=None
    ):
        super().__init__(parent)
        self.slot_index = slot_index
        self.default_title = title
        self.default_subtitle = subtitle
        self.role_badge = role_badge
        self._path = ""
        self._drag_hover = False
        self._pulse_val = 0.0

        self.setFixedSize(320, 216)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("StudioDropCard")
        self.setStyleSheet("QFrame#StudioDropCard { background: transparent; border: none; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        # 顶部角色小胶囊标签
        badge_row = QHBoxLayout()
        badge_row.addStretch(1)
        self.lbl_role_badge = QLabel(self.role_badge)
        self.lbl_role_badge.setAlignment(Qt.AlignCenter)
        badge_row.addWidget(self.lbl_role_badge)
        badge_row.addStretch(1)
        layout.addLayout(badge_row)

        layout.addSpacing(4)

        self.lbl_icon = QLabel()
        self.lbl_icon.setAlignment(Qt.AlignCenter)
        self.lbl_icon.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.lbl_icon)

        layout.addSpacing(4)

        self.lbl_title = QLabel(self.default_title)
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setStyleSheet(
            "font-size: 16px; font-weight: 600; color: #f4f4f5; background: transparent; border: none;"
        )
        layout.addWidget(self.lbl_title)

        self.lbl_sub = QLabel(self.default_subtitle)
        self.lbl_sub.setAlignment(Qt.AlignCenter)
        self.lbl_sub.setWordWrap(True)
        self.lbl_sub.setStyleSheet(
            "font-size: 12px; color: #71717a; background: transparent; border: none;"
        )
        layout.addWidget(self.lbl_sub)

        self._pulse_anim = QVariantAnimation(self)
        self._pulse_anim.setDuration(420)
        self._pulse_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._pulse_anim.valueChanged.connect(self._on_pulse_step)

        self._refresh_visuals(drag_hover=False)

    def _on_pulse_step(self, val):
        self._pulse_val = float(val)
        self.update()

    def trigger_mode_pulse(self, new_title: Optional[str] = None, new_badge: Optional[str] = None):
        if new_title is not None:
            self.default_title = new_title
        if new_badge is not None:
            self.role_badge = new_badge
        self._refresh_visuals(drag_hover=False)
        self._pulse_anim.stop()
        self._pulse_anim.setStartValue(1.0)
        self._pulse_anim.setEndValue(0.0)
        self._pulse_anim.start()

    def set_folder_path(self, path: str):
        self._path = os.path.normpath(path) if path else ""
        self._refresh_visuals(drag_hover=False)
        self._pulse_anim.stop()
        self._pulse_anim.setStartValue(1.0)
        self._pulse_anim.setEndValue(0.0)
        self._pulse_anim.start()

    def _refresh_visuals(self, drag_hover: bool = False):
        self._drag_hover = drag_hover
        self.lbl_role_badge.setText(self.role_badge)

        is_cross_role = ("A" in self.role_badge or "B" in self.role_badge)
        if is_cross_role:
            self.lbl_role_badge.setStyleSheet(
                "background-color: rgba(37, 99, 235, 0.14); color: #60a5fa; "
                "border: 1px solid rgba(59, 130, 246, 0.30); border-radius: 4px; "
                "padding: 1px 8px; font-size: 11px; font-weight: 600;"
            )
        else:
            self.lbl_role_badge.setStyleSheet(
                "background-color: #27272a; color: #a1a1aa; "
                "border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 4px; "
                "padding: 1px 8px; font-size: 11px; font-weight: 500;"
            )

        if drag_hover:
            self.lbl_icon.setPixmap(LucideIcon.pixmap("folder-plus", 28, "#2563eb", 1.6))
        elif self._path and os.path.isdir(self._path):
            self.lbl_icon.setPixmap(LucideIcon.pixmap("folder", 28, "#2563eb", 1.6))
            name = os.path.basename(self._path) or self._path
            self.lbl_title.setText(name)
            self.lbl_sub.setText(shorten_path(self._path, 36))
            self.setToolTip(f"{self._path}\n点击重新选择，或拖入新文件夹")
        else:
            self.lbl_icon.setPixmap(LucideIcon.pixmap("folder-plus", 28, "#71717a", 1.5))
            self.lbl_title.setText(self.default_title)
            self.lbl_sub.setText(self.default_subtitle)
            self.setToolTip("")

        self.update()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        hovered = self.underMouse()
        has_dir = bool(self._path and os.path.isdir(self._path))
        pulse = self._pulse_val

        bg = QColor("#242428") if hovered else QColor("#202023")
        p.setBrush(bg)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(rect, 12.0, 12.0)

        if pulse > 0.01:
            p.setBrush(QColor(37, 99, 235, int(36 * pulse)))
            p.drawRoundedRect(rect, 12.0, 12.0)

        if self._drag_hover:
            pen = QPen(QColor("#2563eb"), 1.5, Qt.SolidLine)
        elif pulse > 0.05:
            pen = QPen(QColor(59, 130, 246, int(60 + 185 * pulse)), 1.4, Qt.SolidLine)
        elif has_dir:
            pen = QPen(QColor("#2563eb") if hovered else QColor(37, 99, 235, 115), 1.0, Qt.SolidLine)
        else:
            pen = QPen(QColor(255, 255, 255, 56 if hovered else 31), 1.0, Qt.DashLine)

        p.setBrush(Qt.NoBrush)
        p.setPen(pen)
        p.drawRoundedRect(rect, 12.0, 12.0)
        p.end()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            start_dir = self._path if os.path.isdir(self._path) else os.path.expanduser("~\\Desktop")
            folder = QFileDialog.getExistingDirectory(self, f"选择文件夹 {self.slot_index}", start_dir)
            if folder:
                norm = os.path.normpath(folder)
                self.set_folder_path(norm)
                self.folderSelected.emit(self.slot_index, norm)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if extract_folders_from_mime(event.mimeData()):
            event.acceptProposedAction()
            self._refresh_visuals(drag_hover=True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if extract_folders_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._refresh_visuals(drag_hover=False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self._refresh_visuals(drag_hover=False)
        folders = extract_folders_from_mime(event.mimeData())
        if not folders:
            event.ignore()
            return
        event.acceptProposedAction()
        if len(folders) >= 2:
            self.multipleFoldersDropped.emit(folders)
        else:
            self.set_folder_path(folders[0])
            self.folderSelected.emit(self.slot_index, folders[0])


class TransitionToastBanner(QWidget):
    """
    顶部浮动状态切换胶囊提示 (Dynamic Toast Banner)：
    - 支持高频连续切换查重模式或灵敏度模式；
    - 每次切换均立即触发：新旧文案垂直滚轮交替 (Slot-Roll) + 胶囊弹性微跳 (Spring Bounce)
      + 胶囊自适应宽度平滑变形 + 状态点声呐波纹扩散 + 底部倒计时流光条。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(720, 48)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setVisible(False)

        self._prev_title = ""
        self._prev_subtitle = ""
        self._prev_rgb: Tuple[int, int, int] = (59, 130, 246)
        self._prev_pill_w = 560.0

        self._title = ""
        self._subtitle = ""
        self._accent_rgb: Tuple[int, int, int] = (59, 130, 246)
        self._target_pill_w = 560.0
        self._cur_pill_w = 560.0

        self._enter_progress = 0.0   # 0.0 (隐藏) <-> 1.0 (在场)
        self._switch_progress = 1.0  # 每次触发从 0.0 -> 1.0 执行滚轮翻页与波纹脉冲
        self._timer_progress = 1.0   # 1.0 -> 0.0 底部停留进度流光条

        # 进出场动画
        self._enter_anim = QVariantAnimation(self)
        self._enter_anim.setDuration(220)
        self._enter_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._enter_anim.valueChanged.connect(self._on_enter_step)
        self._enter_anim.finished.connect(self._on_enter_finished)

        # 连续切换时的内容滚轮翻页与回弹动画（每次必从 0.0 -> 1.0 重新触发）
        self._switch_anim = QVariantAnimation(self)
        self._switch_anim.setDuration(250)
        self._switch_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._switch_anim.valueChanged.connect(self._on_switch_step)

        # 停留倒计时进度动画（兼具 1.8s 自动淡出触发器与底部流光条渲染）
        self._hold_anim = QVariantAnimation(self)
        self._hold_anim.setDuration(1800)
        self._hold_anim.setStartValue(1.0)
        self._hold_anim.setEndValue(0.0)
        self._hold_anim.valueChanged.connect(self._on_hold_step)
        self._hold_anim.finished.connect(self._on_hold_finished)

    @property
    def title(self) -> str:
        return self._title

    def _compute_ideal_width(self, title: str, subtitle: str) -> float:
        from PySide6.QtGui import QFontMetrics
        fm_t = QFontMetrics(QFont("Microsoft YaHei", 9, QFont.DemiBold))
        fm_s = QFontMetrics(QFont("Microsoft YaHei", 9))
        tw = fm_t.horizontalAdvance(title)
        sw = fm_s.horizontalAdvance(subtitle)
        return float(max(440, min(708, 36 + tw + 14 + sw + 28)))

    def show_toast(self, title: str, subtitle: str, accent_rgb: Tuple[int, int, int] = (59, 130, 246)):
        already_showing = self.isVisible() and self._enter_progress > 0.15

        if already_showing and self._title:
            self._prev_title = self._title
            self._prev_subtitle = self._subtitle
            self._prev_rgb = self._accent_rgb
            self._prev_pill_w = self._cur_pill_w
        else:
            self._prev_title = ""
            self._prev_subtitle = ""
            self._prev_rgb = accent_rgb

        self._title = title
        self._subtitle = subtitle
        self._accent_rgb = accent_rgb
        self._target_pill_w = self._compute_ideal_width(title, subtitle)
        if not already_showing:
            self._prev_pill_w = self._target_pill_w
            self._cur_pill_w = self._target_pill_w

        self._reposition()
        self.setVisible(True)
        self.raise_()

        # 1. 确保进场状态为 1.0
        self._enter_anim.stop()
        if self._enter_progress < 0.99:
            self._enter_anim.setDuration(200)
            self._enter_anim.setStartValue(max(0.15, self._enter_progress))
            self._enter_anim.setEndValue(1.0)
            self._enter_anim.start()
        else:
            self._enter_progress = 1.0

        # 2. 每次调用必从 0.0 -> 1.0 重新触发滚轮翻页、波纹扩散与弹性微跳
        self._switch_anim.stop()
        self._switch_progress = 0.0
        self._switch_anim.setStartValue(0.0)
        self._switch_anim.setEndValue(1.0)
        self._switch_anim.start()

        # 3. 重置底部停留流光倒计时
        self._hold_anim.stop()
        self._timer_progress = 1.0
        self._hold_anim.start()

        self.update()

    def _on_enter_step(self, val):
        self._enter_progress = float(val)
        self._reposition()
        self.update()

    def _on_enter_finished(self):
        if self._enter_progress <= 0.02:
            self.setVisible(False)
            self._title = ""

    def _on_switch_step(self, val):
        self._switch_progress = float(val)
        self._cur_pill_w = self._prev_pill_w + (self._target_pill_w - self._prev_pill_w) * self._switch_progress
        self.update()

    def _on_hold_step(self, val):
        self._timer_progress = float(val)
        self.update()

    def _on_hold_finished(self):
        if self._timer_progress <= 0.02:
            self._enter_anim.stop()
            self._enter_anim.setDuration(260)
            self._enter_anim.setStartValue(self._enter_progress)
            self._enter_anim.setEndValue(0.0)
            self._enter_anim.start()

    def _reposition(self):
        if not self.parentWidget():
            return
        pw = self.parentWidget().width()
        x = (pw - self.width()) // 2
        y = int(42 + 12 * self._enter_progress)
        self.move(x, y)

    def _draw_row_content(self, p: QPainter, pill_x: float, pill_y: float, pill_w: float, pill_h: float, title: str, subtitle: str):
        p.setFont(QFont("Microsoft YaHei", 9, QFont.DemiBold))
        p.setPen(QColor("#f4f4f5"))
        fm_title = p.fontMetrics()
        tw = fm_title.horizontalAdvance(title)
        tx = pill_x + 32.0
        p.drawText(QRectF(tx, pill_y, tw + 6, pill_h), Qt.AlignLeft | Qt.AlignVCenter, title)

        p.setFont(QFont("Microsoft YaHei", 9))
        p.setPen(QColor("#a1a1aa"))
        sub_x = tx + tw + 10.0
        sub_w = max(40.0, (pill_x + pill_w) - sub_x - 16.0)
        elided_sub = p.fontMetrics().elidedText(subtitle, Qt.ElideRight, int(sub_w))
        p.drawText(QRectF(sub_x, pill_y, sub_w, pill_h), Qt.AlignLeft | Qt.AlignVCenter, elided_sub)

    def paintEvent(self, event):
        if self._enter_progress <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setOpacity(self._enter_progress)

        s = self._switch_progress
        pr, pg, pb = self._prev_rgb
        tr, tg, tb = self._accent_rgb
        r = int(pr + (tr - pr) * s)
        g = int(pg + (tg - pg) * s)
        b = int(pb + (tb - pb) * s)

        # 连续切换时的弹性微跳偏移 (0 -> -4.5px -> 0)
        bounce_dy = -4.5 * math.sin(s * math.pi) if self._prev_title else 0.0
        pill_w = self._cur_pill_w
        pill_h = 38.0
        pill_x = (self.width() - pill_w) / 2.0
        pill_y = 5.0 + bounce_dy
        rect = QRectF(pill_x, pill_y, pill_w, pill_h)

        # 胶囊底色与切换高光边框
        p.setBrush(QColor(39, 39, 42, 246))
        pulse_boost = int(115 * (1.0 - s))
        p.setPen(QPen(QColor(r, g, b, min(255, 140 + pulse_boost)), 1.3 if s < 0.6 else 1.0))
        p.drawRoundedRect(rect, 19.0, 19.0)

        # 左侧状态圆点与声呐扩散波纹
        dot_center = QPointF(pill_x + 18.0, pill_y + pill_h / 2.0)
        if s < 0.95:
            ripple_r = 4.0 + 10.5 * s
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(r, g, b, int(190 * (1.0 - s))), 1.4))
            p.drawEllipse(dot_center, ripple_r, ripple_r)

        p.setBrush(QColor(r, g, b))
        p.setPen(Qt.NoPen)
        p.drawEllipse(dot_center, 4.2, 4.2)

        # 裁剪胶囊内部进行新旧文案垂直滚轮交替 (Slot-Roll)
        p.save()
        p.setClipRect(rect.adjusted(28.0, 2.0, -12.0, -3.0))

        if self._prev_title and s < 0.98:
            p.setOpacity(self._enter_progress * max(0.0, (1.0 - s) ** 1.5))
            self._draw_row_content(
                p, pill_x, pill_y - 16.0 * s, pill_w, pill_h,
                self._prev_title, self._prev_subtitle
            )

        p.setOpacity(self._enter_progress * max(0.08, s))
        in_dy = (1.0 - s) * 16.0 if self._prev_title else (1.0 - s) * 8.0
        self._draw_row_content(
            p, pill_x, pill_y + in_dy, pill_w, pill_h,
            self._title, self._subtitle
        )
        p.restore()

        # 胶囊底部极细倒计时流光进度线
        if self._timer_progress > 0.02:
            bar_max_w = pill_w - 38.0
            bar_w = bar_max_w * self._timer_progress
            bar_x = pill_x + 19.0
            bar_y = pill_y + pill_h - 2.2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(r, g, b, 150))
            p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, 1.6), 0.8, 0.8)

        p.end()


# ==================== 5. 阶段 2：审阅与决断态核心组件 ====================

class GroupDrawerItemWidget(QWidget):
    """
    左侧 260px 分组导航抽屉列表项：
    展示：双图微型缩略图卡片 (56×32px) + 组号 + 相似度百分比 (如 99.4%) + 差异状态标签
    """

    def __init__(self, group: MatchGroup, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        active = group.active_items
        items_src = active if len(active) >= 2 else group.items
        p_a = items_src[0].filepath if len(items_src) >= 1 else ""
        p_b = items_src[1].filepath if len(items_src) >= 2 else p_a

        # 双图微型缩略图
        lbl_thumb = QLabel()
        lbl_thumb.setFixedSize(56, 32)
        lbl_thumb.setPixmap(make_dual_thumbnail_pixmap(p_a, p_b, 56, 32))
        lbl_thumb.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(lbl_thumb)

        # 右侧两行文字区
        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(2)

        row_top = QHBoxLayout()
        row_top.setContentsMargins(0, 0, 0, 0)
        row_top.setSpacing(6)

        lbl_id = QLabel(f"第 {group.group_id:02d} 组")
        lbl_id.setStyleSheet("color: #f4f4f5; font-size: 12px; font-weight: 600; background: transparent; border: none;")
        row_top.addWidget(lbl_id)

        row_top.addStretch(1)

        # 相似度百分比
        sim_color = "#10b981" if group.similarity_pct >= 99.0 else "#a1a1aa"
        lbl_sim = QLabel(group.similarity_str)
        lbl_sim.setStyleSheet(
            f"color: {sim_color}; font-size: 11px; font-weight: 600; background: transparent; border: none;"
        )
        row_top.addWidget(lbl_sim)
        info_col.addLayout(row_top)

        # 第二行：差异状态标签
        row_bot = QHBoxLayout()
        row_bot.setContentsMargins(0, 0, 0, 0)
        row_bot.setSpacing(6)

        if group.whitelisted:
            tag_text = "白名单保留"
            tag_css = "color: #60a5fa; font-size: 11px; background: transparent; border: none;"
        elif len(active) <= 1:
            tag_text = "已决断"
            tag_css = "color: #10b981; font-size: 11px; background: transparent; border: none;"
        else:
            short_type = "完全相同" if "MD5" in group.match_type else (
                "像素同款" if "像素" in group.match_type else "局部变体"
            )
            tag_text = f"{short_type} · {len(active)}张"
            tag_css = "color: #71717a; font-size: 11px; background: transparent; border: none;"

        lbl_tag = QLabel(tag_text)
        lbl_tag.setStyleSheet(tag_css)
        row_bot.addWidget(lbl_tag)
        row_bot.addStretch(1)
        info_col.addLayout(row_bot)

        layout.addLayout(info_col, stretch=1)


class SyncZoomImageView(QGraphicsView):
    """像素级联动缩放与平移视口"""
    viewChanged = Signal(float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = QGraphicsPixmapItem()
        self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self._pixmap_item)

        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background-color: #18181b; border-radius: 6px;")
        self.setAcceptDrops(False)

        self._zoom_level = 1.0
        self._is_syncing = False
        self._has_image = False

        self.horizontalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

    def set_pixmap(self, pixmap: QPixmap):
        self._scene.clear()
        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self._pixmap_item)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._has_image = not pixmap.isNull()
        self.reset_view()

    def reset_view(self):
        if not self._has_image:
            return
        self.resetTransform()
        self._zoom_level = 1.0
        rect = self._scene.sceneRect()
        if not rect.isEmpty():
            self.fitInView(rect, Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._zoom_level == 1.0 and self._has_image:
            self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def _find_parent_scroll_area(self) -> Optional[QScrollArea]:
        w = self.parentWidget()
        while w:
            if isinstance(w, QScrollArea):
                return w
            w = w.parentWidget()
        return None

    def wheelEvent(self, event: QWheelEvent):
        if not self._has_image:
            event.ignore()
            return

        is_ctrl = bool(event.modifiers() & Qt.ControlModifier)
        if not is_ctrl and self._zoom_level <= 1.001:
            parent_scroll = self._find_parent_scroll_area()
            if parent_scroll and parent_scroll.verticalScrollBar().maximum() > 0:
                event.ignore()
                return

        angle = event.angleDelta().y()
        if angle == 0:
            event.ignore()
            return
        factor = 1.22 if angle > 0 else 1 / 1.22
        new_zoom = self._zoom_level * factor
        if new_zoom < 0.95:
            self.reset_view()
            self._emit_sync()
            event.accept()
            return
        if new_zoom > 20.0:
            event.accept()
            return
        self._zoom_level = new_zoom
        self.scale(factor, factor)
        self._emit_sync()
        event.accept()

    def _on_scroll_changed(self):
        if not self._is_syncing and self._has_image:
            self._emit_sync()

    def _emit_sync(self):
        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()
        h_range = max(1, hbar.maximum() - hbar.minimum())
        v_range = max(1, vbar.maximum() - vbar.minimum())
        h_ratio = (hbar.value() - hbar.minimum()) / h_range
        v_ratio = (vbar.value() - vbar.minimum()) / v_range
        self.viewChanged.emit(self._zoom_level, h_ratio, v_ratio)

    def sync_from_other(self, zoom_level: float, h_ratio: float, v_ratio: float):
        if not self._has_image:
            return
        self._is_syncing = True
        try:
            self.resetTransform()
            rect = self._scene.sceneRect()
            if not rect.isEmpty():
                self.fitInView(rect, Qt.KeepAspectRatio)
            if zoom_level > 1.001:
                self.scale(zoom_level, zoom_level)
            self._zoom_level = zoom_level

            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            h_range = hbar.maximum() - hbar.minimum()
            v_range = vbar.maximum() - vbar.minimum()
            hbar.setValue(int(hbar.minimum() + h_ratio * h_range))
            vbar.setValue(int(vbar.minimum() + v_ratio * v_range))
        finally:
            self._is_syncing = False


class CurtainCompareWidget(QWidget):
    """
    滑动卷帘对比组件 (Split Curtain Comparison)：
    支持鼠标左右拖动分割线，在同一视口原位比对图 A (左) 与图 B (右) 的细节差异。
    """

    def __init__(self, pix_a: QPixmap, pix_b: QPixmap, label_a: str, label_b: str, parent=None):
        super().__init__(parent)
        self.pix_a = pix_a
        self.pix_b = pix_b
        self.label_a = label_a
        self.label_b = label_b
        self.split_ratio = 0.5
        self._dragging = False
        self.setCursor(Qt.SplitHCursor)
        self.setMinimumSize(400, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._update_ratio(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            self._update_ratio(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False

    def _update_ratio(self, x: float):
        w = max(1, self.width())
        self.split_ratio = max(0.02, min(0.98, x / w))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        rect = self.rect()
        p.fillRect(rect, QColor("#18181b"))

        if self.pix_a.isNull() or self.pix_b.isNull():
            p.end()
            return

        # 计算居中保持宽高比的目标绘制区域
        img_w = self.pix_a.width()
        img_h = self.pix_a.height()
        scale = min((rect.width() - 24) / max(1, img_w), (rect.height() - 24) / max(1, img_h))
        draw_w = int(img_w * scale)
        draw_h = int(img_h * scale)
        ox = (rect.width() - draw_w) // 2
        oy = (rect.height() - draw_h) // 2
        target_rect = QRectF(ox, oy, draw_w, draw_h)

        split_x = int(rect.width() * self.split_ratio)

        # 绘制右底层：图 B
        p.drawPixmap(target_rect.toRect(), self.pix_b)

        # 裁剪左半区绘制：图 A
        p.save()
        p.setClipRect(QRectF(0, 0, split_x, rect.height()))
        p.drawPixmap(target_rect.toRect(), self.pix_a)
        p.restore()

        # 绘制垂直分割线与手柄
        p.setPen(QPen(QColor("#2563eb"), 1.5))
        p.drawLine(split_x, oy, split_x, oy + draw_h)

        handle_rect = QRectF(split_x - 14, rect.height() / 2 - 14, 28, 28)
        p.setBrush(QBrush(QColor("#27272a")))
        p.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
        p.drawEllipse(handle_rect)

        p.setPen(QColor("#f4f4f5"))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(handle_rect, Qt.AlignCenter, "‹ ›")

        # 左右角标
        p.setFont(QFont("Microsoft YaHei", 9))
        p.setPen(QColor("#a1a1aa"))
        p.drawText(ox + 10, oy + 22, f"A: {self.label_a}")
        p.drawText(ox + draw_w - 180, oy + 22, f"B: {self.label_b}")

        p.end()


class ViewportUnit(QFrame):
    """
    中央双视口单侧单元：
    顶部轻量状态栏 + 联动缩放视口 + 底部克制微亮决策按钮（[保留 (1)] / [删除]）
    """
    keepRequested = Signal(object)
    deleteRequested = Signal(object)
    locateRequested = Signal(object)
    candidateSelected = Signal(int)

    def __init__(
        self,
        index_in_group: int,
        item: ImageItem,
        is_recommended: bool,
        parent=None,
        candidates: Optional[List[Tuple[int, ImageItem]]] = None,
        current_candidate_idx: int = -1,
        display_key_num: int = -1
    ):
        super().__init__(parent)
        self.index_in_group = index_in_group
        self.item = item
        self.is_recommended = is_recommended
        self.candidates = candidates or []
        self.current_candidate_idx = current_candidate_idx
        self.display_key_num = display_key_num
        self.setObjectName("ViewportUnit")
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("""
            QFrame#ViewportUnit {
                background-color: #202023;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        # 顶部标识栏
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(8)

        side_code = chr(ord("A") + self.index_in_group)
        role_title = f"原始图 ({side_code})" if self.index_in_group == 0 else f"对比图 ({side_code})"
        lbl_role = QLabel(role_title)
        lbl_role.setStyleSheet("color: #e4e4e7; font-size: 12px; font-weight: 600; border: none;")
        hdr.addWidget(lbl_role)

        lbl_folder = QLabel(self.item.folder_tag)
        lbl_folder.setStyleSheet(
            "background-color: #27272a; color: #a1a1aa; font-size: 11px; "
            "padding: 2px 6px; border-radius: 4px; border: none;"
        )
        hdr.addWidget(lbl_folder)

        if self.is_recommended and not self.item.deleted:
            lbl_rec = QLabel("智能推荐保留")
            lbl_rec.setStyleSheet(
                "background-color: rgba(16, 185, 129, 0.12); color: #10b981; "
                "border: 1px solid rgba(16, 185, 129, 0.30); font-size: 11px; "
                "padding: 1px 6px; border-radius: 4px;"
            )
            hdr.addWidget(lbl_rec)

        # 多候选图切换胶囊按钮组
        if self.candidates and len(self.candidates) > 1:
            lbl_cand_tip = QLabel("切换副本:")
            lbl_cand_tip.setStyleSheet("color: #71717a; font-size: 11px; margin-left: 2px; border: none;")
            hdr.addWidget(lbl_cand_tip)
            for c_idx, c_item in self.candidates:
                c_code = chr(ord("A") + c_idx)
                btn_c = QPushButton(f"图 {c_code}")
                btn_c.setFixedHeight(22)
                btn_c.setCursor(Qt.PointingHandCursor)
                btn_c.setToolTip(f"切换对比图 ({c_code}): {c_item.filename} [{c_item.folder_tag}]")
                if c_idx == self.current_candidate_idx:
                    btn_c.setStyleSheet("""
                        QPushButton {
                            background-color: #2563eb;
                            color: #ffffff;
                            font-size: 11px;
                            font-weight: 600;
                            padding: 0 8px;
                            border: 1px solid #3b82f6;
                            border-radius: 4px;
                        }
                    """)
                else:
                    btn_c.setStyleSheet("""
                        QPushButton {
                            background-color: #27272a;
                            color: #a1a1aa;
                            font-size: 11px;
                            font-weight: 500;
                            padding: 0 8px;
                            border: 1px solid rgba(255, 255, 255, 0.08);
                            border-radius: 4px;
                        }
                        QPushButton:hover {
                            background-color: #3f3f46;
                            color: #f4f4f5;
                        }
                    """)
                btn_c.clicked.connect(lambda _, ci=c_idx: self.candidateSelected.emit(ci))
                hdr.addWidget(btn_c)

        hdr.addStretch(1)

        btn_loc = QPushButton()
        btn_loc.setIcon(LucideIcon.icon("folder", 14, "#71717a"))
        btn_loc.setFixedSize(24, 24)
        btn_loc.setCursor(Qt.PointingHandCursor)
        btn_loc.setToolTip(f"在资源管理器中定位：{self.item.filepath}")
        btn_loc.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #27272a;
                border-color: rgba(255, 255, 255, 0.08);
            }
        """)
        btn_loc.clicked.connect(lambda: self.locateRequested.emit(self.item))
        hdr.addWidget(btn_loc)

        layout.addLayout(hdr)

        # 中央视口画布
        self.canvas = SyncZoomImageView(self)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        if os.path.exists(self.item.filepath) and not self.item.deleted:
            self.canvas.set_pixmap(load_qpixmap_safe(self.item.filepath))
        else:
            ph = QPixmap(400, 400)
            ph.fill(QColor("#18181b"))
            p = QPainter(ph)
            p.setPen(QColor("#71717a"))
            p.setFont(QFont("Microsoft YaHei", 12))
            p.drawText(ph.rect(), Qt.AlignCenter, "已移至回收暂存区 (Ctrl+Z 撤销)")
            p.end()
            self.canvas.set_pixmap(ph)

        layout.addWidget(self.canvas, stretch=1)

        # 底部决策按钮栏 (克制微点亮设计，禁止大面积刺眼填充)
        act_row = QHBoxLayout()
        act_row.setContentsMargins(0, 2, 0, 0)
        act_row.setSpacing(8)

        key_num = self.display_key_num if self.display_key_num > 0 else (self.index_in_group + 1)
        self.btn_keep = QPushButton(f" 保留 ({key_num})")
        self.btn_keep.setIcon(LucideIcon.icon("check", 14, "#10b981" if self.is_recommended else "#a1a1aa"))
        self.btn_keep.setFixedHeight(34)
        self.btn_keep.setCursor(Qt.PointingHandCursor)
        self.btn_keep.setToolTip(f"保留此图并自动移除同组其余重复项 (快捷键 {key_num})")

        if self.is_recommended:
            self.btn_keep.setStyleSheet("""
                QPushButton {
                    background-color: rgba(16, 185, 129, 0.12);
                    color: #10b981;
                    border: 1px solid rgba(16, 185, 129, 0.35);
                    border-radius: 6px;
                    font-size: 12px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: rgba(16, 185, 129, 0.22);
                    border-color: #10b981;
                }
                QPushButton:disabled {
                    background-color: #18181b;
                    color: #52525b;
                    border-color: rgba(255, 255, 255, 0.05);
                }
            """)
        else:
            self.btn_keep.setStyleSheet("""
                QPushButton {
                    background-color: #27272a;
                    color: #d4d4d8;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 6px;
                    font-size: 12px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: rgba(16, 185, 129, 0.14);
                    color: #10b981;
                    border-color: rgba(16, 185, 129, 0.35);
                }
                QPushButton:disabled {
                    background-color: #18181b;
                    color: #52525b;
                    border-color: rgba(255, 255, 255, 0.05);
                }
            """)
        self.btn_keep.clicked.connect(lambda: self.keepRequested.emit(self.item))
        act_row.addWidget(self.btn_keep, stretch=2)

        self.btn_del = QPushButton(" 删除此图")
        self.btn_del.setIcon(LucideIcon.icon("trash", 14, "#ef4444"))
        self.btn_del.setFixedHeight(34)
        self.btn_del.setCursor(Qt.PointingHandCursor)
        self.btn_del.setToolTip("仅移除此张图片 (软删除至暂存区，可按 Ctrl+Z 撤销)")
        self.btn_del.setStyleSheet("""
            QPushButton {
                background-color: rgba(239, 68, 68, 0.10);
                color: #ef4444;
                border: 1px solid rgba(239, 68, 68, 0.28);
                border-radius: 6px;
                font-size: 12px;
                font-weight: 500;
                padding: 0 12px;
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 0.20);
                border-color: #ef4444;
            }
            QPushButton:disabled {
                background-color: #18181b;
                color: #52525b;
                border-color: rgba(255, 255, 255, 0.05);
            }
        """)
        self.btn_del.clicked.connect(lambda: self.deleteRequested.emit(self.item))
        act_row.addWidget(self.btn_del, stretch=1)

        if self.item.deleted or not os.path.exists(self.item.filepath):
            self.btn_keep.setEnabled(False)
            self.btn_del.setEnabled(False)
            self.btn_del.setText("已移除")

        layout.addLayout(act_row)


class AttributeInspectorPanel(QFrame):
    """
    右侧 240px 属性差异检视面板 (支持折叠)：
    垂直对比两张图的文件名、分辨率、体积、格式与修改时间，自动高亮差异属性。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(240)
        self.setObjectName("InspectorPanel")
        self.setStyleSheet("""
            QFrame#InspectorPanel {
                background-color: #202023;
                border-left: 1px solid rgba(255, 255, 255, 0.08);
            }
        """)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(16, 16, 16, 16)
        self.main_layout.setSpacing(12)

        lbl_hdr = QLabel("属性差异检视")
        lbl_hdr.setStyleSheet("color: #f4f4f5; font-size: 13px; font-weight: 600; border: none;")
        self.main_layout.addWidget(lbl_hdr)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)
        self.main_layout.addWidget(self.content_widget)
        self.main_layout.addStretch(1)

    def update_group(self, group: Optional[MatchGroup], item_a: Optional[ImageItem] = None, item_b: Optional[ImageItem] = None):
        while self.content_layout.count():
            child = self.content_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not group or not group.items:
            return

        active = group.active_items
        items = active if len(active) >= 2 else group.items
        if len(items) < 2 and item_b is None:
            return

        a = item_a if item_a is not None else items[0]
        b = item_b if item_b is not None else (items[1] if len(items) > 1 else items[0])

        code_a = chr(ord("A") + group.items.index(a)) if a in group.items else "A"
        code_b = chr(ord("A") + group.items.index(b)) if b in group.items else "B"

        # 1. 智能预选判别结论卡片
        verdict_box = QFrame()
        verdict_box.setStyleSheet("""
            QFrame {
                background-color: #18181b;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
            }
        """)
        v_layout = QVBoxLayout(verdict_box)
        v_layout.setContentsMargins(10, 8, 10, 8)
        v_layout.setSpacing(4)

        lbl_v_title = QLabel(f"相似度 {group.similarity_str} · {group.match_type}")
        lbl_v_title.setStyleSheet("color: #e4e4e7; font-size: 11px; font-weight: 600; border: none;")
        v_layout.addWidget(lbl_v_title)

        if a.pixel_count > b.pixel_count:
            reason = f"系统预选保留 图 {code_a}（分辨率更高）"
        elif b.pixel_count > a.pixel_count:
            reason = f"系统预选保留 图 {code_b}（分辨率更高）"
        elif a.filesize > b.filesize:
            reason = f"系统预选保留 图 {code_a}（文件体积更大）"
        elif b.filesize > a.filesize:
            reason = f"系统预选保留 图 {code_b}（文件体积更大）"
        else:
            reason = f"两图规格一致，推荐保留 图 {code_a}"

        lbl_v_sub = QLabel(reason)
        lbl_v_sub.setWordWrap(True)
        lbl_v_sub.setStyleSheet("color: #10b981; font-size: 11px; border: none;")
        v_layout.addWidget(lbl_v_sub)

        # 多图提示
        if len(group.items) > 2:
            tip_multi = QLabel(f"本组包含 {len(group.items)} 张同款图片\n可在顶部切换对比或按 Delete 一键清理其余副本")
            tip_multi.setWordWrap(True)
            tip_multi.setStyleSheet("color: #60a5fa; font-size: 11px; border: none; padding-top: 4px;")
            v_layout.addWidget(tip_multi)

        self.content_layout.addWidget(verdict_box)

        # 2. 逐项属性垂直对比（自动高亮不一致项）
        ext_a = os.path.splitext(a.filename)[1].upper().lstrip(".") or "IMG"
        ext_b = os.path.splitext(b.filename)[1].upper().lstrip(".") or "IMG"
        mtime_a = datetime.datetime.fromtimestamp(a.mtime).strftime("%Y-%m-%d %H:%M") if a.mtime else "-"
        mtime_b = datetime.datetime.fromtimestamp(b.mtime).strftime("%Y-%m-%d %H:%M") if b.mtime else "-"

        rows_spec = [
            ("文件名", a.filename, b.filename, "neutral"),
            ("分辨率", a.resolution_str, b.resolution_str, "res"),
            ("文件体积", a.size_str, b.size_str, "size"),
            ("文件格式", ext_a, ext_b, "diff_warn" if ext_a != ext_b else "same"),
            ("修改时间", mtime_a, mtime_b, "neutral"),
        ]

        for attr_name, val_a, val_b, mode in rows_spec:
            block = QFrame()
            block.setStyleSheet("""
                QFrame {
                    background-color: #18181b;
                    border: 1px solid rgba(255, 255, 255, 0.06);
                    border-radius: 6px;
                }
            """)
            b_lay = QVBoxLayout(block)
            b_lay.setContentsMargins(10, 8, 10, 8)
            b_lay.setSpacing(4)

            is_diff = (val_a != val_b)
            hdr_row = QHBoxLayout()
            hdr_row.setContentsMargins(0, 0, 0, 0)
            lbl_k = QLabel(attr_name)
            lbl_k.setStyleSheet("color: #71717a; font-size: 11px; border: none;")
            hdr_row.addWidget(lbl_k)
            hdr_row.addStretch(1)

            if is_diff and mode in ("res", "size", "diff_warn"):
                lbl_badge = QLabel("存在差异")
                lbl_badge.setStyleSheet("color: #f59e0b; font-size: 10px; border: none;")
                hdr_row.addWidget(lbl_badge)
            b_lay.addLayout(hdr_row)

            # 计算 A / B 属性颜色
            col_a, col_b = "#d4d4d8", "#d4d4d8"
            if mode == "res" and a.pixel_count != b.pixel_count:
                col_a = "#10b981" if a.pixel_count > b.pixel_count else "#f59e0b"
                col_b = "#10b981" if b.pixel_count > a.pixel_count else "#f59e0b"
            elif mode == "size" and a.filesize != b.filesize:
                col_a = "#10b981" if a.filesize > b.filesize else "#f59e0b"
                col_b = "#10b981" if b.filesize > a.filesize else "#f59e0b"
            elif mode == "diff_warn" and is_diff:
                col_a, col_b = "#f59e0b", "#f59e0b"

            lbl_va = QLabel(f"{code_a}: {val_a}")
            lbl_va.setWordWrap(True)
            lbl_va.setStyleSheet(f"color: {col_a}; font-size: 11px; font-weight: 500; border: none;")
            b_lay.addWidget(lbl_va)

            lbl_vb = QLabel(f"{code_b}: {val_b}")
            lbl_vb.setWordWrap(True)
            lbl_vb.setStyleSheet(f"color: {col_b}; font-size: 11px; font-weight: 500; border: none;")
            b_lay.addWidget(lbl_vb)

            self.content_layout.addWidget(block)


class ScanWorker(QThread):
    """后台扫描工作线程"""
    progressUpdated = Signal(int, int, str)
    scanFinished = Signal(list, dict)
    scanFailed = Signal(str)

    def __init__(
        self,
        engine: DedupEngine,
        folder1: str,
        folder2: Optional[str],
        sensitivity: str,
        is_recheck: bool,
        include_subfolders: bool = False
    ):
        super().__init__()
        self.engine = engine
        self.folder1 = folder1
        self.folder2 = folder2
        self.sensitivity = sensitivity
        self.is_recheck = is_recheck
        self.include_subfolders = include_subfolders

    def run(self):
        try:
            groups, stats = self.engine.run_scan(
                folder1=self.folder1,
                folder2=self.folder2,
                sensitivity=self.sensitivity,
                is_recheck=self.is_recheck,
                progress_cb=lambda cur, tot, msg: self.progressUpdated.emit(cur, tot, msg),
                include_subfolders=self.include_subfolders
            )
            self.scanFinished.emit(groups, stats)
        except Exception as e:
            self.scanFailed.emit(str(e))


class ExportWorker(QThread):
    """后台异步分类导出工作线程（严禁主线程同步批量 IO 拷贝导致界面假死）"""
    exportFinished = Signal(int, int, str)
    exportFailed = Signal(str)

    def __init__(self, engine: DedupEngine, groups: List[MatchGroup], final_dest: str, is_cross: bool):
        super().__init__()
        self.engine = engine
        self.groups = groups
        self.final_dest = final_dest
        self.is_cross = is_cross

    def run(self):
        try:
            g_cnt, f_cnt, out_path = self.engine.export_groups_to_folder(
                self.groups, self.final_dest, is_cross=self.is_cross
            )
            self.exportFinished.emit(g_cnt, f_cnt, out_path)
        except Exception as e:
            self.exportFailed.emit(str(e))


# ==================== 6. 主窗口：双阶段解耦生产力工作台 ====================

class DedupMainWindow(QMainWindow):
    PHASE_IMPORT = 0
    PHASE_REVIEW = 1

    def __init__(self, paths: Optional[AppPaths] = None):
        super().__init__()
        self.paths = paths or AppPaths()
        self.logger = setup_rotating_logger(self.paths)
        self.license_mgr = AsymmetricLicenseManager(self.paths, self.logger)
        self.engine = DedupEngine(self.paths)
        self.export_worker: Optional[ExportWorker] = None
        self.groups: List[MatchGroup] = []
        self.filtered_groups: List[MatchGroup] = []
        self.current_group: Optional[MatchGroup] = None
        self.current_units: List[ViewportUnit] = []
        self.current_candidate_idx: int = 1
        self.worker: Optional[ScanWorker] = None

        self._folder1_path: str = ""
        self._folder2_path: str = ""
        self._sensitivity: str = "standard"
        self._include_subfolders: bool = False  # 默认不包含子文件夹扫描，用户可按需开启
        self._sync_zoom_enabled: bool = True
        self._view_mode: str = "dual"  # "dual" | "heatmap" | "curtain"

        self.setWindowTitle(f"图像智能查重工作台 v{APP_VERSION}")
        self.resize(1480, 900)
        self.setMinimumSize(1160, 720)
        self.setAcceptDrops(True)

        self._apply_studio_dark_theme()
        self._init_ui()
        self._bind_shortcuts()
        self._switch_phase(self.PHASE_IMPORT)

    def _apply_studio_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #18181b;
                color: #e4e4e7;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QPushButton, QToolButton, QComboBox {
                outline: none;
            }
            QComboBox {
                background-color: #18181b;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 4px 10px;
                color: #d4d4d8;
                font-size: 12px;
            }
            QComboBox:hover {
                border-color: rgba(255, 255, 255, 0.16);
            }
            QComboBox QAbstractItemView {
                background-color: #202023;
                color: #e4e4e7;
                border: 1px solid rgba(255, 255, 255, 0.08);
                selection-background-color: #2563eb;
            }
            QLineEdit {
                background-color: #18181b;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 4px 8px;
                color: #e4e4e7;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #2563eb;
            }
            QListWidget {
                background-color: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background-color: #18181b;
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 6px;
                margin-bottom: 6px;
            }
            QListWidget::item:hover {
                background-color: #242428;
                border-color: rgba(255, 255, 255, 0.12);
            }
            QListWidget::item:selected {
                background-color: #27272a;
                border: 1px solid #2563eb;
            }
            QMenu {
                background-color: #202023;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 4px;
                color: #e4e4e7;
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 20px 6px 12px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2563eb;
                color: #ffffff;
            }
            QScrollBar:vertical {
                background-color: #18181b;
                width: 12px;
                margin: 0px;
                border-radius: 6px;
            }
            QScrollBar:horizontal {
                background-color: #18181b;
                height: 12px;
                margin: 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #52525b;
                min-height: 36px;
                border-radius: 5px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal {
                background-color: #52525b;
                min-width: 36px;
                border-radius: 5px;
                margin: 2px;
            }
            QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
                background-color: #71717a;
            }
            QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed {
                background-color: #3b82f6;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                height: 0px;
                background: none;
                border: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
            QToolTip {
                background-color: #202023;
                color: #e4e4e7;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 12px;
            }
        """)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ==================== 1. 顶部单行工具栏 (高 48px) ====================
        self.top_toolbar = QFrame()
        self.top_toolbar.setFixedHeight(48)
        self.top_toolbar.setStyleSheet("""
            QFrame#TopToolbar {
                background-color: #202023;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            }
        """)
        self.top_toolbar.setObjectName("TopToolbar")
        tb_layout = QHBoxLayout(self.top_toolbar)
        tb_layout.setContentsMargins(16, 0, 16, 0)
        tb_layout.setSpacing(12)

        # 左侧折叠按钮（仅在审阅态显示）
        self.btn_toggle_left = QPushButton()
        self.btn_toggle_left.setIcon(LucideIcon.icon("panel-left", 16, "#a1a1aa"))
        self.btn_toggle_left.setFixedSize(32, 32)
        self.btn_toggle_left.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_left.setToolTip("折叠 / 展开左侧分组导航抽屉")
        self.btn_toggle_left.setStyleSheet(self._icon_btn_css())
        self.btn_toggle_left.clicked.connect(lambda: self.left_drawer.setVisible(not self.left_drawer.isVisible()))
        tb_layout.addWidget(self.btn_toggle_left)

        # 应用标题与版本号
        lbl_title = QLabel("图像智能查重工作台")
        lbl_title.setStyleSheet("color: #f4f4f5; font-size: 14px; font-weight: 600; border: none;")
        tb_layout.addWidget(lbl_title)

        lbl_ver = QLabel(f"v{APP_VERSION}")
        lbl_ver.setStyleSheet(
            "background-color: #27272a; color: #71717a; font-size: 11px; "
            "padding: 1px 6px; border-radius: 4px; border: none;"
        )
        tb_layout.addWidget(lbl_ver)

        tb_layout.addSpacing(4)

        # 分段控制器：单文件夹查重 vs 跨文件夹交叉比对
        self.seg_mode = SegmentedControl()
        self.seg_mode.modeChanged.connect(self._on_mode_changed)
        tb_layout.addWidget(self.seg_mode)

        tb_layout.addStretch(1)

        # 中间：紧凑路径输入框（支持拖入文件夹或点击浏览）
        self.path_input_1 = CompactPathInput(slot_index=1, placeholder="选择或拖入文件夹 1")
        self.path_input_1.pathSelected.connect(self._on_folder_selected)
        self.path_input_1.multiplePathsDropped.connect(self._on_multiple_folders_dropped)
        tb_layout.addWidget(self.path_input_1)

        # 顶栏第二路径框平滑展缩抽屉 (宽 0 <-> 212px)
        self.toolbar_path2_drawer = QWidget()
        self.toolbar_path2_drawer.setFixedHeight(32)
        self.toolbar_path2_drawer.setFixedWidth(0)
        self.toolbar_path2_drawer.setVisible(False)
        tp2_layout = QHBoxLayout(self.toolbar_path2_drawer)
        tp2_layout.setContentsMargins(0, 0, 0, 0)
        tp2_layout.setSpacing(10)

        self.lbl_path_sep = QLabel("↔")
        self.lbl_path_sep.setStyleSheet("color: #3b82f6; font-size: 12px; font-weight: 600; border: none;")
        tp2_layout.addWidget(self.lbl_path_sep)

        self.path_input_2 = CompactPathInput(slot_index=2, placeholder="选择或拖入文件夹 2")
        self.path_input_2.pathSelected.connect(self._on_folder_selected)
        self.path_input_2.multiplePathsDropped.connect(self._on_multiple_folders_dropped)
        tp2_layout.addWidget(self.path_input_2)

        tb_layout.addWidget(self.toolbar_path2_drawer)

        tb_layout.addStretch(1)

        # 右侧：审阅态快速复查按钮 + 灵敏度配置下拉框 + 关于帮助 + 右侧抽屉折叠
        self.btn_recheck = QPushButton(" 极速复查")
        self.btn_recheck.setIcon(LucideIcon.icon("refresh", 14, "#ffffff"))
        self.btn_recheck.setFixedHeight(32)
        self.btn_recheck.setCursor(Qt.PointingHandCursor)
        self.btn_recheck.setToolTip("复用特征缓存与排除矩阵，1秒复查当前剩余文件是否零重复")
        self.btn_recheck.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-size: 12px;
                font-weight: 500;
                padding: 0 12px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover { background-color: #3b82f6; }
        """)
        self.btn_recheck.clicked.connect(lambda: self._start_scan(is_recheck=True))
        tb_layout.addWidget(self.btn_recheck)

        self.sens_selector = SensitivitySelector()
        self.sens_selector.sensitivityChanged.connect(self._on_sensitivity_changed)
        tb_layout.addWidget(self.sens_selector)

        # 顶栏：包含子文件夹可选开关（默认关闭：仅扫描顶层目录）
        self.btn_subfolders_tb = QPushButton(" 包含子文件夹")
        self.btn_subfolders_tb.setCheckable(True)
        self.btn_subfolders_tb.setChecked(self._include_subfolders)
        self.btn_subfolders_tb.setFixedHeight(32)
        self.btn_subfolders_tb.setCursor(Qt.PointingHandCursor)
        self.btn_subfolders_tb.clicked.connect(self._on_subfolders_toggled)
        tb_layout.addWidget(self.btn_subfolders_tb)

        # 帮助与更多菜单按钮（收纳所有辅助技巧与次要操作）
        self.btn_help = QToolButton()
        self.btn_help.setIcon(LucideIcon.icon("help", 16, "#a1a1aa"))
        self.btn_help.setFixedSize(32, 32)
        self.btn_help.setCursor(Qt.PointingHandCursor)
        self.btn_help.setPopupMode(QToolButton.InstantPopup)
        self.btn_help.setToolTip("操作指南、导出副本与缓存管理")
        self.btn_help.setStyleSheet(self._icon_btn_css() + "QToolButton::menu-indicator { image: none; }")
        self._build_help_menu()
        tb_layout.addWidget(self.btn_help)

        self.btn_toggle_right = QPushButton()
        self.btn_toggle_right.setIcon(LucideIcon.icon("panel-right", 16, "#a1a1aa"))
        self.btn_toggle_right.setFixedSize(32, 32)
        self.btn_toggle_right.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_right.setToolTip("折叠 / 展开右侧属性差异检视面板")
        self.btn_toggle_right.setStyleSheet(self._icon_btn_css())
        self.btn_toggle_right.clicked.connect(
            lambda: self.right_inspector.setVisible(not self.right_inspector.isVisible())
        )
        tb_layout.addWidget(self.btn_toggle_right)

        root_layout.addWidget(self.top_toolbar)

        # ==================== 2. 双阶段中央主容器 (QStackedWidget) ====================
        self.phase_stack = QStackedWidget()
        root_layout.addWidget(self.phase_stack, stretch=1)

        # 构建阶段 1：准备与导入态 (PHASE_IMPORT)
        self._build_phase_import()
        self._refresh_subfolder_toggle_ui()

        # 构建阶段 2：审阅与决断态三栏工作台 (PHASE_REVIEW)
        self._build_phase_review()

        # ==================== 3. 底部极简状态 Dock (高 40px) ====================
        self.bottom_dock = QFrame()
        self.bottom_dock.setFixedHeight(40)
        self.bottom_dock.setObjectName("BottomDock")
        self.bottom_dock.setStyleSheet("""
            QFrame#BottomDock {
                background-color: #202023;
                border-top: 1px solid rgba(255, 255, 255, 0.08);
            }
        """)
        dock_layout = QHBoxLayout(self.bottom_dock)
        dock_layout.setContentsMargins(16, 0, 16, 0)
        dock_layout.setSpacing(16)

        # 靠左：进度指示 (如 第 12 / 180 组)
        self.lbl_dock_progress = QLabel("就绪")
        self.lbl_dock_progress.setStyleSheet("color: #a1a1aa; font-size: 12px; border: none;")
        dock_layout.addWidget(self.lbl_dock_progress)

        self.scan_progress_bar = QProgressBar()
        self.scan_progress_bar.setFixedSize(160, 6)
        self.scan_progress_bar.setTextVisible(False)
        self.scan_progress_bar.setVisible(False)
        self.scan_progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #27272a;
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #2563eb;
                border-radius: 3px;
            }
        """)
        dock_layout.addWidget(self.scan_progress_bar)

        dock_layout.addStretch(1)

        # 靠中：居中紧凑翻页控制器 [← 上一组] [下一组 →]
        self.dock_pager = QWidget()
        pager_layout = QHBoxLayout(self.dock_pager)
        pager_layout.setContentsMargins(0, 0, 0, 0)
        pager_layout.setSpacing(8)

        self.btn_prev_grp = QPushButton(" 上一组")
        self.btn_prev_grp.setIcon(LucideIcon.icon("chevron-left", 14, "#d4d4d8"))
        self.btn_prev_grp.setFixedHeight(28)
        self.btn_prev_grp.setCursor(Qt.PointingHandCursor)
        self.btn_prev_grp.setStyleSheet(self._secondary_pill_css())
        self.btn_prev_grp.clicked.connect(self._go_prev_group)
        pager_layout.addWidget(self.btn_prev_grp)

        self.btn_next_grp = QPushButton("下一组 ")
        self.btn_next_grp.setIcon(LucideIcon.icon("chevron-right", 14, "#d4d4d8"))
        self.btn_next_grp.setLayoutDirection(Qt.RightToLeft)
        self.btn_next_grp.setFixedHeight(28)
        self.btn_next_grp.setCursor(Qt.PointingHandCursor)
        self.btn_next_grp.setStyleSheet(self._secondary_pill_css())
        self.btn_next_grp.clicked.connect(self._go_next_group)
        pager_layout.addWidget(self.btn_next_grp)

        dock_layout.addWidget(self.dock_pager)

        dock_layout.addStretch(1)

        # 靠右：极弱暗灰字体收敛常用快捷键提示
        self.lbl_dock_shortcuts = QLabel("1 保留A  |  2 保留B  |  Space 白名单  |  Delete 废弃  |  Ctrl+Z 撤销")
        self.lbl_dock_shortcuts.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_dock_shortcuts.setStyleSheet("color: #52525b; font-size: 11px; border: none;")
        dock_layout.addWidget(self.lbl_dock_shortcuts)

        root_layout.addWidget(self.bottom_dock)

        # 顶部浮动切换状态 Toast 胶囊与模式展缩动画器
        self.toast_banner = TransitionToastBanner(self)
        self._mode_progress = 0.0
        self._mode_anim = QVariantAnimation(self)
        self._mode_anim.setDuration(260)
        self._mode_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._mode_anim.valueChanged.connect(self._on_mode_anim_step)

        # 启动后 1.5 秒自动在后台检测是否有新版本可用
        self._ota_check_worker: Optional[UpdateCheckWorker] = None
        QTimer.singleShot(1500, self._start_silent_ota_check)

    def _start_silent_ota_check(self):
        cfg = self.paths.get_github_ota_config()
        if not cfg.get("github_repo") and not os.environ.get("TDPRO_UPDATE_URL"):
            return
        self._ota_check_worker = UpdateCheckWorker(self.paths)
        self._ota_check_worker.updateCheckFinished.connect(self._on_silent_ota_check_done)
        self._ota_check_worker.start()

    def _on_silent_ota_check_done(self, has_new: bool, manifest: dict, msg: str):
        if not has_new:
            return
        remote_v = str(manifest.get("version", ""))
        self.logger.info(f"New OTA version detected on startup: v{remote_v} ({msg})")
        dlg = AutoUpdateDialog(self.paths, self.logger, self, preloaded_manifest=manifest)
        dlg.exec()

    def _icon_btn_css(self) -> str:
        return """
            QPushButton, QToolButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
            }
            QPushButton:hover, QToolButton:hover {
                background-color: #27272a;
                border-color: rgba(255, 255, 255, 0.08);
            }
        """

    def _secondary_pill_css(self) -> str:
        return """
            QPushButton {
                background-color: #27272a;
                color: #d4d4d8;
                font-size: 12px;
                padding: 0 12px;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #323236;
                color: #ffffff;
            }
        """

    def _build_help_menu(self):
        menu = QMenu(self)

        act_guide = QAction("使用指南与常见问题 (白名单 / 找回已删图)... [F1]", self)
        act_guide.triggered.connect(self._show_about_dialog)
        menu.addAction(act_guide)

        act_lic = QAction("商业授权与机器码管理 (RSA-2048)...", self)
        act_lic.triggered.connect(lambda: LicenseActivationDialog(self.license_mgr, self).exec())
        menu.addAction(act_lic)

        act_upd = QAction("检查版本更新 (OTA)...", self)
        act_upd.triggered.connect(lambda: AutoUpdateDialog(self.paths, self.logger, self).exec())
        menu.addAction(act_upd)

        menu.addSeparator()

        act_export = QAction("导出分组副本至文件夹...", self)
        act_export.triggered.connect(self._export_groups)
        menu.addAction(act_export)

        act_return = QAction("返回准备与导入态视图", self)
        act_return.triggered.connect(lambda: self._switch_phase(self.PHASE_IMPORT))
        menu.addAction(act_return)

        menu.addSeparator()

        act_open_trash = QAction("打开已删除图片回收暂存区 (staging_trash)...", self)
        act_open_trash.triggered.connect(lambda: os.startfile(self.paths.trash_dir))
        menu.addAction(act_open_trash)

        act_open_logs = QAction("打开运行日志与缓存目录 (%LOCALAPPDATA%)...", self)
        act_open_logs.triggered.connect(lambda: os.startfile(self.paths.local_root))
        menu.addAction(act_open_logs)

        act_clear = QAction("清空保留白名单与特征缓存...", self)
        act_clear.triggered.connect(self._on_reset_whitelist_menu)
        menu.addAction(act_clear)

        self.btn_help.setMenu(menu)

    def _on_sensitivity_changed(self, key: str):
        self._sensitivity = key
        spec = SENSITIVITY_SPECS.get(key, SENSITIVITY_SPECS["standard"])
        self.sens_selector.set_sensitivity(key, emit_signal=False)
        self.sens_interactive_bar.set_sensitivity(key, emit_signal=False)
        self.toast_banner.show_toast(
            f"灵敏度已切换：{spec['title']}",
            spec["desc"],
            spec["accent_rgb"]
        )
        if self.phase_stack.currentIndex() == self.PHASE_REVIEW:
            self.lbl_dock_progress.setText(f"已切换至 [{spec['short']}] — 点击顶栏「极速复查」可按新灵敏度重扫")

    def _on_subfolders_toggled(self, checked: bool):
        self._include_subfolders = bool(checked)
        self._refresh_subfolder_toggle_ui()
        if self._include_subfolders:
            self.toast_banner.show_toast(
                "已开启：包含子文件夹扫描",
                "将递归扫描所选文件夹及其所有嵌套子文件夹内的全部图片",
                (59, 130, 246)
            )
        else:
            self.toast_banner.show_toast(
                "已关闭：仅扫描当前顶层文件夹（默认）",
                "仅扫描所选文件夹第一层目录内的图片，自动忽略所有子文件夹",
                (161, 161, 170)
            )
        if self.phase_stack.currentIndex() == self.PHASE_REVIEW:
            scope_str = "含子文件夹" if self._include_subfolders else "仅顶层文件夹"
            self.lbl_dock_progress.setText(f"已切换扫描范围 [{scope_str}] — 点击顶栏「极速复查」可立即重扫")

    def _refresh_subfolder_toggle_ui(self):
        checked = self._include_subfolders
        for btn in (getattr(self, "btn_subfolders_tb", None), getattr(self, "btn_subfolders_cta", None)):
            if btn is None:
                continue
            btn.blockSignals(True)
            btn.setChecked(checked)
            btn.blockSignals(False)

        if hasattr(self, "btn_subfolders_tb"):
            if checked:
                self.btn_subfolders_tb.setIcon(LucideIcon.icon("check", 14, "#60a5fa"))
                self.btn_subfolders_tb.setText(" 包含子文件夹: 开")
                self.btn_subfolders_tb.setToolTip("当前：递归扫描全部嵌套子文件夹。点击可切换为仅扫描顶层文件夹")
                self.btn_subfolders_tb.setStyleSheet("""
                    QPushButton {
                        background-color: rgba(37, 99, 235, 0.18);
                        color: #60a5fa;
                        font-size: 12px;
                        font-weight: 600;
                        padding: 0 10px;
                        border: 1px solid rgba(59, 130, 246, 0.55);
                        border-radius: 6px;
                    }
                    QPushButton:hover {
                        background-color: rgba(37, 99, 235, 0.28);
                    }
                """)
            else:
                self.btn_subfolders_tb.setIcon(LucideIcon.icon("folder-plus", 14, "#a1a1aa"))
                self.btn_subfolders_tb.setText(" 包含子文件夹")
                self.btn_subfolders_tb.setToolTip("当前：默认仅扫描当前顶层文件夹（不含子文件夹）。点击可开启子文件夹扫描")
                self.btn_subfolders_tb.setStyleSheet("""
                    QPushButton {
                        background-color: #18181b;
                        color: #a1a1aa;
                        font-size: 12px;
                        padding: 0 10px;
                        border: 1px solid rgba(255, 255, 255, 0.08);
                        border-radius: 6px;
                    }
                    QPushButton:hover {
                        background-color: #27272a;
                        color: #e4e4e7;
                        border-color: rgba(255, 255, 255, 0.16);
                    }
                """)

        if hasattr(self, "btn_subfolders_cta"):
            if checked:
                self.btn_subfolders_cta.setIcon(LucideIcon.icon("check", 15, "#60a5fa"))
                self.btn_subfolders_cta.setText(" 包含子文件夹：已开启")
                self.btn_subfolders_cta.setToolTip("当前已开启：将递归扫描所选文件夹及其全部子文件夹。点击可关闭")
                self.btn_subfolders_cta.setStyleSheet("""
                    QPushButton {
                        background-color: rgba(37, 99, 235, 0.16);
                        color: #60a5fa;
                        font-size: 13px;
                        font-weight: 600;
                        padding: 0 16px;
                        border-radius: 8px;
                        border: 1px solid rgba(59, 130, 246, 0.55);
                    }
                    QPushButton:hover {
                        background-color: rgba(37, 99, 235, 0.25);
                    }
                """)
            else:
                self.btn_subfolders_cta.setIcon(LucideIcon.icon("folder-plus", 15, "#a1a1aa"))
                self.btn_subfolders_cta.setText(" 包含子文件夹（可选）")
                self.btn_subfolders_cta.setToolTip("默认不扫描子文件夹。点击勾选后，可一并递归扫描所有子文件夹")
                self.btn_subfolders_cta.setStyleSheet("""
                    QPushButton {
                        background-color: #202023;
                        color: #a1a1aa;
                        font-size: 13px;
                        font-weight: 500;
                        padding: 0 16px;
                        border-radius: 8px;
                        border: 1px solid rgba(255, 255, 255, 0.10);
                    }
                    QPushButton:hover {
                        background-color: #27272a;
                        color: #f4f4f5;
                        border-color: rgba(255, 255, 255, 0.20);
                    }
                """)

    # ==================== 阶段 1：准备与导入态构建 ====================

    def _build_phase_import(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(0)

        layout.addStretch(1)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(0)
        cards_row.addStretch(1)

        self.drop_card_1 = StudioDropCard(
            slot_index=1,
            title="目标图像文件夹",
            subtitle="拖入文件夹或点击浏览",
            role_badge="单文件夹内部查重",
            parent=page
        )
        self.drop_card_1.folderSelected.connect(self._on_folder_selected)
        self.drop_card_1.multipleFoldersDropped.connect(self._on_multiple_folders_dropped)
        cards_row.addWidget(self.drop_card_1)

        # 跨文件夹动态展开容器（内含 64px 旋转交叉连接器 + 320px 文件夹 B 卡片，展开总宽 384px）
        self.cross_card_drawer = QWidget(page)
        self.cross_card_drawer.setFixedHeight(216)
        self.cross_card_drawer.setFixedWidth(0)
        self.cross_card_drawer.setVisible(False)
        cross_lay = QHBoxLayout(self.cross_card_drawer)
        cross_lay.setContentsMargins(0, 0, 0, 0)
        cross_lay.setSpacing(0)

        self.cross_connector = CrossConnectorBadge(self.cross_card_drawer)
        cross_lay.addWidget(self.cross_connector)

        self.drop_card_2 = StudioDropCard(
            slot_index=2,
            title="对比图像文件夹 (B)",
            subtitle="拖入文件夹或点击浏览",
            role_badge="文件夹 B · 比对源",
            parent=self.cross_card_drawer
        )
        self.drop_card_2.folderSelected.connect(self._on_folder_selected)
        self.drop_card_2.multipleFoldersDropped.connect(self._on_multiple_folders_dropped)
        cross_lay.addWidget(self.drop_card_2)

        cards_row.addWidget(self.cross_card_drawer)

        cards_row.addStretch(1)
        layout.addLayout(cards_row)

        layout.addSpacing(32)

        # 居中主行动按钮 + 包含子文件夹可选开关
        cta_row = QHBoxLayout()
        cta_row.setSpacing(12)
        cta_row.addStretch(1)

        self.btn_start_cta = QPushButton("开始智能查重")
        self.btn_start_cta.setFixedSize(220, 40)
        self.btn_start_cta.setCursor(Qt.PointingHandCursor)
        self.btn_start_cta.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-size: 14px;
                font-weight: 600;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #3b82f6;
            }
            QPushButton:pressed {
                background-color: #1d4ed8;
            }
            QPushButton:disabled {
                background-color: #27272a;
                color: #71717a;
            }
        """)
        self.btn_start_cta.clicked.connect(lambda: self._start_scan(is_recheck=False))
        cta_row.addWidget(self.btn_start_cta)

        self.btn_subfolders_cta = QPushButton(" 包含子文件夹（可选）")
        self.btn_subfolders_cta.setCheckable(True)
        self.btn_subfolders_cta.setChecked(self._include_subfolders)
        self.btn_subfolders_cta.setFixedHeight(40)
        self.btn_subfolders_cta.setCursor(Qt.PointingHandCursor)
        self.btn_subfolders_cta.clicked.connect(self._on_subfolders_toggled)
        cta_row.addWidget(self.btn_subfolders_cta)

        cta_row.addStretch(1)
        layout.addLayout(cta_row)

        layout.addSpacing(18)

        # 交互式三档灵敏度滑块与动态说明卡片（双向联动顶栏下拉框，带 280ms 上浮淡入与语义色描边呼吸）
        sens_row = QHBoxLayout()
        sens_row.addStretch(1)
        self.sens_interactive_bar = SensitivityInteractiveBar(page)
        self.sens_interactive_bar.sensitivitySelected.connect(self._on_sensitivity_changed)
        self.lbl_sens_inline = self.sens_interactive_bar
        sens_row.addWidget(self.sens_interactive_bar)
        sens_row.addStretch(1)
        layout.addLayout(sens_row)

        layout.addStretch(1)
        self.phase_stack.addWidget(page)

    # ==================== 阶段 2：审阅与决断态三栏工作台构建 ====================

    def _build_phase_review(self):
        workbench = QWidget()
        wb_layout = QHBoxLayout(workbench)
        wb_layout.setContentsMargins(0, 0, 0, 0)
        wb_layout.setSpacing(0)

        # ---- 左栏：分组导航抽屉 (宽 260px，支持折叠) ----
        self.left_drawer = QFrame()
        self.left_drawer.setFixedWidth(260)
        self.left_drawer.setObjectName("LeftDrawer")
        self.left_drawer.setStyleSheet("""
            QFrame#LeftDrawer {
                background-color: #202023;
                border-right: 1px solid rgba(255, 255, 255, 0.08);
            }
        """)
        ld_layout = QVBoxLayout(self.left_drawer)
        ld_layout.setContentsMargins(12, 12, 12, 12)
        ld_layout.setSpacing(8)

        # 快速过滤搜索框
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(6)

        self.edit_search = QLineEdit()
        self.edit_search.setFixedHeight(30)
        self.edit_search.setPlaceholderText("搜索文件名或组号...")
        self.edit_search.textChanged.connect(self._refresh_group_list)
        search_row.addWidget(self.edit_search, stretch=1)
        ld_layout.addLayout(search_row)

        # 排序与筛选同行
        sort_row = QHBoxLayout()
        sort_row.setContentsMargins(0, 0, 0, 0)
        sort_row.setSpacing(6)

        self.combo_filter = QComboBox()
        self.combo_filter.setFixedHeight(28)
        self.combo_filter.addItem("待决断", "pending")
        self.combo_filter.addItem("全部组", "all")
        self.combo_filter.addItem("已处理", "resolved")
        self.combo_filter.currentIndexChanged.connect(self._refresh_group_list)
        sort_row.addWidget(self.combo_filter, stretch=1)

        self.combo_sort = QComboBox()
        self.combo_sort.setFixedHeight(28)
        self.combo_sort.addItem("按相似度降序", "sim_desc")
        self.combo_sort.addItem("按体积差降序", "size_diff")
        self.combo_sort.addItem("按默认组号", "id_asc")
        self.combo_sort.currentIndexChanged.connect(self._refresh_group_list)
        sort_row.addWidget(self.combo_sort, stretch=1)

        ld_layout.addLayout(sort_row)

        # 垂直重复图片组列表
        self.list_groups = QListWidget()
        self.list_groups.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_groups.verticalScrollBar().setSingleStep(24)
        self.list_groups.currentRowChanged.connect(self._on_group_selected)
        ld_layout.addWidget(self.list_groups, stretch=1)

        wb_layout.addWidget(self.left_drawer)

        # ---- 中栏：双视口图像画布 (主工作区) ----
        center_stage = QWidget()
        cs_layout = QVBoxLayout(center_stage)
        cs_layout.setContentsMargins(16, 12, 16, 16)
        cs_layout.setSpacing(12)

        # 顶部浮动胶囊操作条 (#27272a, 高 36px, 圆角 18px)
        capsule_row = QHBoxLayout()
        capsule_row.setContentsMargins(0, 0, 0, 0)
        capsule_row.addStretch(1)

        self.floating_capsule = QFrame()
        self.floating_capsule.setFixedHeight(36)
        self.floating_capsule.setObjectName("FloatingCapsule")
        self.floating_capsule.setStyleSheet("""
            QFrame#FloatingCapsule {
                background-color: #27272a;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
            }
        """)
        cap_layout = QHBoxLayout(self.floating_capsule)
        cap_layout.setContentsMargins(6, 3, 6, 3)
        cap_layout.setSpacing(4)

        # [1:1 复位]
        self.btn_cap_reset = QPushButton(" 1:1 复位")
        self.btn_cap_reset.setIcon(LucideIcon.icon("maximize", 14, "#d4d4d8"))
        self.btn_cap_reset.setFixedHeight(28)
        self.btn_cap_reset.setCursor(Qt.PointingHandCursor)
        self.btn_cap_reset.clicked.connect(self._reset_all_canvas_zoom)
        cap_layout.addWidget(self.btn_cap_reset)

        # [联动缩放/平移]
        self.btn_cap_sync = QPushButton(" 联动缩放/平移")
        self.btn_cap_sync.setIcon(LucideIcon.icon("link", 14, "#ffffff"))
        self.btn_cap_sync.setFixedHeight(28)
        self.btn_cap_sync.setCheckable(True)
        self.btn_cap_sync.setChecked(True)
        self.btn_cap_sync.setCursor(Qt.PointingHandCursor)
        self.btn_cap_sync.toggled.connect(self._on_sync_toggled)
        cap_layout.addWidget(self.btn_cap_sync)

        # [像素差异热图]
        self.btn_cap_heatmap = QPushButton(" 像素差异热图")
        self.btn_cap_heatmap.setIcon(LucideIcon.icon("layers", 14, "#d4d4d8"))
        self.btn_cap_heatmap.setFixedHeight(28)
        self.btn_cap_heatmap.setCheckable(True)
        self.btn_cap_heatmap.setCursor(Qt.PointingHandCursor)
        self.btn_cap_heatmap.toggled.connect(self._on_heatmap_toggled)
        cap_layout.addWidget(self.btn_cap_heatmap)

        # [滑动卷帘对比]
        self.btn_cap_curtain = QPushButton(" 滑动卷帘对比")
        self.btn_cap_curtain.setIcon(LucideIcon.icon("columns", 14, "#d4d4d8"))
        self.btn_cap_curtain.setFixedHeight(28)
        self.btn_cap_curtain.setCheckable(True)
        self.btn_cap_curtain.setCursor(Qt.PointingHandCursor)
        self.btn_cap_curtain.toggled.connect(self._on_curtain_toggled)
        cap_layout.addWidget(self.btn_cap_curtain)

        # [网格平铺 (多图时显示，默认保持勾选平铺)]
        self.btn_cap_grid = QPushButton(" 网格平铺")
        self.btn_cap_grid.setIcon(LucideIcon.icon("grid", 14, "#ffffff"))
        self.btn_cap_grid.setFixedHeight(28)
        self.btn_cap_grid.setCheckable(True)
        self.btn_cap_grid.setChecked(True)
        self.btn_cap_grid.setCursor(Qt.PointingHandCursor)
        self.btn_cap_grid.setToolTip("组内有 3 张以上图片时默认开启 2 列网格平铺，全部副本一览无余；取消勾选可切换为 1 对 1 聚焦双视口")
        self.btn_cap_grid.toggled.connect(self._on_grid_toggled)
        self.btn_cap_grid.setVisible(False)
        cap_layout.addWidget(self.btn_cap_grid)

        # 分隔竖线
        sep = QFrame()
        sep.setFixedSize(1, 16)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 0.10); border: none;")
        cap_layout.addWidget(sep)

        # [白名单保留 (Space)]
        self.btn_cap_whitelist = QPushButton(" 白名单 (Space)")
        self.btn_cap_whitelist.setIcon(LucideIcon.icon("check", 14, "#d4d4d8"))
        self.btn_cap_whitelist.setFixedHeight(28)
        self.btn_cap_whitelist.setCursor(Qt.PointingHandCursor)
        self.btn_cap_whitelist.setToolTip("将该组标记为合规模板变体加入白名单，后续复查不再报警")
        self.btn_cap_whitelist.clicked.connect(self._whitelist_current_group)
        cap_layout.addWidget(self.btn_cap_whitelist)

        # [撤销 (Ctrl+Z)]
        self.btn_cap_undo = QPushButton(" 撤销")
        self.btn_cap_undo.setIcon(LucideIcon.icon("undo", 14, "#a1a1aa"))
        self.btn_cap_undo.setFixedHeight(28)
        self.btn_cap_undo.setEnabled(False)
        self.btn_cap_undo.setCursor(Qt.PointingHandCursor)
        self.btn_cap_undo.clicked.connect(self._undo_last_delete)
        cap_layout.addWidget(self.btn_cap_undo)

        self._refresh_capsule_styles()
        capsule_row.addWidget(self.floating_capsule)
        capsule_row.addStretch(1)
        cs_layout.addLayout(capsule_row)

        # 双视口画布承载区 (永久关闭横向滚动条，杜绝底部横向拉杆)
        self.viewport_scroll = QScrollArea()
        self.viewport_scroll.setWidgetResizable(True)
        self.viewport_scroll.setFrameShape(QFrame.NoFrame)
        self.viewport_scroll.setStyleSheet("background: transparent; border: none;")
        self.viewport_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewport_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.viewport_container = QWidget()
        self.viewport_container.setStyleSheet("background: transparent;")
        self.viewport_layout = QGridLayout(self.viewport_container)
        self.viewport_layout.setContentsMargins(0, 0, 0, 0)
        self.viewport_layout.setSpacing(12)

        self.viewport_scroll.setWidget(self.viewport_container)
        cs_layout.addWidget(self.viewport_scroll, stretch=1)

        wb_layout.addWidget(center_stage, stretch=1)

        # ---- 右栏：属性差异检视面板 (宽 240px，支持折叠) ----
        self.right_inspector = AttributeInspectorPanel()
        wb_layout.addWidget(self.right_inspector)

        self.phase_stack.addWidget(workbench)

    def _refresh_capsule_styles(self):
        idle_pill = """
            QPushButton {
                background-color: transparent;
                color: #a1a1aa;
                font-size: 12px;
                font-weight: 500;
                padding: 0 10px;
                border-radius: 14px;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.06);
                color: #f4f4f5;
            }
            QPushButton:disabled {
                color: #52525b;
            }
        """
        active_pill = """
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-size: 12px;
                font-weight: 600;
                padding: 0 10px;
                border-radius: 14px;
                border: none;
            }
        """
        self.btn_cap_reset.setStyleSheet(idle_pill)
        self.btn_cap_whitelist.setStyleSheet(idle_pill)
        self.btn_cap_undo.setStyleSheet(idle_pill)

        self.btn_cap_sync.setStyleSheet(active_pill if self.btn_cap_sync.isChecked() else idle_pill)
        self.btn_cap_sync.setIcon(LucideIcon.icon("link", 14, "#ffffff" if self.btn_cap_sync.isChecked() else "#a1a1aa"))

        self.btn_cap_heatmap.setStyleSheet(active_pill if self.btn_cap_heatmap.isChecked() else idle_pill)
        self.btn_cap_heatmap.setIcon(LucideIcon.icon("layers", 14, "#ffffff" if self.btn_cap_heatmap.isChecked() else "#a1a1aa"))

        self.btn_cap_curtain.setStyleSheet(active_pill if self.btn_cap_curtain.isChecked() else idle_pill)
        self.btn_cap_curtain.setIcon(LucideIcon.icon("columns", 14, "#ffffff" if self.btn_cap_curtain.isChecked() else "#a1a1aa"))

        self.btn_cap_grid.setStyleSheet(active_pill if self.btn_cap_grid.isChecked() else idle_pill)
        self.btn_cap_grid.setIcon(LucideIcon.icon("grid", 14, "#ffffff" if self.btn_cap_grid.isChecked() else "#a1a1aa"))

    # ==================== 阶段切换与交互逻辑 ====================

    def _switch_phase(self, phase: int):
        """严格控制阶段 1 (导入态) 与阶段 2 (审阅态) 的界面元素显隐"""
        self.phase_stack.setCurrentIndex(phase)
        is_review = (phase == self.PHASE_REVIEW)

        self.btn_toggle_left.setVisible(is_review)
        self.btn_toggle_right.setVisible(is_review)
        self.btn_recheck.setVisible(is_review)
        self.bottom_dock.setVisible(is_review)

    def _on_mode_anim_step(self, val):
        p = float(val)
        self._mode_progress = p

        # 主工作区文件夹 B 抽屉与旋转连接器 (0 <-> 384px)
        target_card_w = int(384 * p)
        self.cross_card_drawer.setFixedWidth(target_card_w)
        self.cross_connector.set_progress(p)
        if p <= 0.01 and not self.seg_mode.is_cross:
            self.cross_card_drawer.setVisible(False)
            self.drop_card_2.setVisible(False)

        # 顶栏第二路径输入框抽屉 (0 <-> 212px)
        target_tb_w = int(212 * p)
        self.toolbar_path2_drawer.setFixedWidth(target_tb_w)
        if p <= 0.01 and not self.seg_mode.is_cross:
            self.toolbar_path2_drawer.setVisible(False)

    def _on_mode_changed(self, is_cross: bool):
        if is_cross:
            self.drop_card_2.setVisible(True)
            self.cross_card_drawer.setVisible(True)
            self.toolbar_path2_drawer.setVisible(True)
            self.drop_card_2.trigger_mode_pulse(
                new_title="对比图像文件夹 (B)",
                new_badge="文件夹 B · 比对源"
            )

        self.drop_card_1.trigger_mode_pulse(
            new_title="主图像文件夹 (A)" if is_cross else "目标图像文件夹",
            new_badge="文件夹 A · 基准源" if is_cross else "单文件夹内部查重"
        )

        self._mode_anim.stop()
        self._mode_anim.setStartValue(self._mode_progress)
        self._mode_anim.setEndValue(1.0 if is_cross else 0.0)
        self._mode_anim.start()

        if is_cross:
            self.toast_banner.show_toast(
                "已切换至：跨文件夹交叉比对",
                "仅比对文件夹 A 与文件夹 B 之间的跨库重复与相似图案，忽略同目录内部相似",
                (59, 130, 246)
            )
        else:
            self.toast_banner.show_toast(
                "已切换至：单文件夹查重",
                "在单个目标文件夹内部全面排查重复、尺寸缩放及微调变体图案",
                (59, 130, 246)
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "toast_banner") and self.toast_banner.isVisible():
            self.toast_banner._reposition()

    def _on_folder_selected(self, slot_index: int, folder_path: str):
        norm = os.path.normpath(folder_path)
        if slot_index == 1:
            self._folder1_path = norm
            self.path_input_1.set_path(norm)
            self.drop_card_1.set_folder_path(norm)
        else:
            self._folder2_path = norm
            self.seg_mode.set_cross_mode(True)
            self.path_input_2.set_path(norm)
            self.drop_card_2.set_folder_path(norm)

    def _on_multiple_folders_dropped(self, folders: List[str]):
        f1 = os.path.normpath(folders[0])
        f2 = os.path.normpath(folders[1])
        self._folder1_path = f1
        self._folder2_path = f2
        self.seg_mode.set_cross_mode(True)
        self.path_input_1.set_path(f1)
        self.path_input_2.set_path(f2)
        self.drop_card_1.set_folder_path(f1)
        self.drop_card_2.set_folder_path(f2)

    # ==================== 全窗口拖拽支持 ====================

    def dragEnterEvent(self, event: QDragEnterEvent):
        if extract_folders_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if extract_folders_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        folders = extract_folders_from_mime(event.mimeData())
        if not folders:
            event.ignore()
            return
        event.acceptProposedAction()
        if len(folders) >= 2:
            self._on_multiple_folders_dropped(folders)
        else:
            if self.seg_mode.is_cross and self._folder1_path and not self._folder2_path:
                self._on_folder_selected(2, folders[0])
            else:
                self._on_folder_selected(1, folders[0])

    # ==================== 扫描与后台任务 ====================

    def _start_scan(self, is_recheck: bool = False):
        if self.worker and self.worker.isRunning():
            return

        if not self._folder1_path or not os.path.isdir(self._folder1_path):
            QMessageBox.warning(self, "提示", "请先拖入或选择有效的【文件夹 1】。")
            return

        folder2 = None
        if self.seg_mode.is_cross:
            if not self._folder2_path or not os.path.isdir(self._folder2_path):
                QMessageBox.warning(self, "提示", "跨文件夹比对模式下，请拖入或选择有效的【文件夹 2】。")
                return
            if os.path.normcase(os.path.abspath(self._folder1_path)) == os.path.normcase(os.path.abspath(self._folder2_path)):
                QMessageBox.warning(self, "提示", "文件夹 1 与文件夹 2 不能为同一目录。")
                return
            folder2 = self._folder2_path

        self.btn_start_cta.setEnabled(False)
        self.btn_start_cta.setText("正在分析图像特征...")
        self.btn_recheck.setEnabled(False)
        self.scan_progress_bar.setVisible(True)
        self.scan_progress_bar.setValue(0)

        self.worker = ScanWorker(
            engine=self.engine,
            folder1=self._folder1_path,
            folder2=folder2,
            sensitivity=self._sensitivity,
            is_recheck=is_recheck,
            include_subfolders=self._include_subfolders
        )
        self.worker.progressUpdated.connect(self._on_scan_progress)
        self.worker.scanFinished.connect(self._on_scan_finished)
        self.worker.scanFailed.connect(self._on_scan_failed)
        self.worker.start()

    def _on_scan_progress(self, cur: int, tot: int, msg: str):
        self.scan_progress_bar.setMaximum(max(1, tot))
        self.scan_progress_bar.setValue(cur)
        if self.phase_stack.currentIndex() == self.PHASE_IMPORT:
            self.btn_start_cta.setText(f"正在扫描 ({cur}/{tot})...")
        else:
            self.lbl_dock_progress.setText(msg)

    def _on_scan_finished(self, groups: List[MatchGroup], stats: Dict):
        self.btn_start_cta.setEnabled(True)
        self.btn_start_cta.setText("开始智能查重")
        self.btn_recheck.setEnabled(True)
        self.scan_progress_bar.setVisible(False)

        self.groups = groups
        elapsed = stats.get("elapsed", 0.0)
        c1 = stats.get("count1", 0)
        c2 = stats.get("count2", 0)
        is_cross = stats.get("is_cross", False)
        inc_sub = stats.get("include_subfolders", self._include_subfolders)
        has_subdirs = stats.get("has_subdirs", False)

        if groups:
            self._switch_phase(self.PHASE_REVIEW)
            self._refresh_group_list()
        else:
            self._switch_phase(self.PHASE_IMPORT)
            scope_label = "已递归扫描（含子文件夹）" if inc_sub else "已扫描当前顶层文件夹（不含子文件夹）"
            if is_cross:
                detail = f"{scope_label}：文件夹 A 共 {c1} 张，文件夹 B 共 {c2} 张。"
            else:
                detail = f"{scope_label}：共 {c1} 张图片。"
            subdir_hint = ""
            if not inc_sub and has_subdirs:
                subdir_hint = "\n\n提示：检测到所选目录内存在子文件夹。若需扫描子文件夹内的图片，请点击勾选【包含子文件夹】后再试。"
            QMessageBox.information(
                self,
                "扫描完成",
                f"{detail}\n耗时 {elapsed:.2f} 秒，未检出任何重复或高相似图片组。{subdir_hint}"
            )

    def _on_scan_failed(self, err_msg: str):
        self.btn_start_cta.setEnabled(True)
        self.btn_start_cta.setText("开始智能查重")
        self.btn_recheck.setEnabled(True)
        self.scan_progress_bar.setVisible(False)
        QMessageBox.critical(self, "扫描出错", err_msg)

    # ==================== 审阅态列表与画布渲染 ====================

    def _refresh_group_list(self):
        filter_mode = self.combo_filter.currentData()
        sort_mode = self.combo_sort.currentData()
        kw = self.edit_search.text().strip().lower()
        prev_group_id = self.current_group.group_id if self.current_group else None

        candidates: List[MatchGroup] = []
        for g in self.groups:
            if filter_mode == "pending" and not g.is_pending:
                continue
            if filter_mode == "resolved" and g.is_pending:
                continue
            if kw:
                match_id = kw in f"{g.group_id:02d}" or kw in str(g.group_id)
                match_fn = any(kw in it.filename.lower() for it in g.items)
                if not (match_id or match_fn):
                    continue
            candidates.append(g)

        if sort_mode == "sim_desc":
            candidates.sort(key=lambda g: (-g.similarity_pct, -g.max_inliers, g.group_id))
        elif sort_mode == "size_diff":
            candidates.sort(key=lambda g: (-g.size_diff_bytes, -g.similarity_pct))
        else:
            candidates.sort(key=lambda g: g.group_id)

        self.filtered_groups = candidates

        self.list_groups.blockSignals(True)
        self.list_groups.clear()

        select_row = 0
        for row_idx, g in enumerate(self.filtered_groups):
            item = QListWidgetItem(self.list_groups)
            item.setSizeHint(QSize(228, 54))
            card_widget = GroupDrawerItemWidget(g)
            self.list_groups.addItem(item)
            self.list_groups.setItemWidget(item, card_widget)
            if prev_group_id is not None and g.group_id == prev_group_id:
                select_row = row_idx

        self.list_groups.blockSignals(False)

        if self.filtered_groups:
            self.list_groups.setCurrentRow(select_row)
            self._on_group_selected(select_row)
        else:
            self.current_group = None
            self.right_inspector.update_group(None)
            self._clear_viewport_layout()
            lbl_done = QLabel("当前列表已全部审阅完毕\n可点击顶部「极速复查」验证最终结果")
            lbl_done.setAlignment(Qt.AlignCenter)
            lbl_done.setStyleSheet("color: #71717a; font-size: 13px; border: none;")
            self.viewport_layout.addWidget(lbl_done)
            self._update_dock_progress()

    def _on_group_selected(self, row: int):
        if 0 <= row < len(self.filtered_groups):
            self.current_group = self.filtered_groups[row]
            self.current_candidate_idx = 1
            self._render_current_group()
            self._update_dock_progress()

    def _on_candidate_selected(self, cand_idx: int):
        self.current_candidate_idx = cand_idx
        self._render_current_group()

    def _update_dock_progress(self):
        total = len(self.filtered_groups)
        cur = self.list_groups.currentRow() + 1 if total > 0 else 0
        pending_total = sum(1 for g in self.groups if g.is_pending)
        self.lbl_dock_progress.setText(f"第 {cur} / {total} 组   ·   剩余待决断 {pending_total} 组")

    def _clear_viewport_layout(self):
        self.current_units.clear()
        while self.viewport_layout.count():
            child = self.viewport_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _on_sync_toggled(self, checked: bool):
        self._sync_zoom_enabled = checked
        self._refresh_capsule_styles()

    def _on_heatmap_toggled(self, checked: bool):
        if checked:
            if self.btn_cap_curtain.isChecked():
                self.btn_cap_curtain.blockSignals(True)
                self.btn_cap_curtain.setChecked(False)
                self.btn_cap_curtain.blockSignals(False)
            if self.btn_cap_grid.isChecked():
                self.btn_cap_grid.blockSignals(True)
                self.btn_cap_grid.setChecked(False)
                self.btn_cap_grid.blockSignals(False)
        self._refresh_capsule_styles()
        self._render_current_group()

    def _on_curtain_toggled(self, checked: bool):
        if checked:
            if self.btn_cap_heatmap.isChecked():
                self.btn_cap_heatmap.blockSignals(True)
                self.btn_cap_heatmap.setChecked(False)
                self.btn_cap_heatmap.blockSignals(False)
            if self.btn_cap_grid.isChecked():
                self.btn_cap_grid.blockSignals(True)
                self.btn_cap_grid.setChecked(False)
                self.btn_cap_grid.blockSignals(False)
        self._refresh_capsule_styles()
        self._render_current_group()

    def _on_grid_toggled(self, checked: bool):
        if checked:
            if self.btn_cap_curtain.isChecked():
                self.btn_cap_curtain.blockSignals(True)
                self.btn_cap_curtain.setChecked(False)
                self.btn_cap_curtain.blockSignals(False)
            if self.btn_cap_heatmap.isChecked():
                self.btn_cap_heatmap.blockSignals(True)
                self.btn_cap_heatmap.setChecked(False)
                self.btn_cap_heatmap.blockSignals(False)
        self._refresh_capsule_styles()
        self._render_current_group()

    def _render_current_group(self):
        grp = self.current_group
        if not grp:
            return

        self._clear_viewport_layout()
        self.btn_cap_whitelist.setText(" 移出白名单 (Space)" if grp.whitelisted else " 白名单 (Space)")

        active = grp.active_items
        if not active:
            active = grp.items

        best_item = max(active, key=lambda it: (it.pixel_count, it.filesize)) if active else (grp.items[0] if grp.items else None)

        has_multi = len(grp.items) > 2
        self.btn_cap_grid.setVisible(has_multi)

        # 候选项列表：除推荐项之外的其他所有图片
        candidates = [(i, it) for i, it in enumerate(grp.items) if best_item is None or it.unique_key != best_item.unique_key]
        candidate_indices = [i for i, _ in candidates]

        if not candidate_indices:
            candidate_indices = [1] if len(grp.items) > 1 else [0]

        if self.current_candidate_idx not in candidate_indices:
            self.current_candidate_idx = candidate_indices[0]

        cand_idx = self.current_candidate_idx
        cand_item = grp.items[cand_idx] if cand_idx < len(grp.items) else (grp.items[1] if len(grp.items) > 1 else grp.items[0])
        ref_item = best_item if best_item else grp.items[0]

        # 1. 滑动卷帘对比模式 (精准比对 基准原图 vs 当前选中对比图)
        if self.btn_cap_curtain.isChecked() and len(active) >= 2:
            pix_a = load_qpixmap_safe(ref_item.filepath)
            pix_b = load_qpixmap_safe(cand_item.filepath)
            curtain = CurtainCompareWidget(pix_a, pix_b, ref_item.filename, cand_item.filename)
            self.viewport_layout.addWidget(curtain, 0, 0, 1, 2)
            self.lbl_dock_shortcuts.setText("左右拖拽滑块对比  |  Delete 废弃非推荐  |  Space 白名单  |  Ctrl+Z 撤销")
            self.right_inspector.update_group(grp, item_a=ref_item, item_b=cand_item)
            return

        # 2. 网格平铺模式 (用户主动勾选平铺 且 组内图片 > 2)
        if self.btn_cap_grid.isChecked() and has_multi:
            for idx, item in enumerate(grp.items):
                is_rec = (best_item is not None and item.unique_key == best_item.unique_key)
                unit = ViewportUnit(
                    index_in_group=idx,
                    item=item,
                    is_recommended=is_rec,
                    parent=self.viewport_container,
                    display_key_num=idx + 1
                )
                unit.keepRequested.connect(self._on_keep_only_item)
                unit.deleteRequested.connect(self._on_delete_single_item)
                unit.locateRequested.connect(self._on_locate_item)
                unit.canvas.viewChanged.connect(
                    lambda z, hr, vr, src=unit: self._on_canvas_view_changed(src, z, hr, vr)
                )
                self.current_units.append(unit)
                row = idx // 2
                col = idx % 2
                self.viewport_layout.addWidget(unit, row, col)

            self.viewport_layout.setColumnStretch(0, 1)
            self.viewport_layout.setColumnStretch(1, 1)
            self.lbl_dock_shortcuts.setText(f"1~{len(grp.items)} 保留单图  |  Delete 废弃其余副本  |  Space 白名单  |  Ctrl+Z 撤销")
            self.right_inspector.update_group(grp, item_a=ref_item, item_b=cand_item)
            return

        # 3. 标准双视口聚焦对比模式 (默认：左侧原始推荐原图 vs 右侧当前选中的对比图)
        self.lbl_dock_shortcuts.setText("1 保留A  |  2 保留B  |  Space 白名单  |  Delete 废弃其余副本  |  Ctrl+Z 撤销")
        ref_idx = grp.items.index(ref_item) if ref_item in grp.items else 0
        unit_a = ViewportUnit(
            index_in_group=ref_idx,
            item=ref_item,
            is_recommended=True,
            parent=self.viewport_container,
            display_key_num=1
        )
        unit_a.keepRequested.connect(self._on_keep_only_item)
        unit_a.deleteRequested.connect(self._on_delete_single_item)
        unit_a.locateRequested.connect(self._on_locate_item)
        unit_a.canvas.viewChanged.connect(
            lambda z, hr, vr, src=unit_a: self._on_canvas_view_changed(src, z, hr, vr)
        )
        self.current_units.append(unit_a)
        self.viewport_layout.addWidget(unit_a, 0, 0)

        if len(grp.items) > 1:
            unit_b = ViewportUnit(
                index_in_group=cand_idx,
                item=cand_item,
                is_recommended=False,
                parent=self.viewport_container,
                candidates=candidates if len(candidates) > 1 else None,
                current_candidate_idx=cand_idx,
                display_key_num=2
            )
            unit_b.keepRequested.connect(self._on_keep_only_item)
            unit_b.deleteRequested.connect(self._on_delete_single_item)
            unit_b.locateRequested.connect(self._on_locate_item)
            unit_b.candidateSelected.connect(self._on_candidate_selected)
            unit_b.canvas.viewChanged.connect(
                lambda z, hr, vr, src=unit_b: self._on_canvas_view_changed(src, z, hr, vr)
            )
            self.current_units.append(unit_b)
            self.viewport_layout.addWidget(unit_b, 0, 1)
            self.right_inspector.update_group(grp, item_a=ref_item, item_b=cand_item)
        else:
            self.right_inspector.update_group(grp, item_a=ref_item, item_b=None)

        self.viewport_layout.setColumnStretch(0, 1)
        self.viewport_layout.setColumnStretch(1, 1)

        # 4. 像素差异热图叠加 (作用于 ref_item vs cand_item)
        if self.btn_cap_heatmap.isChecked() and len(active) >= 2:
            diff_bgr = compute_diff_visualization(ref_item.filepath, cand_item.filepath)
            if diff_bgr is not None:
                heat_frame = QFrame()
                heat_frame.setStyleSheet("""
                    QFrame {
                        background-color: #202023;
                        border: 1px solid rgba(245, 158, 11, 0.35);
                        border-radius: 8px;
                    }
                """)
                h_lay = QVBoxLayout(heat_frame)
                h_lay.setContentsMargins(12, 10, 12, 12)
                h_lay.setSpacing(8)

                lbl_h = QLabel("像素差异热图（高亮区为差异部位）")
                lbl_h.setStyleSheet("color: #f59e0b; font-size: 12px; font-weight: 600; border: none;")
                h_lay.addWidget(lbl_h)

                heat_canvas = SyncZoomImageView(heat_frame)
                heat_canvas.set_pixmap(cv2_to_qpixmap(diff_bgr))
                h_lay.addWidget(heat_canvas, stretch=1)

                self.viewport_layout.addWidget(heat_frame, 1, 0, 1, 2)

    def _on_canvas_view_changed(self, source_unit: ViewportUnit, zoom: float, h_ratio: float, v_ratio: float):
        if not self._sync_zoom_enabled:
            return
        for unit in self.current_units:
            if unit is not source_unit:
                unit.canvas.sync_from_other(zoom, h_ratio, v_ratio)

    def _reset_all_canvas_zoom(self):
        for unit in self.current_units:
            unit.canvas.reset_view()

    # ==================== 纯键盘流水线作业与安全可逆操作 ====================

    def _bind_shortcuts(self):
        # 1~9 保留对应单图 | Space 白名单 | Delete 废弃非推荐项 | Ctrl+Z 撤销 | 左右方向键翻组 | F1 帮助指南
        for digit in range(1, 10):
            QShortcut(QKeySequence(str(digit)), self).activated.connect(lambda d=digit - 1: self._keep_by_index(d))
        QShortcut(QKeySequence(Qt.Key_Space), self).activated.connect(self._whitelist_current_group)
        QShortcut(QKeySequence(Qt.Key_Delete), self).activated.connect(self._discard_non_recommended)
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self._undo_last_delete)
        QShortcut(QKeySequence(Qt.Key_Left), self).activated.connect(self._go_prev_group)
        QShortcut(QKeySequence(Qt.Key_Right), self).activated.connect(self._go_next_group)
        QShortcut(QKeySequence(Qt.Key_F1), self).activated.connect(self._show_about_dialog)

    def _keep_by_index(self, key_num: int):
        if self.phase_stack.currentIndex() != self.PHASE_REVIEW or not self.current_group:
            return
        grp = self.current_group
        if not self.btn_cap_grid.isChecked() or len(grp.items) <= 2:
            # 双视口聚焦模式：1 保留左图 (A/参考图)，2 保留当前右图 (选中的对比图)
            if key_num == 0:
                best_item = max(grp.active_items, key=lambda it: (it.pixel_count, it.filesize)) if grp.active_items else grp.items[0]
                self._on_keep_only_item(best_item)
            elif key_num == 1:
                cand_idx = self.current_candidate_idx
                if 0 <= cand_idx < len(grp.items):
                    cand_item = grp.items[cand_idx]
                    if not cand_item.deleted:
                        self._on_keep_only_item(cand_item)
        else:
            # 网格平铺模式：数字键对应组内卡片序号
            if 0 <= key_num < len(grp.items):
                target = grp.items[key_num]
                if not target.deleted:
                    self._on_keep_only_item(target)

    def _discard_non_recommended(self):
        """按 Delete 键：自动保留智能推荐项并废弃其余重复项"""
        if self.phase_stack.currentIndex() != self.PHASE_REVIEW or not self.current_group:
            return
        active = self.current_group.active_items
        if len(active) >= 2:
            best = max(active, key=lambda it: (it.pixel_count, it.filesize))
            self._on_keep_only_item(best)

    def _on_delete_single_item(self, item: ImageItem):
        if not self.current_group or item.deleted:
            return
        ok, msg = self.engine.delete_items([item], group_id=self.current_group.group_id, action_name=f"删除 {item.filename}")
        self.lbl_dock_progress.setText(msg)
        self.btn_cap_undo.setEnabled(len(self.engine.undo_stack) > 0)
        if ok:
            active_left = [it for it in self.current_group.active_items if not it.deleted]
            if len(active_left) > 1:
                self._refresh_group_list()
                self._render_current_group()
            else:
                self.current_group.resolved = True
                self._after_decision_advance()

    def _on_keep_only_item(self, keep_item: ImageItem):
        if not self.current_group:
            return
        to_delete = [it for it in self.current_group.active_items if it.unique_key != keep_item.unique_key]
        if not to_delete:
            return
        ok, msg = self.engine.delete_items(
            to_delete,
            group_id=self.current_group.group_id,
            action_name=f"保留 {keep_item.filename}"
        )
        self.current_group.resolved = True
        self.lbl_dock_progress.setText(msg)
        self.btn_cap_undo.setEnabled(len(self.engine.undo_stack) > 0)
        if ok:
            self._after_decision_advance()

    def _whitelist_current_group(self):
        if self.phase_stack.currentIndex() != self.PHASE_REVIEW or not self.current_group:
            return
        if self.current_group.whitelisted:
            self.engine.remove_group_from_whitelist(self.current_group)
            self._refresh_group_list()
        else:
            self.engine.add_group_to_whitelist(self.current_group)
            self._after_decision_advance()

    def _after_decision_advance(self):
        if not self.current_group:
            return
        cur_row = self.list_groups.currentRow()
        is_resolved = not self.current_group.is_pending
        if is_resolved:
            if self.combo_filter.currentData() == "pending":
                self._refresh_group_list()
                return
            self._refresh_group_list()
            self._go_next_group()
            return
        self._refresh_group_list()
        if 0 <= cur_row < self.list_groups.count():
            self.list_groups.setCurrentRow(cur_row)

    def _undo_last_delete(self):
        if self.phase_stack.currentIndex() != self.PHASE_REVIEW:
            return
        ok, msg, group_id = self.engine.undo_last_delete()
        self.lbl_dock_progress.setText(msg)
        self.btn_cap_undo.setEnabled(len(self.engine.undo_stack) > 0)
        if ok:
            if group_id is not None:
                for g in self.groups:
                    if g.group_id == group_id:
                        g.resolved = False
                        self.current_group = g
                        break
            self._refresh_group_list()

    def _go_prev_group(self):
        if self.phase_stack.currentIndex() != self.PHASE_REVIEW:
            return
        row = self.list_groups.currentRow()
        if row > 0:
            self.list_groups.setCurrentRow(row - 1)

    def _go_next_group(self):
        if self.phase_stack.currentIndex() != self.PHASE_REVIEW:
            return
        row = self.list_groups.currentRow()
        if row + 1 < self.list_groups.count():
            self.list_groups.setCurrentRow(row + 1)

    def _on_locate_item(self, item: ImageItem):
        if os.path.exists(item.filepath):
            subprocess.Popen(f'explorer /select,"{os.path.normpath(item.filepath)}"')

    def _export_groups(self):
        pending = [g for g in self.groups if len(g.active_items) >= 2]
        if not pending:
            QMessageBox.information(self, "提示", "当前没有待导出的相似图片组。")
            return
        dest_dir = QFileDialog.getExistingDirectory(self, "选择导出目录", os.path.expanduser("~\\Desktop"))
        if not dest_dir:
            return
        sub = "跨文件夹相似对比结果" if self.seg_mode.is_cross else "相似重复图片待确认"
        final_dest = os.path.join(dest_dir, sub)
        self.lbl_dock_status.setText("正在后台异步导出分组文件...")
        self.export_worker = ExportWorker(self.engine, pending, final_dest, is_cross=self.seg_mode.is_cross)
        self.export_worker.exportFinished.connect(self._on_export_finished)
        self.export_worker.exportFailed.connect(self._on_export_failed)
        self.export_worker.start()

    def _on_export_finished(self, g_cnt: int, f_cnt: int, out_path: str):
        self._update_dock_progress()
        self.logger.info(f"Exported {g_cnt} groups ({f_cnt} files) to {out_path}")
        if QMessageBox.question(self, "导出完成", f"已导出 {g_cnt} 组 ({f_cnt} 张) 至：\n{out_path}\n\n是否立即打开？") == QMessageBox.Yes:
            os.startfile(out_path)

    def _on_export_failed(self, err_msg: str):
        self._update_dock_progress()
        self.logger.error(f"Export groups failed: {err_msg}")
        QMessageBox.critical(self, "导出失败", f"导出过程中发生错误：\n{err_msg}")

    def _on_reset_whitelist_menu(self):
        if QMessageBox.question(self, "确认", "确定清空所有保留白名单与特征缓存吗？") == QMessageBox.Yes:
            self.engine.clear_whitelist()
            self.engine.clear_all_caches()
            self.toast_banner.show_toast(
                "已清空所有白名单与特征缓存",
                "下次扫描将重新对所有相似图片进行完整检出",
                (16, 185, 129)
            )

    def _show_about_dialog(self):
        hw_code = MachineFingerprint.get_machine_code()
        dlg = QDialog(self)
        dlg.setWindowTitle(f"使用指南与常见问题帮助中心 — 图像智能查重工作台 v{APP_VERSION}")
        dlg.resize(760, 650)
        dlg.setStyleSheet("""
            QDialog {
                background-color: #18181b;
                color: #e4e4e7;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QTextBrowser {
                background-color: #202023;
                color: #d4d4d8;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 14px 18px;
                font-size: 13px;
            }
        """)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(14)

        hdr = QLabel(f"使用指南与常见问题解答 (FAQ)  ·  v{APP_VERSION}")
        hdr.setStyleSheet("color: #f4f4f5; font-size: 16px; font-weight: 600; border: none;")
        lay.addWidget(hdr)

        browser = QTextBrowser(dlg)
        browser.setOpenExternalLinks(False)
        browser.setHtml(f"""
        <div style="line-height: 1.65; color: #d4d4d8;">
            <h3 style="color: #60a5fa; margin-top: 2px; margin-bottom: 6px;">一、【白名单】的具体功能与操作方式</h3>
            <p style="margin-top: 0; margin-bottom: 6px;">
                <b>1. 白名单有什么用？</b><br/>
                当软件查出一组相似图片（例如<b>同款不同色、不同尺寸版本、或换了局部文字的变体图</b>），如果您觉得<b>“这两张图都有用，两张都要留着，不删任何一张”</b>，就可以将该组加入<b>【白名单】</b>：<br/>
                • <b>零删除、全部保留</b>：组内所有图片均安全保留在原文件夹，不会删除任何文件；<br/>
                • <b>永久免打扰记忆</b>：软件会将这一对图片的放行关系永久记录到本地数据库。之后点击「极速复查」，或日后往文件夹加入新图重新扫描时，<b>这一对图片都不会再重复跳出来打扰您</b>。
            </p>
            <p style="margin-top: 4px; margin-bottom: 12px;">
                <b>2. 白名单具体怎么操作？</b><br/>
                • <b>加入白名单</b>：看图时直接按键盘 <span style="color: #10b981; font-weight: 600;">[空格键 Space]</span>，或点击画布上方胶囊栏的 <b>「白名单 (Space)」</b> 按钮，当前组即全部保留并自动跳到下一组。<br/>
                • <b>加错了怎么移出（单组取消）</b>：将左侧列表顶部的筛选下拉框从「待决断」切换为 <b>「已处理」</b> 或 <b>「全部组」</b>，点中那一组，再次按 <span style="color: #f59e0b; font-weight: 600;">[空格键 Space]</span>（或点「移出白名单」）即可撤回。<br/>
                • <b>清空所有历史白名单</b>：点击本窗口下方 <b>「清空白名单与缓存」</b> 按钮（或右上角 <b>?</b> 菜单 ->「清空保留白名单与特征缓存...」），即可恢复初始状态重新扫描出所有相似图。
            </p>

            <hr style="border: none; border-top: 1px solid #27272a; margin: 12px 0;"/>

            <h3 style="color: #10b981; margin-top: 6px; margin-bottom: 6px;">二、删除的图片去了哪里？如何找回或彻底清空？</h3>
            <p style="margin-top: 0; margin-bottom: 6px;">
                为了防止误删重要原图，软件中的「删除此项 / 仅保留此项」<b>不会直接彻底粉碎文件</b>，而是将淘汰的图片安全移入了软件内置的<b>【安全回收暂存区 (staging_trash)】</b>。
            </p>
            <p style="margin-top: 4px; margin-bottom: 12px;">
                • <b>1. 删错了怎么马上恢复？（最推荐）</b><br/>
                  直接按键盘 <span style="color: #60a5fa; font-weight: 600;">[Ctrl + Z]</span>，或点击画布上方胶囊栏的 <b>「撤销 (Ctrl+Z)」</b> 按钮，图片就会自动恢复成<b>原来的文件名并 100% 放回原来的文件夹路径</b>（支持连续多次撤销）。<br/>
                • <b>2. 存放已删除图片的文件夹在哪里？</b><br/>
                  路径：<code style="color: #f59e0b;">{self.paths.trash_dir}</code><br/>
                  您可以直接点击下方 <b>「打开已删除图片暂存区」</b> 按钮（或右上角 <b>?</b> 菜单 ->「打开已删除图片回收暂存区...」）一键打开该文件夹，随时找回历史删除的图片，或将其彻底清空以释放磁盘空间。
            </p>

            <hr style="border: none; border-top: 1px solid #27272a; margin: 12px 0;"/>

            <h3 style="color: #f59e0b; margin-top: 6px; margin-bottom: 6px;">三、扫描范围与三种查重灵敏度说明</h3>
            <p style="margin-top: 0; margin-bottom: 12px;">
                • <b>扫描范围控制</b>：默认<b>仅扫描当前顶层文件夹</b>（不含子文件夹）；如需连同所有嵌套子文件夹一起查重，请勾选 <b>「包含子文件夹」</b> 按钮。<br/>
                • <b>标准模式（推荐）</b>：兼顾原图与局部变体，精准检出完全相同、跨分辨率缩放压缩，以及加水印/换字、局部微调的相似图片。<br/>
                • <b>严格模式（仅限同图）</b>：仅检出画面高度一致的原图、格式转换与缩放压缩图，自动忽略换字或改色变体，零误报。<br/>
                • <b>深度宽松（广覆盖）</b>：放宽特征匹配阈值，连同大幅调色、AI 图生图重绘变体及近似构图图片一并检出供人工排查。
            </p>

            <hr style="border: none; border-top: 1px solid #27272a; margin: 12px 0;"/>

            <h3 style="color: #a78bfa; margin-top: 6px; margin-bottom: 6px;">四、纯键盘流水线快捷键一览</h3>
            <p style="margin-top: 0; margin-bottom: 12px;">
                • 按 <b>[1]</b>：仅保留左图 A（自动软删除同组其余图片）<br/>
                • 按 <b>[2]</b>：仅保留右图 B（自动软删除同组其余图片）<br/>
                • 按 <b>[Delete]</b>：采纳系统智能推荐（保留分辨率/体积最优原图，软删除其余重复项）<br/>
                • 按 <b>[Space 空格键]</b>：将当前组加入保留白名单（或移出白名单）<br/>
                • 按 <b>[Ctrl + Z]</b>：原路径无损撤销上一步删除操作<br/>
                • 按 <b>[← / → 左右方向键]</b>：切换上一组 / 下一组  |  按 <b>[F1]</b>：打开本帮助中心
            </p>

            <hr style="border: none; border-top: 1px solid #27272a; margin: 12px 0;"/>

            <div style="color: #71717a; font-size: 11px;">
                <b>运行环境与数据隔离信息：</b><br/>
                • 机器授权指纹：{hw_code}<br/>
                • 已删图片暂存区：{self.paths.trash_dir}<br/>
                • 状态数据库 (SQLite)：{self.paths.sqlite_db_path}<br/>
                • 轮转日志目录：{self.paths.log_dir}
            </div>
        </div>
        """)
        lay.addWidget(browser, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_open_trash = QPushButton(" 打开已删除图片暂存区 (staging_trash)")
        btn_open_trash.setIcon(LucideIcon.icon("trash", 14, "#10b981"))
        btn_open_trash.setFixedHeight(34)
        btn_open_trash.setCursor(Qt.PointingHandCursor)
        btn_open_trash.setStyleSheet(self._secondary_pill_css())
        btn_open_trash.clicked.connect(lambda: os.startfile(self.paths.trash_dir))
        btn_row.addWidget(btn_open_trash)

        btn_clear_wl = QPushButton(" 清空白名单与特征缓存")
        btn_clear_wl.setIcon(LucideIcon.icon("refresh", 14, "#f59e0b"))
        btn_clear_wl.setFixedHeight(34)
        btn_clear_wl.setCursor(Qt.PointingHandCursor)
        btn_clear_wl.setStyleSheet(self._secondary_pill_css())
        btn_clear_wl.clicked.connect(self._on_reset_whitelist_menu)
        btn_row.addWidget(btn_clear_wl)

        btn_row.addStretch(1)

        btn_ok = QPushButton("我知道了")
        btn_ok.setFixedSize(110, 34)
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-size: 13px;
                font-weight: 600;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover { background-color: #3b82f6; }
        """)
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_ok)

        lay.addLayout(btn_row)
        dlg.exec()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VisionStudio.ImageDedupPro.4.0")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("图像智能查重工作台")
    app.setApplicationVersion(APP_VERSION)

    # 构建并绑定多尺寸矢量应用图标 (窗口标题栏 + Windows 任务栏)
    app_icon = QIcon()
    master_img = render_studio_icon_qimage(256)
    for sz in (256, 128, 64, 48, 32, 16):
        app_icon.addPixmap(QPixmap.fromImage(master_img.scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
    app.setWindowIcon(app_icon)

    # 1. 初始化符合 Windows 规范的 %APPDATA% / %LOCALAPPDATA% 路径与 10MB×7 轮转日志
    paths = AppPaths()
    logger = setup_rotating_logger(paths)

    # 2. 单例互斥锁保护：若已有实例在运行，自动唤醒并置顶已运行窗口，当前进程安全退出
    instance_guard = SingleInstanceGuard()
    if not instance_guard.try_acquire_or_notify_existing():
        logger.info("Duplicate instance detected; notified primary instance to activate and exiting.")
        sys.exit(0)

    # 3. 安装全局未捕获异常处理器 (主线程 + 后台线程崩溃拦截与转储)
    crash_handler = GlobalCrashHandler(paths, logger)
    crash_handler.install()

    logger.info(f"Starting {app.applicationName()} v{APP_VERSION} | HFP={MachineFingerprint.get_machine_code()}")
    win = DedupMainWindow(paths=paths)
    win.setWindowIcon(app_icon)
    instance_guard.activationRequested.connect(lambda: SingleInstanceGuard.bring_window_to_front(win))
    win.show()

    exit_code = app.exec()
    instance_guard.release()
    logger.info(f"Application exited cleanly with code {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
