"""手绘风格的绘制工具：给卡片、按钮画「像手画」的边框。

Qt 的 QSS 只能画数学意义上的圆角矩形，直边 + 完美弧线放在纸面上会很假。
这里绕开 QSS：把圆角矩形采样成折线，逐点轻微抖动，再描两遍（第二遍更细、
稍微偏移），就能得到铅笔反复描边的手感。

和品牌图标用的是同一套思路（见 brand._hand_drawn），只是幅度更大、可以描两遍。
"""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QPushButton

from .theme import ACCENT, ACCENT_SOFT, BG_CARD, BORDER, BORDER_SOFT, DOODLE_MODE


def rough_path(rect: QRectF, radius: float, seed: int, amplitude: float = 2.3) -> QPainterPath:
    """把圆角矩形换成一条轻微起伏的闭合折线。

    位移不是逐点随机（那会变成锯齿毛刺），而是沿路径距离的正弦叠加，
    所以线是「缓缓地不直」，像手腕自然带出来的抖动。
    """
    base = QPainterPath()
    base.addRoundedRect(rect, radius, radius)

    rng = random.Random(seed)
    phase = rng.uniform(0, math.tau)
    phase2 = rng.uniform(0, math.tau)

    out = QPainterPath()
    for polygon in base.toSubpathPolygons():
        points = list(polygon)
        if len(points) < 3:
            continue

        perimeter = _perimeter(points)
        travelled = 0.0
        previous = points[0]
        start_x = previous.x() + amplitude * _periodic(0.0, perimeter, phase, phase2)
        start_y = previous.y() + amplitude * _periodic(
            perimeter * 0.35, perimeter, phase2, phase
        )
        out.moveTo(start_x, start_y)
        for point in points[1:]:
            travelled += math.hypot(point.x() - previous.x(), point.y() - previous.y())
            previous = point
            out.lineTo(
                point.x() + amplitude * _periodic(travelled, perimeter, phase, phase2),
                point.y() + amplitude * _periodic(travelled + perimeter * 0.35, perimeter, phase2, phase),
            )
        # 显式连回起点：直接 closeSubpath 会在接缝留一个几像素的小钩
        out.lineTo(start_x, start_y)
        out.closeSubpath()
    return out


def _perimeter(points: list) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += math.hypot(b.x() - a.x(), b.y() - a.y())
    total += math.hypot(points[0].x() - points[-1].x(), points[0].y() - points[-1].y())
    return max(total, 1.0)


def _periodic(distance: float, perimeter: float, phase: float, phase2: float) -> float:
    """按周长归一化的周期起伏：走完一圈正好回到起点，闭合处不会有台阶。"""
    t = (distance % perimeter) / perimeter
    return 0.62 * math.sin(math.tau * 3 * t + phase) + 0.38 * math.sin(math.tau * 7 * t + phase2)


