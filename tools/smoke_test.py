"""启动冒烟测试：真的把程序跑起来，等几秒看采集有没有发生。

    .venv/Scripts/python.exe tools/smoke_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["MAO_NO_WELCOME"] = "1"

from PyQt6.QtCore import QTimer  # noqa: E402

import main as entry  # noqa: E402
from core.config import config  # noqa: E402
from core.storage import Storage  # noqa: E402


def main() -> int:
    entry.setup_logging()
    entry.set_taskbar_identity()

    app = entry.Application()
    storage = Storage()
    before = storage.counts(_today()).get("total", 0)

    def finish() -> None:
        counts = storage.counts(_today())
        after = counts.get("total", 0)
        print("\n==== 冒烟测试结果 ====")
        print(f"窗口可见: {app.window.isVisible()}")
        print(f"托盘图标: {'已创建' if app.tray else '不可用'}")
        print(f"采集线程: {'运行中' if app.engine._started else '未启动'}")
        print(f"新增记录: {after - before} 条（启动前 {before}）")
        print(f"状态栏: {app.window.status_text.text()} / {app.window.status_detail.text()}")
        print(f"时间轴段数: {len(app.window.timeline._segments)}")
        if app.tray:
            print(f"托盘状态: {app.tray.toolTip()}")
        app.quit()

    # 首帧在启动 300ms 后就采，留 6 秒足够验证一次完整采集
    QTimer.singleShot(6000, finish)
    code = app.run()
    return code


def _today() -> str:
    from datetime import date

    return date.today().strftime("%Y-%m-%d")


if __name__ == "__main__":
    sys.exit(main())
