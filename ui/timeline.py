"""时间轴组件：把一天的活动画成纵向时间轴。

自绘而非堆 QWidget，几百条记录也能流畅滚动。
点击任意一行可以查看当时的截图，右键可微调分类、编辑活动名称或记住纠偏规则。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QMenu, QWidget

from .theme import (
    DOODLE_MODE,
    ACCENT,
    BG_CARD,
    BG_ELEVATED,
    BORDER,
    BORDER_SOFT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    category_color,
)

ROW_MAIN_H = 24
ROW_SUB_H = 18
ROW_GAP = 12
ROW_H = ROW_MAIN_H + ROW_SUB_H + ROW_GAP

TIME_COL_W = 52
AXIS_X = TIME_COL_W + 6
CONTENT_X = AXIS_X + 16


class TimelineWidget(QWidget):
    segment_clicked = pyqtSignal(object)
    segment_category_changed = pyqtSignal(object, str)
    segment_edit_requested = pyqtSignal(object)
    segment_delete_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: list[dict] = []
        self._hover_index = -1
        self._empty_text = "还没有记录"
        self.setMouseTracking(True)
        self.setMinimumWidth(300)
        self.setToolTip("左键查看截图 · 右键微调分类或记住纠偏规则")

    def set_segments(self, segments: list[dict], empty_text: str = "还没有记录") -> None:
        self._segments = segments
        self._empty_text = empty_text
        self._hover_index = -1
        self.setFixedHeight(max(60, len(segments) * ROW_H + 8))
        self.update()

    def clear(self) -> None:
        self.set_segments([])

    # ---------- 交互 ----------

    def _index_at(self, y: int) -> int:
        if not self._segments:
            return -1
        idx = int(y // ROW_H)
        if 0 <= idx < len(self._segments):
            return idx
        return -1

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        idx = self._index_at(int(event.position().y()))
        if idx != self._hover_index:
            self._hover_index = idx
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if idx >= 0
                else Qt.CursorShape.ArrowCursor
            )
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover_index != -1:
            self._hover_index = -1
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._index_at(int(event.position().y()))
            if idx >= 0:
                self.segment_clicked.emit(self._segments[idx])

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        idx = self._index_at(int(event.pos().y()))
        if idx < 0 or idx >= len(self._segments):
            return
        seg = self._segments[idx]
        cur_cat = seg.get("category") or "其他"

        menu = QMenu(self)
        menu.setStyleSheet(
            f"""
            QMenu {{
                background: {BG_CARD};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 10px;
                padding: 6px;
                font-size: 12.5px;
            }}
            QMenu::item {{
                padding: 6px 14px;
                border-radius: 6px;
            }}
            QMenu::item:selected {{
                background: {BG_ELEVATED};
                color: {ACCENT};
            }}
            QMenu::separator {{
                height: 1px;
                background: {BORDER_SOFT};
                margin: 4px 8px;
            }}
            """
        )

        cat_options = [
            ("📚 改判为「学习」", "学习"),
            ("💻 改判为「工作」", "工作"),
            ("🎮 改判为「娱乐」", "娱乐"),
            ("💬 改判为「沟通」", "沟通"),
            ("⚙️ 改判为「系统」", "系统"),
            ("📌 改判为「其他」", "其他"),
        ]
        cat_actions = {}
        for label, cat in cat_options:
            prefix = "✔ " if cat == cur_cat else "    "
            act = menu.addAction(f"{prefix}{label}")
            cat_actions[act] = cat

        menu.addSeparator()
        act_edit = menu.addAction("✏️ 编辑活动名称 & 记住规则…")
        act_view = menu.addAction("🖼️ 查看当时屏幕截图")
        menu.addSeparator()
        act_delete = menu.addAction("🗑️ 删除此时间段记录")

        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        if chosen in cat_actions:
            new_cat = cat_actions[chosen]
            if new_cat != cur_cat or not seg.get("is_manual"):
                self.segment_category_changed.emit(seg, new_cat)
        elif chosen == act_edit:
            self.segment_edit_requested.emit(seg)
        elif chosen == act_view:
            self.segment_clicked.emit(seg)
        elif chosen == act_delete:
            self.segment_delete_requested.emit(seg)

    # ---------- 绘制 ----------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("transparent"))

        if not self._segments:
            painter.setPen(QColor(TEXT_MUTED))
            painter.setFont(QFont(self.font().family(), 10))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_text)
            return

        w = self.width()
        family = self.font().family()

        # 贯穿的竖轴（手绘模式下为带有轻微呼吸感的线稿竖轴）
        axis_top = ROW_MAIN_H / 2 + 2
        axis_bottom = len(self._segments) * ROW_H - ROW_GAP + ROW_MAIN_H / 2
        if DOODLE_MODE:
            from PyQt6.QtGui import QPainterPath
            import math
            axis_path = QPainterPath()
            axis_path.moveTo(AXIS_X, axis_top)
            curr_y = axis_top
            step_y = 16.0
            idx = 0
            while curr_y < axis_bottom:
                next_y = min(curr_y + step_y, axis_bottom)
                mid_y = (curr_y + next_y) / 2
                offset_x = 0.6 * math.sin(idx * 0.8)
                axis_path.quadTo(AXIS_X + offset_x, mid_y, AXIS_X, next_y)
                curr_y = next_y
                idx += 1
            pen = QPen(QColor(BORDER_SOFT))
            pen.setWidthF(1.2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(axis_path)
        else:
            pen = QPen(QColor(BORDER_SOFT))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawLine(AXIS_X, int(axis_top), AXIS_X, int(axis_bottom))

        for i, seg in enumerate(self._segments):
            top = i * ROW_H
            color = QColor(category_color(seg.get("category")))
            hovered = i == self._hover_index

            if hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(BG_ELEVATED))
                painter.drawRoundedRect(
                    QRectF(CONTENT_X - 10, top - 4, w - CONTENT_X + 8, ROW_H - 4), 8, 8
                )
                # 悬停时用分类色做一枚窄标记，提示这条记录属于哪一类
                painter.setBrush(color)
                painter.drawRoundedRect(
                    QRectF(CONTENT_X - 9, top + 4, 2.5, ROW_MAIN_H + ROW_SUB_H - 8), 1.2, 1.2
                )

            # 时间
            painter.setPen(QColor(TEXT_MUTED))
            painter.setFont(QFont(family, 9))
            painter.drawText(
                QRectF(0, top, TIME_COL_W, ROW_MAIN_H),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                seg.get("start_text", ""),
            )

            # 轴上的圆点（手绘小印章/猫爪小圆点）
            dot_r = 5.0 if hovered else 4.0
            cy = top + ROW_MAIN_H / 2
            dot_rect = QRectF(AXIS_X - dot_r, cy - dot_r, dot_r * 2, dot_r * 2)
            if DOODLE_MODE:
                from .doodle_paint import rough_ellipse

                # 外圈色环 + 内心实心点
                painter.setPen(QPen(color, 1.2))
                painter.setBrush(QColor(BG_CARD))
                painter.drawPath(rough_ellipse(dot_rect, seed=i * 7 + 3, amplitude=0.6))

                inner_dot = dot_rect.adjusted(1.5, 1.5, -1.5, -1.5)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawPath(rough_ellipse(inner_dot, seed=i * 7 + 9, amplitude=0.4))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(dot_rect)

            # 活动名
            title_font = QFont(family, 11)
            title_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(title_font)
            painter.setPen(QColor(TEXT_PRIMARY))
            activity = seg.get("activity") or "未分类"
            metric = QFontMetrics(title_font)

            # 时长文字先算宽度，给标题留空间
            dur_font = QFont(family, 9)
            dur_metric = QFontMetrics(dur_font)
            dur_text = seg.get("duration_text", "")
            dur_w = dur_metric.horizontalAdvance(dur_text) + 4

            title_max = w - CONTENT_X - dur_w - 16
            title_text = metric.elidedText(activity, Qt.TextElideMode.ElideRight, int(title_max))
            painter.drawText(
                QRectF(CONTENT_X, top, title_max, ROW_MAIN_H),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                title_text,
            )

            # 时长
            painter.setFont(dur_font)
            painter.setPen(QColor(TEXT_SECONDARY))
            painter.drawText(
                QRectF(w - dur_w - 4, top, dur_w, ROW_MAIN_H),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                dur_text,
            )

            # 第二行：分类标签 + 可选人工校准标记 + 详情
            sub_top = top + ROW_MAIN_H
            cat_text = seg.get("category") or ""
            if cat_text and seg.get("is_manual"):
                cat_text = f"{cat_text} ✎"
            if cat_text:
                tag_font = QFont(family, 8)
                painter.setFont(tag_font)
                tag_metric = QFontMetrics(tag_font)
                tag_w = tag_metric.horizontalAdvance(cat_text) + 14
                tag_rect = QRectF(CONTENT_X, sub_top + 1, tag_w, ROW_SUB_H - 3)
                painter.setPen(Qt.PenStyle.NoPen)
                tag_color = QColor(color)
                tag_color.setAlpha(58)
                painter.setBrush(tag_color)
                if DOODLE_MODE:
                    from .doodle_paint import rough_path

                    painter.drawPath(rough_path(tag_rect, radius=3.0, seed=i * 11 + 5, amplitude=0.7))
                else:
                    painter.drawRoundedRect(tag_rect, 3, 3)
                painter.setPen(color)
                painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, cat_text)
                detail_x = CONTENT_X + tag_w + 10
            else:
                detail_x = CONTENT_X

            detail_font = QFont(family, 9)
            painter.setFont(detail_font)
            painter.setPen(QColor(TEXT_SECONDARY))
            detail_metric = QFontMetrics(detail_font)
            detail_max = max(0, w - detail_x - 12)
            detail = seg.get("detail") or ""
            if detail:
                painter.drawText(
                    QRectF(detail_x, sub_top, detail_max, ROW_SUB_H),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    detail_metric.elidedText(detail, Qt.TextElideMode.ElideRight, int(detail_max)),
                )