def paint_rough_frame(
    painter: QPainter,
    rect: QRectF,
    color: str = BORDER,
    width: float = 1.9,
    radius: float = 14.0,
    seed: int = 1,
    double_pass: bool = True,
    fill: str | None = None,
    amplitude: float = 2.0,
) -> None:
    """在给定矩形上画一块手裁纸片：可选填充 + 手画描边。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    shape = rough_path(rect.adjusted(0.8, 0.8, -0.8, -0.8), radius, seed, amplitude)

    if fill:
        # 背景也用同一条抖动路径填，否则会出现「白底圆角 + 虚线框」两层边
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(fill))
        painter.drawPath(shape)

    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(shape)

    if double_pass:
        # 第二遍：更淡更细，位置偏一点点，模拟笔尖回头补一笔
        echo = QPen(QColor(color))
        echo.setColor(QColor(color).lighter(112))
        echo.setWidthF(width * 0.55)
        echo.setCapStyle(Qt.PenCapStyle.RoundCap)
        echo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(echo)
        painter.translate(0.6, -0.5)
        painter.drawPath(shape)

    painter.restore()


class RoughFrame(QFrame):
    """手绘模式下自带描边的容器；非手绘模式就是一个普通 QFrame。"""

    def __init__(self, parent=None, radius: float = 14.0, seed: int = 3,
                 color: str | None = None, width: float = 1.9,
                 fill_override: str | None = None, amplitude: float = 2.0,
                 decor: bool = False) -> None:
        super().__init__(parent)
        self._radius = radius
        self._seed = seed
        self._color = color or BORDER
        self._width = width
        self._fill = fill_override or BG_CARD
        self._amplitude = amplitude
        # 是否在卡片空白处撒小花
        self._decor = decor
        self._decor_cache = None
        self._decor_size = None

    def drawBackground(self, painter: QPainter, rect) -> None:  # noqa: N802
        """纸底在这里画：这一阶段早于所有子控件，不会被覆盖。"""
        painter.fillRect(rect, QColor(self._fill))

    def paintEvent(self, event) -> None:  # noqa: N802
        # 背景交给 drawBackground 阶段画好，paintEvent 里只描边框。
        # 不能在 paintEvent 里填背景：那时子控件已经画完了，
        # 一填就把角落的小角色盖掉。
        painter = QPainter(self)
        paint_rough_frame(
            painter,
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            color=self._color,
            width=self._width,
            radius=self._radius,
            seed=self._seed,
            fill=None,
            amplitude=self._amplitude,
        )
        painter.end()
        super().paintEvent(event)

        # 空白处的小花：画在子控件之后，但只落在没被占用的区域
        # RoughButton 也继承本类，没有 _decor 属性，用 getattr 兜底；
        # 否则会在 paintEvent 里抛 AttributeError，整个进程静默退出。
        if getattr(self, "_decor", False) and DOODLE_MODE:
            self._paint_decor()

    def _paint_decor(self) -> None:
        from PyQt6.QtGui import QPixmap

        from .doodle_decor_layer import paint_card_decor

        size = (self.width(), self.height())
        if self._decor_cache is None or self._decor_size != size:
            pixmap = QPixmap(self.size())
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_card_decor(painter, self, seed=self._seed)
            painter.end()
            self._decor_cache = pixmap
            self._decor_size = size

        if self._decor_cache is not None:
            painter = QPainter(self)
            painter.drawPixmap(0, 0, self._decor_cache)
            painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._decor_cache = None
        super().resizeEvent(event)


class RoughButton(QPushButton):
    """手绘模式下的按钮：外形由我们画，文字和图标交给基类。

    关键是把实例级样式表设成「无背景无边框」，基类就只负责画字和图标，
    不会再用 QSS 的圆角矩形盖掉手绘轮廓。
    """

    def __init__(self, text: str = "", parent=None, variant: str = "ghost",
                 radius: float = 9.0, seed: int = 17) -> None:
        super().__init__(text, parent)
        self._variant = variant
        self._radius = radius
        self._seed = seed
        if DOODLE_MODE:
            self.setStyleSheet(
                "QPushButton { background: transparent; border: none; padding: 7px 15px; }"
                "QPushButton:disabled { color: #A9A396; }"
            )

    def paintEvent(self, event) -> None:  # noqa: N802
        if not DOODLE_MODE:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        if self._variant == "primary":
            fill = ACCENT if self.isEnabled() else ACCENT_SOFT
            stroke = ACCENT if self.isEnabled() else ACCENT_SOFT
        elif self._variant == "icon":
            fill = None
            stroke = BORDER_SOFT
        else:
            fill = None
            stroke = BORDER_SOFT

        if self.isDown():
            # 按下时整体下移一点点，像真的按在纸上
            painter.translate(1.0, 1.0)

        paint_rough_frame(
            painter,
            rect,
            color=stroke,
            width=1.5,
            radius=self._radius,
            seed=self._seed,
            fill=fill,
            amplitude=1.1,
        )
        painter.end()
        super().paintEvent(event)

        # 空白处的小花：画在子控件之后，但只落在没被占用的区域
        # RoughButton 也继承本类，没有 _decor 属性，用 getattr 兜底；
        # 否则会在 paintEvent 里抛 AttributeError，整个进程静默退出。
        if getattr(self, "_decor", False) and DOODLE_MODE:
            self._paint_decor()

    def _paint_decor(self) -> None:
        from PyQt6.QtGui import QPixmap

        from .doodle_decor_layer import paint_card_decor

        size = (self.width(), self.height())
        if self._decor_cache is None or self._decor_size != size:
            pixmap = QPixmap(self.size())
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_card_decor(painter, self, seed=self._seed)
            painter.end()
            self._decor_cache = pixmap
            self._decor_size = size

        if self._decor_cache is not None:
            painter = QPainter(self)
            painter.drawPixmap(0, 0, self._decor_cache)
            painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._decor_cache = None
        super().resizeEvent(event)


def rough_arc(rect: QRectF, start_deg: float, span_deg: float, seed: int,
              amplitude: float = 1.6) -> QPainterPath:
    """沿圆弧中线采样，半径做波形起伏——手画的圆从来不是正圆。"""
    rng = random.Random(seed)
    phase = rng.uniform(0, math.tau)
    phase2 = rng.uniform(0, math.tau)

    cx, cy = rect.center().x(), rect.center().y()
    radius = rect.width() / 2
    steps = max(10, int(abs(span_deg) / 3))

    path = QPainterPath()
    for i in range(steps + 1):
        t = i / steps
        angle = math.radians(start_deg + span_deg * t)
        wobble = radius + amplitude * _wave_arc(i * 3.0, phase, phase2)
        x = cx + wobble * math.cos(angle)
        y = cy - wobble * math.sin(angle)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    return path


def _wave_arc(distance: float, phase: float, phase2: float) -> float:
    return 0.62 * math.sin(distance * 0.045 + phase) + 0.38 * math.sin(distance * 0.017 + phase2)


def rough_bar(rect: QRectF, seed: int, amplitude: float = 1.2) -> QPainterPath:
    """条形：直接复用圆角矩形的抖动版本。"""
    return rough_path(rect, radius=min(4.0, rect.height() / 2), seed=seed, amplitude=amplitude)


def rough_ellipse(rect: QRectF, seed: int, amplitude: float = 0.7) -> QPainterPath:
    """小圆点：半径轻微起伏，避免时间轴上排出一列完美圆点。"""
    path = QPainterPath()
    path.addEllipse(rect)
    return roughen_path(path, seed, amplitude)


def roughen_path(path: QPainterPath, seed: int, amplitude: float = 1.0) -> QPainterPath:
    """对任意闭合路径做平滑起伏（卡片、圆点、标签共用）。"""
    rng = random.Random(seed)
    phase = rng.uniform(0, math.tau)
    phase2 = rng.uniform(0, math.tau)

    out = QPainterPath()
    for polygon in path.toSubpathPolygons():
        points = list(polygon)
        if len(points) < 3:
            continue
        travelled = 0.0
        previous = points[0]
        out.moveTo(
            previous.x() + amplitude * _wave_arc(0.0, phase, phase2),
            previous.y() + amplitude * _wave_arc(37.0, phase2, phase),
        )
        for point in points[1:]:
            travelled += math.hypot(point.x() - previous.x(), point.y() - previous.y())
            previous = point
            out.lineTo(
                point.x() + amplitude * _wave_arc(travelled, phase, phase2),
                point.y() + amplitude * _wave_arc(travelled + 37.0, phase2, phase),
            )
        out.closeSubpath()
    return out


# ==================== 手帐手绘高阶视觉组件 ====================


def draw_washi_tape(
    painter: QPainter,
    rect: QRectF,
    color: str = "#E88E85",
    angle: float = 0.0,
    pattern: str = "stripes",
    seed: int = 42,
) -> None:
    """画一段和纸胶带：半透明 + 左右锯齿撕裂边缘 + 胶带花纹。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    cx, cy = rect.center().x(), rect.center().y()
    if abs(angle) > 0.01:
        painter.translate(cx, cy)
        painter.rotate(angle)
        painter.translate(-cx, -cy)

    rng = random.Random(seed)
    left, right = rect.left(), rect.right()
    top, bottom = rect.top(), rect.bottom()
    h = bottom - top

    # 左右锯齿撕裂边缘（Torn paper edges）
    path = QPainterPath()
    path.moveTo(left, top)
    path.lineTo(right, top + (rng.random() - 0.5) * 1.0)

    teeth = max(3, int(h / 4))
    for i in range(1, teeth + 1):
        ty = top + (h / teeth) * i
        tx = right + (rng.random() - 0.5) * 4.0 if i < teeth else right
        path.lineTo(tx, ty)

    path.lineTo(left, bottom + (rng.random() - 0.5) * 1.0)

    for i in range(teeth - 1, -1, -1):
        ty = top + (h / teeth) * i
        tx = left + (rng.random() - 0.5) * 4.0 if i > 0 else left
        path.lineTo(tx, ty)
    path.closeSubpath()

    base_color = QColor(color)
    base_color.setAlpha(195)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(base_color)
    painter.drawPath(path)

    painter.setClipPath(path)

    if pattern == "stripes":
        pen = QPen(QColor(255, 255, 255, 65), 2.5)
        painter.setPen(pen)
        step = 8.0
        x_start = left - h
        while x_start < right + h:
            painter.drawLine(QPointF(x_start, top - 2), QPointF(x_start + h + 4, bottom + 2))
            x_start += step
    elif pattern == "dots":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 80))
        for row in range(int(h / 6)):
            for col in range(int((right - left) / 7)):
                offset = 3.5 if row % 2 else 0.0
                painter.drawEllipse(QPointF(left + 4 + col * 7 + offset, top + 4 + row * 6), 1.3, 1.3)

    border_pen = QPen(QColor(0, 0, 0, 25), 0.8)
    painter.strokePath(path, border_pen)

    painter.restore()


