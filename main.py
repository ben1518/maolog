"""MaoLog · 程序入口。

启动顺序：日志 → 单实例检查 → 品牌启动页 → 界面 → 采集引擎 → 托盘 → 首次引导。
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from pathlib import Path

# 允许直接 python main.py 运行，把项目根目录放进模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtCore import QEventLoop, QMetaObject, QSharedMemory, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from core import housekeeping
from core.analyzer import RecorderEngine
from core.config import DATA_DIR, config
from core.demo_data import ensure_demo_day
from core.storage import Storage
from ui.dialogs import WelcomeDialog, show_info
from ui.main_window import MainWindow
from ui.settings_dialog import SettingsDialog
from ui.splash import StartupSplash
from ui.fonts import load_bundled_fonts
from ui.theme import APP_QSS
from ui.tray import TrayIcon, make_icon

LOGGER = logging.getLogger("mao")

# 必须活到进程结束，否则单实例锁会提前释放
_SHARED_MEM: QSharedMemory | None = None


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.FileHandler(DATA_DIR / "app.log", encoding="utf-8")
    ]
    # 打包成无控制台程序时 stdout 可能是 None，加之前要确认
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def set_taskbar_identity() -> None:
    """让任务栏显示自己的图标，而不是 python.exe 的。"""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MaoRecorder.Desktop.1")
    except Exception:
        pass


class Application:
    def __init__(self, demo_mode: bool = False) -> None:
        self._demo_mode = demo_mode
        self._started_at = time.monotonic()
        self._quitting = False
        self._startup_done = False
        self._welcome_pending = False
        self.splash: StartupSplash | None = None
        self.tray: TrayIcon | None = None

        if self._demo_mode:
            os.environ["MAO_NO_WELCOME"] = "1"

        # WebEngine 需要在 QApplication 创建前共享 OpenGL 上下文。
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        self.app = QApplication(sys.argv)
        # 打包字体要在套样式表之前注册，否则第一次绘制会先落到系统字体
        loaded_fonts = load_bundled_fonts()
        if loaded_fonts:
            LOGGER.info("已加载内置字体: %s", ", ".join(loaded_fonts))
        self.app.setApplicationName("MaoLog")
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setStyleSheet(APP_QSS)
        self.app.setWindowIcon(make_icon(64, "running"))
        self.app.aboutToQuit.connect(self._cleanup)

        self._show_splash()
        self._set_startup_status("正在准备演示数据" if self._demo_mode else "正在检查本地数据")
        self.storage = (
            ensure_demo_day(DATA_DIR / "demo.db", DATA_DIR / "demo_shots")
            if self._demo_mode
            else Storage()
        )

        self._set_startup_status("正在准备今日看板")
        self.window = MainWindow(config, self.storage)
        if self._demo_mode:
            self.window.setWindowTitle("楚师智学（MaoLog）· 演示模式")

        self._set_startup_status("正在连接记录引擎")
        self.engine = RecorderEngine(config, self.storage)
        self._wire()
        self._start_engine()

        self._set_startup_status("正在启动系统托盘")
        self._setup_tray()
        self._set_startup_status("准备完成")

        # 启动稳定后再做清理，不抢启动时的 IO
        QTimer.singleShot(5000, self._auto_cleanup)

        # 启动页不靠固定计时假装加载：只保留很短的最小可见时间，
        # 避免快机器上闪一帧，随后等真实初始化完成再退出。
        elapsed_ms = (time.monotonic() - self._started_at) * 1000
        minimum_ms = 350 if self.splash is not None else 0
        QTimer.singleShot(max(0, int(minimum_ms - elapsed_ms)), self._finish_startup)

    # ---------- 启动页与窗口 ----------

    def _show_splash(self) -> None:
        if os.environ.get("MAO_NO_SPLASH") == "1":
            return
        self.splash = StartupSplash()
        self.splash.show()
        self.app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _set_startup_status(self, text: str) -> None:
        if self.splash is None:
            return
        self.splash.set_status(text)
        # 初始化是同步的；让启动页有机会真正画出来，而不是只存在于内存。
        self.app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _finish_startup(self) -> None:
        if self._startup_done or self._quitting:
            return
        self._startup_done = True
        if self.splash is not None:
            self.splash.finish(self._enter_main_window)
        else:
            self._enter_main_window()

    def _enter_main_window(self) -> None:
        self.splash = None
        if self._quitting:
            return
        minimized = bool(config.get("ui.start_minimized"))
        if minimized and self.tray is not None:
            self.window.hide()
            if getattr(self.window, "desktop_pet", None) is not None and config.get("ui.desktop_pet", True):
                self.window.desktop_pet.show()
            self._welcome_pending = True
            self.tray.notify("MaoLog", "已在后台开始记录")
            return
        # 托盘不可用时即使配置了最小化也显示窗口，否则用户没有办法找回程序。
        self.window.show()
        QTimer.singleShot(250, self._maybe_first_run)

    def _wire(self) -> None:
        self.window.settings_requested.connect(self.open_settings)
        # 窗口按钮和托盘走同一个槽，保证两处恢复时的提示一致
        self.window.pause_toggled.connect(self._on_tray_pause)
        if getattr(self.window, "desktop_pet", None) is not None:
            self.window.desktop_pet.capture_now_requested.connect(self._capture_now)

        self.engine.decision.connect(self._on_decision)
        self.engine.analyzed.connect(lambda *_: self.window.on_analyzed())
        self.engine.failed.connect(self._on_failed)
        self.engine.status.connect(self.window.on_status)
        self.engine.recorder_error.connect(lambda msg: LOGGER.error(msg))

    def _start_engine(self) -> None:
        if self._demo_mode:
            self.window.on_status("演示模式 · 已加载今日学业样例数据（与真实记录隔离）")
            return
        self.engine.start()

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            LOGGER.warning("系统托盘不可用，窗口关闭后程序会直接退出")
            return

        self.tray = TrayIcon()
        self.tray.open_requested.connect(self.show_window)
        self.tray.settings_requested.connect(self.open_settings)
        self.tray.pause_toggled.connect(self._on_tray_pause)
        self.tray.pet_toggled.connect(self.window.set_desktop_pet_visible)
        if getattr(self.window, "desktop_pet", None) is not None:
            self.window.desktop_pet.visibility_changed.connect(self.tray.act_pet.setChecked)
        self.tray.capture_now.connect(self._capture_now)
        self.tray.open_folder.connect(self._open_screenshot_folder)
        self.tray.quit_requested.connect(self.quit)
        self.tray.show()
        self._sync_tray()

    def _sync_tray(self) -> None:
        if self.tray is None:
            return
        if self._demo_mode:
            self.tray.set_state("running", "演示模式（隔离样例库）")
            return
        if config.get("privacy.paused"):
            self.tray.set_state("paused", "已暂停")
            return
        ready, msg = _ai_state()
        if ready:
            self.tray.set_state("running", "正在记录")
        elif config.get("ai.local_fallback", True):
            self.tray.set_state("running", "正在记录（本地免 Key）")
        else:
            self.tray.set_state("error", msg)

    # ---------- 槽 ----------

    def _on_decision(self, action: str, message: str) -> None:
        if action == "queued":
            self.window.on_status(message)
        elif action == "reused":
            self.window.on_status(message)
        else:
            self.window.on_status(f"已跳过：{message}")
        self.window.on_captured()
        self._sync_tray()

    def _on_failed(self, _snapshot_id: int, message: str) -> None:
        LOGGER.warning("AI 分析失败：%s", message)
        self.window.on_status(f"AI 分析失败：{message}")
        self._sync_tray()

    def _on_tray_pause(self, paused: bool) -> None:
        config.set("privacy.paused", paused)
        self.window.refresh_status()
        self._sync_tray()
        if not self.tray:
            return
        if paused:
            self.tray.notify("MaoLog", "已暂停记录")
        else:
            left = self.storage.count_status("paused")
            if left:
                self.tray.notify("MaoLog", f"已恢复记录，{left} 条暂停期间的记录会在后台慢慢补上")
            else:
                self.tray.notify("MaoLog", "已恢复记录")

    def _capture_now(self) -> None:
        QMetaObject.invokeMethod(
            self.engine.recorder, "tick", Qt.ConnectionType.QueuedConnection
        )

    def _open_screenshot_folder(self) -> None:
        target = Path(config.get("capture.output_dir", "") or DATA_DIR)
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _auto_cleanup(self) -> None:
        """按保留天数清理旧截图。keep_days 为 0 时什么都不做。"""
        if int(config.get("capture.keep_days", 0) or 0) <= 0:
            return
        import threading

        def _worker() -> None:
            try:
                report = housekeeping.run(config, self.storage)
            except Exception:
                LOGGER.exception("自动清理过期截图失败，已放弃本次清理")
                return

            if report.get("removed_files"):
                LOGGER.info(
                    "自动清理：%s 天 / %s 张 / %.1f MB",
                    report.get("removed_days", 0),
                    report["removed_files"],
                    report.get("removed_bytes", 0) / 1024 / 1024,
                )
            for note in report.get("skipped") or []:
                LOGGER.info("清理跳过：%s", note)

        threading.Thread(target=_worker, name="maolog-cleanup", daemon=True).start()

    def show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()
        self.window.reload()
        if self._welcome_pending and self._startup_done:
            self._welcome_pending = False
            QTimer.singleShot(250, self._maybe_first_run)

    def open_settings(self) -> None:
        dialog = SettingsDialog(config, self.window, storage=self.storage)
        if dialog.exec():
            LOGGER.info("设置已保存")
            self.window.reload()
            self._sync_tray()

    def _maybe_first_run(self) -> None:
        self._welcome_pending = False
        if os.environ.get("MAO_NO_WELCOME") == "1":
            return
        ready, _ = _ai_state()
        if ready:
            return
        QTimer.singleShot(400, self._show_welcome)

    def _show_welcome(self) -> None:
        dlg = WelcomeDialog(self.window)
        dlg.exec()
        if dlg.go_settings:
            self.open_settings()

    # ---------- 生命周期 ----------

    def run(self) -> int:
        return self.app.exec()

    def quit(self) -> None:
        self._cleanup()
        if self.tray:
            self.tray.hide()
        self.app.quit()

    def _cleanup(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        try:
            if self.splash is not None:
                self.splash.force_close()
                self.splash = None
            self.window.prepare_quit()
            self.engine.stop()
        except Exception:
            pass


def _ai_state() -> tuple[bool, str]:
    from core.ai_client import PROVIDERS

    provider = (config.get("ai.provider") or "qwen").lower()
    meta = PROVIDERS.get(provider, PROVIDERS["qwen"])
    if meta["need_key"] and not (config.get("ai.api_key") or "").strip():
        return False, f"未配置 {meta['label']}"
    return True, ""


def main() -> int:
    global _SHARED_MEM

    demo_mode = "--demo" in sys.argv
    setup_logging()
    set_taskbar_identity()

    # 单实例：两个进程同时截图会写出两份重复数据
    lock_key = "mao-recorder-demo-instance-v1" if demo_mode else "mao-recorder-single-instance-v1"
    _SHARED_MEM = QSharedMemory(lock_key)
    if not _SHARED_MEM.create(1):
        LOGGER.warning("检测到已有实例在运行")
        temp = QApplication(sys.argv)  # noqa: F841  弹窗之前必须先有 QApplication
        load_bundled_fonts()
        temp.setStyleSheet(APP_QSS)
        show_info(
            None,
            "MaoLog 已在运行",
            "MaoLog 已经在后台运行了，看一下右下角的托盘图标。",
        )
        return 0

    LOGGER.info("启动 MaoLog%s", "（演示模式）" if demo_mode else "")
    app = Application(demo_mode=demo_mode)
    code = app.run()
    LOGGER.info("退出 MaoLog，返回码 %s", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
