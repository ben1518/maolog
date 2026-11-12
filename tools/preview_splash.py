"""渲染品牌启动页为 PNG，不弹出真实窗口、不影响正在运行的程序。

    .venv/Scripts/python.exe tools/preview_splash.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QEventLoop, QTimer, Qt
from PyQt6.QtWidgets import QApplication

from ui.splash import StartupSplash
from ui.theme import APP_QSS

OUT = ROOT / "data" / "v2_preview" / "启动页.png"


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    splash = StartupSplash()
    splash.set_status("正在连接记录引擎")
    splash.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    splash.show()

    loop = QEventLoop()
    QTimer.singleShot(620, loop.quit)
    loop.exec()

    if not splash.grab().save(str(OUT)):
        raise RuntimeError(f"启动页截图保存失败：{OUT}")
    print(f"启动页已渲染 -> {OUT}  ({splash.width()}x{splash.height()})")
    splash.force_close()


if __name__ == "__main__":
    main()
