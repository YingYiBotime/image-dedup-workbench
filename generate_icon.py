# -*- coding: utf-8 -*-
"""
图像智能查重工作台 v4.0 — 通用商业级视觉图像比对与查重图标生成器 (generate_icon.py)
设计视觉概念（面向全行业通用图像资产、摄影图库、设计素材、电商主图与 AI 视觉去重）：
1. 基底：现代 Windows 11 / macOS 超椭圆圆角矩阵 (Squircle)，曜石暗灰渐变 (#232631 -> #0d111c) + 1px 微光金属内描边；
2. 左后方图框 (Image A)：暖珀金描边的标准摄影/图像画幅卡片（内含经典几何山峰与太阳构图，代表原始图像资产）；
3. 右前方主视口 (Image B)：科技蓝 (#3b82f6 -> #38bdf8) 图像对比画幅卡片：
   - 左半幅：标准高清几何山峰与太阳图像；
   - 右半幅：AI 特征关键点网格 (SIFT Keypoints Constellation) 与像素级透视矩阵；
   - 中轴线：高光滑动卷帘分界激光线 (Split-Curtain Laser) + 居中双向比对滑块；
4. 右下角徽章：翠绿 (#10b981) 精准查重核验徽章，传递工业级视觉去重与像素比对的专业感。
"""

import os
import sys
import struct
from PySide6.QtCore import Qt, QPointF, QRectF, QBuffer, QIODevice
from PySide6.QtGui import (
    QGuiApplication, QImage, QPainter, QPen, QBrush, QColor,
    QLinearGradient, QRadialGradient, QPainterPath
)


