"""AI 协作回看：实时分析一段记录，查看依据、改判并保存到本机。"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QDate, QTime
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .dialogs import show_warning
from core.ai_profile import (
    AI_LIMITATIONS,
    MODE_UNKNOWN,
    OVERRIDABLE_MODES,
    analyze_collaboration,
    override_collaboration,
    save_collaboration,
    weekly_summary,
)
from core.config import Config
from core.storage import Storage
from core.v2_runtime import get_v2_storage, v2_table_exists
from core.v2_storage import V2Storage

from .theme import BG_CARD, BG_INSET, BORDER_SOFT, SUCCESS, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY


class AIProfileDialog(QDialog):
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
        self.judgment: dict | None = None
        self.judgment_id: int | None = None
        self._signature: tuple | None = None
        self._v2: V2Storage | None = None

        self.setWindowTitle("AI 协作回看")
        self.resize(820, 780)
        self.setMinimumSize(720, 680)
        self.setStyleSheet(f"QDialog {{ background: {BG_CARD}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(11)

        title = QLabel("AI 协作回看")
        title.setStyleSheet(f"color:{TEXT_PRIMARY}; font-size:18px; font-weight:600;")
        root.addWidget(title)
        intro = QLabel(
            "这里只描述窗口的先后关系：先想后问、边做边问，还是直接要答案。"
            "看完可以问自己一句：这段任务里，哪一部分是我自己做的。"
            "这是启发式描述，不是能力判断，也不进入成绩。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:12px;")
        root.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(9)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.fromString(initial_day, "yyyy-MM-dd"))
        self.time_start = QTimeEdit()
        self.time_start.setDisplayFormat("HH:mm")
        self.time_end = QTimeEdit()
        self.time_end.setDisplayFormat("HH:mm")
        self.edit_task = QLineEdit()
        self.edit_task.setPlaceholderText("例如：操作系统作业、竞赛项目")
        self.edit_task.setText("AI 协作回看")
        form.addRow("日期", self.date_edit)
        form.addRow("开始时间", self.time_start)
        form.addRow("结束时间", self.time_end)
        form.addRow("任务上下文", self.edit_task)
        root.addLayout(form)

        action_row = QHBoxLayout()
        self.btn_analyze = QPushButton("分析这段记录")
        self.btn_analyze.setObjectName("Primary")
        self.btn_analyze.clicked.connect(self._analyze)
        action_row.addWidget(self.btn_analyze)
        self.analysis_status = QLabel("")
        self.analysis_status.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11.5px;")
        action_row.addWidget(self.analysis_status, 1)
        root.addLayout(action_row)

        self.mode_label = QLabel("还没有分析")
        self.mode_label.setStyleSheet(f"color:{TEXT_MUTED}; font-size:26px; font-weight:700;")
        root.addWidget(self.mode_label)
        self.override_note = QLabel("")
        self.override_note.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11.5px;")
        root.addWidget(self.override_note)

        self.evidence = QTextBrowser()
        self.evidence.setOpenExternalLinks(False)
        self.evidence.setMinimumHeight(190)
        self.evidence.setStyleSheet(
            f"QTextBrowser {{ background:{BG_INSET}; color:{TEXT_SECONDARY};"
            f"border:1px solid {BORDER_SOFT}; border-radius:10px; padding:8px; }}"
        )
        root.addWidget(self.evidence, 1)

        override = QFrame()
        override.setObjectName("Card")
        override_layout = QHBoxLayout(override)
        override_layout.setContentsMargins(16, 10, 16, 10)
        prompt = QLabel("判断有误，改为：")
        prompt.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:12px;")
        override_layout.addWidget(prompt)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(sorted(OVERRIDABLE_MODES))
        self.mode_combo.setCurrentText(MODE_UNKNOWN)
        override_layout.addWidget(self.mode_combo)
        self.btn_save = QPushButton("保存判断")
        self.btn_save.setObjectName("Ghost")
        self.btn_save.clicked.connect(self._save_only)
        self.btn_override = QPushButton("保存我的改判")
        self.btn_override.setObjectName("Ghost")
        self.btn_override.clicked.connect(self._save_override)
        override_layout.addWidget(self.btn_save)
        override_layout.addWidget(self.btn_override)
        self.save_status = QLabel("")
        self.save_status.setStyleSheet(f"color:{SUCCESS}; font-size:11.5px;")
        override_layout.addWidget(self.save_status, 1)
        root.addWidget(override)
        self.btn_save.setEnabled(False)
        self.btn_override.setEnabled(False)

        self.week_label = QLabel("")
        self.week_label.setWordWrap(True)
        self.week_label.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11.5px;")
        root.addWidget(self.week_label)

        bottom = QHBoxLayout()
        hint = QLabel("修改只影响本机记录；已保存的判断不会因为重新分析被覆盖。")
        hint.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        bottom.addWidget(hint, 1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("Ghost")
        close_button.clicked.connect(self.reject)
        bottom.addWidget(close_button)
        root.addLayout(bottom)

        self.date_edit.dateChanged.connect(self._load_day_times)
        self.time_start.timeChanged.connect(self._mark_stale)
        self.time_end.timeChanged.connect(self._mark_stale)
        self.edit_task.textChanged.connect(self._mark_stale)

        self._load_day_times()
        self._load_week()

    # ---------- 范围 ----------

    def _day(self) -> str:
        return self.date_edit.date().toString("yyyy-MM-dd")

    def _range(self) -> tuple[str, str]:
        day = self._day()
        return (
            f"{day} {self.time_start.time().toString('HH:mm')}:00",
            f"{day} {self.time_end.time().toString('HH:mm')}:00",
        )

    def _signature_now(self) -> tuple:
        return (*self._range(), self.edit_task.text().strip(), self.cfg.interval_seconds)

    def _v2_path(self) -> Path:
        configured = str(self.cfg.get("v2.db_path", "") or "").strip()
        return Path(configured) if configured else Path(self.storage.db_path)

    def _v2_store(self) -> V2Storage:
        if self._v2 is None:
            if str(self.cfg.get("v2.db_path", "") or "").strip():
                self._v2 = get_v2_storage(self.cfg)
            else:
                self._v2 = V2Storage(self.storage.db_path)
        return self._v2

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
        self._analyze()

    def _mark_stale(self) -> None:
        if self._signature is not None and self._signature_now() != self._signature:
            self.analysis_status.setText("参数已变化，请重新分析")
            self.btn_save.setEnabled(False)
            self.btn_override.setEnabled(False)

    # ---------- 分析与保存 ----------

    def _analyze(self) -> None:
        task = self.edit_task.text().strip()
        if not task:
            show_warning(self, "还差一步", "任务上下文不能为空。")
            return
        start, end = self._range()
        if end <= start:
            show_warning(self, "时间范围不对", "结束时间必须晚于开始时间。")
            return
        try:
            judgment = analyze_collaboration(
                self.storage, task, start, end, self.cfg.interval_seconds
            )
        except ValueError as exc:
            show_warning(self, "无法分析", str(exc))
            return
        self.judgment = judgment
        self.judgment_id = None
        self._signature = self._signature_now()
        self._render_judgment(judgment)
        evidence = judgment["evidence"]
        has_samples = evidence["sample_count"] > 0
        self.btn_save.setEnabled(has_samples)
        self.btn_override.setEnabled(has_samples)
        self.analysis_status.setText(
            f"已分析 {evidence['sample_count']} 条记录"
            if has_samples
            else "所选范围没有可用的行为记录"
        )

    def _render_judgment(self, judgment: dict) -> None:
        mode = judgment.get("mode") or MODE_UNKNOWN
        self.mode_label.setText(mode)
        self.mode_label.setStyleSheet(f"color:{SUCCESS}; font-size:30px; font-weight:700;")
        if mode in OVERRIDABLE_MODES:
            self.mode_combo.setCurrentText(mode)
        if judgment.get("overridden"):
            self.override_note.setText(
                f"本次结论已由你修改；机器原判：{judgment.get('original_mode') or '未记录'}。"
            )
        else:
            self.override_note.setText("机器初判，可在下方修改；保存后只影响本机记录。")

        evidence = judgment.get("evidence") or {}
        threshold = evidence.get("thresholds", {})
        items = [
            f"所选时段 {evidence.get('sample_count', 0)} 条记录，"
            f"覆盖约 {evidence.get('coverage', 0):.0%}。",
            f"AI 窗口 {evidence.get('ai_sample_count', 0)} 条"
            f"（占比 {evidence.get('ai_sample_ratio', 0):.0%}），"
            f"合计约 {evidence.get('ai_active_seconds', 0) // 60} 分钟。",
            f"AI 与本地窗口在 {threshold.get('switch_window_seconds', 300) // 60} 分钟内"
            f"交替 {evidence.get('alternations_within_5min', 0)} 次。",
            f"首个 AI 之前累计本地产出 {evidence.get('prior_local_seconds', 0) // 60} 分钟"
            f"（门槛 {threshold.get('prior_local_seconds', 600) // 60} 分钟）。",
            "AI 结束后 15 分钟内出现本地产出。"
            if evidence.get("local_within_15min_after_ai")
            else "AI 结束后 15 分钟内未发现本地产出。",
        ]
        segments = evidence.get("segments") or []
        if segments:
            shown = "；".join(
                f"{item['start']}–{item['end']} {item['kind']}" for item in segments[:8]
            )
            items.append(f"窗口序列：{shown}")
        notes = list(evidence.get("notes") or [])
        items.extend(notes)
        body = "<br>".join(f"· {html.escape(str(item))}" for item in items)
        limits = "<br>".join(f"· {html.escape(str(item))}" for item in AI_LIMITATIONS)
        self.evidence.setHtml(
            f"<div style='font-size:12px;line-height:1.8'><b>判断依据</b><br>{body}"
            f"<br><br><b>这套规则测不到什么</b><br>{limits}</div>"
        )

    def _ensure_saved(self) -> int | None:
        if self.judgment is None:
            return None
        if self.judgment_id is not None:
            return self.judgment_id
        try:
            storage = self._v2_store()
            judgment_id, preserved = save_collaboration(storage, self.judgment)
        except (ValueError, OSError) as exc:
            show_warning(self, "保存失败", str(exc))
            return None
        self.judgment_id = judgment_id
        if preserved:
            stored = storage.get_ai_judgment(judgment_id)
            if stored is not None:
                self.judgment = stored
                self._render_judgment(stored)
            self.save_status.setText("这一天已有你的改判，未覆盖")
        else:
            self.save_status.setText("已保存到本机")
        self._load_week()
        return judgment_id

    def _save_only(self) -> None:
        self._ensure_saved()

    def _save_override(self) -> None:
        judgment_id = self._ensure_saved()
        if judgment_id is None:
            return
        mode = self.mode_combo.currentText()
        current = self.judgment.get("mode") if self.judgment else None
        if mode == current:
            self.save_status.setText("与当前判断相同，无需改判")
            return
        try:
            storage = self._v2_store()
            updated = override_collaboration(storage, judgment_id, mode)
        except (ValueError, OSError) as exc:
            show_warning(self, "改判失败", str(exc))
            return
        self.judgment = updated
        self._render_judgment(updated)
        self.save_status.setText("改判已保存，只改本机记录")
        self._load_week()

    # ---------- 本周 ----------

    def _load_week(self) -> None:
        day = self._day()
        path = self._v2_path()
        if not v2_table_exists(path, "ai_use_daily"):
            self.week_label.setText("本周还没有已保存的判断；保存一次后会在这里汇总。")
            return
        try:
            items = self._v2_store().list_ai_judgments(limit=200)
        except Exception:
            items = []
        target = datetime.strptime(day, "%Y-%m-%d").isocalendar()[:2]
        same_week = [
            item
            for item in items
            if item
            and datetime.strptime(item["day"], "%Y-%m-%d").isocalendar()[:2] == target
        ]
        summary = weekly_summary(same_week)
        if not summary["sample_count"]:
            self.week_label.setText("本周还没有已保存的判断；保存一次后会在这里汇总。")
            return
        modes = "，".join(f"{mode} {count} 次" for mode, count in summary["modes"].items())
        self.week_label.setText(
            f"本周已保存 {summary['sample_count']} 个任务时段：{modes}。"
            f"{summary['note']}。"
        )
