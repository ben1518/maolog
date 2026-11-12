"""系统托盘。

最小化后靠它常驻，不占任务栏。
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from .brand import app_icon


def make_icon(size: int = 64, state: str = "running") -> QIcon:
    """统一品牌图标；size 保留用于兼容既有调用。"""
    return app_icon(state)


class TrayIcon(QSystemTrayIcon):
    open_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    pause_toggled = pyqtSignal(bool)
    pet_toggled = pyqtSignal(bool)
    capture_now = pyqtSignal()
    open_folder = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(make_icon(64, "running"), parent)
        self.setToolTip("MaoLog · 正在记录")

        menu = QMenu()
        menu.setStyleSheet("")

        act_open = QAction("打开看板", menu)
        act_open.triggered.connect(self.open_requested.emit)
        menu.addAction(act_open)

        self.act_pet = QAction("蘑菇小精灵悬浮窗", menu)
        self.act_pet.setCheckable(True)
        self.act_pet.setChecked(True)
        self.act_pet.triggered.connect(self.pet_toggled.emit)
        menu.addAction(self.act_pet)

        self.act_pause = QAction("暂停记录", menu)
        self.act_pause.setCheckable(True)
        self.act_pause.triggered.connect(self._on_pause)
        menu.addAction(self.act_pause)

        act_capture = QAction("立即截一张", menu)
        act_capture.triggered.connect(self.capture_now.emit)
        menu.addAction(act_capture)

        act_folder = QAction("打开截图文件夹", menu)
        act_folder.triggered.connect(self.open_folder.emit)
        menu.addAction(act_folder)

        menu.addSeparator()
        act_settings = QAction("设置…", menu)
        act_settings.triggered.connect(self.settings_requested.emit)
        menu.addAction(act_settings)

        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self.quit_requested.emit)
        menu.addAction(act_quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()

    def _on_pause(self, checked: bool) -> None:
        self.pause_toggled.emit(checked)

    def set_state(self, state: str, text: str) -> None:
        """state: running / paused / error。"""
        self.setIcon(make_icon(64, state))
        self.setToolTip(f"MaoLog · {text}")
        self.act_pause.setChecked(state == "paused")
        self.act_pause.setText("继续记录" if state == "paused" else "暂停记录")

    def notify(self, title: str, message: str) -> None:
        self.showMessage(title, message, make_icon(64, "running"), 4000)
