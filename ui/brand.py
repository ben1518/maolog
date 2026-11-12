"""应用图标与界面小图标。

品牌符号是一条折返的时间轨迹，末端收成笔尖：记录时间，也留下自己的产出。
几何图形直接用 QPainter 绘制，16px 托盘图标也不依赖缩放一张大照片。
"""

from __future__ import annotations

import random
from functools import lru_cache

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from .theme import (
    ACCENT,
    DOODLE_MODE,
    BG_CARD,
    BG_ROOT,
    DANGER,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
)



def _hand_drawn(path: QPainterPath, amplitude: float, seed: int) -> QPainterPath:
    """把几何路径采样成折线再逐点抖动，得到「手画」的轮廓。

    只抖动顶点、不改曲率，所以图标的语义不会变，只是边不再是数学上的直。
    同一个图标用固定 seed，重绘时不会跳来跳去。
    """
    rng = random.Random(seed)
    out = QPainterPath()
    for polygon in path.toSubpathPolygons():
        points = list(polygon)
        if len(points) < 2:
            continue
        first = points[0]
        out.moveTo(
            first.x() + rng.uniform(-amplitude, amplitude),
            first.y() + rng.uniform(-amplitude, amplitude),
        )
        for point in points[1:]:
            out.lineTo(
                point.x() + rng.uniform(-amplitude, amplitude),
                point.y() + rng.uniform(-amplitude, amplitude),
            )
    return out