def draw_wavy_underline(
    painter: QPainter,
    x: float,
    y: float,
    width: float,
    color: str = "#D44A3A",
    amplitude: float = 2.0,
    wavelength: float = 9.0,
) -> None:
    """画一条手绘红色/彩色波浪下划线（划重点效果）。"""
    if width <= 4:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    path = QPainterPath()
    path.moveTo(x, y)
    cur_x = x
    step = wavelength / 2
    direction = -1

    while cur_x < x + width:
        next_x = min(cur_x + step, x + width)
        mid_x = (cur_x + next_x) / 2
        path.quadTo(mid_x, y + direction * amplitude, next_x, y)
        cur_x = next_x
        direction *= -1

    pen = QPen(QColor(color))
    pen.setWidthF(1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)

    echo_pen = QPen(QColor(color))
    echo_pen.setColor(QColor(color).lighter(120))
    echo_pen.setWidthF(0.9)
    painter.setPen(echo_pen)
    painter.translate(0.4, -0.3)
    painter.drawPath(path)

    painter.restore()


def draw_highlighter_stroke(
    painter: QPainter,
    rect: QRectF,
    color: str,
    seed: int = 0,
) -> None:
    """画一段马克笔/荧光笔涂抹条（用于应用排行、进度条等）。"""
    if rect.width() <= 1 or rect.height() <= 1:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    rng = random.Random(seed)
    left = rect.left()
    right = rect.right()
    top = rect.top()
    bottom = rect.bottom()

    path = QPainterPath()
    tilt_left = 2.0 + rng.uniform(-0.5, 0.5)
    tilt_right = 2.5 + rng.uniform(-0.5, 0.5)

    path.moveTo(left + tilt_left, top + rng.uniform(-0.4, 0.4))
    path.lineTo(right - tilt_right * 0.3, top + rng.uniform(-0.4, 0.4))
    path.lineTo(right, bottom + rng.uniform(-0.4, 0.4))
    path.lineTo(left, bottom + rng.uniform(-0.4, 0.4))
    path.closeSubpath()

    fill_color = QColor(color)
    fill_color.setAlpha(175)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill_color)
    painter.drawPath(path)

    end_blob = QRectF(right - min(6.0, rect.width() * 0.3), top, min(6.0, rect.width() * 0.3), rect.height())
    blob_color = QColor(color)
    blob_color.setAlpha(65)
    painter.setBrush(blob_color)
    painter.drawRoundedRect(end_blob, 2.0, 2.0)

    painter.restore()


