"""v2 学习复盘原型窗口。

只用于本地演示与视觉检查，不发起任何网络请求。
"""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.ai_profile import OVERRIDABLE_MODES, override_collaboration
from core.attest import export_process_pdf
from core.outbound import (
    PURPOSE_FRAME,
    PURPOSE_SUMMARY,
    PURPOSE_TEST,
    export_data_passport,
    set_future_outbound,
)
from core.time_estimate import compare_estimate, set_plan, trend
from core.v2_storage import V2Storage

from .components import StatCard
from .theme import (
    ACCENT,
    ACCENT_DARK,
    ACCENT_SOFT,
    BG_ELEVATED,
    BG_INSET,
    BORDER_SOFT,
    CATEGORY_COLORS,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)

TABLE_QSS = f"""
QTableWidget {{
    background: transparent;
    border: 1px solid {BORDER_SOFT};
    border-radius: 10px;
    gridline-color: {BORDER_SOFT};
    color: {TEXT_PRIMARY};
    font-size: 12px;
}}
QTableWidget::item {{ padding: 6px; }}
QHeaderView::section {{
    background: {BG_ELEVATED};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER_SOFT};
    padding: 7px;
    font-size: 12px;
}}
QTableCornerButton::section {{ background: {BG_INSET}; border: none; }}
"""


