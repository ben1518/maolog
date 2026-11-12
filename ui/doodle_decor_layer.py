"""把童趣装饰撒到界面的空白处。

关键原则：**装饰只许出现在空白里**。
之前便签压在按钮上就是因为没做遮挡检测，这里先算出所有子控件的占位，
再挑空的地方画。
"""

from __future__ import annotations

import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget

from .doodle_decor import draw_dots, draw_flower, draw_grass, draw_star
from .theme import DOODLE_MODE


# 自绘数据控件的类名：它们自己 paintEvent，没有文字子控件，
# 如果不显式列入，装饰就会直接压在图表、时间轴、应用排行上。
PAINTED_WIDGET_NAMES = {
    "TimelineWidget",
    "DonutChart",
    "AppRankWidget",
    "PulseBar",
    "RingProgress",
    "StickerNote",
    "StickyNote",
    "PetCorner",
}

SKIP_NAMES = {"PetCorner", "StickyNote"}


def occupied_rects(host: QWidget, inflate: int = 8) -> list[QRectF]:
    """收集 host 里**所有**可见子控件的占位，不只是文字控件。

    之前的版本只收 QLabel/QPushButton，漏掉了自绘的图表和时间轴，
    结果就是装饰压在应用排行和分类环上。

    现在分三层：
    1. 自绘数据控件（TimelineWidget/DonutChart/AppRankWidget 等）整块都算占用；
    2. 文字与按钮照常算占用；
    3. 纯装饰（宠物、便签）只算占位、不算禁区（它们自己会让开）。
    """
    rects: list[QRectF] = []
    for child in host.findChildren(QWidget):
        if child is host or not child.isVisible():
            continue
        cls = type(child).__name__
        if cls in SKIP_NAMES:
            # 宠物和便签不算占用——它们是装饰，不是内容
            continue

        is_painted = cls in PAINTED_WIDGET_NAMES or hasattr(child, "paintEvent")
        has_text = isinstance(child, (QLabel, QPushButton)) and child.text().strip()

        if not (is_painted or has_text):
            # 普通容器不算占用，否则整块都是禁区
            continue

        top = child.mapTo(host, child.rect().topLeft())
        rects.append(
            QRectF(
                top.x() - inflate,
                top.y() - inflate,
                child.width() + inflate * 2,
                child.height() + inflate * 2,
            )
        )
    return rects


def free_spots(
    host: QWidget,
    size: int = 46,
    count: int = 3,
    seed: int = 0,
) -> list[QRectF]:
    """在 host 里找几块没被占用的空白，返回可放装饰的方框。"""
    if not DOODLE_MODE:
        return []

    busy = occupied_rects(host)
    rng = random.Random(seed or 11)

    spots: list[QRectF] = []
    w, h = host.width(), host.height()
    if w < size or h < size:
        return []

    # 随机试探：撒点，撞到占用区就重来
    attempts = 0
    while len(spots) < count and attempts < 260:
        attempts += 1
        x = rng.randint(12, max(12, w - size - 12))
        y = rng.randint(12, max(12, h - size - 12))
        box = QRectF(x, y, size, size)

        if any(box.intersects(r) for r in busy):
            continue
        if any(box.intersects(s.adjusted(-8, -8, 8, 8)) for s in spots):
            continue
        spots.append(box)

    return spots


def _preset_corners(card_w: int, card_h: int, size: int) -> list[QRectF]:
    """候选装饰位，按"最可能空"排序。

    关键经验：**别往正文区域塞**。
    卡片正文是图表/时间轴/排行，自绘画布整块都算占用，
    唯一能安全放装饰的地方是：
    - 标题栏右边横向空白（文字只占左边一小段）
    - 卡片最右侧那条窄带（正文通常居中，右边缘有空）
    - 卡片底部但要在左下角（右下是宠物位）
    """
    m = 8
    return [
        # 顶部：标题结束处往右（中文标题 6 字约 100px，起点 120 就够）
        QRectF(140, 12, size, size),
        QRectF(220, 12, size, size),
        QRectF(card_w * 0.45, 12, size, size),
        # 底部靠左（正文一般居中，左边大概率空）
        QRectF(m, card_h - size - m, size, size),
        # 底部偏右但留出宠物位（右下 90px 给猫狗）
        QRectF(card_w - size - m - 90, card_h - size - m, size, size),
    ]


