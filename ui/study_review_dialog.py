"""学习复盘：选日期与时段，看这段时间的节奏，再决定要不要导出。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QDate, Qt, QTime
from PyQt6.QtWidgets import (
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .dialogs import show_info, show_warning
from core.attest import (
    build_process_report,
    export_process_html,
    export_process_pdf,
    report_to_html,
)
from core.paths import data_root
from core.config import Config
from core.storage import Storage

from .theme import (
    BG_CARD,
    BORDER_SOFT,
    IS_DARK_SKIN,
    DOODLE_MODE,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)

EXPORT_DIR = data_root() / "data" / "v2_exports"


class StudyReviewDialog(QDialog):
    def __init__(
        self,
        cfg: Config,
        storage: Storage,
        initial_day: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.storage = storage
        self._report: dict | None = None
        self._signature: tuple | None = None

        self.setWindowTitle("学习复盘")
        self.resize(760, 780)
        self.setMinimumSize(680, 620)
        self.setStyleSheet(f"QDialog {{ background: {BG_CARD}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("学习复盘")
        title.setStyleSheet(f"color:{TEXT_PRIMARY}; font-size:18px; font-weight:600;")
        root.addWidget(title)
        intro = QLabel(
            "选一段时间，看看这段时间的节奏：哪一块投入最完整、在哪里被打断、"
            "下次可以怎么调。结论只描述行为，不评价努力程度，也不判断内容是谁写的。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:12px;")
        root.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.fromString(initial_day, "yyyy-MM-dd"))
        self.time_start = QTimeEdit()
        self.time_start.setDisplayFormat("HH:mm")
        self.time_end = QTimeEdit()
        self.time_end.setDisplayFormat("HH:mm")
        self.edit_task = QLineEdit()
        self.edit_task.setPlaceholderText("例如：课程论文、竞赛项目")
        self.edit_task.setText("当天学习记录")
        form.addRow("日期", self.date_edit)
        form.addRow("开始时间", self.time_start)
        form.addRow("结束时间", self.time_end)
        form.addRow("这段时间在做什么", self.edit_task)
        root.addLayout(form)

        self.data_hint = QLabel("")
        self.data_hint.setWordWrap(True)
        self.data_hint.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11.5px;")
        root.addWidget(self.data_hint)

        self.empty_art = None
        if DOODLE_MODE:
            from .components import doodle_art

            art = doodle_art("review-empty.png", 210)
            if art is not None:
                self.empty_art = QLabel()
                self.empty_art.setPixmap(art)
                self.empty_art.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                self.empty_art.hide()
                root.addWidget(self.empty_art)

        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setStyleSheet(
            f"QTextBrowser {{ background:{BG_CARD}; color:{TEXT_PRIMARY};"
            f" border:1px solid {BORDER_SOFT}; padding:8px; }}"
        )
        root.addWidget(self.preview, 1)

        bottom = QHBoxLayout()
        self.export_status = QLabel("")
        self.export_status.setStyleSheet(f"color:{SUCCESS}; font-size:11.5px;")
        bottom.addWidget(self.export_status, 1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("Ghost")
        close_button.clicked.connect(self.reject)
        self.btn_html = QPushButton("导出 HTML")
        self.btn_html.setObjectName("Ghost")
        self.btn_html.clicked.connect(self._export_html)
        self.btn_pdf = QPushButton("导出 PDF")
        self.btn_pdf.setObjectName("Primary")
        self.btn_pdf.clicked.connect(self._export_pdf)
        self.btn_achieve = QPushButton("成就便签 🍄")
        self.btn_achieve.setObjectName("Ghost")
        self.btn_achieve.setToolTip("生成今日拍立得手绘学业成就长图")
        self.btn_achieve.clicked.connect(self._open_achievement_card)
        preview_button = QPushButton("刷新复盘")
        preview_button.setObjectName("Ghost")
        preview_button.clicked.connect(self._refresh_preview)
        bottom.addWidget(preview_button)
        bottom.addWidget(close_button)
        bottom.addWidget(self.btn_achieve)
        bottom.addWidget(self.btn_html)
        bottom.addWidget(self.btn_pdf)
        root.addLayout(bottom)

        self.date_edit.dateChanged.connect(self._load_day_times)
        self.time_start.timeChanged.connect(self._mark_stale)
        self.time_end.timeChanged.connect(self._mark_stale)
        self.edit_task.textChanged.connect(self._mark_stale)

        self._load_day_times()
        self._refresh_preview()

    # ---------- 范围与预览 ----------

    def _is_dark(self) -> bool:
        skin = str(self.cfg.get("ui.skin", "") or "").lower()
        if skin:
            return skin == "dark"
        return IS_DARK_SKIN

    def _day(self) -> str:
        return self.date_edit.date().toString("yyyy-MM-dd")

    def _range(self) -> tuple[str, str]:
        day = self._day()
        start = self.time_start.time().toString("HH:mm")
        end = self.time_end.time().toString("HH:mm")
        return f"{day} {start}:00", f"{day} {end}:00"

    def _load_day_times(self) -> None:
        day = self._day()
        overview = self.storage.overview(day, interval=self.cfg.interval_seconds)
        if overview["records"]:
            start = QTime.fromString(overview["first_ts"], "HH:mm")
            last = QTime.fromString(overview["last_ts"], "HH:mm")
            end = last.addSecs(self.cfg.interval_seconds) if last.isValid() else QTime(18, 0)
            if start.isValid():
                self.time_start.setTime(start)
            if end.isValid() and end > start:
                self.time_end.setTime(end)
        else:
            self.time_start.setTime(QTime(9, 0))
            self.time_end.setTime(QTime(18, 0))
        self._mark_stale()

    def _signature_now(self) -> tuple:
        return (*self._range(), self.edit_task.text().strip(), self.cfg.interval_seconds)

    def _mark_stale(self) -> None:
        if self._signature is not None and self._signature_now() != self._signature:
            self.export_status.setText("范围或任务名已变化，请刷新复盘后再导出")
            self.btn_pdf.setEnabled(False)
            self.btn_html.setEnabled(False)
        self._update_data_hint()

    def _update_data_hint(self) -> None:
        day = self._day()
        counts = self.storage.counts(day)
        total = counts.get("total", 0)
        analyzed = counts.get("done", 0) + counts.get("reused", 0)
        if not total:
            self.data_hint.setText("这一天还没有屏幕记录。仍可预览边界说明，但不能导出。")
            if self.empty_art is not None:
                self.empty_art.show()
        elif not analyzed:
            self.data_hint.setText(f"这一天有 {total} 条记录，但还没有分析结论，暂时无法复盘。")
        else:
            if self.empty_art is not None:
                self.empty_art.hide()
            self.data_hint.setText(f"这一天共 {total} 条记录，其中 {analyzed} 条已有分析结论。")

    def _refresh_preview(self) -> None:
        task = self.edit_task.text().strip()
        if not task:
            show_warning(self, "还差一步", "先写一句这段时间在做什么，复盘才有落点。")
            return
        start, end = self._range()
        if end <= start:
            show_warning(self, "时间范围不对", "结束时间必须晚于开始时间。")
            return
        try:
            report = build_process_report(
                self.storage, task, start, end, self.cfg.interval_seconds
            )
        except ValueError as exc:
            show_warning(self, "无法生成", str(exc))
            return
        self._report = report
        self._signature = self._signature_now()
        self.preview.setHtml(report_to_html(report, compact=True, dark=self._is_dark()))
        has_data = report["metrics"]["source_records"] > 0
        self.btn_pdf.setEnabled(has_data)
        self.btn_html.setEnabled(has_data)
        self.export_status.setText("复盘已刷新，尚未导出" if has_data else "没有可复盘的记录")

    def _ensure_report(self) -> dict | None:
        if self._signature_now() != self._signature:
            self._refresh_preview()
        if self._report is None or self._report["metrics"]["source_records"] == 0:
            return None
        return self._report

    # ---------- 导出 ----------

    def _export_pdf(self) -> None:
        report = self._ensure_report()
        if report is None:
            return
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        default = EXPORT_DIR / f"学习复盘_{self._day()}.pdf"
        chosen, _ = QFileDialog.getSaveFileName(
            self, "导出学习复盘 PDF", str(default), "PDF 文件 (*.pdf)"
        )
        if not chosen:
            return
        target = Path(chosen)
        if target.suffix.casefold() != ".pdf":
            target = target.with_suffix(".pdf")
        try:
            export_process_pdf(report, target, target.parent, overwrite=True)
        except (ValueError, OSError, RuntimeError) as exc:
            show_warning(self, "导出失败", str(exc))
            return
        self.export_status.setText("PDF 已导出")
        show_info(self, "已导出", f"文件位置：\n{target}")

    def _export_html(self) -> None:
        report = self._ensure_report()
        if report is None:
            return
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        default = EXPORT_DIR / f"学习复盘_{self._day()}.html"
        chosen, _ = QFileDialog.getSaveFileName(
            self, "导出学习复盘 HTML", str(default), "HTML 文件 (*.html)"
        )
        if not chosen:
            return
        target = Path(chosen)
        if target.suffix.casefold() != ".html":
            target = target.with_suffix(".html")
        try:
            export_process_html(report, target, target.parent, overwrite=True)
        except (ValueError, OSError) as exc:
            show_warning(self, "导出失败", str(exc))
            return
        self.export_status.setText("HTML 已导出")
        show_info(self, "已导出", f"文件位置：\n{target}")

    def _open_achievement_card(self) -> None:
        from core.achievements import extract_achievements
        from .achievement_card import AchievementDialog

        ach = extract_achievements(
            self.storage,
            self._day(),
            interval=self.cfg.interval_seconds,
        )
        AchievementDialog(self, ach).exec()
