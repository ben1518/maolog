"""渲染全部图标的对照表。

用法：
    MAO_DOODLE=0 python tools/preview_icons.py out-original.png
    MAO_DOODLE=1 python tools/preview_icons.py out-doodle.png
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QSize, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui.brand import ui_icon  # noqa: E402
from ui.theme import BG_ROOT, DOODLE_MODE, TEXT_PRIMARY, TEXT_SECONDARY  # noqa: E402

NAMES = [
    "book", "ai", "pause", "play", "play-circle", "settings",
    "chevron-left", "chevron-right", "calendar", "chart", "image", "apps",
    "music", "skip-back", "skip-forward", "volume", "folder", "refresh",
    "search", "spark", "clock", "check", "shield",
]

COLS = 6
CELL_W, CELL_H = 150, 128
PAD = 22
HEADER = 72


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "icons.png"
    app = QApplication.instance() or QApplication(sys.argv)

    rows = (len(NAMES) + COLS - 1) // COLS
    width = PAD * 2 + COLS * CELL_W
    height = HEADER + rows * CELL_H + PAD
    canvas = QPixmap(width, height)
    canvas.fill(QColor(BG_ROOT))

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    painter.setPen(QColor(TEXT_PRIMARY))
    title = QFont("Microsoft YaHei UI", 13)
    title.setWeight(QFont.Weight.DemiBold)
    painter.setFont(title)
    label = "手绘模式" if DOODLE_MODE else "原版几何"
    painter.drawText(PAD, 30, f"图标对照 · {label}（{len(NAMES)} 个）")

    painter.setPen(QColor(TEXT_SECONDARY))
    painter.setFont(QFont("Microsoft YaHei UI", 8))
    painter.drawText(PAD, 50, "上：48px　下：24px（界面里实际使用的大小）")

    for i, name in enumerate(NAMES):
        col, row = i % COLS, i // COLS
        x = PAD + col * CELL_W
        y = HEADER + row * CELL_H

        icon_big = ui_icon(name, TEXT_PRIMARY)
        icon_small = ui_icon(name, TEXT_PRIMARY)
        painter.drawPixmap(x + 10, y + 4, icon_big.pixmap(QSize(48, 48)))
        painter.drawPixmap(x + 10, y + 56, icon_small.pixmap(QSize(24, 24)))

        painter.setPen(QColor(TEXT_SECONDARY))
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(x + 44, y + 70, name)

    painter.end()
    canvas.save(str(out))
    print(f"图标表 -> {out}  ({canvas.width()}x{canvas.height()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
