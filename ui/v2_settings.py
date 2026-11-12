"""v2 实盘台账与数据护照设置面板。

独立组件，只被设置对话框挂一个入口；默认关闭，不建表、不写库。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.paths import data_root
from .dialogs import ask_confirm, show_info, show_warning
from core.config import Config
from core.outbound import (
    ALLOWED_PURPOSES,
    build_data_passport,
    export_data_passport,
    set_future_outbound,
)
from core.v2_runtime import (
    enforcement_enabled,
    get_v2_storage,
    ledger_enabled,
)

from .theme import BG_CARD, SUCCESS, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY

EXPORT_DIR = data_root() / "data" / "v2_exports"


def load_policy_state(cfg: Config) -> dict[str, bool]:
    if not ledger_enabled(cfg):
        return {purpose: True for purpose in ALLOWED_PURPOSES}
    return get_v2_storage(cfg).outbound_policy_state()


def apply_settings(
    cfg: Config,
    enabled: bool,
    enforce: bool,
    policies: dict[str, bool],
) -> None:
    unknown = set(policies) - set(ALLOWED_PURPOSES)
    if unknown:
        raise ValueError(f"未知外发用途：{'、'.join(sorted(unknown))}")
    cfg.set("v2.outbound_ledger", bool(enabled), save=False)
    cfg.set("v2.enforce_outbound", bool(enabled and enforce), save=False)
    if enabled:
        storage = get_v2_storage(cfg)
        for purpose in sorted(ALLOWED_PURPOSES):
            set_future_outbound(storage, purpose, bool(policies.get(purpose, True)))
    cfg.save()


def export_live_passport(cfg: Config, export_dir: Path = EXPORT_DIR) -> Path:
    if not ledger_enabled(cfg):
        raise ValueError("外发台账尚未开启")
    storage = get_v2_storage(cfg)
    passport = build_data_passport(
        storage,
        image_keep_days=int(cfg.get("capture.keep_days", 0) or 0),
        ledger_wired=True,
        policy_enforcement="on" if enforcement_enabled(cfg) else "off",
    )
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    name = f"数据护照_实盘_{datetime.now():%Y%m%d_%H%M%S}.json"
    return export_data_passport(passport, export_dir / name, export_dir, overwrite=False)


def cleanup_v2_day(cfg: Config, day: str) -> dict[str, int]:
    if not ledger_enabled(cfg):
        raise ValueError("外发台账尚未开启，没有可清理的 v2 元数据")
    return get_v2_storage(cfg).delete_day_v2(day)


class V2SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("数据护照与外发台账")
        self.setMinimumWidth(560)
        self.setStyleSheet(f"QDialog {{ background: {BG_CARD}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        title = QLabel("数据护照与外发台账")
        title.setStyleSheet(f"color:{TEXT_PRIMARY}; font-size:17px; font-weight:600;")
        root.addWidget(title)
        intro = QLabel(
            "记录 AI 请求的厂商、模型、大小和用途，不记录提示词、图片内容或窗口标题。"
            "默认关闭；关闭时不建表、不写任何请求记录。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:12px;")
        root.addWidget(intro)

        switches = QFrame()
        switches.setObjectName("Card")
        switch_layout = QVBoxLayout(switches)
        switch_layout.setContentsMargins(16, 14, 16, 14)
        switch_layout.setSpacing(9)
        self.check_enabled = QCheckBox("开启外发台账（重新启动 MaoLog 后生效）")
        self.check_enforce = QCheckBox("按用途拦截请求（关闭时只记录，不改变一期 AI 行为）")
        switch_layout.addWidget(self.check_enabled)
        switch_layout.addWidget(self.check_enforce)
        root.addWidget(switches)

        policy_frame = QFrame()
        policy_frame.setObjectName("Card")
        policy_layout = QVBoxLayout(policy_frame)
        policy_layout.setContentsMargins(16, 12, 16, 14)
        policy_layout.setSpacing(8)
        policy_layout.addWidget(_text_label("允许后续外发（仅在拦截模式下生效）"))
        row = QHBoxLayout()
        self.policy_boxes: dict[str, QCheckBox] = {}
        for purpose in sorted(ALLOWED_PURPOSES):
            box = QCheckBox(purpose)
            self.policy_boxes[purpose] = box
            row.addWidget(box)
        row.addStretch(1)
        policy_layout.addLayout(row)
        root.addWidget(policy_frame)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11.5px;")
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.btn_export = QPushButton("导出数据护照")
        self.btn_export.setObjectName("Ghost")
        self.btn_export.clicked.connect(self._export)
        actions.addWidget(self.btn_export)
        actions.addStretch(1)
        root.addLayout(actions)

        cleanup_frame = QFrame()
        cleanup_frame.setObjectName("Card")
        cleanup_layout = QHBoxLayout(cleanup_frame)
        cleanup_layout.setContentsMargins(16, 12, 16, 12)
        cleanup_layout.addWidget(_text_label("删除某日的 v2 元数据"))
        self.date_edit = QDateEdit(QDate.currentDate().addDays(-1))
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        cleanup_layout.addWidget(self.date_edit)
        self.btn_cleanup = QPushButton("删除")
        self.btn_cleanup.setObjectName("Danger")
        self.btn_cleanup.clicked.connect(self._cleanup)
        cleanup_layout.addWidget(self.btn_cleanup)
        root.addWidget(cleanup_frame)
        note = QLabel("删除只涉及 AI 判断、外发记录和估时，不会删除一期快照、日终总结或截图。")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{TEXT_MUTED}; font-size:11px;")
        root.addWidget(note)

        bottom = QHBoxLayout()
        self.save_status = QLabel("")
        self.save_status.setStyleSheet(f"color:{SUCCESS}; font-size:11.5px;")
        bottom.addWidget(self.save_status, 1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("Ghost")
        close_button.clicked.connect(self.reject)
        save_button = QPushButton("保存设置")
        save_button.setObjectName("Primary")
        save_button.clicked.connect(self._save)
        bottom.addWidget(close_button)
        bottom.addWidget(save_button)
        root.addLayout(bottom)

        self._load()
        self.check_enabled.toggled.connect(self._refresh)
        self.check_enforce.toggled.connect(self._refresh)
        self._refresh()

    def _load(self) -> None:
        enabled = ledger_enabled(self.cfg)
        self.check_enabled.setChecked(enabled)
        self.check_enforce.setChecked(enforcement_enabled(self.cfg))
        policies = load_policy_state(self.cfg)
        for purpose, box in self.policy_boxes.items():
            box.setChecked(bool(policies.get(purpose, True)))

    def _refresh(self) -> None:
        enabled = self.check_enabled.isChecked()
        self.check_enforce.setEnabled(enabled)
        for box in self.policy_boxes.values():
            box.setEnabled(enabled)
        self.btn_export.setEnabled(enabled)
        self.btn_cleanup.setEnabled(enabled)
        self.date_edit.setEnabled(enabled)
        if enabled and ledger_enabled(self.cfg):
            counts = get_v2_storage(self.cfg).table_counts()
            self.status_label.setText(
                f"已登记外发 {counts['outbound_log']} 条；AI 判断 {counts['ai_use_daily']} 条。"
                f"当前模式：{'按用途拦截' if self.check_enforce.isChecked() else '只记录'}。"
            )
        elif enabled:
            self.status_label.setText("尚未保存。点击“保存设置”后创建台账；重新启动 MaoLog 后生效。")
        else:
            self.status_label.setText("台账关闭：不创建 v2 表，也不写任何请求记录。")

    def _save(self) -> bool:
        policies = {purpose: box.isChecked() for purpose, box in self.policy_boxes.items()}
        if (
            self.check_enabled.isChecked()
            and self.check_enforce.isChecked()
            and not any(policies.values())
        ):
            show_warning(
                self,
                "拦截会挡住所有 AI 请求",
                "拦截模式已开启，但三类用途全部关闭。重启后画面识别、日终总结和连接测试都会被阻止。\n"
                "请至少允许一类用途，或关闭拦截模式。",
            )
            return False
        try:
            apply_settings(
                self.cfg,
                self.check_enabled.isChecked(),
                self.check_enforce.isChecked(),
                policies,
            )
        except (ValueError, OSError) as exc:
            show_warning(self, "保存失败", str(exc))
            return False
        self.save_status.setText("已保存；重新启动 MaoLog 后生效")
        self._refresh()
        return True

    def _export(self) -> None:
        if not self._save():
            return
        try:
            path = export_live_passport(self.cfg)
        except (ValueError, OSError) as exc:
            show_warning(self, "导出失败", str(exc))
            return
        show_info(self, "数据护照已导出", f"文件位置：\n{path}")

    def _cleanup(self) -> None:
        if not self._save():
            return
        day = self.date_edit.date().toString("yyyy-MM-dd")
        if not ask_confirm(
            self,
            "确认删除 v2 元数据",
            f"将永久删除 {day} 的 AI 判断、外发记录和估时。\n\n"
            "不会删除一期快照、日终总结或截图。\n"
            "删除后无法恢复，确定继续吗？",
            confirm_text="确认删除",
            cancel_text="取消",
            danger=True,
        ):
            return
        try:
            result = cleanup_v2_day(self.cfg, day)
        except (ValueError, OSError) as exc:
            show_warning(self, "删除失败", str(exc))
            return
        total = sum(result.values())
        show_info(
            self,
            "删除完成",
            f"{day}：已删除 {total} 条 v2 元数据。\n"
            f"AI 判断 {result['ai_judgments']} 条，外发 {result['outbound_records']} 条，"
            f"估时 {result['time_estimates']} 条。",
        )
        self._refresh()


def _text_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:12px;")
    return label
