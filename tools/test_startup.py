"""启动页回归：状态更新、淡出回调与防止误关闭。

    .venv/Scripts/python.exe tools/test_startup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QEventLoop, QTimer, Qt
from PyQt6.QtWidgets import QApplication

from ui.splash import StartupSplash

PASS = "✅"
FAIL = "❌"
OK = True


def check(name: str, condition: bool, detail: str = "") -> None:
    global OK
    if not condition:
        OK = False
    print(f"{PASS if condition else FAIL} {name}" + (f"  ({detail})" if detail else ""))


def wait(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    splash = StartupSplash()
    splash.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    splash.show()
    app.processEvents()

    from ui.splash import DOODLE_WINDOW_H, DOODLE_WINDOW_W

    check(
        "启动页尺寸固定",
        splash.width() == DOODLE_WINDOW_W and splash.height() == DOODLE_WINDOW_H,
        f"{splash.width()}x{splash.height()}",
    )
    check("启动页不进入任务栏", bool(splash.windowFlags() & Qt.WindowType.SplashScreen))
    splash.set_status("正在连接记录引擎")
    check("启动状态可更新", "记录引擎" in splash._status)

    splash.close()
    check("启动中不能被误关闭", splash.isVisible())

    finished: list[bool] = []
    splash.finish(lambda: finished.append(True))
    wait(320)
    check("淡出后执行进入窗口回调", finished == [True], str(finished))
    check("启动页已完成并关闭", not splash.isVisible())

    print("\n" + "=" * 46)
    print(f"{PASS} 全部通过" if OK else f"{FAIL} 有失败项，需要修复")
    print("=" * 46)
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
