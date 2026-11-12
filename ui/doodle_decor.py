"""童趣小装饰：小花、星星、小圆点、草叶。

为什么要有：
界面再精致也是"信息"，缺一点"没用但可爱"的东西。小孩画画时会在
页边画花、画星、点几个彩色圆点——这些东西不承载任何信息，
但会让整页从"报表"变成"手账"。

设计约束：
- 全部用代码画，不用图片：尺寸可变、颜色跟主题走、零加载开销；
- 笔画要抖：花瓣边缘不能是完美的贝塞尔曲线；
- 只出现在空白处，绝不压在文字上（由调用方保证位置）。
"""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen

from .theme import ACCENT, DOODLE_MODE, DOODLE_RED, IS_DARK_SKIN

# 童趣配色：柔和、明亮、彼此能区分
# 花瓣色：故意避开黄色系，因为花心固定用暖黄，
# 花瓣再来黄色整朵花就糊成一片黄。
PETAL_COLORS_DARK = ["#E8A0A8", "#82A9D6", "#C9A8D8", "#A6BE91", "#E8A8B8"]
PETAL_COLORS_LIGHT = ["#E88E85", "#7FA3CC", "#B394C8", "#8FAE7A", "#E8A0A0"]


def _jitter(seed: int, scale: float = 1.0) -> float:
    return (random.Random(seed).random() - 0.5) * 2 * scale


