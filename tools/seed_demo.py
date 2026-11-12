"""生成一整天的演示数据，用于预览界面效果 / 参赛演示。

用法：
    .venv/Scripts/python.exe tools/seed_demo.py

会写入 data/demo.db 和 data/demo_shots/，不会动你的真实数据。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.demo_data import DEMO_PLAN, ensure_demo_day  # noqa: E402

DEMO_DB = ROOT / "data" / "demo.db"
DEMO_SHOTS = ROOT / "data" / "demo_shots"


def main() -> None:
    storage = ensure_demo_day(DEMO_DB, DEMO_SHOTS, force_reseed=True)
    day = datetime.now().strftime("%Y-%m-%d")
    overview = storage.overview(day, interval=60)
    print(f"已生成 {overview['records']} 条演示记录 -> {DEMO_DB}")
    print(f"演示截图 {len(DEMO_PLAN)} 张 -> {DEMO_SHOTS}")
    print(
        f"当天汇总：{overview['records']} 条，"
        f"{overview['tracked_seconds'] // 60} 分钟，"
        f"平均专注 {overview['avg_focus']}"
    )


if __name__ == "__main__":
    main()