@lru_cache(maxsize=64)
def _svg_icon(name: str, color: str, background: str) -> QIcon:
    path = QPainterPath()
    stroke = 1.7
    if name == "book":
        path.moveTo(12, 4)
        path.cubicTo(9, 2.7, 5.7, 3, 3, 4)
        path.lineTo(3, 19)
        path.cubicTo(6, 17.5, 9, 17.5, 12, 19)
        path.cubicTo(15, 17.5, 18, 17.5, 21, 19)
        path.lineTo(21, 4)
        path.cubicTo(18.3, 3, 15, 2.7, 12, 4)
        path.closeSubpath()
        path.moveTo(12, 4)
        path.lineTo(12, 19)
        path.moveTo(6, 7)
        path.lineTo(9, 7.7)
        path.moveTo(6, 10)
        path.lineTo(9, 10.7)
        path.moveTo(15, 7.7)
        path.lineTo(18, 7)
        path.moveTo(15, 10.7)
        path.lineTo(18, 10)
    elif name == "ai":
        path.addRoundedRect(QRectF(3, 6, 18, 14), 4, 4)
        path.moveTo(12, 3)
        path.lineTo(12, 6)
        path.moveTo(9, 3)
        path.lineTo(15, 3)
        path.moveTo(8, 11)
        path.lineTo(8, 12)
        path.moveTo(16, 11)
        path.lineTo(16, 12)
        path.moveTo(8, 16)
        path.quadTo(12, 18, 16, 16)
        path.moveTo(3, 11)
        path.lineTo(1.5, 11)
        path.lineTo(1.5, 15)
        path.lineTo(3, 15)
        path.moveTo(21, 11)
        path.lineTo(22.5, 11)
        path.lineTo(22.5, 15)
        path.lineTo(21, 15)
    elif name == "pause":
        path.addRoundedRect(QRectF(6, 4, 4, 16), 1.2, 1.2)
        path.addRoundedRect(QRectF(14, 4, 4, 16), 1.2, 1.2)
        stroke = 0
    elif name == "play":
        path.moveTo(7, 4)
        path.lineTo(19, 12)
        path.lineTo(7, 20)
        path.closeSubpath()
        stroke = 0
    elif name == "play-circle":
        path.moveTo(10, 5)
        path.lineTo(18, 9)
        path.lineTo(10, 13)
        path.closeSubpath()
        stroke = 0
    elif name == "settings":
        # 三条滑杆比齿轮更能在 24px 下读出来，也更适合手绘
        for y, knob_x in ((7.5, 8.5), (12.0, 15.5), (16.5, 10.5)):
            path.moveTo(3, y)
            path.lineTo(21, y)
            # 小圆点比方块在 20px 下更容易读成「旋钮」
            path.addEllipse(QRectF(knob_x - 1.9, y - 1.9, 3.8, 3.8))
    elif name == "chevron-left":
        path.moveTo(15, 5)
        path.lineTo(8, 12)
        path.lineTo(15, 19)
    elif name == "chevron-right":
        path.moveTo(9, 5)
        path.lineTo(16, 12)
        path.lineTo(9, 19)
    elif name == "calendar":
        path.addRoundedRect(QRectF(3, 5, 18, 16), 3, 3)
        path.moveTo(7, 3)
        path.lineTo(7, 8)
        path.moveTo(17, 3)
        path.lineTo(17, 8)
        path.moveTo(3, 10)
        path.lineTo(21, 10)
        path.moveTo(7, 14)
        path.lineTo(9, 14)
        path.moveTo(15, 14)
        path.lineTo(17, 14)
    elif name == "chart":
        path.addEllipse(QRectF(3, 3, 18, 18))
        path.moveTo(12, 3)
        path.lineTo(12, 12)
        path.lineTo(21, 12)
    elif name == "image":
        path.addRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
        path.addEllipse(QRectF(6.5, 7, 3.5, 3.5))
        path.moveTo(3.5, 17.2)
        path.lineTo(8.6, 12.4)
        path.lineTo(12.2, 15.5)
        path.lineTo(15.6, 12.1)
        path.lineTo(20.6, 17.4)
    elif name == "apps":
        for x, y in ((3, 3), (14, 3), (3, 14), (14, 14)):
            path.addRoundedRect(QRectF(x, y, 7, 7), 1.8, 1.8)
    elif name == "music":
        path.addEllipse(QRectF(4, 15, 6.5, 6.5))
        path.moveTo(10.5, 18)
        path.lineTo(10.5, 5)
        path.cubicTo(15.2, 5.4, 18.5, 7.6, 19, 11)
        path.lineTo(19, 14)
    elif name == "skip-back":
        path.moveTo(15, 4)
        path.lineTo(5.5, 12)
        path.lineTo(15, 20)
        path.closeSubpath()
        path.addRoundedRect(QRectF(3.5, 4, 2.6, 16), 1.2, 1.2)
        stroke = 0
    elif name == "skip-forward":
        path.moveTo(9, 4)
        path.lineTo(18.5, 12)
        path.lineTo(9, 20)
        path.closeSubpath()
        path.addRoundedRect(QRectF(17.9, 4, 2.6, 16), 1.2, 1.2)
        stroke = 0
    elif name == "volume":
        path.moveTo(4, 9)
        path.lineTo(8, 9)
        path.lineTo(12, 5)
        path.lineTo(12, 19)
        path.lineTo(8, 15)
        path.lineTo(4, 15)
        path.closeSubpath()
        path.moveTo(15.5, 9)
        path.quadTo(18, 12, 15.5, 15)
        path.moveTo(18.5, 6.5)
        path.quadTo(22.5, 12, 18.5, 17.5)
    elif name == "folder":
        path.moveTo(3, 6)
        path.quadTo(3, 4.5, 4.5, 4.5)
        path.lineTo(9, 4.5)
        path.lineTo(11, 7)
        path.lineTo(19.5, 7)
        path.quadTo(21, 7, 21, 8.5)
        path.lineTo(21, 18)
        path.quadTo(21, 19.5, 19.5, 19.5)
        path.lineTo(4.5, 19.5)
        path.quadTo(3, 19.5, 3, 18)
        path.closeSubpath()
    elif name == "refresh":
        path.moveTo(19.5, 8)
        path.cubicTo(18.2, 4.7, 15.3, 3, 12, 3)
        path.cubicTo(7.8, 3, 4.3, 6, 3.4, 10)
        path.moveTo(19.5, 3.5)
        path.lineTo(19.5, 8)
        path.lineTo(15, 8)
        path.moveTo(4.5, 16)
        path.cubicTo(5.8, 19.3, 8.7, 21, 12, 21)
        path.cubicTo(16.2, 21, 19.7, 18, 20.6, 14)
        path.moveTo(4.5, 20.5)
        path.lineTo(4.5, 16)
        path.lineTo(9, 16)
    elif name == "search":
        path.addEllipse(QRectF(4, 4, 12.5, 12.5))
        path.moveTo(15, 15)
        path.lineTo(20, 20)
    elif name == "spark":
        path.moveTo(12, 2)
        path.lineTo(12, 22)
        path.moveTo(2, 12)
        path.lineTo(22, 12)
        path.moveTo(5, 5)
        path.lineTo(19, 19)
        path.moveTo(5, 19)
        path.lineTo(19, 5)
    elif name == "clock":
        path.addEllipse(QRectF(3, 3, 18, 18))
        path.moveTo(12, 7)
        path.lineTo(12, 12)
        path.lineTo(16, 14)
    elif name == "check":
        path.moveTo(4, 12)
        path.lineTo(9, 17)
        path.lineTo(20, 6)
    elif name == "shield":
        path.moveTo(12, 3)
        path.lineTo(20, 6)
        path.lineTo(19, 13)
        path.quadTo(17, 18, 12, 21)
        path.quadTo(7, 18, 5, 13)
        path.lineTo(4, 6)
        path.closeSubpath()
        path.moveTo(8, 12)
        path.lineTo(11, 15)
        path.lineTo(16, 9)
    else:
        path.addEllipse(QRectF(5, 5, 14, 14))

    if DOODLE_MODE:
        # 手绘模式下线条略粗一点，否则抖动会被抗锯齿吃掉
        stroke = max(stroke, 1.9)
        path = _hand_drawn(path, 0.32, abs(hash(name)) % 10000)

    pix = QPixmap(48, 48)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(2, 2)
    if background != "transparent":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(QRectF(0, 0, 24, 24), 6, 6)
    pen = QPen(QColor(color))
    pen.setWidthF(stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QColor(color) if stroke == 0 else Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    if DOODLE_MODE:
        # 第二遍轻描，模拟笔尖回头补一笔，线条就有了粗细变化
        second = QPen(QColor(color))
        second.setColor(QColor(color).lighter(115))
        second.setWidthF(stroke * 0.55)
        second.setCapStyle(Qt.PenCapStyle.RoundCap)
        second.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(second)
        painter.translate(0.18, -0.14)
        painter.drawPath(path)
    painter.end()
    return QIcon(pix)


def ui_icon(name: str, color: str = TEXT_SECONDARY, background: str = "transparent") -> QIcon:
    return _svg_icon(name, color, background)


# 品牌主图标专用调色板（恒定暗色方圆手帐便签标，与视觉标准及用户指定图标一致）
BRAND_BG = "#2E2C31"       # 暗色卡片底
BRAND_BORDER = "#8A8279"   # 柔和手绘质感灰边
BRAND_STRIPE = "#9C9481"   # 便签刻度线条
BRAND_TRACK = "#2A4B7C"    # 回看时间轨迹（深蓝）
BRAND_PEN = "#1E1D20"      # 墨水笔尖
BRAND_DOT = "#F5CC68"      # 笔芯暖金原点


def brand_pixmap(size: int = 128, state: str = "running") -> QPixmap:
    """绘制主图标。

    采用暗色方圆手帐便签标设计：深墨色圆角卡片 + 柔和灰边 + 便签刻度 + 回看弧线与金色笔尖。
    确保在 16/24/32/48/64/128/256/1024 所有尺寸下均具有一致的暗色方圆品牌识别，
    不会在小尺寸切换成黄色方块。
    """
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 128.0, size / 128.0)

    # 1. 外层暗色圆角方标与手绘灰边
    border_w = 6.0 if size <= 24 else 4.0
    p.setPen(QPen(QColor(BRAND_BORDER), border_w))
    p.setBrush(QColor(BRAND_BG))
    p.drawRoundedRect(QRectF(4, 4, 120, 120), 26, 26)

    # 2. 便签刻度线（暖灰线条）
    stripe_w = 7.0 if size <= 24 else 5.0
    p.setPen(
        QPen(
            QColor(BRAND_STRIPE),
            stripe_w,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
    )
    p.drawLine(QPointF(25, 34), QPointF(70, 34))
    p.drawLine(QPointF(25, 48), QPointF(83, 48))
    if size > 16:
        p.drawLine(QPointF(25, 62), QPointF(61, 62))

    # 3. 主轨迹：深蓝折返时间曲线
    track_w = 14.0 if size <= 24 else 9.0
    p.setPen(
        QPen(
            QColor(BRAND_TRACK),
            track_w,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    path = QPainterPath()
    path.moveTo(86, 24)
    path.cubicTo(108, 42, 107, 77, 84, 94)
    path.cubicTo(70, 104, 52, 103, 39, 92)
    p.drawPath(path)

    # 4. 笔尖
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(BRAND_PEN))
    pen_path = QPainterPath()
    pen_path.moveTo(37, 82)
    pen_path.lineTo(22, 113)
    pen_path.lineTo(56, 99)
    pen_path.closeSubpath()
    p.drawPath(pen_path)

    # 5. 金色笔心点
    dot_color = {"running": BRAND_DOT, "paused": WARNING, "error": DANGER}.get(state, BRAND_DOT)
    p.setBrush(QColor(dot_color))
    p.drawEllipse(QRectF(36, 88, 10, 10))

    # 暂停/异常状态加一枚角标
    if state in {"paused", "error"}:
        badge_color = WARNING if state == "paused" else DANGER
        p.setBrush(QColor(BRAND_BG))
        p.setPen(QPen(QColor(badge_color), 2.5))
        p.drawEllipse(QRectF(94, 14, 20, 20))

    p.end()
    return pix


def app_icon(state: str = "running") -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(brand_pixmap(size, state))
    return icon


def save_brand_assets(directory) -> None:
    """生成源码运行和打包共用的 PNG / ICO，避免依赖系统图标。

    ICO 的每个尺寸都单独绘制，而不是把 1024px 缩下去：16px 需要省略细刻度，
    直接缩放会让它在任务栏里糊成脏点。
    """
    import struct
    from pathlib import Path

    from PyQt6.QtCore import QBuffer, QIODevice

    owned_app = QGuiApplication.instance() is None
    app = QGuiApplication([]) if owned_app else None
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    brand_pixmap(1024).save(str(target / "icon.png"), "PNG")
    brand_pixmap(256).save(str(target / "icon-256.png"), "PNG")

    sizes = (16, 24, 32, 48, 64, 128, 256)
    frames: list[bytes] = []
    for size in sizes:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        brand_pixmap(size).save(buffer, "PNG")
        frames.append(bytes(buffer.data()))
        buffer.close()

    header = struct.pack("<HHH", 0, 1, len(frames))
    tables: list[bytes] = []
    offset = 6 + 16 * len(frames)
    for size, frame in zip(sizes, frames):
        dimension = 0 if size == 256 else size
        tables.append(
            struct.pack(
                "<BBBBHHII",
                dimension,
                dimension,
                0,
                0,
                1,
                32,
                len(frame),
                offset,
            )
        )
        offset += len(frame)
    (target / "icon.ico").write_bytes(header + b"".join(tables) + b"".join(frames))

    if owned_app and app is not None:
        app.quit()


def make_icon_label(name: str, size: int = 20, color: str = ACCENT, background: str = BG_CARD):
    from PyQt6.QtWidgets import QLabel

    label = QLabel()
    label.setFixedSize(size, size)
    label.setPixmap(ui_icon(name, color, background).pixmap(QSize(size, size)))
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def make_wordmark():
    """主窗口左侧紧凑品牌区，避免产品名和功能按钮抢同一层级。"""
    from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    mark = QLabel()
    mark.setPixmap(brand_pixmap(48))
    mark.setFixedSize(48, 48)
    row.addWidget(mark)
    text = QVBoxLayout()
    text.setSpacing(1)
    title = QLabel("MaoLog 🐾")
    title.setObjectName("Title")
    subtitle = QLabel("看见时间，复盘成长")
    subtitle.setObjectName("Subtitle")
    text.addWidget(title)
    text.addWidget(subtitle)
    row.addLayout(text)
    return box
