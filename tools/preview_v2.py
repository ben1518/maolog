"""生成 v2 学习复盘的隔离演示数据、PDF、数据护照和界面截图。

不读取真实记录，不连接网络。

    .venv/Scripts/python.exe tools/preview_v2.py --reset
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QTabWidget  # noqa: E402

from core.attest import export_process_html, export_process_pdf  # noqa: E402
from core.config import Config  # noqa: E402
from core.outbound import export_data_passport  # noqa: E402
from core.v2_demo import build_demo_bundle  # noqa: E402
from ui.ai_profile_dialog import AIProfileDialog  # noqa: E402
from ui.study_review_dialog import StudyReviewDialog  # noqa: E402
from ui.theme import APP_QSS  # noqa: E402
from ui.time_estimate_dialog import TimeEstimateDialog  # noqa: E402
from ui.v2_preview import V2PreviewWindow  # noqa: E402


def render(window: V2PreviewWindow, output_dir: Path) -> list[Path]:
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    for _ in range(6):
        QApplication.processEvents()
    paths: list[Path] = []
    tabs = window.findChild(QTabWidget)
    if tabs is None:
        path = output_dir / "v2_预览.png"
        window.grab().save(str(path))
        return [path]
    labels = ["过程", "AI协作", "数据护照", "估时"]
    for index in range(tabs.count()):
        tabs.setCurrentIndex(index)
        for _ in range(4):
            QApplication.processEvents()
        label = labels[index] if index < len(labels) else f"tab{index + 1}"
        path = output_dir / f"v2_预览_{label}.png"
        if not window.grab().save(str(path)):
            raise RuntimeError(f"界面截图保存失败：{path}")
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="重建演示数据库")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "v2_preview",
        help="演示输出目录",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "v2_preview.db"
    if args.reset:
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        for pattern in (
            "学习复盘*.pdf",
            "学习复盘*.html",
            "学习过程说明*.pdf",
            "学习过程说明*.html",
            "数据护照*.json",
            "v2_预览_*.png",
            "PDF*.png",
        ):
            for stale in output_dir.glob(pattern):
                if stale.is_file():
                    stale.unlink()

    bundle = build_demo_bundle(db_path)
    storage = bundle["storage"]
    day = bundle["day"]
    report = bundle["report"]
    saved_judgment = bundle["judgment"]
    passport = bundle["passport"]
    estimate = bundle["estimate"]

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    html_path = export_process_html(
        report, output_dir / "学习复盘_演示.html", output_dir, overwrite=True
    )
    pdf_path = export_process_pdf(
        report, output_dir / "学习复盘_演示.pdf", output_dir, overwrite=True
    )
    passport_path = export_data_passport(
        passport, output_dir / "数据护照_演示.json", output_dir, overwrite=True
    )

    window = V2PreviewWindow(
        storage, report, saved_judgment, passport, estimate, output_dir
    )
    images = render(window, output_dir)

    demo_window = V2PreviewWindow(
        storage,
        report,
        saved_judgment,
        passport,
        estimate,
        output_dir,
        demo_mode=True,
    )
    demo_window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    demo_window.resize(1180, 820)
    demo_window.show()
    for _ in range(5):
        QApplication.processEvents()
    demo_path = output_dir / "v2_预览_隔离演示.png"
    if not demo_window.grab().save(str(demo_path)):
        raise RuntimeError(f"隔离演示截图保存失败：{demo_path}")
    images.append(demo_path)

    preview_cfg = Config(output_dir / "preview_config.json")
    review = StudyReviewDialog(
        preview_cfg,
        storage,
        day.strftime("%Y-%m-%d"),
    )
    review.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    review.resize(760, 780)
    review.show()
    for _ in range(5):
        QApplication.processEvents()
    review_path = output_dir / "v2_预览_学习复盘.png"
    if not review.grab().save(str(review_path)):
        raise RuntimeError(f"学习复盘截图保存失败：{review_path}")
    images.append(review_path)

    ai_dialog = AIProfileDialog(preview_cfg, storage, day.strftime("%Y-%m-%d"))
    ai_dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    ai_dialog.resize(820, 780)
    ai_dialog.show()
    for _ in range(5):
        QApplication.processEvents()
    ai_path = output_dir / "v2_预览_AI协作回看.png"
    if not ai_dialog.grab().save(str(ai_path)):
        raise RuntimeError(f"AI 协作回看截图保存失败：{ai_path}")
    images.append(ai_path)

    estimate_dialog = TimeEstimateDialog(preview_cfg, storage, day.strftime("%Y-%m-%d"))
    estimate_dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    estimate_dialog.resize(620, 560)
    estimate_dialog.show()
    for _ in range(5):
        QApplication.processEvents()
    estimate_path = output_dir / "v2_预览_估时校准.png"
    if not estimate_dialog.grab().save(str(estimate_path)):
        raise RuntimeError(f"估时校准截图保存失败：{estimate_path}")
    images.append(estimate_path)

    print("v2 预览已生成：")
    for path in [html_path, pdf_path, passport_path, *images]:
        size = path.stat().st_size if path.exists() else 0
        print(f"  - {path}  ({size} bytes)")
    print(f"演示数据库：{db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
