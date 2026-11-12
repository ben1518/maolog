"""设置对话框：AI 接入、采集参数、隐私开关。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.ai_client import PROVIDERS, AIClient
from core.config import Config
from core.housekeeping import execute as clean_execute
from .dialogs import ask_confirm, show_info, show_warning
from core.housekeeping import plan as clean_plan
from core.storage import Storage, format_duration

from .doodle_paint import RoughButton
from .theme import (
    ACCENT,
    BG_CARD,
    BG_INSET,
    BORDER,
    DANGER,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
)
from .v2_settings import V2SettingsDialog

SENSITIVITY = {
    "高（画面稍有变化就重新分析）": 0.015,
    "中（推荐）": 0.035,
    "低（明显变化才重新分析，更省钱）": 0.06,
}


class SettingsDialog(QDialog):
    def __init__(
        self,
        cfg: Config,
        parent: QWidget | None = None,
        storage: Storage | None = None,
    ) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.storage = storage
        self._test_worker: _TestWorker | None = None

        self.setWindowTitle("设置")
        self.setMinimumSize(680, 610)
        self.setStyleSheet(f"QDialog {{ background: {BG_CARD}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)

        title = QLabel("设置")
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 17px; font-weight: 600;")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_ai_tab(), "AI 接入")
        tabs.addTab(self._build_capture_tab(), "采集")
        tabs.addTab(self._build_privacy_tab(), "隐私")
        tabs.addTab(self._build_appearance_tab(), "外观")
        layout.addWidget(tabs, stretch=1)

        bottom = QHBoxLayout()
        self.btn_open_dir = RoughButton("打开截图文件夹")
        self.btn_open_dir.setObjectName("Ghost")
        self.btn_open_dir.clicked.connect(self._open_output_dir)
        bottom.addWidget(self.btn_open_dir)

        self.btn_v2 = RoughButton("数据护照…")
        self.btn_v2.setObjectName("Ghost")
        self.btn_v2.clicked.connect(self._open_v2_settings)
        bottom.addWidget(self.btn_v2)
        bottom.addStretch(1)

        btn_cancel = RoughButton("取消")
        btn_cancel.setObjectName("Ghost")
        btn_cancel.clicked.connect(self.reject)

        btn_save = RoughButton("保存", variant="primary")
        btn_save.setObjectName("Primary")
        btn_save.clicked.connect(self._save)

        bottom.addWidget(btn_cancel)
        bottom.addWidget(btn_save)
        layout.addLayout(bottom)

        self._initial_skin = str(self.cfg.get("ui.skin", "dark") or "dark")
        self._load_values()

    # ---------- AI 页 ----------

    def _build_ai_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(11)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.combo_provider = QComboBox()
        for key, meta in PROVIDERS.items():
            self.combo_provider.addItem(meta["label"], key)
        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)

        self.edit_key = QLineEdit()
        self.edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_key.setPlaceholderText("粘贴 API Key")

        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        key_row.addWidget(self.edit_key, stretch=1)
        self.btn_eye = RoughButton("显示", radius=7.0)
        self.btn_eye.setObjectName("Ghost")
        self.btn_eye.setFixedWidth(56)
        self.btn_eye.setCheckable(True)
        self.btn_eye.toggled.connect(
            lambda on: (
                self.edit_key.setEchoMode(
                    QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
                ),
                self.btn_eye.setText("隐藏" if on else "显示"),
            )
        )
        key_row.addWidget(self.btn_eye)

        key_box = QWidget()
        key_box.setLayout(key_row)

        self.combo_model = QComboBox()
        self.combo_model.setEditable(True)
        self.combo_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        self.edit_base_url = QLineEdit()
        self.edit_base_url.setPlaceholderText("留空使用默认地址")

        form.addRow(_label("服务商"), self.combo_provider)
        form.addRow(_label("API Key"), key_box)
        form.addRow(_label("模型"), self.combo_model)
        form.addRow(_label("接口地址"), self.edit_base_url)
        layout.addLayout(form)

        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11.5px; background: {BG_INSET};"
            f" border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;"
        )
        layout.addWidget(self.hint_label)

        test_row = QHBoxLayout()
        self.btn_test = RoughButton("测试连接", radius=7.0)
        self.btn_test.setObjectName("Ghost")
        self.btn_test.clicked.connect(self._test_connection)
        test_row.addWidget(self.btn_test)

        self.test_result = QLabel("")
        self.test_result.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        test_row.addWidget(self.test_result, stretch=1)
        layout.addLayout(test_row)

        self.check_local_fallback = QCheckBox(
            "开启「本地免 Key 模式」（未配 API Key 或请求受限时自动用本地规则识别）"
        )
        self.check_local_fallback.setChecked(True)
        layout.addWidget(self.check_local_fallback)

        self.local_fallback_note = QLabel(
            "开启后不填 API Key 也能正常记录：后台会根据前台应用名与窗口标题在本地完成分类，"
            "完整生成时间轴、占比图表与复盘，数据 100% 留在本地；\n"
            "若已配置可用视觉大模型，则优先用 AI 深入识别画面，遇到断网或限流时再自动回退到本地规则。"
            "关闭此开关则仅使用视觉大模型分析。"
        )
        self.local_fallback_note.setWordWrap(True)
        self.local_fallback_note.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11.5px; background: {BG_INSET};"
            f" border: 1px solid {BORDER}; border-radius: 8px; padding: 9px 12px;"
        )
        layout.addWidget(self.local_fallback_note)

        layout.addStretch(1)
        return page

    # ---------- 采集页 ----------

    def _build_capture_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(11)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(10, 1800)
        self.spin_interval.setSuffix(" 秒")
        self.spin_interval.setSingleStep(10)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        self.edit_dir = QLineEdit()
        self.btn_browse = RoughButton("浏览…", radius=7.0)
        self.btn_browse.setObjectName("Ghost")
        self.btn_browse.setFixedWidth(72)
        self.btn_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(self.edit_dir, stretch=1)
        dir_row.addWidget(self.btn_browse)
        dir_box = QWidget()
        dir_box.setLayout(dir_row)

        self.combo_sensitivity = QComboBox()
        for label, value in SENSITIVITY.items():
            self.combo_sensitivity.addItem(label, value)

        self.spin_max_width = QSpinBox()
        self.spin_max_width.setRange(0, 3840)
        self.spin_max_width.setSingleStep(320)
        self.spin_max_width.setSuffix(" px")
        self.spin_max_width.setSpecialValueText("原图尺寸（不缩放）")

        self.spin_jpeg_quality = QSpinBox()
        self.spin_jpeg_quality.setRange(60, 100)
        self.spin_jpeg_quality.setSingleStep(2)
        self.spin_jpeg_quality.setSuffix(" %（推荐 92%）")

        self.spin_keep_days = QSpinBox()
        self.spin_keep_days.setRange(0, 365)
        self.spin_keep_days.setSuffix(" 天")
        self.spin_keep_days.setSpecialValueText("永久保留")

        self.check_change = QCheckBox("画面没有变化时跳过 AI，直接沿用上次结论")
        self.check_change.setChecked(True)

        form.addRow(_label("截图间隔"), self.spin_interval)
        form.addRow(_label("截图保存位置"), dir_box)
        form.addRow(_label("重新分析灵敏度"), self.combo_sensitivity)
        form.addRow(_label("图片最大宽度"), self.spin_max_width)
        form.addRow(_label("截图画质"), self.spin_jpeg_quality)
        form.addRow(_label("原图保留"), self.spin_keep_days)

        self.btn_clean = RoughButton("立即清理过期截图", radius=7.0)
        self.btn_clean.setObjectName("Ghost")
        self.btn_clean.setMaximumWidth(190)
        self.btn_clean.clicked.connect(self._clean_now)
        if self.storage is None:
            self.btn_clean.setEnabled(False)
            self.btn_clean.setToolTip("只有在完整程序里才能清理")
        form.addRow(_label(""), self.btn_clean)

        form.addRow(_label(""), self.check_change)
        layout.addLayout(form)

        tip = QLabel(
            "间隔越短记录越细，但截图更多、AI 调用也更多。60 秒是比较平衡的默认值。\n"
            "本地保存的高清截图（默认 2560px / 92% 4:4:4 无色度抽样）仅用于本机查看，上传 AI 分析时会自动在内存中压缩，不额外消耗流量。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11.5px;")
        layout.addWidget(tip)
        layout.addStretch(1)
        return page

    # ---------- 隐私页 ----------

    def _build_appearance_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        layout.addWidget(_label("界面外观", align_left=True))
        self.combo_skin = QComboBox()
        self.combo_skin.addItem("手绘 · 深色（默认）", "dark")
        self.combo_skin.addItem("手绘 · 米色纸面", "paper")
        self.combo_skin.setToolTip(
            "手绘外观用纸质底色、楷体字和手画边框，插图与字体随程序一起分发。\n"
            "切换后需要重启 MaoLog 才会完全生效。"
        )
        layout.addWidget(self.combo_skin)

        note = QLabel(
            "两套都是手绘风格，区别只在纸的颜色：\n"
            "· 深色：深墨黑板面 + 奶白字 + 暖黄强调，夜里看着不刺眼\n"
            "· 米色纸面：本子底色 + 墨蓝字，像白天随手记的一页\n\n"
            "字体、手画边框、线稿插图两套共用，数据完全一致。\n"
            "因为配色和字体在程序启动时就定了，切换后请重启一次。"
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11.5px;")
        layout.addWidget(note)

        layout.addStretch(1)
        return page

    def _build_privacy_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        layout.addWidget(_label("这些程序出现在前台时不截图（一行一个）", align_left=True))
        self.edit_exclude = QPlainTextEdit()
        self.edit_exclude.setPlaceholderText("KeePass.exe\n1Password.exe")
        self.edit_exclude.setMaximumHeight(110)
        layout.addWidget(self.edit_exclude)

        layout.addWidget(_label("窗口标题包含这些词时不截图（一行一个）", align_left=True))
        self.edit_keywords = QPlainTextEdit()
        self.edit_keywords.setPlaceholderText("密码\n银行卡\n身份证")
        self.edit_keywords.setMaximumHeight(110)
        layout.addWidget(self.edit_keywords)

        note = QLabel(
            "命中以上规则时，这一条整条丢弃：不截图、不上传，也不写入任何记录。\n"
            "窗口标题只在内存里比对一次就被丢掉，不会进数据库——"
            "所以你在看板上连一条「跳过」都看不到。状态栏会闪一下提示，说明它确实生效了。"
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11.5px;")
        layout.addWidget(note)

        layout.addStretch(1)
        return page

    # ---------- 数据装载与保存 ----------

    def _load_values(self) -> None:
        skin = str(self.cfg.get("ui.skin", "dark") or "dark")
        idx = self.combo_skin.findData(skin)
        self.combo_skin.setCurrentIndex(max(0, idx))

        provider = (self.cfg.get("ai.provider") or "qwen").lower()
        idx = self.combo_provider.findData(provider)
        self.combo_provider.setCurrentIndex(max(0, idx))
        self._refresh_models()
        self.combo_model.setCurrentText(self.cfg.get("ai.model") or "")
        self.edit_key.setText(self.cfg.get("ai.api_key") or "")
        self.edit_base_url.setText(self.cfg.get("ai.base_url") or "")
        self.check_local_fallback.setChecked(bool(self.cfg.get("ai.local_fallback", True)))

        self.spin_interval.setValue(int(self.cfg.get("capture.interval_seconds", 60)))
        self.edit_dir.setText(str(self.cfg.get("capture.output_dir", "")))
        self.spin_max_width.setValue(int(self.cfg.get("capture.max_width", 2560)))
        self.spin_jpeg_quality.setValue(int(self.cfg.get("capture.jpeg_quality", 92)))
        self.spin_keep_days.setValue(int(self.cfg.get("capture.keep_days", 0)))
        self.check_change.setChecked(bool(self.cfg.get("capture.change_detection", True)))

        threshold = float(self.cfg.get("capture.change_threshold", 0.035))
        best = min(SENSITIVITY.items(), key=lambda kv: abs(kv[1] - threshold))
        self.combo_sensitivity.setCurrentText(best[0])

        self.edit_exclude.setPlainText("\n".join(self.cfg.get("capture.exclude_apps") or []))
        self.edit_keywords.setPlainText("\n".join(self.cfg.get("privacy.sensitive_keywords") or []))
        # 只刷新提示文案，不能重置模型名——否则用户保存的自定义模型会被冲掉
        self._apply_provider_ui(reset_model=False)

    def _refresh_models(self) -> None:
        provider = self.combo_provider.currentData() or "qwen"
        meta = PROVIDERS.get(provider, PROVIDERS["qwen"])
        current = self.combo_model.currentText()
        self.combo_model.clear()
        self.combo_model.addItems(meta["models"])
        if current:
            self.combo_model.setCurrentText(current)

    def _on_provider_changed(self) -> None:
        self._apply_provider_ui(reset_model=True)

    def _apply_provider_ui(self, reset_model: bool) -> None:
        provider = self.combo_provider.currentData() or "qwen"
        meta = PROVIDERS.get(provider, PROVIDERS["qwen"])
        self._refresh_models()
        if reset_model:
            self.combo_model.setCurrentText(meta["default_model"])
        self.edit_key.setEnabled(meta["need_key"])
        if not meta["need_key"]:
            self.edit_key.setPlaceholderText("本地服务，无需 Key")
        else:
            self.edit_key.setPlaceholderText("粘贴 API Key")
        hint = f"{meta['label']}：{meta['key_hint']}"
        self.hint_label.setText(hint)

    def _browse_dir(self) -> None:
        start = self.edit_dir.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择截图保存位置", start)
        if chosen:
            self.edit_dir.setText(chosen)

    def _open_output_dir(self) -> None:
        target = Path(self.cfg.get("capture.output_dir", "") or ".")
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _open_v2_settings(self) -> None:
        V2SettingsDialog(self.cfg, self).exec()

    def _clean_now(self) -> None:
        if self.storage is None:
            return
        if self.spin_keep_days.value() <= 0:
            show_info(
                self,
                "当前是永久保留",
                "把「原图保留」改成 7 天之类的天数，才能清理更早的截图。",
            )
            return

        # 用界面上当前填的天数去算，而不是用已保存的旧值
        self._apply_to_config(save=False)
        report = clean_plan(self.cfg, self.storage)
        if not report["dirs"]:
            show_info(self, "不用清理", "没有超出保留天数的截图。")
            return

        size_mb = report["bytes"] / 1024 / 1024
        text = (
            f"将永久删除 {len(report['days'])} 个日期目录、共 {report['files']} 张截图"
            f"（约 {size_mb:.1f} MB），只保留最近 {self.spin_keep_days.value()} 天。\n\n"
            "数据库里的记录不会删除，只是点开时间轴时看不到当时的原图。\n"
            "删除后无法恢复，确定继续吗？"
        )
        if not ask_confirm(
            self,
            "确认清理",
            text,
            confirm_text="继续清理",
            cancel_text="先留着",
            danger=True,
        ):
            return

        result = clean_execute(report, self.storage)
        msg = (
            f"已删除 {result['removed_files']} 张，"
            f"释放约 {result['removed_bytes'] / 1024 / 1024:.1f} MB。"
        )
        if result.get("skipped"):
            msg += f"\n{len(result['skipped'])} 个日期被跳过（还有没分析完的记录）。"
        show_info(self, "清理完成", msg)

    def _apply_to_config(self, save: bool) -> None:
        provider = self.combo_provider.currentData() or "qwen"
        self.cfg.set("ai.provider", provider, save=False)
        self.cfg.set("ai.api_key", self.edit_key.text().strip(), save=False)
        self.cfg.set("ai.model", self.combo_model.currentText().strip(), save=False)
        self.cfg.set("ai.base_url", self.edit_base_url.text().strip(), save=False)
        self.cfg.set("ai.local_fallback", self.check_local_fallback.isChecked(), save=False)

        self.cfg.set("capture.interval_seconds", self.spin_interval.value(), save=False)
        self.cfg.set("capture.output_dir", self.edit_dir.text().strip(), save=False)
        self.cfg.set("capture.max_width", self.spin_max_width.value(), save=False)
        self.cfg.set("capture.jpeg_quality", self.spin_jpeg_quality.value(), save=False)
        self.cfg.set("capture.keep_days", self.spin_keep_days.value(), save=False)
        self.cfg.set("capture.change_detection", self.check_change.isChecked(), save=False)
        self.cfg.set("capture.change_threshold", self.combo_sensitivity.currentData(), save=False)

        excludes = [
            line.strip() for line in self.edit_exclude.toPlainText().splitlines() if line.strip()
        ]
        keywords = [
            line.strip() for line in self.edit_keywords.toPlainText().splitlines() if line.strip()
        ]
        self.cfg.set("capture.exclude_apps", excludes, save=False)
        self.cfg.set("privacy.sensitive_keywords", keywords, save=False)
        self.cfg.set("ui.skin", self.combo_skin.currentData() or "dark", save=False)

        if save:
            self.cfg.save()

    def _save(self) -> None:
        if not self.edit_dir.text().strip():
            show_warning(self, "还差一步", "截图保存位置不能为空。")
            return

        new_skin = self.combo_skin.currentData() or "dark"
        skin_changed = new_skin != self._initial_skin
        self._apply_to_config(save=True)

        if skin_changed:
            show_info(
                self,
                "外观已保存",
                "界面外观会在下次启动 MaoLog 时生效。\n\n"
                "配色和字体是在程序启动时加载的，所以不能当场切换。"
                "退出后重新打开一次就好，数据和设置都不会受影响。",
            )
        self.accept()

    # ---------- 测试连接 ----------

    def _test_connection(self) -> None:
        if self._test_worker is not None:
            return
        self._apply_to_config(save=False)
        self.btn_test.setEnabled(False)
        self.test_result.setText("正在测试…")
        self.test_result.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")

        self._test_worker = _TestWorker(self.cfg)
        self._test_worker.ok.connect(self._on_test_ok)
        self._test_worker.failed.connect(self._on_test_failed)
        self._test_worker.finished.connect(self._on_test_done)
        self._test_worker.start()

    def _on_test_ok(self, reply: str) -> None:
        self.test_result.setText(f"连接成功，模型回复：{reply}")
        self.test_result.setStyleSheet(f"color: {SUCCESS}; font-size: 12px;")

    def _on_test_failed(self, message: str) -> None:
        self.test_result.setText(f"连接失败：{message}")
        self.test_result.setStyleSheet(f"color: {DANGER}; font-size: 12px;")

    def _on_test_done(self) -> None:
        self.btn_test.setEnabled(True)
        worker = self._test_worker
        self._test_worker = None
        if worker is not None:
            worker.deleteLater()

    def _stop_test_worker(self) -> None:
        worker = self._test_worker
        if worker is not None and worker.isRunning():
            worker.abort()
            if not worker.wait(500):
                _ORPHAN_TEST_WORKERS.append(worker)
                worker.finished.connect(
                    lambda w=worker: (_ORPHAN_TEST_WORKERS.remove(w) if w in _ORPHAN_TEST_WORKERS else None, w.deleteLater())
                )
                self._test_worker = None

    def reject(self) -> None:
        self._stop_test_worker()
        # 取消时把可能被测试改动的配置从文件重新读回来
        self.cfg.load()
        super().reject()

    def accept(self) -> None:
        self._stop_test_worker()
        super().accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_test_worker()
        super().closeEvent(event)


_ORPHAN_TEST_WORKERS: list[QThread] = []


class _TestWorker(QThread):
    ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self._client = AIClient(cfg)

    def abort(self) -> None:
        self._client.abort()

    def run(self) -> None:
        try:
            reply = self._client.test_connection()
            self.ok.emit(reply)
        except Exception as exc:
            self.failed.emit(str(exc))


def _label(text: str, align_left: bool = False) -> QLabel:
    label = QLabel(text)
    if align_left:
        label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12.5px; font-weight: 600;")
    else:
        label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12.5px;")
    return label
