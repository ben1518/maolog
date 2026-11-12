"""时间轴活动微调与「本地纠偏记忆规则」对话框。"""

from __future__ import annotations

import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.app_names import resolve_app_display_name
from core.local_classifier import CATEGORIES, PRESET_ACTIVITIES

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


def _guess_title_keyword(window_title: str) -> str:
    """从窗口标题中提取一个最具代表性的短关键词供规则匹配预填。"""
    t = (window_title or "").strip()
    if not t:
        return ""
    parts = [p.strip() for p in re.split(r"\s*[-—|_｜]\s*", t) if p.strip()]
    if len(parts) >= 2:
        # 往往倒数第二段或第一段是站点/课程/项目名
        candidate = parts[-2] if len(parts[-1]) <= 14 else parts[0]
        return candidate[:24]
    return t[:24]


class SegmentEditDialog(QDialog):
    """编辑单段时间轴记录，并可选保存为永久本地纠偏规则。"""

    def __init__(self, parent: QWidget | None, segment: dict) -> None:
        super().__init__(parent)
        self.segment = segment
        self.result_data: dict | None = None

        self.setWindowTitle("✏️ 校准时间段记录 & 记忆规则")
        self.setModal(True)
        self.setFixedWidth(480)
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {BG_CARD};
                color: {TEXT_PRIMARY};
            }}
            QLabel {{
                color: {TEXT_PRIMARY};
                font-size: 12.5px;
            }}
            QLineEdit, QComboBox {{
                background: {BG_ELEVATED};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 12.5px;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 1px solid {ACCENT};
            }}
            QCheckBox {{
                color: {TEXT_PRIMARY};
                font-size: 12.5px;
                spacing: 8px;
            }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        # 顶部时间段信息提示
        app_raw = segment.get("app_name") or ""
        win_title = segment.get("window_title") or ""
        app_label = resolve_app_display_name(app_raw, win_title) or "未知应用"
        info_lbl = QLabel(
            f"🕒 时段：{segment.get('start_text', '')} - {segment.get('end_text', '')} "
            f"（{segment.get('duration_text', '')}） · 应用：{app_label}"
        )
        info_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; font-weight: 600;")
        info_lbl.setWordWrap(True)
        root.addWidget(info_lbl)

        # 1. 所属分类
        cat_row = QHBoxLayout()
        cat_lbl = QLabel("所属分类：")
        cat_lbl.setFixedWidth(76)
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(CATEGORIES)
        cur_cat = segment.get("category") or "其他"
        if cur_cat in CATEGORIES:
            self.cat_combo.setCurrentText(cur_cat)
        cat_row.addWidget(cat_lbl)
        cat_row.addWidget(self.cat_combo, stretch=1)
        root.addLayout(cat_row)

        # 2. 活动名称（可下拉选高频预设，也可自由输入）
        act_row = QHBoxLayout()
        act_lbl = QLabel("活动名称：")
        act_lbl.setFixedWidth(76)
        self.act_combo = QComboBox()
        self.act_combo.setEditable(True)
        cur_act = segment.get("activity") or ""
        presets: list[str] = []
        if isinstance(PRESET_ACTIVITIES, dict):
            for items in PRESET_ACTIVITIES.values():
                for it in items:
                    if it not in presets:
                        presets.append(it)
        else:
            presets = list(PRESET_ACTIVITIES)
        if cur_act and cur_act not in presets:
            presets.insert(0, cur_act)
        self.act_combo.addItems(presets)
        self.act_combo.setCurrentText(cur_act or "课程学习")
        act_row.addWidget(act_lbl)
        act_row.addWidget(self.act_combo, stretch=1)
        root.addLayout(act_row)

        # 3. 详细说明
        det_row = QHBoxLayout()
        det_lbl = QLabel("具体内容：")
        det_lbl.setFixedWidth(76)
        self.det_edit = QLineEdit(segment.get("detail") or "")
        self.det_edit.setPlaceholderText("例如：在 B 站看宋浩老师高数网课 / 编写课程设计代码")
        det_row.addWidget(det_lbl)
        det_row.addWidget(self.det_edit, stretch=1)
        root.addLayout(det_row)

        # 4. 本地纠偏记忆规则卡片
        rule_box = QFrame()
        rule_box.setStyleSheet(
            f"""
            QFrame {{
                background: {BG_ELEVATED};
                border: 1px dashed {BORDER};
                border-radius: 10px;
            }}
            """
        )
        rule_layout = QVBoxLayout(rule_box)
        rule_layout.setContentsMargins(14, 12, 14, 12)
        rule_layout.setSpacing(8)

        self.chk_remember = QCheckBox("🧠 记住这条纠偏规则（以后遇到同类窗口自动归类，免耗 Token）")
        self.chk_remember.setChecked(True)
        rule_layout.addWidget(self.chk_remember)

        rule_hint = QLabel("当窗口同时满足以下条件时，自动按上方分类与活动名称落库，并回溯校准今日同类记录：")
        rule_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11.5px; border: none;")
        rule_hint.setWordWrap(True)
        rule_layout.addWidget(rule_hint)

        r_app_row = QHBoxLayout()
        r_app_lbl = QLabel("匹配进程：")
        r_app_lbl.setFixedWidth(70)
        r_app_lbl.setStyleSheet("border: none; font-size: 12px;")
        self.rule_app_edit = QLineEdit(app_raw)
        self.rule_app_edit.setPlaceholderText("留空表示任意应用")
        r_app_row.addWidget(r_app_lbl)
        r_app_row.addWidget(self.rule_app_edit, stretch=1)
        rule_layout.addLayout(r_app_row)

        r_kw_row = QHBoxLayout()
        r_kw_lbl = QLabel("标题包含：")
        r_kw_lbl.setFixedWidth(70)
        r_kw_lbl.setStyleSheet("border: none; font-size: 12px;")
        self.rule_kw_edit = QLineEdit(_guess_title_keyword(win_title))
        self.rule_kw_edit.setPlaceholderText("窗口标题关键词（留空则匹配该进程所有窗口）")
        r_kw_row.addWidget(r_kw_lbl)
        r_kw_row.addWidget(self.rule_kw_edit, stretch=1)
        rule_layout.addLayout(r_kw_row)

        self.chk_remember.toggled.connect(self.rule_app_edit.setEnabled)
        self.chk_remember.toggled.connect(self.rule_kw_edit.setEnabled)

        root.addWidget(rule_box)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        btn_cancel = QPushButton("取消")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_SOFT};
                border-radius: 8px;
                padding: 6px 16px;
                font-size: 12.5px;
            }}
            """
        )
        btn_cancel.clicked.connect(self.reject)

        btn_ok = QPushButton("保存校准")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setStyleSheet(
            f"""
            QPushButton {{
                background: {ACCENT};
                color: {ON_ACCENT};
                border: none;
                border-radius: 8px;
                padding: 6px 18px;
                font-size: 12.5px;
                font-weight: 600;
            }}
            """
        )
        btn_ok.clicked.connect(self._on_accept)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        root.addLayout(btn_row)

    def _on_accept(self) -> None:
        cat = self.cat_combo.currentText().strip() or "其他"
        act = self.act_combo.currentText().strip() or cat
        det = self.det_edit.text().strip()
        self.result_data = {
            "category": cat,
            "activity": act,
            "detail": det,
            "remember_rule": self.chk_remember.isChecked(),
            "rule_app": self.rule_app_edit.text().strip(),
            "rule_keyword": self.rule_kw_edit.text().strip(),
        }
        self.accept()
