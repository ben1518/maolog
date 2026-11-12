"""学业成就勋章与成就卡片数据萃取模块。

根据当天的学习工时、连续心流时长、AI 协作画像、产出占比等客观数据，
为学生自动颁发当日手绘勋章与提炼高光数据，供生成拍立得/手绘成就便签。
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Any, Dict, List

from .storage import Storage, format_duration
from .app_names import resolve_app_display_name


def extract_achievements(
    storage: Storage,
    day_str: str,
    interval: int = 60,
) -> Dict[str, Any]:
    """萃取指定日期的学业成就与打卡卡片所需数据。"""
    overview = storage.overview(day_str, interval=interval)
    segments = storage.segments(day_str, interval=interval)
    cats = storage.category_stats(day_str, interval=interval)
    apps = storage.app_stats(day_str, interval=interval, limit=5)
    summary_record = storage.get_daily_summary(day_str)

    tracked_seconds = overview.get("tracked_seconds", 0)
    productive_seconds = overview.get("productive_seconds", 0)
    total_records = overview.get("records", 0)
    avg_focus = overview.get("avg_focus", 0.0)

    total_hours = round(tracked_seconds / 3600.0, 1)
    productive_hours = round(productive_seconds / 3600.0, 1)
    produce_ratio = (
        round(productive_seconds / tracked_seconds * 100) if tracked_seconds > 0 else 0
    )

    # 计算最长连续心流（同类工作/学习且专注度 >= 3 的最大连续段）
    max_flow_seconds = 0
    current_flow = 0
    for seg in segments:
        sec = seg.get("seconds", 0)
        cat = seg.get("category", "")
        focus = seg.get("focus_score", 0)
        if cat in ("工作", "学习") and focus >= 3:
            current_flow += sec
            if current_flow > max_flow_seconds:
                max_flow_seconds = current_flow
        else:
            current_flow = 0
    if not max_flow_seconds and segments:
        max_flow_seconds = max((s.get("seconds", 0) for s in segments), default=0)
    max_flow_minutes = max(1, round(max_flow_seconds / 60))

    # 计算分类时长
    cat_durations: Dict[str, int] = {c["category"]: c.get("seconds", 0) for c in cats}
    work_mins = cat_durations.get("工作", 0) // 60
    study_mins = cat_durations.get("学习", 0) // 60

    # 勋章判定
    badges: List[Dict[str, str]] = []

    # 1. 深度心流小精灵
    if max_flow_minutes >= 40:
        badges.append({
            "icon": "🍄",
            "name": "深度心流小精灵",
            "desc": f"最长连续心流投入达 {max_flow_minutes} 分钟",
        })

    # 2. 代码工匠小精灵
    coding_hits = any("编程" in s.get("activity", "") or "代码" in s.get("activity", "") for s in segments)
    if coding_hits and (work_mins >= 40 or "Visual Studio Code" in [a["app"] for a in apps[:2]]):
        badges.append({
            "icon": "💻",
            "name": "代码工匠小精灵",
            "desc": f"主线编程推进扎实 ({max(1, work_mins // 60)}h)",
        })

    # 3. 笔耕不辍小精灵
    writing_hits = any("文档" in s.get("activity", "") or "写作" in s.get("activity", "") or "阅读" in s.get("activity", "") for s in segments)
    if writing_hits and (study_mins + work_mins >= 35):
        badges.append({
            "icon": "✍️",
            "name": "笔耕不辍小精灵",
            "desc": "专注文档写作与资料梳理",
        })

    # 4. 研精覃思小精灵
    if study_mins >= 40:
        badges.append({
            "icon": "📚",
            "name": "研精覃思小精灵",
            "desc": f"学术与知识汲取投入 {round(study_mins / 60, 1)}h",
        })

    # 5. 自律早鸟小精灵
    first_ts = overview.get("first_ts", "")
    if first_ts and "05:00" <= first_ts <= "08:45":
        badges.append({
            "icon": "🌅",
            "name": "自律早鸟小精灵",
            "desc": f"{first_ts} 早起开启今日研学",
        })

    # 6. 先思后问达人（检查 AI 协作模式）
    try:
        from .v2_storage import V2Storage
        v2 = V2Storage(storage.db_path)
        ai_judgments = v2.get_ai_judgments_for_day(day_str)
        if any(j.get("mode") == "先思后问" for j in ai_judgments):
            badges.append({
                "icon": "🧠",
                "name": "先思后问达人",
                "desc": "自主构思再向 AI 探求启发",
            })
    except Exception:
        pass

    # 7. 学业劳模小精灵
    if tracked_seconds >= 5 * 3600:
        badges.append({
            "icon": "⭐",
            "name": "学业劳模小精灵",
            "desc": f"今日总研学生产力累计达 {total_hours}h",
        })

    # 兜底勋章：如果一个都没中但有记录
    if not badges and total_records > 0:
        badges.append({
            "icon": "🌱",
            "name": "笃行启程小精灵",
            "desc": f"迈出扎实一步 · 累计记录 {total_records} 次采样",
        })

    # 最多展示 3 枚最亮眼徽章
    display_badges = badges[:3]

    # AI 评语或高光提炼
    highlight = ""
    if summary_record and summary_record.get("summary"):
        highlight = summary_record["summary"].strip()
    elif summary_record and summary_record.get("highlights"):
        highlight = " · ".join(summary_record["highlights"])
    elif segments:
        top_act = overview.get("top_activity") or "自主研学"
        highlight = f"全天最常投入在「{top_act}」，共聚合完成 {len(segments)} 个学习与工作时间段。"
    else:
        highlight = "今天还没有足够的采样记录，带上蘑菇小精灵开启专注的一天吧！"

    # 日期与星期格式化
    try:
        d = datetime.strptime(day_str, "%Y-%m-%d")
        weekday = "周" + "一二三四五六日"[d.weekday()]
    except Exception:
        weekday = ""

    # 主要应用占比
    top_apps = []
    if apps and tracked_seconds > 0:
        for a in apps[:4]:
            ratio = round(a["seconds"] / tracked_seconds * 100)
            top_apps.append({
                "app": a["app"],
                "ratio": ratio,
                "duration": format_duration(a["seconds"]),
            })

    return {
        "day": day_str,
        "weekday": weekday,
        "total_records": total_records,
        "total_seconds": tracked_seconds,
        "total_hours": total_hours,
        "productive_hours": productive_hours,
        "produce_ratio": produce_ratio,
        "avg_focus": avg_focus,
        "max_flow_minutes": max_flow_minutes,
        "badges": display_badges,
        "highlight": highlight,
        "top_apps": top_apps,
        "first_ts": overview.get("first_ts", "—"),
        "last_ts": overview.get("last_ts", "—"),
    }