def card_free_spots(card: QWidget, size: int = 44, seed: int = 0) -> list[QRectF]:
    """在卡片**内部**找空白。

    卡片铺满页面时页面层几乎没有空隙，装饰只能落在卡片里。
    同时要避开角落的小动物（它是 QWidget 子控件，会被 occupied_rects 收进去）。
    """
    if not DOODLE_MODE:
        return []

    busy = occupied_rects(card, inflate=4)
    # 卡片自己的标题栏、正文都已经在 busy 里
    rng = random.Random(seed or 23)

    spots: list[QRectF] = []
    w, h = card.width(), card.height()
    if w < size + 24 or h < size + 24:
        return []

    def usable(box: QRectF) -> bool:
        if box.right() > w - 8 or box.bottom() > h - 8:
            return False
        if any(box.intersects(r) for r in busy):
            return False
        return not any(box.intersects(s2.adjusted(-8, -8, 8, 8)) for s2 in spots)

    # 先试预设角落
    for box in _preset_corners(w, h, size):
        if usable(box):
            spots.append(box)
        if len(spots) >= 3:
            return spots

    # 不够再随机补
    for _ in range(220):
        if len(spots) >= 3:
            break
        x = rng.randint(14, max(14, w - size - 14))
        y = rng.randint(26, max(26, h - size - 14))
        box = QRectF(x, y, size, size)
        if usable(box):
            spots.append(box)

    return spots


def paint_card_decor(painter: QPainter, card: QWidget, seed: int = 0) -> None:
    """在卡片内部的空白处画一两朵小花。"""
    if not DOODLE_MODE:
        return
    # 每块空白按序轮换三种组合：花 / 星+点 / 双花+草
    for index, box in enumerate(card_free_spots(card, size=66, seed=seed)):
        kind = (seed + index) % 3
        cx, cy = box.center().x(), box.center().y()

        if kind == 0:
            draw_flower(painter, QPointF(cx, cy - 4), box.width() * 0.30,
                        seed=seed + index * 6, stem=True)
            draw_dots(painter, QPointF(box.left() + 2, box.top() + 6),
                      count=2, spacing=6.5, radius=1.9, seed=seed + index)

        elif kind == 1:
            draw_star(painter, QPointF(cx, cy), box.width() * 0.26,
                      seed=seed + index * 9)
            draw_flower(painter, QPointF(box.left() + 10, box.bottom() - 6),
                        box.width() * 0.16, seed=seed + index * 4,
                        stem=False, petals=4)

        else:
            # 一大一小两朵，配一小丛草，最像手账
            draw_flower(painter, QPointF(cx - 8, cy - 2), box.width() * 0.24,
                        seed=seed + index * 5, stem=True)
            draw_flower(painter, QPointF(cx + 14, cy + 8), box.width() * 0.16,
                        seed=seed + index * 8, stem=False, petals=4)
            draw_grass(painter, QPointF(box.left() + 4, box.bottom()),
                       width=14, count=3, height=9, seed=seed + index)


def page_decor_spots(host: QWidget, size: int = 60) -> list[QRectF]:
    """页面级留白：页眉右侧、页脚。

    这两块区域永远空着（页眉左边是品牌、右边是操作按钮，页脚什么都没），
    比在卡片内部碰运气可靠。
    """
    w, h = host.width(), host.height()
    busy = occupied_rects(host, inflate=4)
    candidates = [
        # 页眉右端（操作按钮一般到 85% 就结束）
        QRectF(w * 0.90, 14, size, size),
        QRectF(w * 0.82, 16, size, size),
        # 页脚（卡片底边通常在 h-45 之上）
        QRectF(w * 0.06, h - size - 4, size, size),
        QRectF(w * 0.20, h - size - 6, size, size),
        QRectF(w - size - 24, h - size - 4, size, size),
    ]
    return [
        box
        for box in candidates
        if box.right() <= w - 6
        and box.bottom() <= h - 2
        and not any(box.intersects(r) for r in busy)
    ]


def paint_free_decor(painter: QPainter, host: QWidget, seed: int = 0) -> None:
    """在页面留白处画花和星星。"""
    if not DOODLE_MODE:
        return

    for index, box in enumerate(page_decor_spots(host, size=58)):
        kind = (seed + index) % 3
        cx, cy = box.center().x(), box.center().y()
        if kind == 0:
            draw_flower(painter, QPointF(cx, cy - 3), box.width() * 0.30,
                        seed=seed + index * 5, stem=True)
        elif kind == 1:
            draw_star(painter, QPointF(cx, cy), box.width() * 0.24,
                      seed=seed + index * 7)
            draw_dots(painter, QPointF(box.left(), box.bottom() - 5),
                      count=3, spacing=6.0, radius=1.9, seed=seed + index)
        else:
            draw_flower(painter, QPointF(cx - 6, cy), box.width() * 0.24,
                        seed=seed + index * 3, stem=True)
            draw_flower(painter, QPointF(cx + 16, cy + 10), box.width() * 0.15,
                        seed=seed + index * 9, stem=False, petals=4)


