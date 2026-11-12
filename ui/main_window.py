"""主窗口：今日看板。

结构：
  顶栏（标题 + 日期导航 + 操作）
  概览卡片 × 4
  主体：左时间轴 / 右分类占比 + 应用排行
  AI 今日总结
  状态栏
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QRectF, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QPixmap, QTextDocument
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.ai_client import AIClient
from core.app_names import resolve_app_display_name
from .dialogs import ask_confirm, show_warning
from core.config import Config
from core.daily import generate as generate_summary
from core.daily import fallback_summary
from core.local_classifier import save_user_rule
from core.storage import Storage, format_duration

from .ai_profile_dialog import AIProfileDialog
from .study_review_dialog import StudyReviewDialog
from .brand import make_icon_label, make_wordmark, ui_icon
from .components import AppRankWidget, DonutChart, EmptyState, FadeOverlay, StatCard
from .doodle_paint import RoughButton, RoughFrame
from .segment_edit_dialog import SegmentEditDialog
from .theme import (
    DOODLE_MODE,
    ON_ACCENT,
    ACCENT,
    BG_CARD,
    BG_ELEVATED,
    BG_INSET,
    BORDER,
    BORDER_SOFT,
    CATEGORY_COLORS,
    DANGER,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
    category_color,
)
from .time_estimate_dialog import TimeEstimateDialog
from .timeline import TimelineWidget


def _tool_button(text: str = "", variant: str = "ghost", radius: float = 9.0) -> QPushButton:
    """手绘模式返回自绘按钮，否则还是普通 QPushButton。"""
    if DOODLE_MODE:
        return RoughButton(text, variant=variant, radius=radius)
    return QPushButton(text)


class _DecorRoot(QWidget):
    """页面根容器：在空白处撒手绘小花和星星。

    装饰画在最后、且逐次跳过被占用的区域，所以不会压到任何控件上。
    只画一次（缓存成 pixmap），避免每次重绘都重新算一遍随机点。
    """

    def __init__(self) -> None:
        super().__init__()
        self._decor_cache = None
        self._decor_size = None

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not DOODLE_MODE:
            return

        from PyQt6.QtGui import QPainter, QPixmap

        from .doodle_decor_layer import paint_free_decor

        size = (self.width(), self.height())
        if self._decor_cache is None or self._decor_size != size:
            pixmap = QPixmap(self.size())
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_free_decor(painter, self, seed=17)
            painter.end()
            self._decor_cache = pixmap
            self._decor_size = size

        painter = QPainter(self)
        from .doodle_paint import draw_notebook_background
        from .theme import IS_DARK_SKIN

        draw_notebook_background(painter, QRectF(self.rect()), is_dark=IS_DARK_SKIN)
        painter.drawPixmap(0, 0, self._decor_cache)
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._decor_cache = None
        super().resizeEvent(event)


class MainWindow(QMainWindow):
    settings_requested = pyqtSignal()
    pause_toggled = pyqtSignal(bool)

    def __init__(
        self,
        cfg: Config,
        storage: Storage,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self.storage = storage
        self._day = date.today()
        self._last_count = -1
        self._last_capture_at: datetime | None = None
        self._summary_busy = False
        self._force_quit = False
        self._summary_worker: SummaryWorker | None = None
        self._demo_window: QWidget | None = None
        self._all_segments: list[dict] = []
        self._timeline_cat_filter: str = "全部"
        self._timeline_search_kw: str = ""
        self._filter_pills: dict[str, QPushButton] = {}

        self.setWindowTitle("MaoLog · 电脑使用看板")
        self.resize(1380, 920)
        self.setMinimumSize(1080, 720)

        root = _DecorRoot()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        self.root_widget = root
        self._build(root)
        if DOODLE_MODE:
            from .desktop_pet import DesktopPetWindow
            self.desktop_pet: DesktopPetWindow | None = DesktopPetWindow(self.cfg, self.storage)
            self.desktop_pet.open_dashboard_requested.connect(self._summon_dashboard)
            self.desktop_pet.open_achievement_requested.connect(self._open_achievement_card)
            self.desktop_pet.open_review_requested.connect(self._open_study_review)
            self.desktop_pet.open_ai_profile_requested.connect(self._open_ai_profile)
            self.desktop_pet.toggle_pause_requested.connect(self._toggle_pause)
        else:
            self.desktop_pet = None

        # 后台分析突发时合并重刷（250ms 防抖），避免连续回调卡住界面线程
        self._reloading = False
        self._reload_pending = False
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(250)
        self._reload_timer.timeout.connect(self._do_scheduled_reload)

        # 每 5 秒检查一次是否有新记录，有变化才重绘，避免动画一直重启
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._tick_refresh)
        self._refresh_timer.start(5000)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)

        self.reload()

    # ---------- 界面搭建 ----------

    def _build(self, root: QWidget) -> None:

        outer = QVBoxLayout(root)
        outer.setContentsMargins(26, 20, 26, 12)
        outer.setSpacing(16)

        outer.addLayout(self._build_header())
        outer.addLayout(self._build_stat_row())
        outer.addLayout(self._build_body(), stretch=1)
        outer.addWidget(self._build_summary_card())
        outer.addLayout(self._build_status_bar())

    def _build_header(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)
        bar.addWidget(make_wordmark())
        bar.addStretch(1)

        # 日期是一个整体，不再和产品名、功能按钮混在同一视觉层级。
        if DOODLE_MODE:
            navigator = RoughFrame(radius=10.0, seed=5, fill_override=BG_INSET)
        else:
            navigator = QFrame()
        navigator.setObjectName("DateNavigator")
        nav = QHBoxLayout(navigator)
        nav.setContentsMargins(4, 3, 4, 3)
        nav.setSpacing(2)

        self.btn_prev = _tool_button(variant="icon", radius=8.0)
        self.btn_prev.setObjectName("IconButton")
        self.btn_prev.setIcon(ui_icon("chevron-left"))
        self.btn_prev.setIconSize(QSize(18, 18))
        self.btn_prev.setFixedSize(36, 36)
        self.btn_prev.setToolTip("前一天")
        self.btn_prev.clicked.connect(lambda: self._shift_day(-1))

        self.date_btn = QPushButton("")
        self.date_btn.setObjectName("DateButton")
        self.date_btn.setIcon(ui_icon("calendar"))
        self.date_btn.setIconSize(QSize(15, 15))
        self.date_btn.setMinimumWidth(152)
        self.date_btn.setFixedHeight(36)
        self.date_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.date_btn.setToolTip("点击打开日历快捷选天 📅")
        self.date_btn.clicked.connect(self._open_calendar_popup)
        self.date_label = self.date_btn

        self.btn_next = _tool_button(variant="icon", radius=8.0)
        self.btn_next.setObjectName("IconButton")
        self.btn_next.setIcon(ui_icon("chevron-right"))
        self.btn_next.setIconSize(QSize(18, 18))
        self.btn_next.setFixedSize(36, 36)
        self.btn_next.setToolTip("后一天")
        self.btn_next.clicked.connect(lambda: self._shift_day(1))

        self.btn_today = _tool_button("今天", radius=8.0)
        self.btn_today.setObjectName("Ghost")
        self.btn_today.setFixedHeight(36)
        self.btn_today.clicked.connect(self._goto_today)
        for button in (self.btn_prev, self.date_label, self.btn_next, self.btn_today):
            nav.addWidget(button)
        bar.addWidget(navigator)
        bar.addSpacing(4)

        self.btn_pause = _tool_button("暂停记录")
        self.btn_pause.setObjectName("Ghost")
        self.btn_pause.setMinimumWidth(100)
        self.btn_pause.clicked.connect(self._toggle_pause)

        self.btn_ai = _tool_button("AI 协作")
        self.btn_ai.setObjectName("Ghost")
        self.btn_ai.setIcon(ui_icon("ai"))
        self.btn_ai.setToolTip("回看一段记录里人与 AI 的先后关系，可改判")
        self.btn_ai.clicked.connect(self._open_ai_profile)

        self.btn_float_pet = _tool_button("桌面精灵 🍄")
        self.btn_float_pet.setObjectName("Ghost")
        self.btn_float_pet.setToolTip("开启/隐藏常驻桌面的蘑菇小精灵（鼠标移入小精灵可展开看板与便签入口）")
        self.btn_float_pet.clicked.connect(self.toggle_desktop_pet)

        self.btn_badge = _tool_button("成就便签 🍄")
        self.btn_badge.setObjectName("Ghost")
        self.btn_badge.setToolTip("生成今日手绘拍立得学业成就便签，支持一键复制与保存高清长图")
        self.btn_badge.clicked.connect(self._open_achievement_card)

        self.btn_review = _tool_button("学习复盘", variant="primary")
        self.btn_review.setObjectName("Primary")
        self.btn_review.setIcon(ui_icon("book", ON_ACCENT))
        self.btn_review.setMinimumWidth(112)
        self.btn_review.setToolTip("看看这段时间的节奏：哪块投入最完整、在哪被打断、下次怎么调")
        self.btn_review.clicked.connect(self._open_study_review)

        self.btn_settings = _tool_button(variant="icon", radius=8.0)
        self.btn_settings.setObjectName("IconButton")
        self.btn_settings.setIcon(ui_icon("settings"))
        self.btn_settings.setIconSize(QSize(20, 20))
        self.btn_settings.setFixedSize(40, 40)
        self.btn_settings.setToolTip("设置")
        self.btn_settings.clicked.connect(self.settings_requested.emit)

        for button in (self.btn_float_pet, self.btn_ai, self.btn_pause, self.btn_badge, self.btn_review):
            button.setIconSize(QSize(18, 18))
            bar.addWidget(button)
        bar.addWidget(self.btn_settings)
        return bar

    def _build_stat_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self.card_time = StatCard("⏱️ 有效记录时长", ACCENT)
        self.card_focus = StatCard("🎯 平均专注度", CATEGORY_COLORS["工作"])
        self.card_main = StatCard("💻 主要活动", CATEGORY_COLORS["娱乐"])
        self.card_apps = StatCard("📦 涉及应用", CATEGORY_COLORS["沟通"])
        for card in (self.card_time, self.card_focus, self.card_main, self.card_apps):
            row.addWidget(card)
        return row

    def _build_body(self) -> QHBoxLayout:
        body = QHBoxLayout()
        body.setSpacing(12)

        # 左：时间轴
        timeline_card = self._card("今日时间轴", "clock")
        self.timeline_hint = QLabel("")
        self.timeline_hint.setObjectName("Muted")
        timeline_card.head_layout.addWidget(self.timeline_hint)

        # 分类胶囊筛选 + 关键词秒搜工具栏
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 2)
        filter_row.setSpacing(5)

        for cat_name in ("全部", "学习", "工作", "娱乐", "沟通", "系统", "其他"):
            pill = QPushButton(cat_name)
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.setFixedHeight(26)
            pill.clicked.connect(lambda _checked=False, c=cat_name: self._set_timeline_cat_filter(c))
            self._filter_pills[cat_name] = pill
            filter_row.addWidget(pill)
        self._refresh_filter_pill_styles()

        filter_row.addStretch(1)

        self.timeline_search = QLineEdit()
        self.timeline_search.setPlaceholderText("🔍 搜索活动 / 应用 / 窗口关键词…")
        self.timeline_search.setClearButtonEnabled(True)
        self.timeline_search.setFixedHeight(27)
        self.timeline_search.setMinimumWidth(155)
        self.timeline_search.setMaximumWidth(240)
        self.timeline_search.setStyleSheet(
            f"""
            QLineEdit {{
                background: {BG_ELEVATED};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_SOFT};
                border-radius: 13px;
                padding: 2px 11px;
                font-size: 11.5px;
            }}
            QLineEdit:focus {{
                border: 1px solid {ACCENT};
            }}
            """
        )
        self.timeline_search.textChanged.connect(self._on_timeline_search_changed)
        filter_row.addWidget(self.timeline_search)
        timeline_card.layout().addLayout(filter_row)

        self.timeline = TimelineWidget()
        self.timeline.segment_clicked.connect(self._show_segment)
        self.timeline.segment_category_changed.connect(self._on_segment_category_changed)
        self.timeline.segment_edit_requested.connect(self._on_segment_edit_requested)
        self.timeline.segment_delete_requested.connect(self._on_segment_delete_requested)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.timeline)
        _make_transparent(scroll)
        self._timeline_scroll = scroll

        # 底部渐隐，暗示还有更多内容可以滚
        self._timeline_card = timeline_card
        self._fade = FadeOverlay(timeline_card, BG_CARD)
        scroll.installEventFilter(self)

        self.empty_timeline = EmptyState(
            "今天还没有记录",
            "程序会在后台每隔一段时间截一次屏，自动通过 AI 或本地智能规则识别你在做什么。",
            art="empty-board.png",
            note="支持免 Key 本地智能识别",
        )
        self.timeline_stack = QStackedWidget()
        self.timeline_stack.addWidget(scroll)
        self.timeline_stack.addWidget(self.empty_timeline)
        timeline_card.layout().addWidget(self.timeline_stack, stretch=1)

        # 右：分类 + 应用。
        # 窗口压到最小高度时，两张卡按最小高度会被裁切；让这一列独立滚动，
        # 而不是把图表硬压扁或藏掉应用排行。
        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(12)

        donut_card = self._card("分类占比", "chart")
        self.donut = DonutChart()
        donut_card.layout().addWidget(self.donut, stretch=1)
        right.addWidget(donut_card, stretch=3)

        app_card = self._card("应用排行", "apps")
        self.app_rank = AppRankWidget()
        app_card.layout().addWidget(self.app_rank, stretch=1)
        right.addWidget(app_card, stretch=2)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setWidget(right_widget)
        _make_transparent(right_scroll)
        self._right_scroll = right_scroll

        # 低高度时右列会出现内部滚动。给一个明确入口，避免“应用排行”静默消失。
        self.right_scroll_hint = QPushButton("应用排行 ↓", right_scroll.viewport())
        self.right_scroll_hint.setObjectName("ScrollHint")
        self.right_scroll_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        self.right_scroll_hint.setFixedHeight(26)
        self.right_scroll_hint.hide()
        self.right_scroll_hint.clicked.connect(self._scroll_to_app_rank)
        bar = right_scroll.verticalScrollBar()
        bar.rangeChanged.connect(self._sync_right_scroll_hint)
        bar.valueChanged.connect(self._sync_right_scroll_hint)
        right_scroll.installEventFilter(self)

        body.addWidget(timeline_card, stretch=3)
        body.addWidget(right_scroll, stretch=2)

        # 图表都加进布局之后，才给每张卡预留底部空带并挂上宠物。
        # 早挂会把占位条插在图表上方，图表反而被挤到下面。

        return body

    def _build_summary_card(self) -> QFrame:
        card = self._card("🍄 小精灵今日复盘手记", "spark", insight=True)
        head = card.head_layout

        self.summary_badge = QLabel("")
        self.summary_badge.setObjectName("Muted")
        head.addWidget(self.summary_badge)

        self.btn_estimate = _tool_button("估时校准", radius=8.0)
        self.btn_estimate.setObjectName("Ghost")
        self.btn_estimate.setToolTip("对照今天的计划投入和实际产出")
        self.btn_estimate.clicked.connect(self._open_time_estimate)
        head.addWidget(self.btn_estimate)

        self.btn_summary = _tool_button("生成总结", radius=8.0)
        self.btn_summary.setObjectName("Ghost")
        self.btn_summary.clicked.connect(self._make_summary)
        head.addWidget(self.btn_summary)

        self.summary_text = QLabel("还没有生成总结。点右上角「生成总结」，让 AI 帮你复盘今天。")
        self.summary_text.setWordWrap(True)
        self.summary_text.setTextFormat(Qt.TextFormat.RichText)
        self.summary_text.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12.5px;"
        )
        self.summary_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.summary_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        # 手绘模式：没总结时先摆一张线稿，避免一大块白
        self.summary_art = None
        if DOODLE_MODE:
            from .components import doodle_art

            art = doodle_art("empty-summary.png", 150)
            if art is not None:
                self.summary_art = QLabel()
                self.summary_art.setPixmap(art)
                self.summary_art.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                card.layout().addWidget(self.summary_art)

        card.layout().addWidget(self.summary_text, stretch=1)
        card.setMinimumHeight(176)

        # 便签改成布局内的手写风标签：单独一行、贴在正文下方。
        # 这样它参与布局，永远不会压到别的内容。
        if DOODLE_MODE:
            from .doodle_note import NoteLine

            self.summary_note = NoteLine("今天还没有记录")
            card.layout().addWidget(self.summary_note)
        else:
            self.summary_note = None
        card.setMaximumHeight(360)
        self.summary_card = card
        return card

    def _build_status_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)

        self.status_dot = QFrame()
        self.status_dot.setFixedSize(7, 7)
        self._set_status_dot(SUCCESS)
        self.status_text = QLabel("正在记录")
        self.status_text.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")

        self.status_detail = QLabel("")
        self.status_detail.setObjectName("Muted")

        self.status_next = QLabel("")
        self.status_next.setObjectName("Muted")

        bar.addWidget(self.status_dot)
        bar.addWidget(self.status_text)
        bar.addWidget(self.status_detail)

        # 状态栏的弹性空白里塞一朵小花。这是布局明确留出的空间，
        # 不会像往卡片里塞装饰那样压到正文。
        if DOODLE_MODE:
            from .doodle_decor import DecorStrip

            bar.addStretch(1)
            bar.addWidget(DecorStrip(width=120, height=24, seed=11))
            bar.addStretch(1)
        else:
            bar.addStretch(1)
        bar.addWidget(self.status_next)
        return bar

    def _refresh_summary_note(self, overview: dict, has_data: bool) -> None:
        """便签上写今天的"一句话摘要"：时长 + 记录条数。

        只看两个数，不用 AI，这样即使没配 API Key 也有内容可写。
        """
        note = getattr(self, "summary_note", None)
        if note is None:
            return

        if not has_data:
            note.set_text("今天还没有记录")
            return

        tracked = format_duration(overview["tracked_seconds"])
        records = overview["records"]
        top = overview.get("top_activity") or ""
        if top:
            note.set_text(f"专注 {tracked} · {records} 条记录 · 主要在{top}")
        else:
            note.set_text(f"专注 {tracked} · {records} 条记录")

    def _card(self, title: str, icon: str = "", insight: bool = False) -> QFrame:
        """统一的卡片外壳：标题行 + 内容区。

        标题行的布局挂在 card.head_layout 上，方便调用方往里加按钮或提示。
        小图标只为标题提供语义，不参与装饰；只有复盘卡使用强调边框。
        """
        if DOODLE_MODE:
            card = RoughFrame(seed=abs(hash(title)) % 97, radius=15.0, decor=False)
        else:
            card = QFrame()
        card.setObjectName("InsightCard" if insight else "Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(8)
        if icon:
            head.addWidget(make_icon_label(icon, 18, ACCENT, "transparent"))
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        head.addWidget(label)

        # 标题和右侧按钮之间放一个更大的装饰槽。
        # 宽度固定、不伸缩，所以不会挤坏布局；
        # 放在 stretch 之前，按钮仍能被推到最右。
        if DOODLE_MODE:
            from .doodle_pet import PetInline

            # 标题行只留一只静态小精灵装饰，不响应点击弹窗
            head.addSpacing(6)
            head.addWidget(PetInline(height=32, seed=abs(hash(title)) % 53))
        head.addStretch(1)
        layout.addLayout(head)
        card.head_layout = head  # type: ignore[attr-defined]

        # 手绘模式下在角落坐一只小动物。
        # 总结卡正文是整块富文本、铺满整张卡，塞宠物会压字，所以跳过。
        card._is_insight = insight  # type: ignore[attr-defined]
        return card

    # ---------- 时间轴筛选与右键校准 ----------

    def _refresh_filter_pill_styles(self) -> None:
        for cat_name, pill in self._filter_pills.items():
            active = cat_name == self._timeline_cat_filter
            if active:
                bg = category_color(cat_name) if cat_name != "全部" else ACCENT
                pill.setStyleSheet(
                    f"""
                    QPushButton {{
                        background: {bg};
                        color: {ON_ACCENT};
                        border: none;
                        border-radius: 13px;
                        padding: 2px 9px;
                        font-size: 11.5px;
                        font-weight: 600;
                    }}
                    """
                )
            else:
                pill.setStyleSheet(
                    f"""
                    QPushButton {{
                        background: {BG_ELEVATED};
                        color: {TEXT_SECONDARY};
                        border: 1px solid {BORDER_SOFT};
                        border-radius: 13px;
                        padding: 2px 9px;
                        font-size: 11.5px;
                    }}
                    QPushButton:hover {{
                        color: {TEXT_PRIMARY};
                        border-color: {ACCENT};
                    }}
                    """
                )

    def _set_timeline_cat_filter(self, cat: str) -> None:
        if self._timeline_cat_filter == cat:
            return
        self._timeline_cat_filter = cat
        self._refresh_filter_pill_styles()
        self._apply_timeline_filter()

    def _on_timeline_search_changed(self, text: str) -> None:
        self._timeline_search_kw = (text or "").strip().lower()
        self._apply_timeline_filter()

    def _apply_timeline_filter(self, counts: dict[str, int] | None = None) -> None:
        if counts is None:
            counts = self.storage.counts(self._day_str())

        segments = self._all_segments
        cat_f = self._timeline_cat_filter
        kw = self._timeline_search_kw

        filtered: list[dict] = []
        for seg in segments:
            if cat_f != "全部" and (seg.get("category") or "其他") != cat_f:
                continue
            if kw:
                app_raw = seg.get("app_name") or ""
                win_title = seg.get("window_title") or ""
                app_friendly = resolve_app_display_name(app_raw, win_title)
                haystack = " ".join(
                    [
                        seg.get("activity") or "",
                        seg.get("detail") or "",
                        seg.get("category") or "",
                        app_raw,
                        app_friendly,
                        win_title,
                    ]
                ).lower()
                if kw not in haystack:
                    continue
            filtered.append(seg)

        is_filtering = (cat_f != "全部") or bool(kw)
        empty_msg = "当前筛选条件下没有匹配的时间段记录" if is_filtering else "还没有记录"
        self.timeline.set_segments(filtered, empty_text=empty_msg)
        # 只要当天有原始记录，就保持展示 timeline 视图（便于看到空筛选提示并随时切回全部）
        self.timeline_stack.setCurrentIndex(0 if segments else 1)
        self._sync_fade()

        pending = counts.get("pending", 0) + counts.get("analyzing", 0)
        if is_filtering:
            filt_secs = sum(int(s.get("seconds") or 0) for s in filtered)
            hint = f"筛选 {len(filtered)}/{len(segments)} 段 · 共 {format_duration(filt_secs)}"
        else:
            hint = f"{len(segments)} 段"
        if pending:
            hint += f" · {pending} 条待分析"
        if counts.get("paused"):
            hint += f" · {counts['paused']} 条待回补"
        self.timeline_hint.setText(hint)

    def _on_segment_category_changed(self, segment: dict, new_cat: str) -> None:
        ids = segment.get("ids") or []
        if not ids:
            return
        act = segment.get("activity") or new_cat
        det = segment.get("detail") or ""
        self.storage.update_snapshots_manual(ids, category=new_cat, activity=act, detail=det)
        self.reload()
        self.status_detail.setText(f" · 已将该时段校准为「{new_cat} ✎」，图表已实时更新")
        if self.desktop_pet is not None and self.desktop_pet.isVisible():
            self.desktop_pet.show_bubble(
                f"已帮你把「{act}」改判为【{new_cat}】啦，占比统计已同步刷新 🍄",
                tone="praise",
                duration_ms=4500,
            )

    def _on_segment_edit_requested(self, segment: dict) -> None:
        dlg = SegmentEditDialog(self, segment)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_data:
            return
        res = dlg.result_data
        ids = segment.get("ids") or []
        cat = res["category"]
        act = res["activity"]
        det = res["detail"]

        if ids:
            self.storage.update_snapshots_manual(ids, category=cat, activity=act, detail=det)

        retro_count = 0
        if res.get("remember_rule"):
            r_app = res.get("rule_app") or ""
            r_kw = res.get("rule_keyword") or ""
            if r_app or r_kw:
                save_user_rule(
                    app_name=r_app,
                    title_keyword=r_kw,
                    category=cat,
                    activity=act,
                    detail_prefix=det,
                )
                retro_count = self.storage.apply_rule_to_day(
                    self._day_str(),
                    app_name=r_app,
                    title_keyword=r_kw,
                    category=cat,
                    activity=act,
                    detail_prefix=det,
                )

        self.reload()
        if retro_count > len(ids):
            msg = f"已校准并记住规则，今日共 {retro_count} 条同类记录已同步更新 🍄"
        elif res.get("remember_rule") and (res.get("rule_app") or res.get("rule_keyword")):
            msg = f"已校准为「{cat} · {act}」并写入本地记忆规则 🍄"
        else:
            msg = f"已校准该时间段为「{cat} · {act}」"
        self.status_detail.setText(" · " + msg)
        if self.desktop_pet is not None and self.desktop_pet.isVisible():
            self.desktop_pet.show_bubble(msg, tone="praise", duration_ms=5000)

    def _on_segment_delete_requested(self, segment: dict) -> None:
        ids = segment.get("ids") or []
        if not ids:
            return
        if not ask_confirm(
            self,
            "删除时间段记录",
            f"确定要删除「{segment.get('start_text')} - {segment.get('end_text')} · "
            f"{segment.get('activity') or '未分类'}」（共 {len(ids)} 条快照）吗？",
            confirm_text="删除记录",
            cancel_text="取消",
            danger=True,
        ):
            return
        self.storage.delete_snapshots(ids)
        self.reload()
        self.status_detail.setText(" · 已删除所选时间段记录")

    # ---------- 数据刷新 ----------

    def _day_str(self) -> str:
        return self._day.strftime("%Y-%m-%d")

    def _tick_refresh(self) -> None:
        if self._force_quit or self._reloading or self._day != date.today():
            return
        counts = self.storage.counts(self._day_str())
        total = counts.get("total", 0)
        if total != self._last_count:
            self.reload()
            self._check_pet_care(force=False)

    def _do_scheduled_reload(self) -> None:
        if self._force_quit or self._day != date.today():
            return
        self.reload()

    def reload(self) -> None:
        if self._reloading:
            self._reload_pending = True
            return
        self._reload_timer.stop()
        self._reloading = True
        try:
            self._reload_impl()
        finally:
            self._reloading = False
            if self._reload_pending and not self._force_quit:
                self._reload_pending = False
                self._reload_timer.start()

    def _reload_impl(self) -> None:
        day = self._day_str()
        interval = self.cfg.interval_seconds

        counts = self.storage.counts(day)
        self._last_count = counts.get("total", 0)

        segments = self.storage.segments(day, interval=interval)
        self._all_segments = segments
        overview = self.storage.overview(day, interval=interval)
        cats = self.storage.category_stats(day, interval=interval)
        apps = self.storage.app_stats(day, interval=interval, limit=8)

        # 日期。日期本身已经能表达顺序，不再同时显示“今天 + 回到今天”
        today = date.today()
        earliest = self._get_earliest_day()
        weekday = "一二三四五六日"[self._day.weekday()]
        delta = (today - self._day).days
        self.date_label.setText(f"{day} 周{weekday}")
        self.date_label.setToolTip(
            "今天 · 点击打开日历快捷选天 📅"
            if delta == 0
            else f"{delta} 天前 · 点击打开日历快捷选天 📅"
        )
        self.btn_prev.setEnabled(self._day > earliest)
        self.btn_prev.setToolTip("已经是记录的第一天啦" if self._day <= earliest else "前一天")
        self.btn_next.setEnabled(self._day < today)
        self.btn_today.setEnabled(self._day != today)

        # 概览
        has_data = overview["records"] > 0
        self.card_time.set_value(
            format_duration(overview["tracked_seconds"]) if has_data else "—",
            f"{overview['first_ts']} - {overview['last_ts']}" if has_data else "等待数据",
        )
        self.card_focus.set_value(
            f"{overview['avg_focus']:.1f} / 5" if has_data else "—",
            f"有效产出 {format_duration(overview['productive_seconds'])}"
            if has_data
            else "AI 分析后计算",
        )
        self.card_main.set_value(
            (overview["top_activity"] or "—") if has_data else "—",
            f"共 {len(segments)} 个时间段" if segments else "等待数据",
        )
        self.card_apps.set_value(
            f"{overview['app_count']} 个" if has_data else "—",
            "按前台窗口统计" if has_data else "等待数据",
        )

        self._refresh_summary_note(overview, has_data)

        # 时间轴（应用胶囊筛选与搜索关键词）
        self._apply_timeline_filter(counts)

        # 图表
        self.donut.set_data(cats, total_seconds=overview["tracked_seconds"])
        self.app_rank.set_data(apps)

        self._load_summary(day)
        self._update_status(counts)
        if self.desktop_pet is not None:
            self.desktop_pet.refresh_stats()

    def _load_summary(self, day: str) -> None:
        record = self.storage.get_daily_summary(day)
        if record:
            self._render_summary(
                record["summary"], record["highlights"], record["suggestions"], record.get("model", "")
            )
            return
        # 没有 AI 总结时，先用本地统计凑一版，看板不至于空着
        if self.storage.overview(day, self.cfg.interval_seconds)["records"]:
            local = fallback_summary(day, self.storage, self.cfg.interval_seconds)
            self._render_summary(
                local["summary"], local["highlights"], local["suggestions"], "local"
            )
            self.summary_badge.setText("本地统计")
        else:
            if getattr(self, "summary_art", None) is not None:
                self.summary_art.show()
            self.summary_text.setText(
                "还没有生成总结。点右上角「生成总结」，让 AI 帮你复盘今天。"
            )
            self.summary_badge.setText("")

    def _render_summary(
        self, summary: str, highlights: list[str], suggestions: list[str], model: str
    ) -> None:
        parts: list[str] = [
            f'<div style="color:{TEXT_PRIMARY}; font-size:13px; line-height:175%; letter-spacing:0.3px;">{_escape(summary)}</div>'
        ]
        for h in highlights:
            parts.append(
                f'<div style="margin-top:7px; line-height:150%;"><span style="color:{SUCCESS}; font-weight:bold; background-color:rgba(126,166,110,0.18); padding:1px 7px; border-radius:4px; font-size:11px;">✔ 亮点</span> <span style="color:{TEXT_PRIMARY}; font-size:12.5px;">{_escape(h)}</span></div>'
            )
        for s in suggestions:
            parts.append(
                f'<div style="margin-top:7px; line-height:150%;"><span style="color:#D44A3A; font-weight:bold; background-color:rgba(212,74,58,0.15); padding:1px 7px; border-radius:4px; font-size:11px;">★ 建议</span> <span style="color:{TEXT_PRIMARY}; font-size:12.5px;">{_escape(s)}</span></div>'
            )
        if getattr(self, "summary_art", None) is not None:
            self.summary_art.hide()
        self.summary_text.setText("".join(parts))
        self.summary_badge.setText("🍄 AI 伴读复盘" if model and model != "local" else "🍄 今日速记")
        QTimer.singleShot(0, self._fit_summary_height)

    def _fit_summary_height(self) -> None:
        """按实际渲染结果算卡片高度。

        QLabel.heightForWidth() 对富文本不准（QSS 改过字体后偏差能到 40%），
        所以直接用 QTextDocument 按真实宽度排版一次，取它的高度。
        """
        width = self.summary_text.width()
        if width <= 0:
            return

        doc = QTextDocument()
        doc.setDefaultFont(self.summary_text.font())
        doc.setDocumentMargin(0)
        doc.setHtml(self.summary_text.text())
        doc.setTextWidth(width)
        need = doc.size().height()
        doc.deleteLater()

        # 卡片高度 = 标题行 + 上下内边距 + 行间距 + 正文；
        # 之前只加固定值，三条建议时会差十几像素，最后一行被卡片裁掉。
        card_layout = self.summary_card.layout()
        margins = card_layout.contentsMargins()
        header_h = self.summary_card.head_layout.sizeHint().height()
        note_h = (
            self.summary_note.height() + card_layout.spacing()
            if getattr(self, "summary_note", None) is not None
            else 0
        )
        chrome = header_h + margins.top() + margins.bottom() + card_layout.spacing() + note_h
        target = max(188, min(380, int(need) + chrome + 8))
        self.summary_card.setFixedHeight(target)

    def _set_status_dot(self, color: str) -> None:
        self.status_dot.setStyleSheet(f"background: {color}; border: none; border-radius: 3px;")

    def _update_status(self, counts: dict[str, int]) -> None:
        paused = bool(self.cfg.get("privacy.paused"))
        ready, msg = _ai_ready(self.cfg)
        local_fallback = bool(self.cfg.get("ai.local_fallback", True))

        if paused:
            self._set_status_dot(WARNING)
            self.status_text.setText("已暂停")
        elif not ready:
            if local_fallback:
                self._set_status_dot(SUCCESS)
                self.status_text.setText("正在记录（本地智能）")
            else:
                self._set_status_dot(DANGER)
                self.status_text.setText("未配置 AI")
        else:
            self._set_status_dot(SUCCESS)
            self.status_text.setText("正在记录")

        pieces = [f"今日采集 {counts.get('total', 0)} 条"]
        if counts.get("pending"):
            pieces.append(f"待分析 {counts['pending']}")
        if counts.get("paused"):
            pieces.append(f"待回补 {counts['paused']}")
        if counts.get("failed"):
            pieces.append(f"失败 {counts['failed']}")
        if not ready:
            pieces.append("免 Key 本地窗口语义引擎已启用" if local_fallback else msg)
        self.status_detail.setText(" · " + " · ".join(pieces))

        self.btn_pause.setText("继续记录" if paused else "暂停记录")

        interval = self.cfg.interval_seconds
        if self._last_capture_at:
            elapsed = (datetime.now() - self._last_capture_at).total_seconds()
            remain = max(0, interval - elapsed)
            self.status_next.setText(f"下次截图 {int(remain)} 秒后 · 间隔 {interval} 秒")
        else:
            self.status_next.setText(f"采集间隔 {interval} 秒")

    # ---------- 交互 ----------

    def _get_earliest_day(self) -> date:
        today = date.today()
        cfg_first = self.cfg.get("app.first_launch_date")
        if not cfg_first:
            cfg_first = today.strftime("%Y-%m-%d")
            self.cfg.set("app.first_launch_date", cfg_first)

        candidates: list[date] = []
        db_min = self.storage.earliest_day()
        if db_min:
            try:
                candidates.append(datetime.strptime(db_min, "%Y-%m-%d").date())
            except ValueError:
                pass
        if cfg_first:
            try:
                candidates.append(datetime.strptime(cfg_first, "%Y-%m-%d").date())
            except ValueError:
                pass
        return min(candidates) if candidates else today

    def _shift_day(self, delta: int) -> None:
        target = self._day + timedelta(days=delta)
        today = date.today()
        earliest = self._get_earliest_day()
        if target > today or target < earliest:
            return
        self._day = target
        self.reload()

    def _open_calendar_popup(self) -> None:
        from PyQt6.QtCore import QPoint
        from .calendar_popup import CalendarPopup

        earliest = self._get_earliest_day()
        all_days = self.storage.all_days_with_data()
        popup = CalendarPopup(
            current_date=self._day,
            earliest_date=earliest,
            days_with_data=all_days,
            parent=self,
        )
        popup.date_selected.connect(self._goto_date)
        global_pos = self.date_label.mapToGlobal(QPoint(0, self.date_label.height() + 4))
        popup.popup_at(global_pos)

    def _goto_date(self, chosen: date) -> None:
        earliest = self._get_earliest_day()
        today = date.today()
        if chosen < earliest:
            chosen = earliest
        elif chosen > today:
            chosen = today
        self._day = chosen
        self.reload()

    def _sync_fade(self) -> None:
        """内容超过可视区时才显示底部渐隐。"""
        if not hasattr(self, "_fade"):
            return
        viewport_h = self._timeline_scroll.viewport().height()
        overflow = self.timeline.height() > viewport_h + 4
        self._fade.setVisible(overflow)
        if not overflow:
            return

        # scroll 挂在中转容器里，坐标要换算到卡片坐标系才能对齐
        from PyQt6.QtCore import QPoint

        card = self._timeline_card
        bottom = self._timeline_scroll.mapTo(card, QPoint(0, self._timeline_scroll.height()))
        self._fade.setGeometry(
            bottom.x(),
            bottom.y() - self._fade.height(),
            self._timeline_scroll.width(),
            self._fade.height(),
        )
        self._fade.raise_()

    def _scroll_to_app_rank(self) -> None:
        bar = self._right_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _sync_right_scroll_hint(self, *_args) -> None:
        if not hasattr(self, "right_scroll_hint"):
            return
        bar = self._right_scroll.verticalScrollBar()
        # 12px 级别的溢出不值得打扰用户；只有整张应用排行明显被折在下面时才提示。
        needs_scroll = bar.maximum() > 60 and bar.value() < bar.maximum() - 4
        if not needs_scroll:
            self.right_scroll_hint.hide()
            return
        self.right_scroll_hint.adjustSize()
        viewport = self._right_scroll.viewport()
        # 放在分类卡标题行右侧，避免覆盖图例或应用时长。
        self.right_scroll_hint.move(
            max(8, viewport.width() - self.right_scroll_hint.width() - 18),
            15,
        )
        self.right_scroll_hint.show()
        self.right_scroll_hint.raise_()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        from PyQt6.QtCore import QEvent

        if obj is getattr(self, "_timeline_scroll", None) and event.type() == QEvent.Type.Resize:
            self._sync_fade()
        if obj is getattr(self, "_right_scroll", None) and event.type() == QEvent.Type.Resize:
            self._sync_right_scroll_hint()
        return super().eventFilter(obj, event)

    def _goto_today(self) -> None:
        self._day = date.today()
        self.reload()

    def _toggle_pause(self) -> None:
        paused = not bool(self.cfg.get("privacy.paused"))
        self.cfg.set("privacy.paused", paused)
        self.pause_toggled.emit(paused)
        self._update_status(self.storage.counts(self._day_str()))
        if self.desktop_pet is not None:
            self.desktop_pet.refresh_stats()

    def _make_summary(self) -> None:
        if self._summary_busy:
            return
        day = self._day_str()
        if not self.storage.overview(day, self.cfg.interval_seconds)["records"]:
            if getattr(self, "summary_art", None) is not None:
                self.summary_art.show()
            self.summary_text.setText("这一天还没有记录，没法总结。")
            return

        ready, msg = _ai_ready(self.cfg)
        if not ready:
            local = fallback_summary(day, self.storage, self.cfg.interval_seconds)
            self._render_summary(
                local["summary"] + f"\n\n（{msg}，当前显示的是本地统计结果）",
                local["highlights"],
                local["suggestions"],
                "local",
            )
            return

        self._summary_busy = True
        self.btn_summary.setEnabled(False)
        self.btn_summary.setText("生成中…")

        # AI 请求要十几秒，必须放后台线程，否则窗口会卡死
        self._summary_worker = SummaryWorker(day, self.cfg, self.storage)
        self._summary_worker.ok.connect(self._on_summary_ok)
        self._summary_worker.failed.connect(self._on_summary_failed)
        self._summary_worker.finished.connect(self._on_summary_finished)
        self._summary_worker.start()

    def _on_summary_ok(self, result: dict) -> None:
        if self._force_quit:
            return
        self._render_summary(
            result.get("summary", ""),
            result.get("highlights", []),
            result.get("suggestions", []),
            result.get("model", ""),
        )

    def _on_summary_failed(self, message: str) -> None:
        if self._force_quit:
            return
        day = self._day_str()
        local = fallback_summary(day, self.storage, self.cfg.interval_seconds)
        self._render_summary(
            local["summary"] + f"\n\n（AI 生成失败：{message}）",
            local["highlights"],
            local["suggestions"],
            "local",
        )
        # 别让用户只看到一段"正常"文字就以为成功了，徽标和悬停都要说清
        self.summary_badge.setText("AI 失败，已用本地统计")
        self.summary_badge.setStyleSheet(f"color: {WARNING}; font-size: 11.5px;")
        self.summary_badge.setToolTip(message)

    def _on_summary_finished(self) -> None:
        self._summary_busy = False
        self.btn_summary.setEnabled(True)
        self.btn_summary.setText("重新生成")
        self._summary_worker = None

    def _show_segment(self, segment: dict) -> None:
        path = segment.get("image_path")
        if not path or not Path(path).exists():
            # 静默无反应最难受，明确告诉用户图是被清理了还是根本没存
            self.status_detail.setText(
                "这条记录的原图已经不在了（可能被保留天数策略清理）"
                if path
                else "这条记录没有保存截图"
            )
            return
        viewer = ImageViewer(
            path,
            f"{segment.get('start_text')} - {segment.get('end_text')} · "
            f"{segment.get('activity')} · {segment.get('detail')}",
            self,
        )
        viewer.exec()

    # ---------- 外部调用 ----------

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self.desktop_pet is not None and self.cfg.get("ui.desktop_pet", True):
            if not self.desktop_pet.isVisible():
                self.desktop_pet.show()

    def _summon_dashboard(self) -> None:
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle_desktop_pet(self) -> None:
        if self.desktop_pet is None:
            return
        vis = not self.desktop_pet.isVisible()
        self.set_desktop_pet_visible(vis)

    def set_desktop_pet_visible(self, visible: bool) -> None:
        if self.desktop_pet is None:
            return
        self.cfg.set("ui.desktop_pet", visible)
        if visible:
            self.desktop_pet.refresh_stats()
            self.desktop_pet.show()
            self.desktop_pet.raise_()
        else:
            self.desktop_pet.hide()

    def prepare_quit(self) -> None:
        """真正退出前置位，绕过「关闭到托盘」的拦截并安全收尾后台线程。"""
        self._force_quit = True
        self._reload_timer.stop()
        self._refresh_timer.stop()
        self._clock_timer.stop()
        worker = self._summary_worker
        if worker is not None and worker.isRunning():
            worker.abort()
            if not worker.wait(1500):
                _ORPHAN_SUMMARY_WORKERS.append(worker)
                worker.finished.connect(
                    lambda w=worker: (
                        _ORPHAN_SUMMARY_WORKERS.remove(w)
                        if w in _ORPHAN_SUMMARY_WORKERS
                        else None
                    )
                )
        if self.desktop_pet is not None:
            self.desktop_pet.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._force_quit and self.cfg.get("ui.close_to_tray", True):
            event.ignore()
            self.hide()
            if self.desktop_pet is not None and self.desktop_pet.isVisible():
                self.desktop_pet.show_bubble("看板已最小化，蘑菇小精灵继续在桌面陪你自习 🍄", tone="greet", duration_ms=5000)
            return
        if self.desktop_pet is not None:
            self.desktop_pet.close()
        event.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def on_captured(self) -> None:
        self._last_capture_at = datetime.now()
        if self.desktop_pet is not None:
            self.desktop_pet.on_analyzing_started()

    def on_analyzed(self) -> None:
        if self._force_quit:
            return
        if self._day == date.today():
            self._reload_timer.start()
            if self.desktop_pet is not None:
                self.desktop_pet.on_analyzed_done(skip_refresh=True)
        elif self.desktop_pet is not None:
            self.desktop_pet.on_analyzed_done(skip_refresh=False)

    def _open_study_review(self) -> None:
        StudyReviewDialog(
            self.cfg,
            self.storage,
            self._day_str(),
            self,
        ).exec()

    def _open_achievement_card(self) -> None:
        from core.achievements import extract_achievements
        from .achievement_card import AchievementDialog

        ach = extract_achievements(
            self.storage,
            self._day_str(),
            interval=self.cfg.interval_seconds,
        )
        AchievementDialog(self, ach).exec()

    def _check_pet_care(self, force: bool = False) -> None:
        if self.desktop_pet is not None and self.desktop_pet.isVisible():
            self.desktop_pet.check_care_trigger(force=force)

    def _open_ai_profile(self) -> None:
        AIProfileDialog(self.cfg, self.storage, self._day_str(), self).exec()

    def _open_time_estimate(self) -> None:
        TimeEstimateDialog(self.cfg, self.storage, self._day_str(), self).exec()

    def _open_demo_dashboard(self) -> None:
        if self._demo_window is not None:
            self._demo_window.show()
            self._demo_window.raise_()
            return
        try:
            from core.config import DATA_DIR
            from core.v2_demo import build_demo_bundle

            from .v2_preview import V2PreviewWindow

            demo_dir = Path(DATA_DIR) / "v2_demo"
            export_dir = demo_dir / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            bundle = build_demo_bundle(demo_dir / "demo.db")
            window = V2PreviewWindow(
                bundle["storage"],
                bundle["report"],
                bundle["judgment"],
                bundle["passport"],
                bundle["estimate"],
                export_dir,
                demo_mode=True,
            )
            window.setWindowTitle("楚师智学 · 演示看板（隔离数据）")
            self._demo_window = window
            window.show()
            window.raise_()
        except Exception as exc:
            show_warning(self, "演示看板打开失败", str(exc))

    def on_status(self, text: str) -> None:
        self.status_detail.setText(text)

    def refresh_status(self) -> None:
        self._update_status(self.storage.counts(self._day_str()))

    def _tick_clock(self) -> None:
        if self._last_capture_at is None:
            self._last_capture_at = datetime.now()
        interval = self.cfg.interval_seconds
        elapsed = (datetime.now() - self._last_capture_at).total_seconds()
        remain = max(0, int(interval - elapsed))
        state = "已暂停" if self.cfg.get("privacy.paused") else f"下次截图 {remain} 秒后"
        self.status_next.setText(f"{state} · 间隔 {interval} 秒")


_ORPHAN_SUMMARY_WORKERS: list[QThread] = []


class SummaryWorker(QThread):
    """后台生成每日总结，避免阻塞界面。"""

    ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, day: str, cfg: Config, storage: Storage) -> None:
        super().__init__()
        self.day = day
        self.cfg = cfg
        self.storage = storage
        self._client = AIClient(cfg)

    def abort(self) -> None:
        self._client.abort()

    def run(self) -> None:
        try:
            result = generate_summary(
                self.day,
                self.cfg,
                self.storage,
                self.cfg.interval_seconds,
                client=self._client,
            )
            self.ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ImageViewer(QDialog):
    """点击时间轴某一段时弹出的高清大图查看器（支持高分屏 DPI 物理像素渲染与 1:1 原图切换）。"""

    def __init__(self, image_path: str, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("当时的屏幕")
        self.setStyleSheet(f"QDialog {{ background: {BG_CARD}; }}")
        self.resize(1240, 820)
        self._orig_pixmap = QPixmap(image_path)
        self._actual_size_mode = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        _make_transparent(self._scroll)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidget(self._label)
        layout.addWidget(self._scroll, stretch=1)

        res_text = (
            f"（分辨率 {self._orig_pixmap.width()} × {self._orig_pixmap.height()}）"
            if not self._orig_pixmap.isNull()
            else ""
        )
        info = QLabel(f"{caption} {res_text}".strip())
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(info)

        row = QHBoxLayout()
        self._btn_zoom = QPushButton("🔍 1:1 原图尺寸")
        self._btn_zoom.setObjectName("Ghost")
        self._btn_zoom.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_zoom.clicked.connect(self._toggle_zoom_mode)
        if self._orig_pixmap.isNull():
            self._btn_zoom.hide()
        row.addWidget(self._btn_zoom)
        row.addStretch(1)

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("Ghost")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        layout.addLayout(row)

        self._render_pixmap()

    def _toggle_zoom_mode(self) -> None:
        self._actual_size_mode = not self._actual_size_mode
        self._btn_zoom.setText("🗖 适应窗口" if self._actual_size_mode else "🔍 1:1 原图尺寸")
        self._render_pixmap()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._actual_size_mode:
            self._render_pixmap()

    def _render_pixmap(self) -> None:
        if self._orig_pixmap.isNull():
            self._label.setText("图片读不出来了")
            return
        dpr = max(1.0, float(self.devicePixelRatioF()))
        if self._actual_size_mode:
            self._scroll.setWidgetResizable(False)
            pm = QPixmap(self._orig_pixmap)
            pm.setDevicePixelRatio(1.0)
            self._label.setPixmap(pm)
            self._label.resize(pm.size())
        else:
            self._scroll.setWidgetResizable(True)
            vw = max(320, self.width() - 36)
            vh = max(240, self.height() - 96)
            target_phys = QSize(int(vw * dpr), int(vh * dpr))
            scaled = self._orig_pixmap.scaled(
                target_phys,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            self._label.setPixmap(scaled)


def _make_transparent(scroll: QScrollArea) -> None:
    """让滚动区域背景透出卡片底色，否则会出现一块白底。"""
    scroll.setStyleSheet(
        "QScrollArea { background: transparent; border: none; }"
        "QScrollArea > QWidget > QWidget { background: transparent; }"
        "QScrollArea > QWidget { background: transparent; }"
    )
    scroll.viewport().setAutoFillBackground(False)


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )


def _ai_ready(cfg: Config) -> tuple[bool, str]:
    from core.ai_client import PROVIDERS

    provider = (cfg.get("ai.provider") or "qwen").lower()
    meta = PROVIDERS.get(provider, PROVIDERS["qwen"])
    if meta["need_key"] and not (cfg.get("ai.api_key") or "").strip():
        return False, f"未填 {meta['label']} 的 API Key"
    return True, ""