def render_studio_icon_qimage(size: int = 512) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    s = float(size)
    pad = s * 0.055
    box = s - 2 * pad
    radius = s * 0.225

    # 1. 底部柔和环境投影
    shadow_grad = QRadialGradient(QPointF(s * 0.5, s * 0.54), s * 0.48)
    shadow_grad.setColorAt(0.0, QColor(0, 0, 0, 145))
    shadow_grad.setColorAt(0.75, QColor(0, 0, 0, 60))
    shadow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(shadow_grad))
    p.drawRoundedRect(QRectF(pad, pad + s * 0.02, box, box), radius, radius)

    # 2. 主圆角基底 (Studio Dark Slate + 科技蓝微光渐变)
    bg_rect = QRectF(pad, pad, box, box)
    bg_grad = QLinearGradient(QPointF(pad, pad), QPointF(s - pad, s - pad))
    bg_grad.setColorAt(0.0, QColor("#252834"))
    bg_grad.setColorAt(0.45, QColor("#171922"))
    bg_grad.setColorAt(1.0, QColor("#0d111d"))
    p.setBrush(QBrush(bg_grad))
    p.setPen(QPen(QColor(255, 255, 255, 40), max(1.0, s * 0.012)))
    p.drawRoundedRect(bg_rect, radius, radius)

    # 内部中心科技蓝氛围光晕
    glow_grad = QRadialGradient(QPointF(s * 0.52, s * 0.48), s * 0.42)
    glow_grad.setColorAt(0.0, QColor(37, 99, 235, 76))
    glow_grad.setColorAt(0.65, QColor(37, 99, 235, 20))
    glow_grad.setColorAt(1.0, QColor(37, 99, 235, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(glow_grad))
    p.drawRoundedRect(bg_rect, radius, radius)

    card_w, card_h = s * 0.42, s * 0.46
    card_r = s * 0.055

    # 3. 左后方卡片 (原图卡片 A — 通用图像/摄影画幅)
    p.save()
    p.translate(s * 0.36, s * 0.46)
    p.rotate(-8.5)
    rect_a = QRectF(-card_w / 2, -card_h / 2, card_w, card_h)

    grad_a = QLinearGradient(rect_a.topLeft(), rect_a.bottomRight())
    grad_a.setColorAt(0.0, QColor("#2f2838"))
    grad_a.setColorAt(1.0, QColor("#1b1822"))
    p.setBrush(QBrush(grad_a))
    p.setPen(QPen(QColor("#f59e0b"), max(1.3, s * 0.015)))
    p.drawRoundedRect(rect_a, card_r, card_r)

    _draw_universal_image_scene(
        p, rect_a,
        sun_color=QColor("#fbbf24"),
        mtn_front=QColor(245, 158, 11, 165),
        mtn_back=QColor(217, 119, 6, 95),
        line_color=QColor("#fcd34d"),
        canvas_size=s,
        show_keypoints=False
    )
    p.restore()

    # 4. 右前方主视口卡片 (对比卡片 B — 双视口卷帘对比 + AI 特征点校验)
    p.save()
    p.translate(s * 0.58, s * 0.50)
    p.rotate(4.5)
    rect_b = QRectF(-card_w / 2, -card_h / 2, card_w, card_h)

    # 卡片投影
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 135))
    p.drawRoundedRect(rect_b.translated(-s * 0.018, s * 0.022), card_r, card_r)

    grad_b = QLinearGradient(rect_b.topLeft(), rect_b.bottomRight())
    grad_b.setColorAt(0.0, QColor("#1b283d"))
    grad_b.setColorAt(1.0, QColor("#0f172a"))
    p.setBrush(QBrush(grad_b))
    p.setPen(QPen(QColor("#3b82f6"), max(1.5, s * 0.016)))
    p.drawRoundedRect(rect_b, card_r, card_r)

    # 绘制前景图像画幅 (带 SIFT 特征点网络)
    _draw_universal_image_scene(
        p, rect_b,
        sun_color=QColor("#38bdf8"),
        mtn_front=QColor(59, 130, 246, 185),
        mtn_back=QColor(14, 165, 233, 110),
        line_color=QColor("#7dd3fc"),
        canvas_size=s,
        show_keypoints=True
    )

    # 纵向滑动卷帘激光分界线 (Split-Curtain Laser)
    laser_x = 0.0
    laser_glow = QLinearGradient(QPointF(laser_x - s * 0.06, 0), QPointF(laser_x + s * 0.06, 0))
    laser_glow.setColorAt(0.0, QColor(56, 189, 248, 0))
    laser_glow.setColorAt(0.5, QColor(56, 189, 248, 105))
    laser_glow.setColorAt(1.0, QColor(56, 189, 248, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(laser_glow))
    p.drawRect(QRectF(laser_x - s * 0.055, -card_h * 0.45, s * 0.11, card_h * 0.90))

    pen_laser = QPen(QColor("#f0f9ff"), max(1.6, s * 0.014))
    pen_laser.setCapStyle(Qt.RoundCap)
    p.setPen(pen_laser)
    p.drawLine(QPointF(laser_x, -card_h * 0.45), QPointF(laser_x, card_h * 0.45))

    # 卷帘中心圆形滑块手柄
    handle_r = s * 0.034
    p.setBrush(QColor("#2563eb"))
    p.setPen(QPen(QColor("#ffffff"), max(1.3, s * 0.010)))
    p.drawEllipse(QPointF(laser_x, 0), handle_r, handle_r)
    p.restore()

    # 5. 右下角智能检出/核验通过徽章 (Emerald Shield Circle)
    badge_cx, badge_cy = s * 0.75, s * 0.75
    badge_r = s * 0.125

    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 135))
    p.drawEllipse(QPointF(badge_cx, badge_cy + s * 0.012), badge_r * 1.05, badge_r * 1.05)

    badge_grad = QLinearGradient(
        QPointF(badge_cx - badge_r, badge_cy - badge_r),
        QPointF(badge_cx + badge_r, badge_cy + badge_r)
    )
    badge_grad.setColorAt(0.0, QColor("#10b981"))
    badge_grad.setColorAt(1.0, QColor("#059669"))
    p.setBrush(QBrush(badge_grad))
    p.setPen(QPen(QColor("#ffffff"), max(1.5, s * 0.018)))
    p.drawEllipse(QPointF(badge_cx, badge_cy), badge_r, badge_r)

    chk_pen = QPen(QColor("#ffffff"), max(2.0, s * 0.028))
    chk_pen.setCapStyle(Qt.RoundCap)
    chk_pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(chk_pen)
    path_chk = QPainterPath()
    path_chk.moveTo(badge_cx - badge_r * 0.38, badge_cy + badge_r * 0.02)
    path_chk.lineTo(badge_cx - badge_r * 0.08, badge_cy + badge_r * 0.34)
    path_chk.lineTo(badge_cx + badge_r * 0.42, badge_cy - badge_r * 0.28)
    p.drawPath(path_chk)

    p.end()
    return img