def draw_flower(
    painter: QPainter,
    center: QPointF,
    radius: float,
    seed: int = 0,
    color: str | None = None,
    petals: int = 5,
    stem: bool = True,
    tilt: float = 0.0,
) -> None:
    """画一朵小花：花瓣 + 花心 + 可选的茎。

    花瓣用椭圆绕中心排布，每个花瓣带一点随机扭转，
    避免五瓣完全对称——手画的花不会那么准。
    """
    palette = PETAL_COLORS_DARK if IS_DARK_SKIN else PETAL_COLORS_LIGHT
    petal_color = QColor(color or palette[seed % len(palette)])

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if tilt:
        # 整朵花歪一点，像随手画的
        painter.translate(center)
        painter.rotate(tilt)
        painter.translate(-center.x(), -center.y())

    # 茎：一条微微弯的线，从花心往下
    if stem:
        stem_len = radius * 2.1
        path = QPainterPath(QPointF(center.x(), center.y() + radius * 0.4))
        bend = _jitter(seed + 1, radius * 0.28)
        path.quadTo(
            center.x() + bend,
            center.y() + radius * 1.2,
            center.x() + bend * 0.6,
            center.y() + stem_len,
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#8FAE7A" if not IS_DARK_SKIN else "#7E9468"), 1.4))
        painter.drawPath(path)

        # 一片叶子：两段弧拼成的尖椭圆
        leaf_y = center.y() + stem_len * 0.72
        leaf = QPainterPath(QPointF(center.x() + bend * 0.7, leaf_y))
        leaf.quadTo(
            center.x() + bend * 0.7 + radius * 0.9,
            leaf_y - radius * 0.5,
            center.x() + bend * 0.7 + radius * 0.55,
            leaf_y + radius * 0.35,
        )
        leaf.quadTo(
            center.x() + bend * 0.7 + radius * 0.2,
            leaf_y + radius * 0.1,
            center.x() + bend * 0.7,
            leaf_y,
        )
        painter.setBrush(QColor("#8FAE7A" if not IS_DARK_SKIN else "#7E9468"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(leaf)

    # 花瓣：绕中心排一圈椭圆
    painter.setPen(Qt.PenStyle.NoPen)
    for index in range(petals):
        angle = (360.0 / petals) * index + _jitter(seed * 7 + index, 9.0)
        rad = math.radians(angle)
        # 花瓣中心离花心的距离
        dist = radius * 0.52
        cx = center.x() + math.cos(rad) * dist
        cy = center.y() + math.sin(rad) * dist

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(angle + 90)
        c = QColor(petal_color)
        c.setAlpha(228)
        painter.setBrush(c)
        painter.drawEllipse(
            QRectF(-radius * 0.40, -radius * 0.52, radius * 0.80, radius * 1.04)
        )
        painter.restore()

    # 花心
    painter.setBrush(QColor(ACCENT) if not IS_DARK_SKIN else QColor("#E8C070"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(center, radius * 0.30, radius * 0.30)

    painter.restore()


def draw_star(
    painter: QPainter,
    center: QPointF,
    radius: float,
    color: str | None = None,
    points: int = 5,
    seed: int = 0,
    tilt: float = 0.0,
) -> None:
    """四角或五角小星星，边角带抖动。"""
    palette = PETAL_COLORS_DARK if IS_DARK_SKIN else PETAL_COLORS_LIGHT
    col = QColor(color or palette[(seed + 1) % len(palette)])

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(col)
    if tilt:
        painter.translate(center)
        painter.rotate(tilt)
        painter.translate(-center.x(), -center.y())

    path = QPainterPath()
    for index in range(points * 2):
        angle = math.radians(90 + index * (360.0 / (points * 2)))
        r = radius if index % 2 == 0 else radius * 0.42
        r += _jitter(seed * 3 + index, radius * 0.08)
        x = center.x() + math.cos(angle) * r
        y = center.y() - math.sin(angle) * r
        if index == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    painter.drawPath(path)
    painter.restore()


def draw_sparkle(
    painter: QPainter,
    center: QPointF,
    size: float,
    color: str | None = None,
) -> None:
    """四道放射线的小亮点，比星星更轻。"""
    palette = PETAL_COLORS_DARK if IS_DARK_SKIN else PETAL_COLORS_LIGHT
    col = QColor(color or palette[3])
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(col, max(1.2, size * 0.16), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    for angle in (0, 90, 180, 270):
        rad = math.radians(angle)
        painter.drawLine(
            QPointF(center.x() + math.cos(rad) * size * 0.35,
                    center.y() + math.sin(rad) * size * 0.35),
            QPointF(center.x() + math.cos(rad) * size,
                    center.y() + math.sin(rad) * size),
        )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(col)
    painter.drawEllipse(center, size * 0.18, size * 0.18)
    painter.restore()


def draw_dots(
    painter: QPainter,
    origin: QPointF,
    count: int = 3,
    spacing: float = 7.0,
    radius: float = 2.0,
    seed: int = 0,
) -> None:
    """一排小圆点，像小朋友在页边点的。"""
    palette = PETAL_COLORS_DARK if IS_DARK_SKIN else PETAL_COLORS_LIGHT
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    for index in range(count):
        col = QColor(palette[(seed + index) % len(palette)])
        col.setAlpha(200)
        painter.setBrush(col)
        painter.drawEllipse(
            QPointF(origin.x() + index * spacing, origin.y() + _jitter(seed + index, 1.2)),
            radius,
            radius,
        )
    painter.restore()


def draw_grass(
    painter: QPainter,
    origin: QPointF,
    width: float,
    count: int = 3,
    height: float = 9.0,
    seed: int = 0,
) -> None:
    """小草丛：几根弯弯的短线。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#8FAE7A" if not IS_DARK_SKIN else "#7E9468"), 1.3)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for index in range(count):
        x = origin.x() + index * (width / max(1, count))
        lean = _jitter(seed * 5 + index, width * 0.12)
        h = height * (0.7 + 0.3 * random.Random(seed + index).random())
        path = QPainterPath(QPointF(x, origin.y()))
        path.quadTo(x + lean * 0.5, origin.y() - h * 0.6, x + lean, origin.y() - h)
        painter.drawPath(path)
    painter.restore()


def draw_page_decor(
    painter: QPainter,
    rect,
    seed: int = 0,
    scale: float = 1.0,
) -> None:
    """在一小块空白区域里撒一组装饰：一朵花 + 一颗星 + 几点。

    rect 是留给装饰的空白框，这里只保证不画出框外。
    """
    rng = random.Random(seed or 3)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    if w < 30 or h < 30:
        return

    base = min(w, h) * scale

    # 主花：放在左下，留出呼吸
    flower_r = base * 0.13
    draw_flower(
        painter,
        QPointF(x + base * 0.22, y + h * 0.52),
        flower_r,
        seed=seed,
        stem=True,
    )
    # 小花：右上一点
    draw_flower(
        painter,
        QPointF(x + w * 0.72, y + h * 0.28),
        flower_r * 0.62,
        seed=seed + 3,
        stem=False,
        petals=4,
    )
    # 星星
    draw_star(
        painter,
        QPointF(x + w * 0.56, y + h * 0.66),
        base * 0.075,
        seed=seed + 5,
    )
    # 小点
    draw_dots(
        painter,
        QPointF(x + w * 0.40, y + h * 0.20),
        count=3,
        spacing=base * 0.09,
        radius=base * 0.022,
        seed=seed + 7,
    )


class DecorStrip(QWidget):
    """可以放进布局的小装饰条。

    用在状态栏的空白处：不会撑大布局，只占给定的宽度。
    内容是"一朵小花 + 一颗星 + 几粒点"，纯装饰，无交互。
    """

    def __init__(self, parent=None, width: int = 120, height: int = 26, seed: int = 0) -> None:
        super().__init__(parent)
        self._seed = seed
        self.setFixedSize(width, height)
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        if not DOODLE_MODE:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cy = h * 0.5

        # 宽条布局：花 + 星 + 花 + 点，按宽度均匀摊开
        unit = w / 5.0
        r = h * 0.34
        draw_flower(painter, QPointF(unit * 0.7, cy), r, seed=self._seed, stem=False)
        draw_star(painter, QPointF(unit * 1.9, cy), r * 0.78, seed=self._seed + 2)
        draw_flower(painter, QPointF(unit * 3.1, cy), r * 0.82, seed=self._seed + 4,
                    stem=False, petals=4)
        draw_dots(painter, QPointF(unit * 4.0, cy), count=3, spacing=h * 0.30,
                  radius=h * 0.080, seed=self._seed + 6)
        painter.end()


class DecorSlot(QWidget):
    """卡片标题行右侧的装饰槽。

    **不做成整齐排列**。手账的质感来自不规则：每朵花大小不同、高低错落、
    颜色随机、角度各自歪一点。这里用种子驱动的随机数生成布局，
    同一个种子每次画出来一样（不会闪烁），不同卡片各不相同。
    """

    def __init__(self, parent=None, width: int = 210, height: int = 40, seed: int = 0) -> None:
        super().__init__(parent)
        self._seed = seed
        self.setFixedSize(width, height)
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._layout = self._make_layout()

    def _make_layout(self) -> list[dict]:
        """按种子生成一组散落的元素，每个带自己的位置/大小/角度/颜色索引。"""
        rng = random.Random(self._seed * 977 + 31)
        w, h = self.width(), self.height()
        items: list[dict] = []

        # 2~4 个元素，数量本身也随机
        count = rng.choice([2, 3, 3, 4])
        cursor = 6.0
        for i in range(count):
            kind = rng.choices(
                ["flower", "star", "dots", "grass", "small_flower"],
                weights=[4, 2, 2, 2, 3],
            )[0]
            size_ratio = rng.uniform(0.30, 0.62)
            r = h * size_ratio

            # 纵向随机偏移：这是"不规则"最关键的来源
            cy = h * rng.uniform(0.34, 0.70)
            cx = cursor + r * rng.uniform(0.5, 1.1)

            items.append({
                "kind": kind,
                "x": cx,
                "y": cy,
                "r": r,
                "rot": rng.uniform(-16, 16),
                "ci": rng.randrange(5),
                "stem": rng.random() < 0.55,
                "petals": rng.choice([4, 5, 5, 6]),
            })
            cursor = cx + r * rng.uniform(1.3, 2.0)
            if cursor > w - 8:
                break
        return items

    def paintEvent(self, event) -> None:  # noqa: N802
        if not DOODLE_MODE:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = PETAL_COLORS_DARK if IS_DARK_SKIN else PETAL_COLORS_LIGHT

        for it in self._layout:
            center = QPointF(it["x"], it["y"])
            color = palette[it["ci"] % len(palette)]
            kind = it["kind"]

            if kind == "flower":
                draw_flower(painter, center, it["r"] * 0.62, seed=self._seed + it["ci"],
                            color=color, stem=it["stem"], petals=it["petals"],
                            tilt=it["rot"])
            elif kind == "small_flower":
                draw_flower(painter, center, it["r"] * 0.46, seed=self._seed + it["ci"] + 7,
                            color=color, stem=False, petals=4, tilt=it["rot"] * 1.4)
            elif kind == "star":
                draw_star(painter, center, it["r"] * 0.52, color=color,
                          seed=self._seed + it["ci"] + 3, tilt=it["rot"])
            elif kind == "dots":
                draw_dots(painter, QPointF(center.x() - it["r"] * 0.5, center.y()),
                          count=rng_dots(self._seed), spacing=it["r"] * 0.34,
                          radius=it["r"] * 0.11, seed=self._seed + it["ci"])
            else:
                draw_grass(painter, QPointF(center.x(), center.y() + it["r"] * 0.5),
                           width=it["r"] * 0.7, count=3, height=it["r"] * 0.8,
                           seed=self._seed + it["ci"])

        painter.end()


def rng_dots(seed: int) -> int:
    return random.Random(seed + 991).choice([2, 3, 3, 4])




class ScatterDecor(QWidget):
    """散落在卡片空白处的装饰层。

    和 DecorSlot 的区别：这个**不占布局空间**，铺满整张卡片，
    但只往"实测空白"的位置画元素。

    为什么这次敢用浮层：它不 move，而是铺满父容器 + 逐点检测空白。
    位置由像素决定，不由布局推算，所以不存在"算错坐标"的问题。
    """

    def __init__(self, parent, blank_mask: list[QRectF], seed: int = 0, density: int = 3) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")
        self._seed = seed
        self._density = density
        self._mask = blank_mask
        self._items: list[dict] = []
        self._built_size = None
        self.resize(parent.size())

    def _build(self) -> None:
        """在空白框里随机撒元素，位置/大小/角度/颜色全随机。"""
        rng = random.Random(self._seed * 733 + 17)
        self._items = []
        for box in self._mask:
            n = rng.choice([1, 2, 2, 3]) if self._density <= 2 else rng.choice([2, 2, 3, 3, 4])
            for _ in range(n):
                # 在框里随机取点，留出元素半径的边距
                r = min(box.width(), box.height()) * rng.uniform(0.22, 0.40)
                if r < 4:
                    continue
                pad = r * 1.3
                if box.width() < pad * 2 or box.height() < pad * 2:
                    continue
                x = rng.uniform(box.left() + pad, box.right() - pad)
                y = rng.uniform(box.top() + pad, box.bottom() - pad)
                kind = rng.choices(
                    ["flower", "star", "dots", "grass", "small_flower"],
                    weights=[4, 3, 2, 2, 3],
                )[0]
                self._items.append({
                    "kind": kind, "x": x, "y": y, "r": r,
                    "rot": rng.uniform(-22, 22),
                    "ci": rng.randrange(5),
                    "stem": rng.random() < 0.5,
                    "petals": rng.choice([4, 5, 5, 6]),
                })

    def paintEvent(self, event) -> None:  # noqa: N802
        if not DOODLE_MODE:
            return
        if self._built_size != (self.width(), self.height()):
            self._build()
            self._built_size = (self.width(), self.height())

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = PETAL_COLORS_DARK if IS_DARK_SKIN else PETAL_COLORS_LIGHT

        for it in self._items:
            c = QPointF(it["x"], it["y"])
            color = palette[it["ci"] % len(palette)]
            k = it["kind"]
            if k == "flower":
                draw_flower(painter, c, it["r"] * 0.66, seed=self._seed + it["ci"],
                            color=color, stem=it["stem"], petals=it["petals"],
                            tilt=it["rot"])
            elif k == "small_flower":
                draw_flower(painter, c, it["r"] * 0.50, seed=self._seed + it["ci"] + 5,
                            color=color, stem=False, petals=4, tilt=it["rot"] * 1.5)
            elif k == "star":
                draw_star(painter, c, it["r"] * 0.55, color=color,
                          seed=self._seed + it["ci"] + 2, tilt=it["rot"])
            elif k == "dots":
                draw_dots(painter, QPointF(c.x() - it["r"] * 0.6, c.y()),
                          count=rng_dots(self._seed + it["ci"]),
                          spacing=it["r"] * 0.38, radius=it["r"] * 0.12,
                          seed=self._seed + it["ci"])
            else:
                draw_grass(painter, QPointF(c.x(), c.y() + it["r"] * 0.5),
                           width=it["r"] * 0.8, count=3, height=it["r"] * 0.9,
                           seed=self._seed + it["ci"])
        painter.end()
