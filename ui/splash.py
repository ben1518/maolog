"""品牌启动页。

启动页只在一次真实启动过程中出现：显示当前初始化阶段，完成后淡出。
它不会为了展示动画而人为延长启动，关闭后按用户设置进入主窗口或托盘。
"""

from __future__ import annotations

import math

from PyQt6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QWidget

from .brand import brand_pixmap
from .theme import (
    ACCENT,
    BG_CARD,
    BG_ROOT,
    IS_DARK_SKIN,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)

WINDOW_W = 420
WINDOW_H = 300
# 手绘模式改成横向双栏：左边品牌与状态，右边放「推门」插画
DOODLE_WINDOW_W = 560
DOODLE_WINDOW_H = 300
CARD_MARGIN = 8


class StartupSplash(QWidget):
    """无边框品牌启动页；内容少，绘制开销低。"""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        width = DOODLE_WINDOW_W
        height = DOODLE_WINDOW_H
        self.setFixedSize(width, height)
        self._art: QPixmap | None = None
        if True:
            from .theme import ASSET_DIR

            art_path = ASSET_DIR / "doodle" / "splash.png"
            if IS_DARK_SKIN:
                light = art_path.parent / "splash-light.png"
                if light.exists():
                    art_path = light
            if art_path.exists():
                pixmap = QPixmap(str(art_path))
                if not pixmap.isNull():
                    self._art = pixmap.scaledToHeight(
                        168, Qt.TransformationMode.SmoothTransformation
                    )
        self.setWindowTitle("MaoLog · 正在启动")

        self._status = "正在准备本地记录"
        self._finished = False
        self._allow_close = False
        self._on_done = None
        self._fade: QPropertyAnimation | None = None
        self._mark = QPixmap()
        self._clock = QElapsedTimer()
        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self.update)
        self.setWindowOpacity(1.0)
        self._center_on_screen()

    def set_status(self, text: str) -> None:
        if text and text != self._status:
            self._status = text
            self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        self._center_on_screen()
        self._load_mark()
        self._clock.start()
        self._tick.start()
        super().showEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._allow_close:
            event.ignore()
            return
        self._tick.stop()
        super().closeEvent(event)

    def finish(self, callback) -> None:
        """淡出并回调；主窗口要在启动页仍可见时完成准备。"""
        if self._finished:
            return
        self._finished = True
        self._on_done = callback
        self._tick.stop()
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(180)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._finish_now)
        self._fade.start()

    def force_close(self) -> None:
        self._allow_close = True
        self._tick.stop()
        self.close()

    def _finish_now(self) -> None:
        callback = self._on_done
        self._on_done = None
        self._allow_close = True
        self.close()
        if callback is not None:
            callback()

    def _center_on_screen(self) -> None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.center().x() - self.width() // 2,
            area.center().y() - self.height() // 2,
        )

    def _load_mark(self) -> None:
        ratio = max(1.0, float(self.devicePixelRatioF()))
        size = max(56, int(round(64 * ratio)))
        self._mark = brand_pixmap(size)
        self._mark.setDevicePixelRatio(ratio)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        outer = QRectF(self.rect()).adjusted(CARD_MARGIN, CARD_MARGIN, -CARD_MARGIN, -CARD_MARGIN)
        path = QPainterPath()
        path.addRoundedRect(outer, 22, 22)
        painter.setClipPath(path)

        # 渐变直接由主题色算出来，换皮肤时不会再残留旧色值
        base = QColor(BG_CARD)
        gradient = QLinearGradient(outer.topLeft(), outer.bottomRight())
        gradient.setColorAt(0.0, base.lighter(112))
        gradient.setColorAt(0.62, base)
        gradient.setColorAt(1.0, base.darker(108))
        painter.fillPath(path, gradient)

        glow = QRadialGradient(outer.center().x(), outer.top() + 54, 220)
        accent_q = QColor(ACCENT)
        glow_tint = (accent_q.red(), accent_q.green(), accent_q.blue())
        glow.setColorAt(0.0, QColor(*glow_tint, 56))
        glow.setColorAt(0.55, QColor(*glow_tint, 12))
        glow.setColorAt(1.0, QColor(*glow_tint, 0))
        painter.fillPath(path, glow)

        elapsed = self._clock.elapsed() if self._clock.isValid() else 0
        breath = 0.5 + 0.5 * math.sin(elapsed / 720.0)

        if True:
            self._paint_doodle(painter, outer, elapsed, breath)
            painter.setClipping(False)
            self._paint_doodle_border(painter, outer)
            painter.end()
            return

    def _paint_doodle(self, painter: QPainter, outer: QRectF, elapsed: int, breath: float) -> None:
        """纵向排布不变，只把宽度让给右侧插画。"""
        from .doodle_paint import paint_rough_frame

        left_w = outer.width() * 0.62
        left = QRectF(outer.left(), outer.top(), left_w, outer.height())
        center_x = left.center().x()

        # 品牌标记
        if not self._mark.isNull():
            mark_w = self._mark.width() / self._mark.devicePixelRatio()
            mark_h = self._mark.height() / self._mark.devicePixelRatio()
            mark_rect = QRectF(center_x - mark_w / 2, outer.top() + 34, mark_w, mark_h)
            painter.setPen(Qt.PenStyle.NoPen)
            halo_rgb = (232, 201, 122) if IS_DARK_SKIN else (43, 74, 124)
            painter.setBrush(QColor(*halo_rgb, int(10 + breath * 10)))
            painter.drawRoundedRect(mark_rect.adjusted(-8, -8, 8, 8), 18, 18)
            painter.drawPixmap(mark_rect.topLeft(), self._mark)

        painter.setFont(QFont("LXGW WenKai", 19))
        painter.setPen(QColor(TEXT_PRIMARY))
        painter.drawText(
            QRectF(left.left(), outer.top() + 112, left.width(), 32),
            Qt.AlignmentFlag.AlignCenter,
            "MaoLog",
        )

        painter.setFont(QFont("LXGW WenKai", 10))
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(
            QRectF(left.left(), outer.top() + 146, left.width(), 22),
            Qt.AlignmentFlag.AlignCenter,
            "看见时间，复盘成长",
        )

        painter.setPen(QPen(QColor(156, 148, 129, 160), 1.2))
        painter.drawLine(
            QPointF(center_x - 26, outer.top() + 178),
            QPointF(center_x + 26, outer.top() + 178),
        )

        painter.setFont(QFont("LXGW WenKai", 10))
        painter.setPen(QColor(TEXT_SECONDARY))
        painter.drawText(
            QRectF(left.left() + 12, outer.top() + 196, left.width() - 24, 22),
            Qt.AlignmentFlag.AlignCenter,
            self._status,
        )

        # 三点：手绘模式下画成小墨点
        for index in range(3):
            phase = ((elapsed - index * 145) % 1050) / 1050.0
            wave = max(0.0, math.sin(phase * math.tau))
            dot = QColor(ACCENT)
            dot.setAlpha(int(50 + 180 * wave))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot)
            painter.drawEllipse(
                QPointF(center_x + (index - 1) * 12, outer.top() + 228 - wave * 2.5),
                2.4,
                2.4,
            )

        painter.setFont(QFont("LXGW WenKai", 8))
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(
            QRectF(left.left(), outer.bottom() - 34, left.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            "本机记录 · 原图不出本机",
        )

        # 右侧插画：一条发丝线分栏 + 推门小人
        divider_x = outer.left() + left_w
        painter.setPen(QPen(QColor(90, 85, 75, 170), 1))
        painter.drawLine(
            QPointF(divider_x, outer.top() + 26),
            QPointF(divider_x, outer.bottom() - 26),
        )

        if self._art is not None:
            art_w = self._art.width() / self._art.devicePixelRatio()
            art_h = self._art.height() / self._art.devicePixelRatio()
            right_center = (divider_x + outer.right()) / 2
            painter.drawPixmap(
                QPointF(right_center - art_w / 2, outer.center().y() - art_h / 2 - 6),
                self._art,
            )
            painter.setFont(QFont("LXGW WenKai", 9))
            painter.setPen(QColor("#C4503C" if IS_DARK_SKIN else "#B23A2A"))
            painter.drawText(
                QRectF(divider_x, outer.center().y() + art_h / 2, outer.right() - divider_x, 20),
                Qt.AlignmentFlag.AlignCenter,
                "今天也要留下记录",
            )

    def _paint_doodle_border(self, painter: QPainter, outer: QRectF) -> None:
        from .doodle_paint import paint_rough_frame

        paint_rough_frame(
            painter,
            outer,
            color=("#5A554B" if IS_DARK_SKIN else "#9C9481"),
            width=1.8,
            radius=18.0,
            seed=31,
            fill=None,
            amplitude=1.6,
        )

    def sizeHint(self) -> QSize:  # noqa: N802
        if True:
            return QSize(DOODLE_WINDOW_W, DOODLE_WINDOW_H)
        return QSize(WINDOW_W, WINDOW_H)
