"""渲染主窗口为 PNG，用于快速检查视觉效果。

用 WA_DontShowOnScreen 在真实 Windows 平台下渲染（字体才正常），但窗口不会真的弹出来。

用法：
    .venv/Scripts/python.exe tools/preview_ui.py [输出路径]

可用 MAO_PREVIEW_WIDTH / MAO_PREVIEW_HEIGHT 指定窗口尺寸，默认 1380×920。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from core.config import Config  # noqa: E402
from core.storage import Storage  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.settings_dialog import SettingsDialog  # noqa: E402
from ui.fonts import load_bundled_fonts
from ui.theme import APP_QSS  # noqa: E402

DEMO_DB = ROOT / "data" / "demo.db"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "preview.png"
# 允许用环境变量检查最小窗口，避免只验收宽屏效果
WIDTH = int(os.environ.get("MAO_PREVIEW_WIDTH", "1380"))
HEIGHT = int(os.environ.get("MAO_PREVIEW_HEIGHT", "920"))


def main() -> None:
    app = QApplication(sys.argv)
    load_bundled_fonts()
    app.setStyleSheet(APP_QSS)

    storage = Storage(DEMO_DB if DEMO_DB.exists() else ROOT / "data" / "activity.db")
    cfg = Config(ROOT / "data" / "demo_config.json")
    cfg.set("ai.api_key", "sk-demo-key-for-preview", save=False)

    window = MainWindow(cfg, storage)
    # 关键：窗口走真实平台渲染但不上屏，这样字体、样式都和实际运行一致
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(WIDTH, HEIGHT)
    window.show()
    app.processEvents()

    # 停掉动画再设终态，否则动画下一次 tick 会把值覆盖回去
    window.donut._anim.stop()
    window.donut.set_progress(1.0)
    for _ in range(5):
        app.processEvents()
    window.donut._anim.stop()
    window.donut.set_progress(1.0)

    grab = window.grab()
    grab.save(str(OUT))
    print(f"主窗口已渲染 -> {OUT}  ({grab.width()}x{grab.height()})")
    bar = window._right_scroll.verticalScrollBar()
    print(
        f"右栏: viewport={window._right_scroll.viewport().height()} "
        f"content={window._right_scroll.widget().height()} scroll_max={bar.maximum()}"
    )

    dialog = SettingsDialog(cfg)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.resize(680, 600)
    dialog.show()
    for _ in range(5):
        app.processEvents()

    out2 = OUT.with_name("preview_settings.png")
    dialog.grab().save(str(out2))
    print(f"设置窗口已渲染 -> {out2}")

    # 三个标签页各渲一张，方便检查表单排版
    from PyQt6.QtWidgets import QTabWidget

    tabs = dialog.findChild(QTabWidget)
    if tabs is not None:
        for i in range(tabs.count()):
            tabs.setCurrentIndex(i)
            for _ in range(4):
                app.processEvents()
            path = OUT.with_name(f"preview_tab_{i}.png")
            dialog.grab().save(str(path))
            print(f"  标签页 {tabs.tabText(i)} -> {path}")


if __name__ == "__main__":
    main()