def draw_sketch_donut_pie(
    painter: QPainter,
    center: QPointF,
    r_outer: float,
    r_inner: float,
    start_deg: float,
    span_deg: float,
    fill_color: str,
    stroke_color: str,
    seed: int = 0,
) -> None:
    """手绘扇环：外圈起伏 + 内圈起伏 + 水彩/彩铅平涂与排线质感。"""
    if abs(span_deg) < 0.5:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    rng = random.Random(seed)
    phase1 = rng.uniform(0, math.tau)
    phase2 = rng.uniform(0, math.tau)

    steps = max(8, int(abs(span_deg) / 3.5))
    path = QPainterPath()

    # 外圈
    for i in range(steps + 1):
        t = i / steps
        deg = start_deg + span_deg * t
        rad = math.radians(deg)
        wobble = r_outer + 1.2 * (0.6 * math.sin(phase1 + t * 4) + 0.4 * math.sin(phase2 + t * 8))
        x = center.x() + wobble * math.cos(rad)
        y = center.y() - wobble * math.sin(rad)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)

    # 内圈
    for i in range(steps, -1, -1):
        t = i / steps
        deg = start_deg + span_deg * t
        rad = math.radians(deg)
        wobble = r_inner + 0.9 * (0.6 * math.sin(phase2 + t * 4) + 0.4 * math.sin(phase1 + t * 8))
        x = center.x() + wobble * math.cos(rad)
        y = center.y() - wobble * math.sin(rad)
        path.lineTo(x, y)

    path.closeSubpath()

    # 水彩/彩铅平涂
    fc = QColor(fill_color)
    fc.setAlpha(205)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fc)
    painter.drawPath(path)

    # 手绘轮廓描边
    pen = QPen(QColor(stroke_color))
    pen.setWidthF(1.3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)

    # 内部铅笔轻微排线
    if abs(span_deg) >= 16:
        painter.setClipPath(path)
        hatch_pen = QPen(QColor(stroke_color))
        hatch_pen.setColor(QColor(stroke_color).lighter(115))
        hatch_pen.setWidthF(0.9)
        painter.setPen(hatch_pen)
        hatch_step = 6.0
        hatch_span = int(abs(span_deg) / hatch_step)
        for h in range(1, hatch_span):
            h_deg = start_deg + math.copysign(h * hatch_step, span_deg)
            h_rad = math.radians(h_deg)
            x1 = center.x() + (r_inner + 2) * math.cos(h_rad)
            y1 = center.y() - (r_inner + 2) * math.sin(h_rad)
            x2 = center.x() + (r_outer - 2) * math.cos(h_rad)
            y2 = center.y() - (r_outer - 2) * math.sin(h_rad)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    painter.restore()


