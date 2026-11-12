"""红笔批注：圈注、下划线、箭头、手写小字。

手绘风格里，纸和框只是底子；真正让人觉得「有人用过」的是红笔留下的痕迹。
这里的每个元素都故意画得歪一点、接口留一点余量，因为批注本来就不该工整。
"""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

from .theme import DANGER, DOODLE_MODE

RED = DANGER


def _wave_offset(distance: float, phase: float, phase2: float) -> float:
    return 0.62 * math.sin(distance * 0.035 + phase) + 0.38 * math.sin(distance * 0.011 + phase2)


def _roughen(path: QPainterPath, seed: int, amplitude: float) -> QPainterPath:
    """沿路径距离做平滑起伏，形状不变、边不再完美。"""
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
            previous.x() + amplitude * _wave_offset(0.0, phase, phase2),
            previous.y() + amplitude * _wave_offset(37.0, phase2, phase),
        )
        for point in points[1:]:
            travelled += math.hypot(point.x() - previous.x(), point.y() - previous.y())
            previous = point
            out.lineTo(
                point.x() + amplitude * _wave_offset(travelled, phase, phase2),
                point.y() + amplitude * _wave_offset(travelled + 37.0, phase2, phase),
            )
        out.closeSubpath()
    return out


def _pen(width: float, alpha: int = 255) -> QPen:
    color = QColor(RED)
    color.setAlpha(alpha)
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def draw_red_circle(painter: QPainter, rect: QRectF, seed: int = 5, width: float = 1.8) -> None:
    """在文字外面圈一圈，圈不会完全闭合——手圈就是这样。"""
    shape = QPainterPath()
    shape.addEllipse(rect)
    rough = _roughen(shape, seed, 2.0)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(_pen(width))
    painter.drawPath(rough)
    # 第二笔补在缺口处，模拟回头描一下
    painter.setPen(_pen(width * 0.7, 170))
    painter.drawPath(_roughen(shape, seed + 11, 3.0))
    painter.restore()


def draw_red_underline(painter: QPainter, x1: float, y: float, x2: float, seed: int = 3) -> None:
    """两笔的下划线：一粗一细，长度不一致。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    rng = random.Random(seed)
    first = QPainterPath()
    first.moveTo(x1, y)
    first.quadTo((x1 + x2) / 2, y + rng.uniform(-1.5, 1.5), x2, y + rng.uniform(-1.0, 1.0))
    painter.setPen(_pen(2.2))
    painter.drawPath(_roughen(first, seed, 0.9))

    second = QPainterPath()
    second.moveTo(x1 + 6, y + 3.5)
    second.quadTo((x1 + x2) / 2 + 4, y + 2.6, x2 - rng.uniform(0, 18), y + 3.2)
    painter.setPen(_pen(1.3, 160))
    painter.drawPath(_roughen(second, seed + 7, 0.7))
    painter.restore()


def draw_red_arrow(painter: QPainter, start: QPointF, end: QPointF, seed: int = 9) -> None:
    """一条弯一点的红箭头，末端一个小三角。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    mid = QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2 - 14)
    shaft = QPainterPath(start)
    shaft.quadTo(mid, end)
    painter.setPen(_pen(1.9))
    painter.drawPath(_roughen(shaft, seed, 1.2))

    angle = math.atan2(end.y() - mid.y(), end.x() - mid.x())
    size = 7.0
    left = QPointF(
        end.x() - size * math.cos(angle - 0.45),
        end.y() - size * math.sin(angle - 0.45),
    )
    right = QPointF(
        end.x() - size * math.cos(angle + 0.45),
        end.y() - size * math.sin(angle + 0.45),
    )
    painter.setPen(_pen(1.9))
    painter.drawLine(end, left)
    painter.drawLine(end, right)
    painter.restore()


def draw_red_note(
    painter: QPainter,
    x: float,
    y: float,
    text: str,
    size: int = 12,
    angle: float = -2.0,
) -> None:
    """手写小字：用楷体 + 轻微旋转，避免像打印的标签。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont("KaiTi", size)
    painter.setFont(font)
    painter.setPen(QColor(RED))
    painter.translate(x, y)
    painter.rotate(angle)
    painter.drawText(QPointF(0, 0), text)
    painter.restore()


def doodle_marks_enabled() -> bool:
    return DOODLE_MODE
