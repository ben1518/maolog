"""MaoLog（楚师智学）-> MobileClaw 脱敏数据桥接脚本。

读取本地 SQLite 行为库并调用 v2 复盘、AI 协作画像与估时逻辑，
输出不含原始截图路径、不含窗口标题的脱敏 JSON，供 MobileClaw 下游智能体消费。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ai_profile import analyze_collaboration  # noqa: E402
from core.attest import build_process_report  # noqa: E402
from core.config import Config  # noqa: E402
from core.learning_review import analyze_learning  # noqa: E402
from core.storage import Storage, format_duration  # noqa: E402
from core.v2_storage import V2Storage  # noqa: E402


def build_bridge_payload(
    db_path: Path,
    day: str,
    task_name: str = "当日综合学习",
    interval: int = 60,
) -> dict[str, Any]:
    """构建面向 MobileClaw 的脱敏日终上下文 JSON。"""
    storage = Storage(db_path)
    overview = storage.overview(day, interval=interval)
    categories = storage.category_stats(day, interval=interval)

    start_ts = f"{day} 00:00:00"
    end_ts = f"{day} 23:59:59"

    process_report = build_process_report(
        storage,
        task_name=task_name,
        start_ts=start_ts,
        end_ts=end_ts,
        interval=interval,
    )
    learning = analyze_learning(process_report, interval=interval)
    collaboration = analyze_collaboration(
        storage,
        task_context=task_name,
        start_ts=start_ts,
        end_ts=end_ts,
        interval=interval,
    )

    estimate_row = None
    try:
        v2 = V2Storage(db_path)
        estimate_row = v2.get_time_estimate(day)
    except Exception:
        estimate_row = None

    sanitized_categories = [
        {
            "category": c["category"],
            "minutes": round(c["seconds"] / 60.0, 1),
            "ratio_pct": round(c["ratio"] * 100, 1),
        }
        for c in categories
    ]

    summary_lines = [
        f"日期：{day}｜任务：{task_name}",
        f"有效记录：{overview['records']} 条（约 {format_duration(overview['tracked_seconds'])}），平均专注 {overview['avg_focus']}/5",
        "分类分布："
        + ("、".join(f"{c['category']} {c['ratio_pct']}%" for c in sanitized_categories) or "暂无"),
        f"过程复盘：{learning.get('headline', '')} — {learning.get('summary', '')}",
        f"AI 协作模式：{collaboration.get('mode', '无法判断')}",
    ]
    if estimate_row:
        summary_lines.append(
            f"估时对照：计划 {estimate_row['planned_minutes']} 分钟 vs 实际产出 {estimate_row['actual_minutes']} 分钟"
        )

    return {
        "schema": "chushi-zhixue.mobileclaw-bridge.v1",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "privacy_guarantee": {
            "raw_screenshots_included": False,
            "window_titles_included": False,
            "raw_prompts_included": False,
        },
        "day": day,
        "task_name": task_name,
        "overview": {
            "records": overview["records"],
            "tracked_minutes": round(overview["tracked_seconds"] / 60.0, 1),
            "avg_focus": overview["avg_focus"],
            "top_activity": overview["top_activity"],
            "first_ts": overview["first_ts"],
            "last_ts": overview["last_ts"],
        },
        "categories": sanitized_categories,
        "learning_review": {
            "headline": learning.get("headline", ""),
            "summary": learning.get("summary", ""),
            "metrics": learning.get("metrics", {}),
            "strengths": learning.get("strengths", []),
            "frictions": learning.get("frictions", []),
            "suggestions": learning.get("suggestions", []),
            "stage_switches": process_report["metrics"]["stage_switches"],
            "document_revisits": process_report["metrics"]["document_revisits"],
            "data_gaps_count": len(process_report["data_gaps"]),
        },
        "ai_collaboration": {
            "mode": collaboration.get("mode", "无法判断"),
            "ai_samples": collaboration.get("evidence", {}).get("ai_sample_count", 0),
            "ai_sample_ratio": collaboration.get("evidence", {}).get("ai_sample_ratio", 0.0),
            "switch_count": collaboration.get("evidence", {}).get("alternations_within_5min", 0),
        },
        "time_estimate": estimate_row,
        "mobileclaw_prompt_context": "\n".join(summary_lines),
    }


def main() -> int:
    cfg = Config()
    parser = argparse.ArgumentParser(description="导出面向 MobileClaw 的楚师智学脱敏数据包")
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "activity.db",
        help="SQLite 数据库路径（默认 data/activity.db）",
    )
    parser.add_argument(
        "--day",
        default=date.today().strftime("%Y-%m-%d"),
        help="目标日期 YYYY-MM-DD（默认当天）",
    )
    parser.add_argument("--task", default="当日综合学习", help="学习任务名称")
    parser.add_argument(
        "--interval",
        type=int,
        default=cfg.interval_seconds,
        help="采样间隔秒数",
    )
    parser.add_argument("--out", type=Path, default=None, help="可选输出 JSON 文件路径")
    args = parser.parse_args()

    payload = build_bridge_payload(
        db_path=args.db,
        day=args.day,
        task_name=args.task,
        interval=max(1, args.interval),
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"已导出 MobileClaw 桥接包 -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
