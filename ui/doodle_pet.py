"""卡片角落的手绘角色：猫和狗。

有数据的时候界面全是数字和图表，没一点活物；角落里坐一只小动物，
整页就从"仪表盘"变成"有人在用的本子"。

设计约束：
- 只做装饰，不抢信息：默认半透明，鼠标移上去才浮起来；
- 位置固定在卡片右下角外侧一点，不覆盖任何文字；
- 每张卡片按标题哈希挑一只，避免全页都是同一只。
"""

from __future__ import annotations

import random

from PyQt6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

from .theme import ASSET_DIR, DOODLE_MODE, INVERT_ART

# 可用的角色素材（不含 -light 后缀）
PET_FILES = [
    "mushroom_sprites/idle.png",
    "mushroom_sprites/wave.png",
    "mushroom_sprites/salute.png",
    "mushroom_sprites/peek.png",
    "mushroom_sprites/thanks.png",
]


def load_pet(name: str, height: int) -> QImage | None:
    """按高度取一张蘑菇小精灵角色贴图（兼容旧调用）。"""
    if not DOODLE_MODE:
        return None
    # 将旧猫猫文件名自动映射到蘑菇小精灵对应动作贴图
    alias_map = {
        "pet-cat.png": "mushroom_sprites/wave.png",
        "pet-dog.png": "mushroom_sprites/salute.png",
        "pet-cat-lazy.png": "mushroom_sprites/sleep_closed.png",
    }
    rel_name = alias_map.get(name, name)
    path = ASSET_DIR / "doodle" / rel_name
    if not path.exists():
        path = ASSET_DIR / "doodle" / name
        if INVERT_ART:
            light = path.parent / f"{path.stem}-light{path.suffix}"
            if light.exists():
                path = light
    if not path.exists():
        return None

    image = QImage(str(path))
    if image.isNull():
        return None
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    if image.height() > height:
        image = image.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
    return image


class PetCorner(QWidget):
    """坐在卡片右下角的角色，纯装饰、不吃鼠标事件。"""

    def __init__(self, parent=None, height: int = 58, seed: str = "") -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # 背景用 stylesheet 透明，不用 WA_NoSystemBackground（会连带跳过绘制）
        self.setStyleSheet("background: transparent;")
        self._image: QImage | None = None
        self._hover = 0.0

        rng = random.Random(str(seed or "mao"))
        candidates = [f for f in PET_FILES if (ASSET_DIR / "doodle" / f).exists()]
        if candidates:
            self._image = load_pet(rng.choice(candidates), height)
        if self._image is not None:
            self.resize(self._image.width(), self._image.height())
        else:
            self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._image is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # 默认淡一点，不跟正文抢注意力
        painter.setOpacity(0.92)
        painter.drawImage(
            QRectF(0, 0, self._image.width(), self._image.height()),
            self._image,
        )
        painter.end()


def reserve_pet_space(card: QWidget, width: int, height: int) -> None:
    """在卡片布局底部给宠物留一条空带。

    图表是整块自绘画布，宠物飘在右下角一定会压上去。
    正确做法是让布局自己让出这块地方：加一个透明占位 widget，
    宠物坐在占位处，图表自然缩短到它上方。
    """
    layout = card.layout()
    if layout is None:
        return
    from PyQt6.QtWidgets import QSizePolicy

    # 图表是用 addWidget(w, stretch=1) 加的，会把剩余空间全吃掉。
    # 先把所有已有项降为 stretch=0，占位条才拿得到高度。
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is not None and item.widget() is not None:
            layout.setStretch(i, 0)

    spacer = QWidget(card)
    spacer.setMinimumHeight(height)
    spacer.setMaximumHeight(height)
    spacer.setFixedHeight(height)
    # Fixed 策略：图表有 stretch，会抢走空间，占位条必须钉死高度
    spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    spacer.setStyleSheet("background: transparent;")
    spacer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    spacer.setObjectName("PetSpacer")
    layout.addWidget(spacer, 1)  # 剩余的竖向空间给占位条


def layout_needs_spacer(card: QWidget) -> bool:
    """布局里是否还没有宠物占位条。"""
    if card.layout() is None:
        return False
    for i in range(card.layout().count()):
        item = card.layout().itemAt(i)
        w = item.widget() if item else None
        if w is not None and w.objectName() == "PetSpacer":
            return False
    return True


