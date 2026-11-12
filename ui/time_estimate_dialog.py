"""估时校准：计划分钟 vs 实际学习/工作产出。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .dialogs import show_warning
from core.config import Config
from core.storage import Storage
from core.time_estimate import (
    compare_estimate,
    productive_minutes_from_storage,
    set_actual,
    set_plan,
    trend,
)
from core.v2_runtime import get_v2_storage, v2_table_exists
from core.v2_storage import V2Storage

from .theme import BG_CARD, SUCCESS, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY


class TimeEstimateDialog(QDialog):
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
        self._v2: V2Storage | None = None

        self.setWindowTitle("估时校准")
        self.resize(620, 540)
        self.setMinimumSize(560, 500)
        self.setStyleSheet(f"QDialog {{ background: {BG_CARD}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("估时校准")
        title.setStyleSheet(f"color:{TEXT_PRIMARY}; font-size:18px; font-weight:600;")
        root.addWidget(title)
        intro = QLabel(
            "只对照你自己的计划和实际，不做连续打卡，也不生成效率排名。"
            "实际时长统计学习与工作类活动，按采样间隔估算。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:12px;")
        root.addWidget(intro)

        hero = QFrame()
        hero.setObjectName("Card")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(18, 14, 18, 14)
        hero_layout.setSpacing(4)
        hero_layout.addWidget(_muted("这一天实际产出"))
        self.actual_label = QLabel("—")
        self.actual_label.setStyleSheet(f"color:{TEXT_PRIMARY}; font-size:30px; font-weight:700;")
        hero_layout.addWidget(self.actual_label)
        self.actual_hint = QLabel("")
        self.actual_hint.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11.5px;")
        self.actual_hint.setWordWrap(True)
        hero_layout.addWidget(self.actual_hint)
        root.addWidget(hero)

        form = QFormLayout()
        form.setSpacing(9)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.fromString(initial_day, "yyyy-MM-dd"))
        self.plan_spin = QSpinBox()
        self.plan_spin.setRange(0, 24 * 60)
        self.plan_spin.setSuffix(" 分钟")
        self.plan_spin.setValue(120)
        form.addRow("日期", self.date_edit)
        form.addRow("预计投入", self.plan_spin)
        root.addLayout(form)

        actions = QHBoxLayout()
        self.btn_save = QPushButton("保存计划并结算")
        self.btn_save.setObjectName("Primary")
        self.btn_save.clicked.connect(self._save)
        actions.addWidget(self.btn_save)
        self.save_status = QLabel("")
        self.save_status.setStyleSheet(f"color:{SUCCESS}; font-size:11.5px;")
        actions.addWidget(self.save_status, 1)
        root.addLayout(actions)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:12.5px;")
        root.addWidget(self.status_label)
        self.observation = QLabel("")
        self.observation.setWordWrap(True)
        self.observation.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11.5px;")
        root.addWidget(self.observation)

        trend_card = QFrame()
        trend_card.setObjectName("Card")
        trend_layout = QVBoxLayout(trend_card)
        trend_layout.setContentsMargins(16, 12, 16, 12)
        trend_layout.setSpacing(4)
        trend_layout.addWidget(_muted("近期记录"))
        self.trend_label = QLabel("")
        self.trend_label.setWordWrap(True)
        self.trend_label.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:11.5px;")
        trend_layout.addWidget(self.trend_label)
        root.addWidget(trend_card)
        root.addStretch(1)

        bottom = QHBoxLayout()
        hint = QLabel("打开只读取记录；点保存才写入估时元数据。")
        hint.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        bottom.addWidget(hint, 1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("Ghost")
        close_button.clicked.connect(self.reject)
        bottom.addWidget(close_button)
        root.addLayout(bottom)

        self.date_edit.dateChanged.connect(self._load_day)
        self._load_day()

    # ---------- 读取 ----------

    def _day(self) -> str:
        return self.date_edit.date().toString("yyyy-MM-dd")

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

    def _load_day(self) -> None:
        day = self._day()
        actual = productive_minutes_from_storage(
            self.storage, day, interval=self.cfg.interval_seconds
        )
        self.actual_label.setText(f"{actual} 分钟")
        self.actual_hint.setText(
            "这一天还没有学习或工作类记录。"
            if actual == 0
            else "学习与工作类活动的并集，不是所有前台时间。"
        )
        self.save_status.setText("")
        self.observation.setText("")
        has_table = v2_table_exists(self._v2_path(), "time_estimate")
        if not has_table:
            self.plan_spin.setValue(120)
            self.status_label.setText("还没有保存过计划。填写后点“保存计划并结算”。")
            self.trend_label.setText("还没有可对照的记录；保存一次后会在这里汇总。")
            return
        self._v2 = self._v2_store()
        record = self._v2.get_time_estimate(day) or {}
        planned = record.get("planned_minutes")
        self.plan_spin.setValue(int(planned) if planned is not None else 120)
        if not record:
            self.status_label.setText("这一天还没有保存过计划。")
        elif record.get("planned_minutes") is None or record.get("actual_minutes") is None:
            self.status_label.setText("这一天已保存部分数据，补全计划后点保存。")
        else:
            self._render_compare(compare_estimate(self._v2, day))
        self._render_trend()

    def _render_compare(self, result: dict) -> None:
        planned = result.get("planned_minutes")
        actual = result.get("actual_minutes")
        self.status_label.setText(
            f"上次保存：计划 {planned} 分钟，实际 {actual} 分钟；判断为“{result['status']}”。"
        )
        self.observation.setText(result.get("observation") or "")

    def _render_trend(self) -> None:
        week = trend(self._v2_store(), limit=14)
        if not week["sample_count"]:
            self.trend_label.setText("还没有可对照的记录；保存一次后会在这里汇总。")
            return
        self.trend_label.setText(
            f"可对照 {week['sample_count']} 天：偏高 {week['high']} 天，"
            f"偏低 {week['low']} 天，接近 {week['near']} 天，一致 {week['same']} 天。\n"
            f"{week['observation']}"
        )

    # ---------- 保存 ----------

    def _save(self) -> None:
        day = self._day()
        actual = productive_minutes_from_storage(
            self.storage, day, interval=self.cfg.interval_seconds
        )
        try:
            store = self._v2_store()
            set_plan(store, day, self.plan_spin.value())
            set_actual(store, day, actual)
            result = compare_estimate(store, day)
        except (ValueError, OSError) as exc:
            show_warning(self, "保存失败", str(exc))
            return
        self.actual_label.setText(f"{actual} 分钟")
        self._render_compare(result)
        self._render_trend()
        self.save_status.setText("已保存到本机")


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11.5px;")
    return label