def probe_blank_regions(card: QWidget, min_size: int = 22) -> list[QRectF]:
    """从卡片实际渲染像素里找空白块。

    这是唯一可靠的空白判断方式：
    布局几何会说"这里是空的"，但图表可能已经画到那里了；
    像素不会骗人——背景色的地方就是真的空的。

    做法：把卡片截图按 10px 网格切块，全背景色的块标为空，
    再把相邻空块合并成矩形。
    """
    if not DOODLE_MODE or card.width() < 60 or card.height() < 60:
        return []

    from PyQt6.QtGui import QColor, QImage

    from .theme import BG_CARD

    img = card.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    dpr_x = img.width() / max(1, card.width())
    bgc = QColor(BG_CARD)

    def is_bg(x: int, y: int) -> bool:
        c = img.pixelColor(x, y)
        return (
            abs(c.red() - bgc.red()) < 7
            and abs(c.green() - bgc.green()) < 7
            and abs(c.blue() - bgc.blue()) < 7
        )

    cell = 10
    cols = int(card.width() // cell)
    rows = int(card.height() // cell)
    if cols < 3 or rows < 3:
        return []

    # 网格标记：True = 全空
    grid = [[False] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            x0 = int(c * cell * dpr_x)
            y0 = int(r * cell * dpr_x)
            step = max(1, int(5 * dpr_x))
            empty = True
            for dx in range(0, int(cell * dpr_x), step):
                for dy in range(0, int(cell * dpr_x), step):
                    px, py = x0 + dx, y0 + dy
                    if px < img.width() and py < img.height() and not is_bg(px, py):
                        empty = False
                        break
                if not empty:
                    break
            grid[r][c] = empty

    # 合并连续空块（按行扫，再向下延伸）
    used = [[False] * cols for _ in range(rows)]
    boxes: list[QRectF] = []
    need = max(2, min_size // cell)
    for r in range(rows):
        for c in range(cols):
            if not grid[r][c] or used[r][c]:
                continue
            # 向右extend
            w = 0
            while c + w < cols and grid[r][c + w] and not used[r][c + w]:
                w += 1
            # 向下 extend（要求整行都空）
            h = 1
            while r + h < rows and all(
                grid[r + h][c + i] and not used[r + h][c + i] for i in range(w)
            ):
                h += 1
            if w >= need and h >= need:
                for rr in range(r, r + h):
                    for cc in range(c, c + w):
                        used[rr][cc] = True
                boxes.append(
                    QRectF(c * cell, r * cell, w * cell, h * cell)
                )
            else:
                used[r][c] = True  # 太小，丢弃

    boxes.sort(key=lambda b: -b.width() * b.height())
    return boxes[:6]


def scatter_on_card(card: QWidget, seed: int = 0, density: int = 3) -> QWidget | None:
    """在卡片的实测空白处撒装饰。

    时机：必须在卡片内容全部渲染完成后调用（否则探测到的空白是错的）。
    做法：测空白 → 铺一层透明浮层 → 只在空白框里画元素。
    """
    from PyQt6.QtCore import QEvent, QObject, QTimer

    from .doodle_decor import ScatterDecor

    if not DOODLE_MODE or card.width() < 100:
        return None

    boxes = probe_blank_regions(card, min_size=24)
    if not boxes:
        return None

    layer = ScatterDecor(card, boxes, seed=seed, density=density)
    layer.setGeometry(0, 0, card.width(), card.height())

    def reposition() -> None:
        if card.width() < 100:
            return
        layer.setGeometry(0, 0, card.width(), card.height())
        # 尺寸变了要重测空白
        fresh = probe_blank_regions(card, min_size=24)
        if fresh:
            layer._mask = fresh
            layer._built_size = None
        # 必须 raise：卡片自己的 drawBackground 会盖掉 lower 的内容。
        # 安全性由"只画在探测到的空白框内"保证，不靠层级。
        layer.raise_()
        layer.show()

    class _Hook(QObject):
        def eventFilter(self, obj, event) -> bool:  # noqa: N802
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                QTimer.singleShot(120, reposition)
            return False

    hook = _Hook(card)
    card.installEventFilter(hook)
    card._scatter_hook = hook  # type: ignore[attr-defined]

    QTimer.singleShot(300, reposition)
    QTimer.singleShot(900, reposition)
    return layer
