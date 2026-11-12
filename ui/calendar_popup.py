"""Windows 风格深色快捷日历弹窗。

匹配用户系统风格：
- 顶部大标题：11月12日，星期四
- 月份导航：2026年11月 + 上下月切换 + 回到今天
- 星期标题栏：一 二 三 四 五 六 日
- 42 格完整月历（含上月末与下月初留白日期）
- 当前选中日期呈圆角实心暖橙色印章（与系统日历保持一致）
- 有学习/使用记录的日期在数字下方显示精致伴读标记点
- 自动限制在「第一天打开」与「今天」之间，超出范围自动置灰不可点
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from PyQt6.QtCore import QPoint, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import (
    ACCENT,
    BG_CARD,
    BG_ELEVATED,
    BORDER,
    BORDER_SOFT,
    ON_ACCENT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)

WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]


class _DayButton(QPushButton):
    """单个日期按钮，支持选中圆圈、伴读记录小圆点和置灰禁用。"""

    def __init__(
        self,
        day_date: date,
        is_cur_month: bool,
        is_selected: bool,
        is_today: bool,
        has_data: bool,
        is_enabled: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.day_date = day_date
        self.is_cur_month = is_cur_month
        self.is_selected = is_selected
        self.is_today = is_today
        self.has_data = has_data
        self.is_date_enabled = is_enabled

        self.setFixedSize(38, 38)
        self.setEnabled(is_enabled)
        self.setCursor(Qt.CursorShape.PointingHandCursor if is_enabled else Qt.CursorShape.ArrowCursor)

        tip_parts = [day_date.strftime("%Y年%m月%d日")]
        if is_today:
            tip_parts.append("（今天）")
        if has_data:
            tip_parts.append("· 有伴读记录 🍄")
        elif not is_enabled:
            tip_parts.append("· 无记录或未开启")
        self.setToolTip("".join(tip_parts))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect())
        cx = rect.center().x()
        cy = rect.center().y()

        # 1. 选中底色：正圆暖橙色印章
        if self.is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ACCENT))
            painter.drawEllipse(QPoint(int(cx), int(cy)), 17, 17)
        elif self.is_today:
            # 今天的虚线或细圆环标示
            painter.setPen(QPen(QColor(ACCENT), 1.4, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(int(cx), int(cy)), 16, 16)
        elif self.underMouse() and self.is_date_enabled:
            # 悬停微高亮
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BG_ELEVATED))
            painter.drawEllipse(QPoint(int(cx), int(cy)), 16, 16)

        # 2. 数字文字
        font = QFont(self.font().family(), 10)
        if self.is_selected:
            font.setWeight(QFont.Weight.Bold)
            painter.setPen(QColor(ON_ACCENT))
        elif not self.is_date_enabled:
            painter.setPen(QColor(TEXT_MUTED).lighter(70) if not self.is_cur_month else QColor(TEXT_MUTED))
        elif not self.is_cur_month:
            painter.setPen(QColor(TEXT_MUTED))
        else:
            font.setWeight(QFont.Weight.Medium)
            painter.setPen(QColor(TEXT_PRIMARY))

        painter.setFont(font)
        # 上移 2px 为下方小圆点留空
        text_rect = QRectF(rect.left(), rect.top() + (1 if self.has_data else 3), rect.width(), rect.height() - 8)
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignCenter), str(self.day_date.day))

        # 3. 伴读记录标记点（有数据时在数字下方点缀）
        if self.has_data and self.is_date_enabled:
            painter.setPen(Qt.PenStyle.NoPen)
            if self.is_selected:
                painter.setBrush(QColor(ON_ACCENT))
            else:
                painter.setBrush(QColor(ACCENT))
            dot_y = cy + 12.0
            painter.drawEllipse(QPoint(int(cx), int(dot_y)), 2, 2)

        painter.end()


class CalendarPopup(QDialog):
    """弹出式月历选天组件。"""

    date_selected = pyqtSignal(date)

    def __init__(
        self,
        current_date: date,
        earliest_date: date,
        days_with_data: set[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(320)

        self._selected_date = current_date
        self._view_year = current_date.year
        self._view_month = current_date.month
        self._earliest_date = earliest_date
        self._today = date.today()
        self._days_with_data = days_with_data

        self._build_ui()

    def _build_ui(self) -> None:
        container = QFrame(self)
        container.setObjectName("CalendarContainer")
        container.setStyleSheet(
            f"""
            QFrame#CalendarContainer {{
                background: {BG_CARD};
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        # 1. 顶部大标题：11月12日，星期四
        self.lbl_head_title = QLabel()
        self.lbl_head_title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: bold;")
        self.lbl_head_sub = QLabel()
        self.lbl_head_sub.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(self.lbl_head_title)
        layout.addWidget(self.lbl_head_sub)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {BORDER_SOFT}; background-color: {BORDER_SOFT}; max-height: 1px;")
        layout.addWidget(line)

        # 2. 年月与翻月导航
        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)

        self.lbl_month = QLabel()
        self.lbl_month.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13.5px; font-weight: 600;")
        nav_row.addWidget(self.lbl_month)
        nav_row.addStretch(1)

        self.btn_prev_m = QPushButton("▲")
        self.btn_prev_m.setFixedSize(26, 26)
        self.btn_prev_m.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_prev_m.setToolTip("上一个月")
        self.btn_prev_m.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEVATED}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_SOFT}; border-radius: 5px; font-size: 10px; }}"
            f"QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}"
        )
        self.btn_prev_m.clicked.connect(lambda: self._shift_month(-1))

        self.btn_next_m = QPushButton("▼")
        self.btn_next_m.setFixedSize(26, 26)
        self.btn_next_m.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next_m.setToolTip("下一个月")
        self.btn_next_m.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEVATED}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_SOFT}; border-radius: 5px; font-size: 10px; }}"
            f"QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}"
        )
        self.btn_next_m.clicked.connect(lambda: self._shift_month(1))

        self.btn_to_today = QPushButton("今天")
        self.btn_to_today.setFixedHeight(26)
        self.btn_to_today.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_to_today.setStyleSheet(
            f"QPushButton {{ background: {BG_ELEVATED}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_SOFT}; border-radius: 5px; padding: 0 8px; font-size: 11px; }}"
            f"QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}"
        )
        self.btn_to_today.clicked.connect(self._goto_today)

        nav_row.addWidget(self.btn_to_today)
        nav_row.addWidget(self.btn_prev_m)
        nav_row.addWidget(self.btn_next_m)
        layout.addLayout(nav_row)

        # 3. 星期标题栏
        week_row = QHBoxLayout()
        week_row.setSpacing(2)
        for w_name in WEEKDAYS:
            w_lbl = QLabel(w_name)
            w_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            w_lbl.setFixedWidth(38)
            w_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; font-weight: bold;")
            week_row.addWidget(w_lbl)
        layout.addLayout(week_row)

        # 4. 日期表格网格
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(2)
        layout.addLayout(self.grid_layout)

        self._refresh_calendar()

    def _shift_month(self, delta: int) -> None:
        y, m = self._view_year, self._view_month + delta
        if m < 1:
            y -= 1
            m = 12
        elif m > 12:
            y += 1
            m = 1
        self._view_year, self._view_month = y, m
        self._refresh_calendar()

    def _goto_today(self) -> None:
        self._selected_date = self._today
        self._view_year = self._today.year
        self._view_month = self._today.month
        self._refresh_calendar()
        self._on_date_clicked(self._today)

    def _refresh_calendar(self) -> None:
        # 更新头部标题
        w_idx = self._selected_date.weekday()
        w_str = WEEKDAYS[w_idx]
        self.lbl_head_title.setText(f"{self._selected_date.month}月{self._selected_date.day}日，星期{w_str}")
        self.lbl_head_sub.setText(f"伴读记录首日：{self._earliest_date.strftime('%Y年%m月%d日')} 🍄")

        self.lbl_month.setText(f"{self._view_year}年{self._view_month}月")

        # 判断是否能向前/后翻月
        earliest_month_first = date(self._earliest_date.year, self._earliest_date.month, 1)
        cur_view_first = date(self._view_year, self._view_month, 1)
        today_month_first = date(self._today.year, self._today.month, 1)

        self.btn_prev_m.setEnabled(cur_view_first > earliest_month_first)
        self.btn_next_m.setEnabled(cur_view_first < today_month_first)

        # 清除现有表格
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        # 生成 42 天完整网格（以周一为一周起始，补足 6 周确保高度稳定）
        cal = calendar.Calendar(firstweekday=0)
        weeks = list(cal.monthdatescalendar(self._view_year, self._view_month))
        while len(weeks) < 6:
            last_d = weeks[-1][-1]
            extra_week = [last_d + timedelta(days=i) for i in range(1, 8)]
            weeks.append(extra_week)

        for r_idx, week in enumerate(weeks):
            for c_idx, day_d in enumerate(week):
                is_cur_month = day_d.month == self._view_month
                is_selected = day_d == self._selected_date
                is_today = day_d == self._today
                has_data = day_d.strftime("%Y-%m-%d") in self._days_with_data
                is_enabled = self._earliest_date <= day_d <= self._today

                btn = _DayButton(
                    day_date=day_d,
                    is_cur_month=is_cur_month,
                    is_selected=is_selected,
                    is_today=is_today,
                    has_data=has_data,
                    is_enabled=is_enabled,
                )
                if is_enabled:
                    btn.clicked.connect(lambda _checked=False, d=day_d: self._on_date_clicked(d))
                self.grid_layout.addWidget(btn, r_idx, c_idx)

        self.adjustSize()

    def _on_date_clicked(self, chosen: date) -> None:
        self.date_selected.emit(chosen)
        self.accept()

    def popup_at(self, anchor_pos: QPoint) -> None:
        """在指定全局锚点（如日期按钮下方）显示，并确保不出屏幕。"""
        self.adjustSize()
        x = anchor_pos.x()
        y = anchor_pos.y()
        self.move(x, y)
        self.show()
        self.raise_()