def _label(text: str, object_name: str = "") -> QLabel:
    label = QLabel(text)
    if object_name:
        label.setObjectName(object_name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _card(title: str, body: QWidget) -> QFrame:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    layout.addWidget(_label(title, "SectionTitle"))
    layout.addWidget(body)
    return frame


def _table(headers: list[str], rows: list[list[Any]]) -> QTableWidget:
    table = QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    for row_index, values in enumerate(rows):
        for column, value in enumerate(values):
            table.setItem(row_index, column, QTableWidgetItem(str(value)))
    table.setMinimumHeight(48 + 34 * max(1, len(rows)))
    return table


class V2PreviewWindow(QWidget):
    def __init__(
        self,
        storage: V2Storage,
        report: dict[str, Any],
        judgment: dict[str, Any],
        passport: dict[str, Any],
        estimate: dict[str, Any],
        output_dir: Path,
        parent: QWidget | None = None,
        demo_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.report = report
        self.judgment = judgment
        self.passport = passport
        self.estimate = estimate
        self.output_dir = Path(output_dir)
        self.demo_mode = demo_mode
        self.setObjectName("Root")
        self.setStyleSheet(TABLE_QSS)
        self.resize(1180, 820)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 18)
        root.setSpacing(14)
        root.addLayout(self._header())
        root.addLayout(self._stats())

        tabs = QTabWidget()
        tabs.addTab(self._process_tab(), "学习复盘")
        tabs.addTab(self._ai_tab(), "AI 协作画像")
        tabs.addTab(self._passport_tab(), "数据护照")
        tabs.addTab(self._estimate_tab(), "估时校准")
        root.addWidget(tabs, 1)

        footer_text = (
            "演示模式：只读写隔离的演示数据库，不读取真实记录，也不发起网络请求。"
            if self.demo_mode
            else "本地预览：只读写 data/v2_preview.db，不读取真实记录，也不发起网络请求。"
        )
        root.addWidget(_label(footer_text, "Muted"))

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(3)
        title_text = "楚师智学 · 演示看板" if self.demo_mode else "楚师智学 · 学习看板"
        left.addWidget(_label(title_text, "Title"))
        subtitle = _label("看看这段时间是怎么学的：节奏、卡点、AI 怎么参与。", "Subtitle")
        subtitle.setWordWrap(False)
        left.addWidget(subtitle)
        row.addLayout(left)
        row.addStretch(1)
        badge = _label(
            "隔离演示数据 · 不读真实记录" if self.demo_mode else "本地运行 · 数据不上传",
            "Muted",
        )
        badge.setWordWrap(False)
        badge.setStyleSheet(
            f"color:{ACCENT}; border:1px solid {ACCENT_SOFT}; border-radius:10px;"
            f"padding:5px 12px; background:{ACCENT_DARK};"
        )
        row.addWidget(badge)
        return row

    def _stats(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        learning = (self.report.get("review") or {}).get("metrics") or {}
        cards = [
            ("有效记录", f"{learning.get('active_minutes', 0)} 分钟", "有记录的时间", ACCENT),
            (
                "最长连续",
                f"{learning.get('focus_minutes', 0)} 分钟",
                "中间没有中断",
                CATEGORY_COLORS["工作"],
            ),
            (
                "动手占比",
                f"{round(float(learning.get('produce_ratio') or 0) * 100)}%",
                "写作与编程",
                CATEGORY_COLORS["沟通"],
            ),
            ("AI 协作", self.judgment["mode"], self.judgment["task_context"], SUCCESS),
        ]
        for title, value, sub, color in cards:
            card = StatCard(title, color)
            card.set_value(value, sub)
            row.addWidget(card)
            if title == "AI 协作":
                self.ai_card = card
        return row

    def _process_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        review = self.report.get("review") or {}
        layout.addWidget(
            _label(str(review.get("headline") or "没有可用的复盘结论"), "SectionTitle")
        )
        layout.addWidget(_label(str(review.get("summary") or ""), "Subtitle"))

        for heading, key, empty_text in (
            ("值得保留", "strengths", "这段记录里还没有足够长的连续投入。"),
            ("值得留意", "frictions", "没有发现明显的卡点。"),
            ("下次可以试", "suggestions", "保持现在的安排即可。"),
        ):
            items = review.get(key) or []
            lines = [(item["title"], item["detail"]) for item in items] or [empty_text]
            layout.addWidget(_card(heading, self._bullet_block(lines)))


        layout.addWidget(_label("过程明细", "SectionTitle"))
        all_rows = [
            [run["stage"], run["start"][5:16], run["end"][5:16]]
            for run in self.report["runs"]
        ]
        rows = all_rows[:6]
        table = _table(["阶段", "开始", "最后记录"], rows)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(table)
        if len(all_rows) > len(rows):
            layout.addWidget(
                _label(
                    f"共 {len(all_rows)} 段，这里显示前 {len(rows)} 段；完整过程见导出的 PDF。",
                    "Muted",
                )
            )

        notes = self.report["quality_notes"] + [
            f"{gap['start'][5:16]} 至 {gap['end'][5:16]}：{gap['note']}"
            for gap in self.report["data_gaps"]
        ]
        if notes:
            layout.addWidget(_card("数据完整性", self._bullet_block(notes)))
        layout.addWidget(_card("边界说明", self._bullet_block(self.report["limitations"])))

        actions = QHBoxLayout()
        export_button = QPushButton("导出复盘 PDF")
        export_button.setObjectName("Primary")
        export_button.clicked.connect(self._export_pdf)
        actions.addWidget(export_button)
        self.export_status = _label("", "Muted")
        actions.addWidget(self.export_status, 1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return self._scroll(content)

    def _ai_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        self.ai_mode = _label(self.judgment["mode"], "Title")
        self.ai_mode.setStyleSheet(f"color:{SUCCESS}; font-size:30px;")
        layout.addWidget(self.ai_mode)
        layout.addWidget(
            _label(
                "这是窗口先后的启发式描述，不是能力判断，也不进入成绩。",
                "Subtitle",
            )
        )
        original_mode = self.judgment.get("original_mode")
        self.ai_override_note = _label("", "Muted")
        if self.judgment.get("overridden"):
            self.ai_override_note.setText(
                f"本次结论已由你修改；机器原判：{original_mode or '未记录'}。"
            )
        layout.addWidget(self.ai_override_note)

        evidence = self.judgment["evidence"]
        threshold = evidence.get("thresholds", {})
        items = [
            f"所选时段 {evidence['sample_count']} 条记录，覆盖约 {evidence.get('coverage', 0):.0%}；"
            f"其中 AI 窗口 {evidence['ai_sample_count']} 条（占比 {evidence['ai_sample_ratio']:.0%}）。",
            f"AI 窗口合计约 {evidence.get('ai_active_seconds', 0) // 60} 分钟，"
            f"首末跨度 {evidence.get('ai_span_seconds', 0) // 60} 分钟。",
            f"AI 与本地窗口在 {threshold.get('switch_window_seconds', 300) // 60} 分钟内"
            f"交替 {evidence['alternations_within_5min']} 次。",
            f"首个 AI 之前累计本地产出 {evidence.get('prior_local_seconds', 0) // 60} 分钟"
            f"（门槛 {threshold.get('prior_local_seconds', 600) // 60} 分钟）。",
            "AI 结束后 15 分钟内出现本地产出。"
            if evidence.get("local_within_15min_after_ai")
            else "AI 结束后 15 分钟内未发现本地产出。",
        ]
        segments = evidence.get("segments") or []
        if segments:
            shown = "；".join(
                f"{segment['start']}–{segment['end']} {segment['kind']}"
                for segment in segments[:6]
            )
            items.append(f"窗口序列：{shown}")
        if evidence.get("dropped_rows"):
            items.append(f"有 {evidence['dropped_rows']} 条记录时间格式异常，已跳过。")
        items.extend(evidence.get("notes") or [])
        layout.addWidget(_card("判断依据（机器原判）", self._bullet_block(items)))
        layout.addWidget(_card("这套规则测不到什么", self._bullet_block(evidence["limitations"])))

        override = QFrame()
        override.setObjectName("Card")
        override_layout = QHBoxLayout(override)
        override_layout.setContentsMargins(18, 14, 18, 14)
        prompt = _label("判断有误，改为：")
        prompt.setWordWrap(False)
        override_layout.addWidget(prompt)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(sorted(OVERRIDABLE_MODES))
        self.mode_combo.setCurrentText(
            self.judgment["mode"] if self.judgment["mode"] in OVERRIDABLE_MODES else "无法判断"
        )
        override_layout.addWidget(self.mode_combo)
        button = QPushButton("保存我的判断")
        button.setObjectName("Primary")
        button.clicked.connect(self._override_mode)
        override_layout.addWidget(button)
        self.override_status = _label("", "Muted")
        override_layout.addWidget(self.override_status, 1)
        layout.addWidget(override)
        layout.addStretch(1)
        return self._scroll(content)

    def _passport_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        outbound = self.passport["outbound"]
        storage_info = self.passport["local_storage"]
        summary = [
            f"本机快照记录 {storage_info['snapshot_records']} 条；"
            f"日终总结 {storage_info['daily_summaries']} 条。",
            f"另有 AI 判断 {storage_info.get('ai_judgments', 0)} 条、"
            f"估时记录 {storage_info.get('time_estimates', 0)} 条，只在本机。",
            f"图片保留策略：{storage_info['image_retention_text']}"
            f"（{storage_info.get('image_keep_days_source', '调用方传入')}）。",
            f"登记外发 {outbound['recorded_total']} 次；"
            "台账只记录请求元数据，不记录提示词、图片内容或标题全文。",
            outbound.get("ledger_note", ""),
        ]
        layout.addWidget(_card("本机保存与登记外发", self._bullet_block(summary)))

        policy_card = QFrame()
        policy_card.setObjectName("Card")
        policy_layout = QHBoxLayout(policy_card)
        policy_layout.setContentsMargins(18, 12, 18, 12)
        policy_label = _label("允许后续外发（接入后生效）：")
        policy_label.setWordWrap(False)
        policy_layout.addWidget(policy_label)
        self.policy_status = _label("", "Muted")
        for purpose in (PURPOSE_FRAME, PURPOSE_SUMMARY, PURPOSE_TEST):
            box = QCheckBox(purpose)
            box.setChecked(bool(self.passport["outbound_policy"].get(purpose)))
            box.toggled.connect(
                lambda checked, target=purpose: self._toggle_policy(target, checked)
            )
            policy_layout.addWidget(box)
        policy_layout.addWidget(self.policy_status, 1)
        layout.addWidget(policy_card)
        events = self.passport["outbound"]["recent_events"]
        rows = [
            [
                item["ts"][5:16],
                item["purpose"],
                item["provider"],
                item["model"],
                "是" if item["has_thumb"] else "否",
                item["bytes"],
            ]
            for item in events
        ]
        layout.addWidget(
            _table(["时间", "用途", "服务商", "模型", "含缩略图", "字节"], rows)
        )
        revoke = self.passport["revocation"]
        layout.addWidget(
            _card(
                "撤回的三层含义",
                self._bullet_block(
                    [
                        f"未来：{revoke['future']}。",
                        f"本地：{revoke['local']}。",
                        f"已发出：{revoke['already_sent']}。",
                        self.passport["scope_note"],
                    ]
                ),
            )
        )
        actions = QHBoxLayout()
        button = QPushButton("导出数据护照 JSON")
        button.setObjectName("Primary")
        button.clicked.connect(self._export_passport)
        actions.addWidget(button)
        self.passport_status = _label("", "Muted")
        actions.addWidget(self.passport_status, 1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return self._scroll(content)

    def _estimate_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        self.estimate_value = _label("", "BigNumber")
        self.estimate_note = _label("", "Subtitle")
        layout.addWidget(
            _card(
                "今天：我以为 vs 实际（学习与工作类）",
                self._vertical(self.estimate_value, self.estimate_note),
            )
        )
        self._refresh_estimate()

        form = QFrame()
        form.setObjectName("Card")
        form_layout = QHBoxLayout(form)
        form_layout.setContentsMargins(18, 14, 18, 14)
        form_layout.addWidget(_label("今天打算投入"))
        self.plan_spin = QSpinBox()
        self.plan_spin.setRange(0, 24 * 60)
        self.plan_spin.setSuffix(" 分钟")
        self.plan_spin.setValue(
            int(self.estimate.get("planned_minutes") or 0)
            if self.estimate.get("planned_minutes") is not None
            else 120
        )
        form_layout.addWidget(self.plan_spin)
        button = QPushButton("记下计划")
        button.setObjectName("Primary")
        button.clicked.connect(self._save_plan)
        form_layout.addWidget(button)
        self.estimate_status = _label("", "Muted")
        form_layout.addWidget(self.estimate_status, 1)
        layout.addWidget(form)

        self.week_label = self._bullet_block(self._week_items())
        layout.addWidget(_card("近期记录", self.week_label))
        layout.addStretch(1)
        return self._scroll(content)

    def _week_items(self) -> list[str]:
        week = trend(self.storage, limit=14)
        return [
            f"可对照 {week['sample_count']} 天：偏高 {week['high']} 天，"
            f"偏低 {week['low']} 天，接近 {week['near']} 天，一致 {week['same']} 天。",
            week["observation"],
            "实际只统计学习与工作类活动；不做连续打卡，不生成效率排名。",
        ]

    def _refresh_estimate(self) -> None:
        if not hasattr(self, "estimate_value"):
            return
        planned = self.estimate.get("planned_minutes")
        actual = self.estimate.get("actual_minutes")
        planned_text = "未填" if planned is None else f"{planned} 分钟"
        actual_text = "未结算" if actual is None else f"{actual} 分钟"
        self.estimate_value.setText(f"计划 {planned_text}　实际 {actual_text}")
        self.estimate_note.setText(
            self.estimate.get("observation") or self.estimate.get("status") or ""
        )

    def _refresh_week(self) -> None:
        text = "<br>".join(
            f"· {html.escape(item, quote=True)}" for item in self._week_items()
        )
        self.week_label.setText(text)

    def _save_plan(self) -> None:
        day = date.today().isoformat()
        set_plan(self.storage, day, self.plan_spin.value())
        self.estimate = compare_estimate(self.storage, day)
        self._refresh_estimate()
        self._refresh_week()
        self.estimate_status.setText("已记在本机")

    def _toggle_policy(self, purpose: str, allowed: bool) -> None:
        try:
            set_future_outbound(self.storage, purpose, allowed)
        except ValueError as exc:
            self.policy_status.setText(str(exc))
            return
        self.passport["outbound_policy"][purpose] = allowed
        self.policy_status.setText(f"{purpose}：{'允许' if allowed else '已停止'}")

    def _export_pdf(self) -> None:
        target = self.output_dir / "学习复盘.pdf"
        try:
            export_process_pdf(
                self.report, target, self.output_dir, overwrite=True
            )
        except (RuntimeError, ValueError, OSError) as exc:
            self.export_status.setText(str(exc))
            return
        self.export_status.setText(f"已导出：{target.name}")

    def _export_passport(self) -> None:
        target = self.output_dir / "数据护照.json"
        try:
            export_data_passport(
                self.passport, target, self.output_dir, overwrite=True
            )
        except (ValueError, OSError) as exc:
            self.passport_status.setText(str(exc))
            return
        self.passport_status.setText(f"已导出：{target.name}")

    def _override_mode(self) -> None:
        mode = self.mode_combo.currentText()
        try:
            self.judgment = override_collaboration(self.storage, self.judgment["id"], mode)
        except (ValueError, TypeError) as exc:
            self.override_status.setText(str(exc))
            return
        self.ai_mode.setText(mode)
        self.ai_card.set_value(mode, self.judgment["task_context"])
        self.ai_override_note.setText(
            f"本次结论已由你修改；机器原判：{self.judgment.get('original_mode') or '未记录'}。"
        )
        self.override_status.setText("已保存，只改本机记录")

    @staticmethod
    def _bullet_block(items: list) -> QLabel:
        parts = []
        for item in items:
            if isinstance(item, tuple):
                title, detail = item
                parts.append(
                    f"· <span style='color:{TEXT_PRIMARY}'>"
                    f"{html.escape(str(title), quote=True)}</span><br>"
                    f"　{html.escape(str(detail), quote=True)}"
                )
            else:
                parts.append(f"· {html.escape(str(item), quote=True)}")
        label = QLabel("<br>".join(parts))
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:12px; line-height:1.7;")
        return label

    @staticmethod
    def _vertical(*widgets: QWidget) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for widget in widgets:
            layout.addWidget(widget)
        return box

    @staticmethod
    def _scroll(content: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(content)
        return area
