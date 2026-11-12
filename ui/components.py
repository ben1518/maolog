"""自绘看板组件。

全部用 QPainter 手绘，不依赖 QtCharts（少一个依赖，也好控制视觉细节）。
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEvent,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    pyqtProperty,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolTip, QVBoxLayout, QWidget

from core.storage import format_duration

from .brand import make_icon_label
from .doodle_paint import RoughFrame
from .theme import (
    ACCENT,
    ASSET_DIR,
    BG_CARD,
    BG_ELEVATED,
    BG_INSET,
    DOODLE_MODE,
    INVERT_ART,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    category_color,
)


def doodle_image(name: str, width: int) -> QImage | None:
    """线稿返回 QImage：QPixmap 在 Windows 上是预乘 alpha，深色底会压暗浅色线条。"""
    if not DOODLE_MODE or not name:
        return None
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
    if image.width() > width:
        image = image.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    return image


def doodle_art(name: str, width: int) -> QPixmap | None:
    """取 assets/doodle 下的线稿并按宽度缩放。

    深色皮肤用反相版（-light.png），否则浅色线条会消失在深底里。
    这里全程用 QImage 处理并显式转成非预乘 ARGB：QPixmap 在 Windows 上是
    预乘 alpha，半透明边缘会被压暗，深色底上看起来像没画上去。
    """
    if not DOODLE_MODE or not name:
        return None

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
    if image.width() > width:
        image = image.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    return QPixmap.fromImage(image.convertToFormat(QImage.Format.Format_ARGB32))


class StatCard(RoughFrame):
    """顶部概览小卡片：手绘手账便签卡。

    左侧只留一条 3px 分类色，不做彩色圆点：颜色用于区分指标，
    不制造四个同等抢眼的装饰焦点。
    """

    def __init__(self, label: str, accent: str = ACCENT, parent: QWidget | None = None) -> None:
        super().__init__(parent, radius=13.0, seed=abs(hash(label)) % 89, amplitude=1.6, decor=False)
        self.setObjectName("Card")
        self.setMinimumHeight(98)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 12)
        layout.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(8)
        rail = QFrame()
        rail.setFixedSize(3, 12)
        rail.setStyleSheet(f"background: {accent}; border: none; border-radius: 1px;")
        if DOODLE_MODE:
            rail.hide()
        self._label = QLabel(label)
        self._label.setObjectName("CardLabel")
        head.addWidget(rail)
        head.addWidget(self._label)
        head.addStretch(1)
        layout.addLayout(head)

        self._value = QLabel("—")
        self._value.setObjectName("BigNumber")
        self._value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._value)

        self._sub = QLabel("")
        self._sub.setObjectName("Muted")
        self._sub.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._sub)

    def paintEvent(self, event) -> None:  # noqa: N802
        if not DOODLE_MODE:
            super().paintEvent(event)
            return

        from .doodle_paint import draw_washi_tape, draw_wavy_underline, paint_rough_frame
        from .theme import BORDER, DOODLE_RED

        # 1. 绘制手绘描边外框（不填背景，背景由 drawBackground 自动填充，避免覆盖子控件）
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
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

        # 2. 顶部贴一段彩色和纸胶带（手帐固定感）
        tape_colors = ["#E88E85", "#7EA6D2", "#8FAE7A", "#B39CD4"]
        seed_val = abs(hash(self._label.text()))
        tape_col = tape_colors[seed_val % len(tape_colors)]
        angle = ((seed_val % 7) - 3) * 0.7
        draw_washi_tape(
            painter,
            QRectF(self.width() / 2 - 25, -5, 50, 14),
            color=tape_col,
            angle=angle,
            pattern="stripes" if seed_val % 2 == 0 else "dots",
            seed=seed_val,
        )
        painter.end()

        # 3. 正常绘制子控件（标签与大字）
        super().paintEvent(event)

        # 4. 关键指标下方的红笔波浪划线
        val_text = self._value.text().strip()
        if val_text and val_text not in ("—", "等待数据", ""):
            p2 = QPainter(self)
            p2.setRenderHint(QPainter.RenderHint.Antialiasing)
            fm = self._value.fontMetrics()
            tw = min(self.width() - 36, fm.horizontalAdvance(val_text))
            val_geo = self._value.geometry()
            draw_wavy_underline(
                p2,
                val_geo.left(),
                val_geo.bottom() - 1,
                tw,
                color=DOODLE_RED,
                amplitude=1.6,
                wavelength=8.0,
            )
            p2.end()

    def set_value(self, value: str, sub: str = "") -> None:
        self._value.setText(value)
        self._sub.setText(sub)
        # 窄窗口下 QLabel 会裁字，至少让完整内容能通过悬停看到
        self._value.setToolTip(value)
        self._sub.setToolTip(sub)
        self.update()


class DonutChart(QWidget):
    """分类占比环形图，右侧带图例。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: list[dict] = []
        self._total_seconds = 0
        self._progress = 0.0
        self._signature: tuple = ()
        # 184 高度刚好容纳 6 行图例与环形图；再大 12px 会让同列两张卡
        # 在 1380×920 的默认窗口里产生无意义的滚动条。
        self.setMinimumHeight(184)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(620)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # 动画驱动属性
    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, value: float) -> None:
        self._progress = value
        self.update()

    progress = pyqtProperty(float, fget=get_progress, fset=set_progress)

    def set_data(self, data: list[dict], total_seconds: int = 0) -> None:
        self._data = [d for d in data if d.get("seconds", 0) > 0]
        self._total_seconds = total_seconds or sum(d.get("seconds", 0) for d in self._data)

        # 数据没变就只重绘，不重播动画——否则每次刷新都会闪一下
        signature = tuple((d.get("category"), d.get("seconds")) for d in self._data)
        if signature == self._signature and self._progress >= 0.999:
            self.update()
            return
        self._signature = signature

        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    # ---------- 绘制 ----------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        diameter = min(h - 24, 168)
        margin_left = 12
        ring_rect = QRectF(margin_left, (h - diameter) / 2, diameter, diameter)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        thickness = max(14.0, diameter * 0.115)

        if not self._data:
            art = doodle_art("ring-empty.png", 118)
            if art is not None:
                area = QRectF(self.rect())
                x = int(area.center().x() - art.width() / 2)
                y = int(area.center().y() - art.height() / 2) - 12
                painter.drawPixmap(x, y, art)
                painter.setPen(QColor(TEXT_MUTED))
                painter.setFont(QFont(self.font().family(), 10))
                painter.drawText(
                    QRectF(area.left(), y + art.height() + 4, area.width(), 20),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    "暂无数据",
                )
                return
            pen = QPen(QColor(BG_INSET))
            pen.setWidthF(thickness)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            if DOODLE_MODE:
                from .doodle_paint import rough_arc

                centre = ring_rect.adjusted(
                    thickness / 2, thickness / 2, -thickness / 2, -thickness / 2
                )
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawPath(rough_arc(centre, 0, 360, seed=21, amplitude=1.4))
            else:
                painter.drawArc(ring_rect, 0, 360 * 16)
            painter.setPen(QColor(TEXT_MUTED))
            painter.setFont(QFont(self.font().family(), 10))
            painter.drawText(ring_rect, Qt.AlignmentFlag.AlignCenter, "暂无数据")
            return

        total = sum(d["seconds"] for d in self._data) or 1
        start_angle = 90.0
        gap = 2.0 if len(self._data) > 1 else 0.0

        for item in self._data:
            span = -(item["seconds"] / total) * 360.0 * self._progress
            if abs(span) <= gap:
                start_angle += span
                continue

            color = category_color(item["category"])
            if DOODLE_MODE:
                from .doodle_paint import draw_sketch_donut_pie
                from .theme import BORDER

                draw_sketch_donut_pie(
                    painter,
                    center=ring_rect.center(),
                    r_outer=diameter / 2,
                    r_inner=diameter / 2 - thickness,
                    start_deg=start_angle,
                    span_deg=span + gap,
                    fill_color=color,
                    stroke_color=BORDER,
                    seed=abs(hash(item["category"])) % 100,
                )
            else:
                pen = QPen(QColor(color))
                pen.setWidthF(thickness)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                painter.setPen(pen)
                painter.drawArc(ring_rect, int(start_angle * 16), int((span + gap) * 16))
            start_angle += span

        # 圆心文字：累计时长
        inner = ring_rect.adjusted(thickness, thickness, -thickness, -thickness)
        if DOODLE_MODE:
            from .doodle_paint import rough_ellipse
            from .theme import BORDER_SOFT

            center_circle = rough_ellipse(inner.adjusted(3, 3, -3, -3), seed=77, amplitude=1.0)
            painter.setPen(QPen(QColor(BORDER_SOFT), 1.1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(center_circle)

        painter.setPen(QColor(TEXT_PRIMARY))
        font = QFont("Cascadia Mono", 15)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        time_text = format_duration(self._total_seconds)
        painter.drawText(
            inner.adjusted(0, -inner.height() * 0.08, 0, -inner.height() * 0.08),
            Qt.AlignmentFlag.AlignCenter,
            time_text,
        )
        painter.setPen(QColor(TEXT_MUTED))
        painter.setFont(QFont(self.font().family(), 9))
        painter.drawText(
            inner.adjusted(0, inner.height() * 0.22, 0, inner.height() * 0.22),
            Qt.AlignmentFlag.AlignCenter,
            "已记录",
        )

        # 右侧图例
        legend_x = margin_left + diameter + 26
        legend_w = max(0, w - legend_x - 10)
        if legend_w < 60:
            return

        rows = self._data[:6]
        row_h = 30
        total_h = len(rows) * row_h
        y = (h - total_h) / 2

        for item in rows:
            color = QColor(category_color(item["category"]))
            if DOODLE_MODE:
                from .doodle_paint import rough_ellipse
                from .theme import BORDER

                swatch_rect = QRectF(legend_x, y + 8, 10, 10)
                painter.setPen(QPen(QColor(BORDER), 1.0))
                painter.setBrush(color)
                painter.drawPath(rough_ellipse(swatch_rect, seed=abs(hash(item["category"])), amplitude=0.7))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(QRectF(legend_x, y + 9, 9, 9), 2.5, 2.5)

            painter.setPen(QColor(TEXT_SECONDARY))
            painter.setFont(QFont(self.font().family(), 10))
            painter.drawText(
                QRectF(legend_x + 17, y, legend_w - 17, row_h),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                str(item["category"]),
            )

            painter.setPen(QColor(TEXT_PRIMARY))
            pct = int(round(item["seconds"] / total * 100))
            painter.drawText(
                QRectF(legend_x + 17, y, legend_w - 17, row_h),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{pct}%",
            )
            y += row_h


class AppRankWidget(QWidget):
    """应用使用时长排行，横向条形。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: list[dict] = []
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, data: list[dict]) -> None:
        self._data = data
        self.update()

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip and self._data:
            rows = self._data[:6]
            if rows:
                pos = event.pos()
                row_h = min(34, max(24, self.height() / max(1, len(rows))))
                top = max(0, (self.height() - len(rows) * row_h) / 2)
                idx = int((pos.y() - top) // row_h)
                if 0 <= idx < len(rows):
                    item = rows[idx]
                    dur = format_duration(int(item["seconds"]))
                    QToolTip.showText(event.globalPos(), f"{item['app']} · {dur}", self)
                    return True
            QToolTip.hideText()
            event.ignore()
            return True
        return super().event(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("transparent"))

        if not self._data:
            art = doodle_art("apps-empty.png", 132)
            if art is not None:
                x = (self.width() - art.width()) // 2
                y = max(4, (self.height() - art.height()) // 2 - 14)
                painter.drawPixmap(x, y, art)
                painter.setPen(QColor(TEXT_MUTED))
                painter.setFont(QFont(self.font().family(), 10))
                painter.drawText(
                    QRectF(0, y + art.height(), self.width(), 22),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    "还没有数据",
                )
            else:
                painter.setPen(QColor(TEXT_MUTED))
                painter.setFont(QFont(self.font().family(), 10))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "还没有数据")
            return

        rows = self._data[:6]
        w = self.width()
        row_h = min(34, max(24, self.height() / max(1, len(rows))))
        top = max(0, (self.height() - len(rows) * row_h) / 2)

        max_seconds = max(item["seconds"] for item in rows) or 1
        label_w = min(140, max(75, int(w * 0.30)))
        value_w = 58
        bar_x = label_w + 8
        bar_w = max(20, w - bar_x - value_w - 6)

        for i, item in enumerate(rows):
            y = top + i * row_h
            ratio = item["seconds"] / max_seconds

            # 排名手绘徽章 ① ② ③
            if DOODLE_MODE:
                from .doodle_paint import draw_highlighter_stroke, draw_rank_badge

                badge_center = QPointF(10, y + row_h / 2)
                badge_col = ACCENT if i < 3 else TEXT_MUTED
                draw_rank_badge(painter, badge_center, rank=i + 1, color=badge_col)
                name_x = 24.0
                actual_label_w = max(20.0, label_w - 24.0)
            else:
                name_x = 0.0
                actual_label_w = label_w

            painter.setPen(QColor(TEXT_SECONDARY))
            fm_font = QFont(self.font().family(), 10)
            painter.setFont(fm_font)
            fm = QFontMetrics(fm_font)
            name = fm.elidedText(str(item["app"]), Qt.TextElideMode.ElideRight, int(actual_label_w))
            painter.drawText(
                QRectF(name_x, y, actual_label_w, row_h),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                name,
            )

            # 底槽
            bar_height = 12.0 if DOODLE_MODE else 8.0
            track = QRectF(bar_x, y + (row_h - bar_height) / 2, bar_w, bar_height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BG_INSET))
            if DOODLE_MODE:
                from .doodle_paint import rough_bar

                painter.drawPath(rough_bar(track, seed=i * 13 + 5, amplitude=0.8))
            else:
                painter.drawRoundedRect(track, 4, 4)

            # 实际条：荧光笔涂抹质感
            fill = QRectF(bar_x, y + (row_h - bar_height) / 2, max(6.0, bar_w * ratio), bar_height)
            if DOODLE_MODE:
                draw_highlighter_stroke(painter, fill, color=ACCENT, seed=i * 29 + 11)
            else:
                fill_color = QColor(ACCENT)
                fill_color.setAlpha(max(112, 238 - i * 24))
                painter.setBrush(fill_color)
                painter.drawRoundedRect(fill, 4, 4)

            painter.setPen(QColor(TEXT_PRIMARY))
            painter.setFont(QFont("Cascadia Mono", 9))
            painter.drawText(
                QRectF(w - value_w, y, value_w, row_h),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                format_duration(int(item["seconds"])),
            )


class FadeOverlay(QWidget):
    """盖在滚动区底部的渐隐层，暗示下面还有内容。

    透明且不吃鼠标事件，不影响滚动操作。
    """

    def __init__(self, parent: QWidget, color: str, height: int = 34) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._fade_height = height
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(height)
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        grad = QLinearGradient(0, 0, 0, self.height())
        top = QColor(self._color)
        top.setAlpha(0)
        bottom = QColor(self._color)
        bottom.setAlpha(255)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        painter.fillRect(self.rect(), grad)


class EmptyState(QWidget):
    """统一的空状态提示。"""

    def __init__(
        self,
        text: str,
        hint: str = "",
        parent: QWidget | None = None,
        art: str = "",
        note: str = "",
    ) -> None:
        super().__init__(parent)
        self._note = note
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)

        # 手绘模式下用线稿插画替代几何图标；没有素材时回退到图标
        self._art_image = doodle_image(art, 250) if art else None
        if self._art_image is not None and not self._art_image.isNull():
            self._art_size = QSize(self._art_image.width(), self._art_image.height())
            layout.addSpacing(self._art_size.height())
        else:
            self._art_size = None
            layout.addWidget(
                make_icon_label("clock", 42, TEXT_MUTED, BG_ELEVATED),
                alignment=Qt.AlignmentFlag.AlignHCenter,
            )

        main = QLabel(text)
        main.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        layout.addWidget(main)

        if hint:
            sub = QLabel(hint)
            sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sub.setObjectName("Muted")
            sub.setWordWrap(True)
            layout.addWidget(sub)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not (DOODLE_MODE and self._note):
            return
        from .doodle_marks import draw_red_arrow, draw_red_note

        painter = QPainter(self)
        painter.setClipping(False)
        width, height = self.width(), self.height()

        # 手绘插画直接用 drawImage 画：QPixmap 走预乘 alpha，深色底上会被压暗
        if getattr(self, "_art_image", None) is not None and self._art_size is not None:
            art_w, art_h = self._art_size.width(), self._art_size.height()
            painter.drawImage(
                QRectF((width - art_w) / 2, 20, art_w, art_h),
                self._art_image,
            )

        note_x, note_y = width * 0.655, height * 0.225
        draw_red_note(painter, note_x, note_y, self._note, size=13, angle=-2.4)
        draw_red_arrow(
            painter,
            QPointF(note_x - 8, note_y + 7),
            QPointF(width * 0.565, height * 0.335),
        )
        painter.end()