def attach_pet(card: QWidget, height: int = 58, margin: int = 10) -> PetCorner | None:
    """把角色贴到卡片右下角；卡片尺寸变化时跟着走。"""
    if not DOODLE_MODE:
        return None

    tag = str(card.objectName() or "mao")
    tag = f"{tag}:{id(card) % 1000}"
    pet = PetCorner(card, height=height, seed=tag)
    if pet._image is None:
        return None

    def reposition() -> None:
        if card.width() < pet.width() + margin or card.height() < pet.height() + margin:
            return  # 还没完成布局，等下一次回调
        pet.move(
            QPoint(
                card.width() - pet.width() - margin,
                card.height() - pet.height() - margin,
            )
        )
        # 卡片内容布局完成后会重新 stack，这里每次都顶上去
        pet.show()
        pet.raise_()

    # 图表在 _card() 之后才加进布局，所以等布局稳定了再预留空带，
    # 顺序反了会把占位条插在图表上面，图表反而跑到下面去。
    if getattr(card, "_want_pet", False) and layout_needs_spacer(card):
        reserve_pet_space(card, 90, 58)

    hook = _ResizeHook(card, reposition)
    card.installEventFilter(hook)
    card._pet_hook = hook  # type: ignore[attr-defined]

    # 建卡时卡片还是 0 尺寸；滚动区里的卡片更要等布局跑完再摆一次
    reposition()
    QTimer.singleShot(0, reposition)
    QTimer.singleShot(60, reposition)
    return pet


class _ResizeHook(QObject):
    """极简 resize 监听：卡片尺寸变化时重新摆放角色。

    必须继承 QObject，installEventFilter 只接受 QObject。
    """

    def __init__(self, card: QWidget, callback) -> None:
        super().__init__(card)
        self._callback = callback

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._callback()
        return False


def add_pet_to_card(card: QWidget, height: int = 56) -> PetCorner | None:
    """在图表已经加入布局之后调用：先加底部空带，再把宠物放进去。

    这是唯一正确的调用时机——更早的话空带会插在图表上面。
    """
    if getattr(card, "_is_insight", False):
        return None  # 总结卡正文铺满，不放宠物

    reserve_pet_space(card, 90, height)
    return attach_pet(card, height=height, margin=8)


def attach_pet_outside(card: QWidget, host: QWidget, height: int = 56) -> PetCorner | None:
    """把宠物**挂在卡片外侧**：坐在卡片右下角的外沿上，一半在卡片外。

    为什么不放进卡片里：时间轴和应用排行都在 QScrollArea 里，
    滚动内容的尺寸不受卡片布局约束，占位条拦不住它们，
    宠物放进去必然压住图表。挂外墙最干净——那里永远没有内容。
    """
    if getattr(card, "_is_insight", False):
        return None

    pet = PetCorner(host, height=height, seed=f"out:{id(card) % 1000}")
    if pet._image is None:
        return None

    def reposition() -> None:
        if card.width() < 100:
            return
        # 完全坐在卡片外面：横坐标从卡片右边缘开始，不压进卡片
        top_left = card.mapTo(host, card.rect().topLeft())
        x = top_left.x() + card.width() + 6
        y = top_left.y() + card.height() - pet.height()
        # 别跑出宿主范围
        x = max(4, min(x, host.width() - pet.width() - 4))
        y = max(4, min(y, host.height() - pet.height() - 4))
        pet.move(int(x), int(y))
        pet.show()
        pet.raise_()

    from PyQt6.QtCore import QEvent, QObject, QTimer

    class _Hook(QObject):
        def eventFilter(self, obj, event) -> bool:  # noqa: N802
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Move):
                reposition()
            return False

    hook = _Hook(card)
    card.installEventFilter(hook)
    card._pet_hook2 = hook  # type: ignore[attr-defined]

    reposition()
    QTimer.singleShot(0, reposition)
    QTimer.singleShot(80, reposition)
    return pet


class PetInline(QWidget):
    """布局内的小精灵装饰：坐在卡片标题行右侧，纯装饰不响应点击。"""

    def __init__(self, parent=None, height: int = 34, seed: int = 0) -> None:
        super().__init__(parent)
        rng = random.Random(str(seed) + "pet")
        candidates = [f for f in PET_FILES if (ASSET_DIR / "doodle" / f).exists()]
        self._image = None
        if candidates:
            h = max(22, int(height * rng.uniform(0.85, 1.18)))
            self._image = load_pet(rng.choice(candidates), h)
        self._tilt = rng.uniform(-11, 11)
        self._lift = rng.randint(-3, 2)

        if self._image is not None:
            self.setFixedSize(self._image.width() + 10, height + 6)
        else:
            self.setFixedSize(1, 1)
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._image is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        iw, ih = self._image.width(), self._image.height()
        cx, cy = self.width() / 2, self.height() / 2

        painter.translate(cx, cy)
        painter.rotate(self._tilt)
        painter.translate(-cx, -cy)

        painter.setOpacity(0.94)
        painter.drawImage(
            QRectF(cx - iw / 2, self.height() - ih - 1 + self._lift, iw, ih),
            self._image,
        )
        painter.end()
