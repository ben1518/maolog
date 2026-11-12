"""拍立得 / 手绘便签学业成就卡片渲染与弹窗。

采用 QPainter 离屏纯矢量绘制，自适应深色/纸质双皮肤，
支持一键复制到剪贴板（微信/QQ 直接 Ctrl+V 发送）与一键导出超清 PNG。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .dialogs import show_info
from .doodle_paint import (
    draw_highlighter_stroke,
    draw_washi_tape,
    draw_wavy_underline,
    rough_bar,
    rough_ellipse,
    rough_path,
)
from .doodle_pet import load_pet
from .theme import IS_DARK_SKIN


CARD_WIDTH = 800
CARD_HEIGHT = 1180


def render_achievement_card(ach: Dict[str, Any], is_dark: bool = False) -> QPixmap:
    """用 QPainter 绘制自适应高度的超清拍立得手绘成就卡长图。"""
    margin = 32.0
    badges = (ach.get("badges") or [])[:3]
    top_apps = (ach.get("top_apps") or [])[:4]

    header_top = margin + 34
    sep_y = header_top + 86
    grid_top = sep_y + 18
    cell_h = 68.0
    badge_sec_top = grid_top + 2 * (cell_h + 12.0) + 12
    badge_y = badge_sec_top + 38
    badge_h = 42.0
    badges_bottom = badge_y + len(badges) * (badge_h + 8) if badges else badge_y + 20
    quote_top = badges_bottom + 18
    quote_box_y = quote_top + 38
    quote_box_h = 100.0
    apps_top = quote_box_y + quote_box_h + 20
    app_y = apps_top + 38
    apps_bottom = app_y + max(1, len(top_apps)) * 32
    footer_y = apps_bottom + 22
    card_height = int(footer_y + 72 + margin)

    pixmap = QPixmap(CARD_WIDTH, card_height)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    # 调色盘
    if is_dark:
        bg_root = QColor("#19181B")
        bg_card = QColor("#262429")
        bg_box = QColor("#302D33")
        border_card = QColor("#545058")
        border_box = QColor("#433F47")
        text_primary = QColor("#F0EAE1")
        text_title = QColor("#FFFFFF")
        text_muted = QColor("#9E988D")
        accent = QColor("#D96B54")
        accent_blue = QColor("#5C9DFF")
        accent_gold = QColor("#E5A93C")
        tape_color = QColor("#4A4640")
    else:
        bg_root = QColor("#F4ECE1")
        bg_card = QColor("#FFFCF7")
        bg_box = QColor("#F7F1E6")
        border_card = QColor("#C2B7A8")
        border_box = QColor("#DCD3C5")
        text_primary = QColor("#2E2B27")
        text_title = QColor("#141311")
        text_muted = QColor("#7A7367")
        accent = QColor("#C4503C")
        accent_blue = QColor("#2B72D6")
        accent_gold = QColor("#C98818")
        tape_color = QColor("#D8CCA8")

    # 1. 外部底垫
    painter.fillRect(0, 0, CARD_WIDTH, card_height, bg_root)

    # 2. 拍立得主卡片（留外白边）
    card_rect = QRectF(margin, margin, CARD_WIDTH - margin * 2, card_height - margin * 2)

    # 微弱手绘投影
    shadow_rect = QRectF(card_rect.x() + 4, card_rect.y() + 5, card_rect.width(), card_rect.height())
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 45 if is_dark else 25))
    painter.drawPath(rough_path(shadow_rect, radius=20.0, seed=7, amplitude=1.2))

    # 卡身
    painter.setBrush(bg_card)
    painter.setPen(QPen(border_card, 2.0))
    painter.drawPath(rough_path(card_rect, radius=20.0, seed=11, amplitude=1.5))

    # 3. 顶部和纸胶带装饰（Washi tape）
    tape_rect = QRectF(CARD_WIDTH / 2.0 - 85, margin - 10, 170, 26)
    draw_washi_tape(painter, tape_rect, color=tape_color.name(), angle=-2.5, seed=19)

    # 4. 头部：猫猫头像 + 标题
    header_top = margin + 34
    cat_img = load_pet("pet-cat.png", 68)
    if cat_img is not None:
        painter.drawImage(QRectF(margin + 26, header_top + 4, 68, 68), cat_img)
        title_x = margin + 106.0
    else:
        title_x = margin + 30.0

    # 标题文字
    painter.setPen(text_title)
    f_title = QFont("Microsoft YaHei", 20)
    f_title.setBold(True)
    painter.setFont(f_title)
    painter.drawText(
        QRectF(title_x, header_top, 480, 36),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        "楚师智学 · 学业成就便签",
    )

    # 副标（日期 + 星期）
    painter.setPen(text_muted)
    f_sub = QFont("Microsoft YaHei", 12)
    painter.setFont(f_sub)
    date_text = f"{ach.get('day', '')}  {ach.get('weekday', '')}  🍄 小精灵伴学 · 记录属于你，未来属于你"
    painter.drawText(
        QRectF(title_x, header_top + 40, 520, 26),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        date_text,
    )

    # 分割线
    line_y = header_top + 82
    painter.setPen(QPen(border_card, 1.2, Qt.PenStyle.DashLine))
    painter.drawLine(int(margin + 24), int(line_y), int(CARD_WIDTH - margin - 24), int(line_y))

    # 5. 核心 4 宫格指标卡
    metrics_top = line_y + 18
    grid_w = (card_rect.width() - 48 - 14) / 2.0
    grid_h = 72.0

    cards_info = [
        ("今日总工时", f"{ach.get('total_hours', 0)} h", accent),
        ("有效专注产出", f"{ach.get('productive_hours', 0)} h", accent_blue),
        ("最长连续心流", f"{ach.get('max_flow_minutes', 0)} min", accent_gold),
        ("动手产出占比", f"{ach.get('produce_ratio', 0)}%", text_primary),
    ]

    for idx, (label, val, col) in enumerate(cards_info):
        r_col = idx % 2
        r_row = idx // 2
        bx = margin + 24 + r_col * (grid_w + 14)
        by = metrics_top + r_row * (grid_h + 12)
        b_rect = QRectF(bx, by, grid_w, grid_h)

        # 小框底槽
        painter.setPen(QPen(border_box, 1.2))
        painter.setBrush(bg_box)
        painter.drawPath(rough_path(b_rect, radius=12.0, seed=idx * 23 + 3, amplitude=0.8))

        # 标签
        painter.setPen(text_muted)
        painter.setFont(QFont("Microsoft YaHei", 10))
        painter.drawText(
            QRectF(bx + 14, by + 10, grid_w - 28, 20),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label,
        )

        # 数值
        painter.setPen(col)
        f_num = QFont("Cascadia Mono", 16)
        f_num.setBold(True)
        painter.setFont(f_num)
        painter.drawText(
            QRectF(bx + 14, by + 32, grid_w - 28, 30),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            val,
        )

    # 6. 今日荣誉勋章展台
    badges_top = metrics_top + grid_h * 2 + 32
    painter.setPen(text_title)
    f_sec = QFont("Microsoft YaHei", 13)
    f_sec.setBold(True)
    painter.setFont(f_sec)
    painter.drawText(
        QRectF(margin + 24, badges_top, 300, 24),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        "🏅 今日解锁勋章",
    )
    draw_wavy_underline(painter, margin + 24, badges_top + 26, 128, color=accent.name())

    badges = ach.get("badges") or []
    badge_y = badges_top + 38
    badge_w = card_rect.width() - 48
    badge_h = 44.0

    if badges:
        for b_idx, b in enumerate(badges[:3]):
            brect = QRectF(margin + 24, badge_y + b_idx * (badge_h + 8), badge_w, badge_h)
            painter.setPen(QPen(border_box, 1.0))
            painter.setBrush(bg_box)
            painter.drawPath(rough_bar(brect, seed=b_idx * 17 + 5, amplitude=0.6))

            # 徽章图标
            painter.setPen(text_title)
            painter.setFont(QFont("Segoe UI Emoji", 15))
            painter.drawText(
                QRectF(brect.x() + 12, brect.y(), 34, badge_h),
                int(Qt.AlignmentFlag.AlignCenter),
                b.get("icon", "🍄"),
            )

            # 徽章名称
            painter.setPen(accent if b_idx == 0 else text_primary)
            f_bname = QFont("Microsoft YaHei", 11)
            f_bname.setBold(True)
            painter.setFont(f_bname)
            painter.drawText(
                QRectF(brect.x() + 50, brect.y() + 4, 160, badge_h - 8),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                b.get("name", ""),
            )

            # 徽章描述
            painter.setPen(text_muted)
            painter.setFont(QFont("Microsoft YaHei", 10))
            painter.drawText(
                QRectF(brect.x() + 210, brect.y() + 4, brect.width() - 220, badge_h - 8),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                b.get("desc", ""),
            )
        badges_bottom = badge_y + len(badges[:3]) * (badge_h + 8)
    else:
        badges_bottom = badge_y + 20

    # 7. AI 复盘高光评语（引用框）
    quote_top = badges_bottom + 18
    painter.setPen(text_title)
    painter.setFont(f_sec)
    painter.drawText(
        QRectF(margin + 24, quote_top, 300, 24),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        "💡 今日复盘高光",
    )
    draw_wavy_underline(painter, margin + 24, quote_top + 26, 128, color=accent_gold.name())

    quote_box_y = quote_top + 38
    quote_box_h = 100.0
    q_rect = QRectF(margin + 24, quote_box_y, card_rect.width() - 48, quote_box_h)

    painter.setPen(QPen(border_box, 1.2))
    painter.setBrush(bg_box)
    painter.drawPath(rough_path(q_rect, radius=14.0, seed=43, amplitude=1.0))

    # 大引号装饰
    painter.setPen(accent_gold)
    f_quote = QFont("Georgia", 32)
    f_quote.setBold(True)
    painter.setFont(f_quote)
    painter.drawText(QRectF(q_rect.x() + 14, q_rect.y() + 4, 30, 36), int(Qt.AlignmentFlag.AlignLeft), "“")

    # 引文内容自动折行
    painter.setPen(text_primary)
    f_text = QFont("Microsoft YaHei", 10)
    painter.setFont(f_text)
    hl_text = ach.get("highlight", "今天还没有足够的数据，保持自律，开始今天的学习吧！")
    painter.drawText(
        QRectF(q_rect.x() + 44, q_rect.y() + 16, q_rect.width() - 60, q_rect.height() - 24),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
        hl_text,
    )

    # 8. 主要应用精力分布
    apps_top = quote_box_y + quote_box_h + 20
    painter.setPen(text_title)
    painter.setFont(f_sec)
    painter.drawText(
        QRectF(margin + 24, apps_top, 300, 24),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        "📊 主要精力流向",
    )
    draw_wavy_underline(painter, margin + 24, apps_top + 26, 128, color=accent_blue.name())

    app_y = apps_top + 38
    bar_max_w = card_rect.width() - 48 - 190.0

    for a_idx, app_item in enumerate(top_apps):
        ay = app_y + a_idx * 32
        aname = app_item.get("app", "未知")
        apct = app_item.get("ratio", 0)
        adur = app_item.get("duration", "")

        # 应用名
        painter.setPen(text_primary)
        painter.setFont(QFont("Microsoft YaHei", 10))
        fm = QFontMetrics(painter.font())
        elided_name = fm.elidedText(aname, Qt.TextElideMode.ElideRight, 130)
        painter.drawText(
            QRectF(margin + 24, ay, 130, 22),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided_name,
        )

        # 进度底槽
        bar_x = margin + 160.0
        track_rect = QRectF(bar_x, ay + 6, bar_max_w, 10.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_box)
        painter.drawRoundedRect(track_rect, 5.0, 5.0)

        # 荧光笔高亮条
        fill_w = max(6.0, bar_max_w * (apct / 100.0))
        fill_rect = QRectF(bar_x, ay + 6, fill_w, 10.0)
        draw_highlighter_stroke(painter, fill_rect, color=(accent_blue if a_idx == 0 else accent).name(), seed=a_idx * 19 + 7)

        # 百分比与时长
        painter.setPen(text_muted)
        painter.setFont(QFont("Cascadia Mono", 9))
        painter.drawText(
            QRectF(CARD_WIDTH - margin - 85, ay, 65, 22),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            f"{apct}%",
        )

    # 9. 底部签名印章与学业寄语
    footer_y = app_y + max(1, len(top_apps)) * 32 + 22
    painter.setPen(QPen(border_box, 1.0, Qt.PenStyle.DotLine))
    painter.drawLine(int(margin + 24), int(footer_y), int(CARD_WIDTH - margin - 24), int(footer_y))

    # 手绘红印章
    stamp_rect = QRectF(margin + 24, footer_y + 12, 110, 42)
    painter.setPen(QPen(accent, 1.8))
    painter.setBrush(Qt.GlobalColor.transparent)
    painter.drawPath(rough_path(stamp_rect, radius=8.0, seed=51, amplitude=0.9))

    painter.setPen(accent)
    f_stamp = QFont("Microsoft YaHei", 10)
    f_stamp.setBold(True)
    painter.setFont(f_stamp)
    painter.drawText(stamp_rect, int(Qt.AlignmentFlag.AlignCenter), "楚师智学 · 存证")

    # 右侧参赛金句
    painter.setPen(text_muted)
    f_quote_btm = QFont("Microsoft YaHei", 9)
    painter.setFont(f_quote_btm)
    painter.drawText(
        QRectF(margin + 150, footer_y + 14, card_rect.width() - 170, 38),
        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
        "动感地带 AI 赋能校园创新大赛 · 主题一作品\n“所有沉浸在专注里的时刻，都在悄悄塑造未来的你”",
    )

    painter.end()
    return pixmap


class AchievementDialog(QDialog):
    """学业成就便签预览与一键导出弹窗。"""

    def __init__(self, parent, ach_data: Dict[str, Any]) -> None:
        super().__init__(parent)
        self.ach_data = ach_data
        self.is_dark = IS_DARK_SKIN

        self.setWindowTitle("学业成就便签 🍄")
        self.resize(520, 760)
        self.setMinimumSize(460, 600)
        self.setStyleSheet("QDialog { background: #1E1D20; }" if self.is_dark else "QDialog { background: #F6F1EA; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # 头部说明
        top_bar = QHBoxLayout()
        title = QLabel("今日研学成就便签")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF;" if self.is_dark else "font-size: 16px; font-weight: bold; color: #1E1D20;")
        top_bar.addWidget(title)
        top_bar.addStretch(1)

        self.btn_toggle_skin = QPushButton("切换风格 (浅/深)")
        self.btn_toggle_skin.setFixedHeight(28)
        self.btn_toggle_skin.clicked.connect(self._toggle_skin)
        top_bar.addWidget(self.btn_toggle_skin)
        root.addLayout(top_bar)

        # 中间可滚动卡片预览
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.card_label = QLabel()
        self.card_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(self.card_label)
        root.addWidget(scroll, 1)

        # 底部操作栏
        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #4CAF50; font-size: 12px;")
        bottom.addWidget(self.status_label, 1)

        btn_close = QPushButton("关闭")
        btn_close.setFixedHeight(34)
        btn_close.clicked.connect(self.accept)

        self.btn_copy = QPushButton("复制图片 📋")
        self.btn_copy.setFixedHeight(34)
        self.btn_copy.setStyleSheet(
            "QPushButton { background: #45424B; color: #FFF; border-radius: 8px; padding: 0 16px; font-weight: bold; }"
            if self.is_dark else
            "QPushButton { background: #EFE7DA; color: #333; border-radius: 8px; padding: 0 16px; font-weight: bold; }"
        )
        self.btn_copy.clicked.connect(self._copy_image)

        self.btn_save = QPushButton("保存高清长图 💾")
        self.btn_save.setFixedHeight(34)
        self.btn_save.setStyleSheet(
            "QPushButton { background: #D96B54; color: #FFF; border-radius: 8px; padding: 0 18px; font-weight: bold; }"
        )
        self.btn_save.clicked.connect(self._save_image)

        bottom.addWidget(btn_close)
        bottom.addWidget(self.btn_copy)
        bottom.addWidget(self.btn_save)
        root.addLayout(bottom)

        self._current_pixmap = QPixmap()
        self._refresh_card()

    def _toggle_skin(self) -> None:
        self.is_dark = not self.is_dark
        self._refresh_card()

    def _refresh_card(self) -> None:
        self._current_pixmap = render_achievement_card(self.ach_data, is_dark=self.is_dark)
        # 弹窗内按合适宽度缩放展示，导出时保持原超清大图
        scaled = self._current_pixmap.scaledToWidth(440, Qt.TransformationMode.SmoothTransformation)
        self.card_label.setPixmap(scaled)

    def _copy_image(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None and not self._current_pixmap.isNull():
            clipboard.setPixmap(self._current_pixmap)
            self.status_label.setText("✅ 已复制到剪贴板，直接在微信/QQ粘贴即可！")

    def _save_image(self) -> None:
        if self._current_pixmap.isNull():
            return
        day = self.ach_data.get("day", "today")
        default_name = f"楚师智学_成就便签_{day}.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存成就便签长图",
            default_name,
            "PNG 图片 (*.png);;所有文件 (*.*)",
        )
        if path:
            self._current_pixmap.save(path, "PNG")
            self.status_label.setText("✅ 已保存到本地")
            show_info(self, "保存成功", f"成就长图已成功保存到：\n{path}")