def _draw_universal_image_scene(
    p: QPainter,
    rect: QRectF,
    sun_color: QColor,
    mtn_front: QColor,
    mtn_back: QColor,
    line_color: QColor,
    canvas_size: float,
    show_keypoints: bool = False,
):
    """在卡片内绘制通用视觉图像符号（几何山峰 + 太阳光轮 + 可选的 AI 特征关键点网格）"""
    p.save()
    clip = QPainterPath()
    inner = rect.adjusted(canvas_size * 0.02, canvas_size * 0.02, -canvas_size * 0.02, -canvas_size * 0.02)
    clip.addRoundedRect(inner, canvas_size * 0.04, canvas_size * 0.04)
    p.setClipPath(clip)

    w = inner.width()
    h = inner.height()
    left = inner.left()
    top = inner.top()
    bottom = inner.bottom()
    right = inner.right()

    # 1. 太阳/视觉焦点圆环 (左上象限)
    sun_center = QPointF(left + w * 0.30, top + h * 0.28)
    sun_r = w * 0.125
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(sun_color.red(), sun_color.green(), sun_color.blue(), 60))
    p.drawEllipse(sun_center, sun_r * 1.45, sun_r * 1.45)
    p.setBrush(sun_color)
    p.drawEllipse(sun_center, sun_r, sun_r)

    # 2. 远景山峰 (右侧几何折线峰)
    path_back = QPainterPath()
    p1 = QPointF(left + w * 0.22, bottom)
    p2 = QPointF(left + w * 0.68, top + h * 0.34)
    p3 = QPointF(right + w * 0.08, bottom)
    path_back.moveTo(p1)
    path_back.lineTo(p2)
    path_back.lineTo(p3)
    path_back.closeSubpath()
    p.setBrush(mtn_back)
    p.setPen(QPen(line_color, max(1.0, canvas_size * 0.009)))
    p.drawPath(path_back)

    # 3. 近景主山峰 (左侧几何折线峰)
    path_front = QPainterPath()
    f1 = QPointF(left - w * 0.05, bottom)
    f2 = QPointF(left + w * 0.36, top + h * 0.44)
    f3 = QPointF(left + w * 0.80, bottom)
    path_front.moveTo(f1)
    path_front.lineTo(f2)
    path_front.lineTo(f3)
    path_front.closeSubpath()
    p.setBrush(mtn_front)
    p.setPen(QPen(line_color, max(1.2, canvas_size * 0.011)))
    p.drawPath(path_front)

    # 4. 右半幅 AI 视觉特征关键点连线 (代表 SIFT/RANSAC 几何特征点匹配)
    if show_keypoints:
        kp_nodes = [
            p2,
            QPointF(left + w * 0.56, top + h * 0.58),
            QPointF(left + w * 0.78, top + h * 0.52),
            QPointF(left + w * 0.70, top + h * 0.76),
        ]
        kp_pen = QPen(QColor(125, 211, 252, 180), max(1.0, canvas_size * 0.007), Qt.DashLine)
        p.setPen(kp_pen)
        p.drawLine(kp_nodes[0], kp_nodes[1])
        p.drawLine(kp_nodes[0], kp_nodes[2])
        p.drawLine(kp_nodes[1], kp_nodes[3])
        p.drawLine(kp_nodes[2], kp_nodes[3])

        node_r = max(2.0, canvas_size * 0.014)
        p.setPen(QPen(QColor("#ffffff"), max(1.0, canvas_size * 0.006)))
        p.setBrush(QColor("#38bdf8"))
        for pt in kp_nodes:
            p.drawEllipse(pt, node_r, node_r)

    p.restore()


def save_multi_size_ico(master_img: QImage, ico_path: str, sizes=(256, 128, 64, 48, 32, 16)):
    """将 QImage 编码为包含多尺寸 PNG 帧的标准 Windows .ico 图标文件"""
    png_payloads = []
    for sz in sizes:
        scaled = master_img.scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        scaled.save(buf, "PNG")
        png_bytes = bytes(buf.data())
        buf.close()
        png_payloads.append((sz, png_bytes))

    count = len(png_payloads)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + count * 16
    dir_entries = bytearray()
    image_data = bytearray()

    for sz, data in png_payloads:
        w_byte = 0 if sz >= 256 else sz
        h_byte = 0 if sz >= 256 else sz
        entry = struct.pack(
            "<BBBBHHII",
            w_byte,
            h_byte,
            0,
            0,
            1,
            32,
            len(data),
            offset
        )
        dir_entries.extend(entry)
        image_data.extend(data)
        offset += len(data)

    with open(ico_path, "wb") as f:
        f.write(header)
        f.write(dir_entries)
        f.write(image_data)


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    out_dir = os.path.dirname(os.path.abspath(__file__))
    ico_path = os.path.join(out_dir, "app_icon.ico")
    png_path = os.path.join(out_dir, "app_icon_preview.png")

    master = render_studio_icon_qimage(512)
    master.save(png_path, "PNG")
    save_multi_size_ico(master, ico_path, sizes=(256, 128, 64, 48, 32, 16))
    print(f"UNIVERSAL_ICON_GENERATED_OK | ICO={ico_path} ({os.path.getsize(ico_path)} bytes)")


if __name__ == "__main__":
    main()
