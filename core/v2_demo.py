"""隔离的 v2 演示数据。

只写入调用方指定的演示数据库；不读真实 activity.db，不发起网络请求。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .ai_profile import analyze_collaboration, save_collaboration
from .attest import build_process_report
from .outbound import (
    PURPOSE_FRAME,
    PURPOSE_SUMMARY,
    PURPOSE_TEST,
    build_data_passport,
    record_outbound,
    set_future_outbound,
)
from .time_estimate import compare_estimate, productive_minutes_from_storage, set_actual, set_plan
from .v2_storage import V2Storage

DEMO_TASK = "课程论文写作与原型开发"
DEMO_SCENES = [
    ("09:00", 45, "WINWORD.EXE", "课程论文-初稿.docx - Word", "工作", "文档写作", "整理论文的文献综述部分"),
    ("09:45", 20, "chrome.exe", "中国知网 - 文献检索", "学习", "查阅资料", "检索课程论文相关文献"),
    ("10:05", 40, "WINWORD.EXE", "课程论文-初稿.docx - Word", "工作", "文档写作", "继续写论文正文"),
    ("10:45", 20, "chrome.exe", "Kimi - 对话", "学习", "AI 对话", "让 AI 帮忙梳理提纲"),
    ("11:05", 30, "WINWORD.EXE", "课程论文-初稿.docx - Word", "工作", "文档写作", "按提纲修改论文结构"),
    ("14:00", 60, "Code.exe", "attest.py - Visual Studio Code", "工作", "编程开发", "实现过程存证模块"),
    ("15:00", 20, "chrome.exe", "DeepSeek - 对话", "学习", "AI 对话", "询问 SQLite 参数写法"),
    ("15:20", 30, "Code.exe", "ai_profile.py - Visual Studio Code", "工作", "编程开发", "调整 AI 协作判据"),
    ("15:50", 40, "Code.exe", "v2_storage.py - Visual Studio Code", "工作", "编程开发", "补数据表与查询"),
    ("16:30", 20, "chrome.exe", "中国知网 - 文献检索", "学习", "查阅资料", "核对参考文献格式"),
    ("16:50", 50, "WINWORD.EXE", "课程论文-初稿.docx - Word", "工作", "文档写作", "补写结论并检查引用"),
]


def seed_demo_day(storage: V2Storage, day: datetime) -> None:
    for start, minutes, app, title, category, activity, detail in DEMO_SCENES:
        begin = datetime.strptime(f"{day:%Y-%m-%d} {start}", "%Y-%m-%d %H:%M")
        for index in range(minutes):
            snapshot_id = storage.add_snapshot(
                ts=begin + timedelta(minutes=index),
                image_path=None,
                thumb_path=None,
                app_name=app,
                window_title=title,
                status="done",
            )
            storage.save_analysis(
                snapshot_id,
                {
                    "category": category,
                    "activity": activity,
                    "detail": detail,
                    "focus_score": 5 if app in ("Code.exe", "WINWORD.EXE") else 3,
                    "is_productive": True,
                },
            )


def seed_demo_outbound(storage: V2Storage, day: datetime) -> None:
    moments = [
        (PURPOSE_FRAME, "qwen", "qwen-vl-max-latest", 186_000, True, 14),
        (PURPOSE_SUMMARY, "qwen", "qwen-vl-max-latest", 2_400, False, 2),
        (PURPOSE_TEST, "qwen", "qwen-vl-max-latest", 900, False, 1),
    ]
    for purpose, provider, model, byte_count, has_thumb, count in moments:
        for index in range(count):
            record_outbound(
                storage,
                day.replace(hour=9, minute=5) + timedelta(minutes=index * 7),
                provider,
                model,
                byte_count,
                has_thumb,
                purpose,
            )


def build_demo_bundle(db_path: Path) -> dict[str, Any]:
    """生成或复用演示库，返回四页签窗口所需的数据。"""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage = V2Storage(db_path)
    day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    day_text = day.strftime("%Y-%m-%d")
    if not storage.snapshots_between(f"{day_text} 00:00:00", f"{day_text} 23:59:59"):
        seed_demo_day(storage, day)
    if storage.table_counts()["outbound_log"] == 0:
        for purpose in (PURPOSE_FRAME, PURPOSE_SUMMARY, PURPOSE_TEST):
            set_future_outbound(storage, purpose, True)
        seed_demo_outbound(storage, day)
        # 演示也回到真实默认：只展示台账，后续外发保持停止。
        for purpose in (PURPOSE_FRAME, PURPOSE_SUMMARY, PURPOSE_TEST):
            set_future_outbound(storage, purpose, False)

    start_ts = f"{day_text} 09:00:00"
    end_ts = f"{day_text} 18:00:00"
    report = build_process_report(storage, DEMO_TASK, start_ts, end_ts)
    judgment = analyze_collaboration(storage, DEMO_TASK, start_ts, end_ts)
    judgment_id, _ = save_collaboration(storage, judgment)
    saved_judgment = storage.get_ai_judgment(judgment_id)
    if saved_judgment is None:
        raise RuntimeError("演示 AI 判断保存失败")

    set_plan(storage, day_text, 420)
    actual = productive_minutes_from_storage(storage, day_text)
    set_actual(storage, day_text, actual)
    estimate = compare_estimate(storage, day_text)
    passport = build_data_passport(storage, image_keep_days=0, demo=True)
    return {
        "storage": storage,
        "day": day,
        "report": report,
        "judgment": saved_judgment,
        "passport": passport,
        "estimate": estimate,
    }