def draw_notebook_background(
    painter: QPainter,
    rect: QRectF,
    is_dark: bool = False,
    step: float = 24.0,
) -> None:
    """画手帐点阵（Paper模式）或黑板微粉笔颗粒（Dark模式）。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    if not is_dark:
        dot_color = QColor(190, 180, 165, 55)
        painter.setPen(dot_color)
        x = rect.left() + step
        while x < rect.right():
            y = rect.top() + step
            while y < rect.bottom():
                painter.drawPoint(QPointF(x, y))
                y += step
            x += step
    else:
        dot_color = QColor(255, 255, 255, 22)
        painter.setPen(dot_color)
        x = rect.left() + step
        while x < rect.right():
            y = rect.top() + step
            while y < rect.bottom():
                painter.drawPoint(QPointF(x, y))
                y += step
            x += step

    painter.restore()


def draw_rank_badge(
    painter: QPainter,
    center: QPointF,
    rank: int,
    color: str = "#E09F3E",
) -> None:
    """画手绘圆圈排名徽章：① ② ③ 风格。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    circle_path = rough_ellipse(QRectF(center.x() - 8, center.y() - 8, 16, 16), seed=rank * 17, amplitude=0.8)
    if rank <= 3:
        bg = QColor(color)
        bg.setAlpha(45)
        painter.setBrush(bg)
    else:
        painter.setBrush(Qt.BrushStyle.NoBrush)

    pen = QPen(QColor(color), 1.3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawPath(circle_path)

    painter.setPen(QColor(color))
    font = painter.font()
    font.setPixelSize(10)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(
        QRectF(center.x() - 8, center.y() - 8, 16, 16),
        Qt.AlignmentFlag.AlignCenter,
        str(rank),
    )

    painter.restore()
