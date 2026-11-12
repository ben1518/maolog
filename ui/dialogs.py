"""统一手绘手帐风格弹窗：欢迎引导、信息提示、警告与确认对话框。

替代系统默认的 QMessageBox（避免原生蓝底 i 图标和生硬的窗口框破坏手绘视觉一致性）。
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .brand import brand_pixmap
from .doodle_paint import (
    RoughButton,
    draw_notebook_background,
    draw_washi_tape,
    paint_rough_frame,
    rough_ellipse,
)
from .theme import (
    ACCENT,
    ACCENT_DARK,
    ASSET_DIR,
    BG_CARD,
    BG_ELEVATED,
    BG_INSET,
    BORDER,
    BORDER_SOFT,
    DANGER,
    DOODLE_MODE,
    IS_DARK_SKIN,
    ON_ACCENT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
)

_SHADOW_PAD = 16


class _PopupCard(QFrame):
    """带纸面纹理、手绘描边与顶部和纸胶带的弹窗容器。"""

    def __init__(
        self,
        tape_color: str = "#7EA6D2",
        seed: int = 23,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tape_color = tape_color
        self._seed = seed
        self.setObjectName("JournalPopupCard")
        self.setStyleSheet("QFrame#JournalPopupCard { background: transparent; border: none; }")

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        card_rect = QRectF(self.rect()).adjusted(1.5, 6.0, -1.5, -1.5)

        # 1. 背景纸面底色与极淡点阵裁剪
        clip = QPainterPath()
        clip.addRoundedRect(card_rect, 16.0, 16.0)
        painter.save()
        painter.setClipPath(clip)
        painter.fillRect(card_rect, QColor(BG_CARD))
        if DOODLE_MODE:
            draw_notebook_background(painter, card_rect, is_dark=IS_DARK_SKIN)
        painter.restore()

        # 2. 手绘质感外框
        paint_rough_frame(
            painter,
            card_rect,
            color=BORDER,
            width=1.7,
            radius=16.0,
            seed=self._seed,
            fill=None,
            amplitude=1.1,
        )

        # 3. 顶部居中贴一条和纸胶带
        if DOODLE_MODE:
            draw_washi_tape(
                painter,
                QRectF(card_rect.center().x() - 42, card_rect.top() - 5, 84, 15),
                color=self._tape_color,
                angle=-1.6,
                pattern="dots",
                seed=self._seed + 7,
            )

        painter.end()
        super().paintEvent(event)


class _SemanticBadge(QWidget):
    """手绘风格语义角标（替代系统 QMessageBox 的蓝底 i / 黄三角 !）。"""

    def __init__(self, kind: str = "info", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(46, 46)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        palette = {
            "info": (ACCENT, ACCENT_DARK),
            "warning": (WARNING, "#3D311E" if IS_DARK_SKIN else "#FAF0DA"),
            "question": (ACCENT, ACCENT_DARK),
            "danger": (DANGER, "#3F2625" if IS_DARK_SKIN else "#FCEAE8"),
        }
        fg_hex, bg_hex = palette.get(self._kind, palette["info"])
        fg = QColor(fg_hex)
        bg = QColor(bg_hex)

        circle_rect = QRectF(4, 4, 38, 38)
        halo = rough_ellipse(circle_rect, seed=13, amplitude=0.8) if DOODLE_MODE else None
        painter.setBrush(bg)
        painter.setPen(QPen(fg, 1.8))
        if halo is not None:
            painter.drawPath(halo)
        else:
            painter.drawEllipse(circle_rect)

        glyph = {"info": "i", "warning": "!", "question": "?", "danger": "!"}.get(
            self._kind, "i"
        )
        font = QFont(self.font())
        font.setPointSize(16)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(fg)
        painter.drawText(circle_rect.adjusted(0, -1, 0, -1), Qt.AlignmentFlag.AlignCenter, glyph)
        painter.end()


class _JournalPopupBase(QDialog):
    """无边框、可拖拽、带柔和投影的手绘弹窗基类。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        tape_color: str = "#7EA6D2",
        seed: int = 23,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self._drag_offset: QPoint | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_SHADOW_PAD, _SHADOW_PAD, _SHADOW_PAD, _SHADOW_PAD)

        self._card = _PopupCard(tape_color=tape_color, seed=seed, parent=self)
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 140 if IS_DARK_SKIN else 55))
        self._card.setGraphicsEffect(shadow)
        outer.addWidget(self._card)

        self._body_layout = QVBoxLayout(self._card)
        self._body_layout.setContentsMargins(24, 22, 22, 20)
        self._body_layout.setSpacing(14)

    def _make_close_button(self) -> QPushButton:
        btn = QPushButton("×", self._card)
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("关闭")
        btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_MUTED};
                border: none;
                border-radius: 8px;
                font-size: 17px;
                padding: 0;
                min-height: 0;
            }}
            QPushButton:hover {{
                background: {BG_ELEVATED};
                color: {TEXT_PRIMARY};
            }}
            """
        )
        btn.clicked.connect(self.reject)
        return btn

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if not isinstance(child, QPushButton):
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class WelcomeDialog(_JournalPopupBase):
    """首次启动欢迎引导弹窗：突出「本地免 Key 即用」与「AI 视觉增强」双模式。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, tape_color="#7EA6D2", seed=41)
        self.setWindowTitle("欢迎使用 MaoLog")
        self.setFixedWidth(548)
        self.go_settings = False
        self._build_ui()

    def _load_mascot(self) -> QPixmap:
        sprite = ASSET_DIR / "doodle" / "mushroom_sprites" / "wave.png"
        if sprite.exists():
            pix = QPixmap(str(sprite))
            if not pix.isNull():
                return pix.scaled(
                    68, 68,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        return brand_pixmap(56)

    def _build_ui(self) -> None:
        # 1. 顶部：小精灵头像 + 标题 + 关闭按钮
        header = QHBoxLayout()
        header.setSpacing(14)

        mascot_wrap = QLabel(self._card)
        mascot_wrap.setFixedSize(72, 72)
        mascot_wrap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mascot_wrap.setPixmap(self._load_mascot())
        mascot_wrap.setStyleSheet(
            f"""
            QLabel {{
                background: {BG_INSET};
                border: 1px solid {BORDER_SOFT};
                border-radius: 36px;
            }}
            """
        )
        header.addWidget(mascot_wrap, alignment=Qt.AlignmentFlag.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(5)

        eyebrow = QLabel("MAOLOG · 欢迎使用")
        eyebrow.setStyleSheet(
            f"""
            color: {ACCENT};
            font-size: 10.5px;
            font-weight: 600;
            letter-spacing: 1.4px;
            """
        )
        title_col.addWidget(eyebrow)

        title = QLabel("你好呀，我是你的记录小精灵")
        title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 18px; font-weight: 600;"
        )
        title_col.addWidget(title)

        subtitle = QLabel("MaoLog 会安静地在后台记录你的电脑使用节奏，帮你复盘每天的专注时光。")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12.5px; line-height: 1.45;")
        title_col.addWidget(subtitle)

        header.addLayout(title_col, stretch=1)
        header.addWidget(self._make_close_button(), alignment=Qt.AlignmentFlag.AlignTop)
        self._body_layout.addLayout(header)

        # 2. 双模式说明卡片（清晰传达免 Key 可用，消除未配 API 的困惑）
        cards_col = QVBoxLayout()
        cards_col.setSpacing(10)

        cards_col.addWidget(
            self._mode_card(
                badge="本地免 Key",
                badge_color=ACCENT,
                badge_bg=ACCENT_DARK,
                title="●  开箱即用 · 纯本地规则引擎已就绪",
                desc="不接 API 也能直接使用：自动感知前台窗口与软件语义，本地生成时间轴、分类占比与排行，数据 100% 留在你的电脑里。",
            )
        )
        cards_col.addWidget(
            self._mode_card(
                badge="AI 进阶",
                badge_color="#82A9D6" if IS_DARK_SKIN else "#5A85B8",
                badge_bg="#252E3A" if IS_DARK_SKIN else "#E8F0FA",
                title="●  接入视觉大模型 · 看懂屏幕细节",
                desc="推荐「通义千问 VL」或「智谱 GLM-4V」（glm-4v-flash 目前免费、国内直连），填入 API Key 后可解锁深度日常复盘手记。",
            )
        )
        self._body_layout.addLayout(cards_col)

        # 3. 底部操作栏
        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.setContentsMargins(0, 4, 0, 0)

        tip = QLabel("随时可在右上角「设置」中切换")
        tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11.5px;")
        footer.addWidget(tip)
        footer.addStretch(1)

        self.btn_later = RoughButton("先用本地模式", self._card, variant="ghost", radius=9.0, seed=11)
        self.btn_later.setObjectName("Ghost")
        self.btn_later.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_later.clicked.connect(self.reject)
        footer.addWidget(self.btn_later)

        self.btn_go = RoughButton("去设置接入 AI", self._card, variant="primary", radius=9.0, seed=19)
        self.btn_go.setObjectName("Primary")
        self.btn_go.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_go.setStyleSheet(
            f"""
            QPushButton#Primary {{
                background: transparent;
                border: none;
                color: {ON_ACCENT};
                font-weight: 600;
                padding: 8px 18px;
            }}
            """
        )
        self.btn_go.clicked.connect(self._accept_settings)
        footer.addWidget(self.btn_go)

        self._body_layout.addLayout(footer)

    def _mode_card(
        self,
        badge: str,
        badge_color: str,
        badge_bg: str,
        title: str,
        desc: str,
    ) -> QFrame:
        box = QFrame(self._card)
        box.setObjectName("WelcomeModeBox")
        box.setStyleSheet(
            f"""
            QFrame#WelcomeModeBox {{
                background: {BG_INSET};
                border: 1px solid {BORDER_SOFT};
                border-radius: 11px;
            }}
            """
        )
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(8)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 600;")
        top.addWidget(lbl_title)
        top.addStretch(1)

        pill = QLabel(badge)
        pill.setStyleSheet(
            f"""
            color: {badge_color};
            background: {badge_bg};
            border: 1px solid {BORDER_SOFT};
            border-radius: 8px;
            padding: 2px 8px;
            font-size: 10.5px;
            font-weight: 600;
            """
        )
        top.addWidget(pill)
        lay.addLayout(top)

        lbl_desc = QLabel(desc)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; line-height: 1.45;")
        lay.addWidget(lbl_desc)
        return box

    def _accept_settings(self) -> None:
        self.go_settings = True
        self.accept()


class JournalMessageDialog(_JournalPopupBase):
    """统一的手绘信息 / 警告 / 确认弹窗。"""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        text: str,
        kind: str = "info",
        confirm_text: str = "知道了",
        cancel_text: str | None = None,
        danger: bool = False,
    ) -> None:
        tape_map = {
            "info": "#7EA6D2",
            "warning": "#E8B067",
            "question": "#8FAE7A",
            "danger": "#E88E85",
        }
        badge_kind = "danger" if danger else kind
        super().__init__(
            parent,
            tape_color=tape_map.get(badge_kind, "#7EA6D2"),
            seed=abs(hash(title)) % 79 + 7,
        )
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.setMaximumWidth(480)
        self._build_ui(title, text, badge_kind, confirm_text, cancel_text, danger)

    def _build_ui(
        self,
        title: str,
        text: str,
        kind: str,
        confirm_text: str,
        cancel_text: str | None,
        danger: bool,
    ) -> None:
        top = QHBoxLayout()
        top.setSpacing(14)

        badge = _SemanticBadge(kind, self._card)
        top.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)

        content = QVBoxLayout()
        content.setSpacing(6)

        title_row = QHBoxLayout()
        lbl_title = QLabel(title)
        lbl_title.setWordWrap(True)
        lbl_title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15.5px; font-weight: 600;"
        )
        title_row.addWidget(lbl_title, stretch=1)
        title_row.addWidget(self._make_close_button(), alignment=Qt.AlignmentFlag.AlignTop)
        content.addLayout(title_row)

        lbl_body = QLabel(text)
        lbl_body.setWordWrap(True)
        lbl_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl_body.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12.8px; line-height: 1.5;"
        )
        content.addWidget(lbl_body)

        top.addLayout(content, stretch=1)
        self._body_layout.addLayout(top)

        # 底部按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.setContentsMargins(0, 4, 0, 0)
        btn_row.addStretch(1)

        if cancel_text:
            btn_cancel = RoughButton(cancel_text, self._card, variant="ghost", radius=9.0, seed=13)
            btn_cancel.setObjectName("Ghost")
            btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_cancel.clicked.connect(self.reject)
            btn_row.addWidget(btn_cancel)

        if danger:
            btn_ok = RoughButton(confirm_text, self._card, variant="ghost", radius=9.0, seed=29)
            btn_ok.setObjectName("Danger")
            btn_ok.setStyleSheet(
                f"""
                QPushButton#Danger {{
                    background: {"#3F2625" if IS_DARK_SKIN else "#FCEAE8"};
                    border: none;
                    color: {DANGER};
                    font-weight: 600;
                    padding: 7px 16px;
                }}
                QPushButton#Danger:hover {{
                    color: {TEXT_PRIMARY};
                }}
                """
            )
        else:
            btn_ok = RoughButton(confirm_text, self._card, variant="primary", radius=9.0, seed=29)
            btn_ok.setObjectName("Primary")
            btn_ok.setStyleSheet(
                f"""
                QPushButton#Primary {{
                    background: transparent;
                    border: none;
                    color: {ON_ACCENT};
                    font-weight: 600;
                    padding: 7px 18px;
                }}
                """
            )
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)

        self._body_layout.addLayout(btn_row)


def show_info(
    parent: QWidget | None,
    title: str,
    text: str,
    button_text: str = "知道了",
) -> None:
    dlg = JournalMessageDialog(
        parent, title=title, text=text, kind="info", confirm_text=button_text
    )
    dlg.exec()


def show_warning(
    parent: QWidget | None,
    title: str,
    text: str,
    button_text: str = "知道了",
) -> None:
    dlg = JournalMessageDialog(
        parent, title=title, text=text, kind="warning", confirm_text=button_text
    )
    dlg.exec()


def ask_confirm(
    parent: QWidget | None,
    title: str,
    text: str,
    confirm_text: str = "确定",
    cancel_text: str = "取消",
    danger: bool = False,
) -> bool:
    dlg = JournalMessageDialog(
        parent,
        title=title,
        text=text,
        kind="danger" if danger else "question",
        confirm_text=confirm_text,
        cancel_text=cancel_text,
        danger=danger,
    )
    return dlg.exec() == QDialog.DialogCode.Accepted
