"""贴在卡片边上的便签纸。

界面全是规整的圆角矩形时，人会觉得是"软件"；贴一张微微歪的纸片上去，
立刻变成"有人在这里工作过"。

三个细节决定像不像真的：
1. **歪一点**：严格水平的纸片看起来仍是 UI 控件，歪 1.5~3 度才像随手贴的；
2. **有投影**：纸片要"浮"在卡片上，否则像直接印上去的；
3. **顶部胶带**：一小条半透明的色带，比画个图钉更像手边有胶带的人。
"""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from .theme import ACCENT, BORDER, DOODLE_MODE, IS_DARK_SKIN, TEXT_PRIMARY, TEXT_SECONDARY

# 便签纸的颜色：只用柔和的几档，避免抢正文
NOTE_COLORS_DARK = ["#4A4232", "#4A3A38", "#39423A", "#3E3B4A"]
NOTE_COLORS_LIGHT = ["#FBF0CE", "#F8DDD6", "#E4EDDD", "#E3E5F2"]


class StickyNote(QWidget):
    """一张贴在卡片上的便签。

    用法：建好后调 `place()` 摆到父容器的指定角落，
    它会自己处理旋转和投影，不占布局空间。
    """

    def __init__(
        self,
        parent: QWidget,
        text: str,
        width: int = 116,
        height: int = 74,
        angle: float = -2.4,
        seed: int = 0,
        color: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")
        # 便签是浮层，不参与父级布局计算
        from PyQt6.QtWidgets import QSizePolicy

        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(0, 0)

        self._text = text
        self._angle = angle
        self._seed = seed

        palette = NOTE_COLORS_DARK if IS_DARK_SKIN else NOTE_COLORS_LIGHT
        self._paper = QColor(color or palette[seed % len(palette)])

        # 旋转后四角会跑出原矩形，画布要放大。
        # pad 取"旋转后外接矩形比原矩形多出来的部分"，多留 2px 给投影。
        self._w = width
        self._h = height
        rad = math.radians(abs(angle))
        rotated_w = width * math.cos(rad) + height * math.sin(rad)
        rotated_h = width * math.sin(rad) + height * math.cos(rad)
        pad_x = int((rotated_w - width) / 2) + 4
        pad_y = int((rotated_h - height) / 2) + 4
        self._pad_x = pad_x
        self._pad_y = pad_y
        self.resize(width + pad_x * 2, height + pad_y * 2)

    def paintEvent(self, event) -> None:  # noqa: N802
        if not DOODLE_MODE:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        cx = self.width() / 2
        cy = self.height() / 2

        # 绕中心转，转完再画，四个角自然歪出去
        painter.translate(cx, cy)
        painter.rotate(self._angle)
        painter.translate(-cx, -cy)

        paper = QRectF(
            cx - self._w / 2,
            cy - self._h / 2,
            self._w,
            self._h,
        )

        # 投影：往右下偏一点，模拟灯在左上
        shadow = paper.translated(2.5, 3.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 46 if IS_DARK_SKIN else 26))
        painter.drawRoundedRect(shadow, 2.0, 2.0)

        # 纸面：轻微的上浅下深，不是死平涂
        grad = QLinearGradient(paper.topLeft(), paper.bottomLeft())
        grad.setColorAt(0.0, self._paper.lighter(103))
        grad.setColorAt(1.0, self._paper.darker(103))
        painter.setBrush(grad)
        painter.setPen(QPen(QColor(BORDER).darker(115), 1.0))
        painter.drawRoundedRect(paper, 1.6, 1.6)

        # 顶部胶带
        tape_w = self._w * 0.42
        tape = QRectF(cx - tape_w / 2, paper.top() - 5, tape_w, 11)
        tape_color = QColor(ACCENT)
        tape_color.setAlpha(76 if IS_DARK_SKIN else 92)
        painter.setBrush(tape_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(tape)
        # 胶带两端的撕口：画两个小三角，别让它是块规整的长方形
        painter.setBrush(QColor(tape_color.red(), tape_color.green(), tape_color.blue(), 40))
        painter.drawPolygon(
            *[
                QPointF(tape.left(), tape.top()),
                QPointF(tape.left() - 3, tape.top() + 3),
                QPointF(tape.left(), tape.bottom()),
            ]
        )
        painter.drawPolygon(
            *[
                QPointF(tape.right(), tape.top()),
                QPointF(tape.right() + 3, tape.top() + 3),
                QPointF(tape.right(), tape.bottom()),
            ]
        )

        # 文字：手动折行，最多 3 行，多了加省略
        painter.setPen(QColor(TEXT_PRIMARY))
        font = QFont("LXGW WenKai", 10)
        painter.setFont(font)
        inner = paper.adjusted(9, 8, -9, -6)
        lines = self._wrap(self._text, int(inner.width() / 10.2), max_lines=3)
        line_h = 15.0
        y = inner.top() + 2
        for line in lines:
            painter.drawText(
                QRectF(inner.left(), y, inner.width(), line_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                line,
            )
            y += line_h

        # 右下角折角：一个浅色小三角，暗示这纸掀起过
        fold = 12.0
        painter.setBrush(QColor(self._paper.darker(112)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(
            *[
                QPointF(paper.right(), paper.bottom() - fold),
                QPointF(paper.right() - fold, paper.bottom()),
                QPointF(paper.right(), paper.bottom()),
            ]
        )
        painter.end()

    @staticmethod
    def _wrap(text: str, per_line: int, max_lines: int = 3) -> list[str]:
        """按字符数折行。

        先按作者写的换行断开，再对每段自行折行。
        直接把 "\n" 当普通字符数进去，会出现 "40" / "8 条记录" 这种
        把数字劈成两半的情况。
        """
        per_line = max(4, per_line)
        lines: list[str] = []
        for paragraph in text.split("\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            rest = paragraph
            while rest and len(lines) < max_lines:
                if len(rest) <= per_line:
                    lines.append(rest)
                    rest = ""
                    break
                lines.append(rest[:per_line])
                rest = rest[per_line:]
            if len(lines) >= max_lines:
                if rest:
                    lines[-1] = lines[-1][: max(1, per_line - 1)] + "…"
                break
        return lines

    def note_origin(self, corner: str, parent_w: int, parent_h: int) -> tuple[float, float]:
        """算出便签左上角相对父容器左上角的位置。

        inside-* 落在容器内部；outside-* 大部分悬在容器外，只留一角压边。
        """
        pw, ph = parent_w, parent_h
        pad_x, pad_y = self._pad_x, self._pad_y

        if corner.startswith("outside-"):
            if corner == "outside-top-right":
                # 往右上角外面推，只让左下角压住卡片边缘
                return (pw - self._w * 0.62, -self._h * 0.72)
            if corner == "outside-top-left":
                return (-self._w * 0.38, -self._h * 0.72)
            if corner == "outside-right":
                return (pw - self._w * 0.30, ph * 0.14)
            return (pw - self._w * 0.62, ph - self._h * 0.30)

        if corner == "inside-top-right-above-buttons":
            # 卡片右上角有按钮，便签贴在卡片的**外侧上沿**，
            # 竖直方向基本悬在卡片上方，只让底边压住卡片一点点。
            # 这样不占卡片内部任何空间，也不会盖住正文。
            return (pw - self._w - 6, -self._h * 0.74)
        if corner == "top-right":
            return (pw - self._w - 10 - pad_x, 4 - pad_y // 2)
        if corner == "top-left":
            return (10 - pad_x, 4 - pad_y // 2)
        if corner == "bottom-right":
            return (pw - self._w - 10 - pad_x, ph - self._h - 10 - pad_y)
        return (10 - pad_x, ph - self._h - 10 - pad_y)

    def set_text(self, text: str) -> None:
        """换内容后重绘。文字长度变化会影响折行，所以要 update。"""
        if text == self._text:
            return
        self._text = text
        self.update()

    def place(self, corner: str = "top-right", margin: int = 10) -> None:
        """摆到父容器的某个角。

        `outside-*` 系列会把它悬在卡片边缘之外，
        卡片内部通常已经被标题栏按钮占满，便签放进去一定会压到东西。
        """
        parent = self.parentWidget()
        if parent is None:
            return
        pw, ph = parent.width(), parent.height()
        pad_x, pad_y = self._pad_x, self._pad_y

        if corner.startswith("outside-"):
            nx, ny = self.note_origin(corner, pw, ph)
            self.move(int(nx), int(ny))
            self.raise_()
            return

        # 便签主体要落在卡片内：y 用 pad_y 回正，让纸片顶边贴着卡片上沿
        if corner == "top-right":
            self.move(int(pw - self._w - margin - pad_x), int(4 - pad_y // 2))
        elif corner == "top-left":
            self.move(int(margin - pad_x), int(4 - pad_y // 2))
        elif corner == "bottom-right":
            self.move(
                int(pw - self._w - margin - pad_x),
                int(ph - self._h - margin - pad_y),
            )
        else:
            self.move(int(margin - pad_x), int(ph - self._h - margin - pad_y))
        self.raise_()


def attach_note(
    card: QWidget,
    text: str,
    corner: str = "top-right",
    width: int = 112,
    height: int = 68,
    angle: float = -2.4,
    seed: int = 0,
    host: QWidget | None = None,
) -> StickyNote | None:
    """给卡片贴一张便签，卡片尺寸变化时跟着走。

    host 是便签真正的父容器。悬在卡片外侧时**必须**传一个更大的容器
    （通常是页面根 Widget），否则 Qt 会把超出卡片的部分裁掉，
    只剩贴着边缘的一小条。
    """
    if not DOODLE_MODE or not text:
        return None

    parent = host if host is not None else card
    note = StickyNote(parent, text, width=width, height=height, angle=angle, seed=seed)

    def reposition() -> None:
        if card.width() < 50 or card.height() < 50:
            return
        if parent is card:
            note.place(corner)
        else:
            # 挂在更外层：用卡片在 host 里的绝对位置算
            top_left = card.mapTo(parent, card.rect().topLeft())
            nx, ny = note.note_origin(corner, card.width(), card.height())
            note.move(int(top_left.x() + nx), int(top_left.y() + ny))
        note.show()
        note.raise_()

    from PyQt6.QtCore import QObject, QEvent, QTimer

    class _Hook(QObject):
        def eventFilter(self, obj, event) -> bool:  # noqa: N802
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                reposition()
            return False

    hook = _Hook(card)
    card.installEventFilter(hook)
    card._note_hook = hook  # type: ignore[attr-defined]

    reposition()
    QTimer.singleShot(0, reposition)
    QTimer.singleShot(60, reposition)
    return note


class NoteLine(QWidget):
    """布局内的便签行：一张小纸片，贴在正文下方。

    和 StickyNote 的区别：这张**参与布局**，占自己的行高，
    所以永远不会压到别的内容。代价是不能歪太多（会撑高行），
    但仍然带手绘边框、胶带和折角，看起来还是贴上去的纸片。
    """

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self._text = text
        self.setFixedHeight(38)
        self.setStyleSheet("background: transparent;")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not DOODLE_MODE:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # NoteLine 是单行横向便签条，将换行符统一合并为间隔号，防止多行上下裁切
        line_text = " · ".join(
            part.strip() for part in (self._text or "").splitlines() if part.strip()
        )
        font = QFont("LXGW WenKai", 10)
        painter.setFont(font)
        fm = QFontMetrics(font)

        w, h = self.width(), self.height()
        text_w = fm.horizontalAdvance(line_text)
        # 纸片宽度按真实文字像素宽度自适应，留足左右内边距，且不超过容器可用宽度
        paper_w = min(max(text_w + 30, 150), max(150, w - 10))
        paper_h = h - 8
        paper = QRectF(3, 5, paper_w, paper_h)
        rng = random.Random(len(line_text) * 37 + int(line_text[:1].__hash__() % 97))

        # 投影
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 42 if IS_DARK_SKIN else 22))
        painter.drawRoundedRect(paper.translated(1.5, 2), 2, 2)

        # 纸面
        palette = NOTE_COLORS_DARK if IS_DARK_SKIN else NOTE_COLORS_LIGHT
        base = QColor(palette[1])
        painter.setBrush(base)
        painter.setPen(QPen(QColor(BORDER).darker(112), 1.0))
        painter.drawRoundedRect(paper, 1.5, 1.5)

        # 胶带：位置左右随机偏一点，宽度也随机，别总是正中
        tape_w = min(110.0, paper_w * rng.uniform(0.18, 0.28))
        tape_cx = paper.center().x() + rng.uniform(-paper_w * 0.14, paper_w * 0.14)
        tape = QRectF(tape_cx - tape_w / 2, paper.top() - 3, tape_w, 7)
        tape_color = QColor(ACCENT)
        tape_color.setAlpha(72 if IS_DARK_SKIN else 88)
        painter.setBrush(tape_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(tape)

        # 文字（单行垂直居中，超长时优雅省略）
        painter.setPen(QColor(TEXT_PRIMARY))
        text_rect = paper.adjusted(12, 0, -12, 0)
        elided = fm.elidedText(line_text, Qt.TextElideMode.ElideRight, int(text_rect.width()))
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided,
        )

        # 折角
        fold = 8.0
        painter.setBrush(QColor(base.darker(110)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(
            *[
                QPointF(paper.right(), paper.bottom() - fold),
                QPointF(paper.right() - fold, paper.bottom()),
                QPointF(paper.right(), paper.bottom()),
            ]
        )
        painter.end()
