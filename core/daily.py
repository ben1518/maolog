"""每日总结：把一天的记录压成给 AI 看的摘要，再生成复盘文案。"""

from __future__ import annotations

from datetime import datetime

from .ai_client import AIClient, AIError
from .config import Config
from .storage import Storage, format_duration

MAX_LINES = 40


def build_digest(day: str, storage: Storage, interval: int = 60) -> str:
    """构造给模型看的当日摘要文本。"""
    segments = storage.segments(day, interval=interval)
    overview = storage.overview(day, interval=interval)
    cats = storage.category_stats(day, interval=interval)
    apps = storage.app_stats(day, interval=interval, limit=6)

    if not segments:
        return ""

    lines: list[str] = [f"日期：{day}"]
    lines.append(
        f"记录区间：{overview['first_ts']} - {overview['last_ts']}，"
        f"共 {overview['records']} 条采样，累计约 {format_duration(overview['tracked_seconds'])}"
    )
    if cats:
        cat_text = "、".join(
            f"{c['category']} {int(c['ratio'] * 100)}%" for c in cats
        )
        lines.append(f"分类分布：{cat_text}")
    if apps:
        app_text = "、".join(f"{a['app']}（{format_duration(a['seconds'])}）" for a in apps)
        lines.append(f"主要应用：{app_text}")
    lines.append(f"平均专注度：{overview['avg_focus']}/5")
    lines.append("")
    lines.append("时间线：")

    picked = _compress(segments, MAX_LINES)
    for seg in picked:
        lines.append(
            f"{seg['start_text']}-{seg['end_text']} "
            f"{seg['activity'] or '未分类'}（{seg['category']}）· "
            f"{seg['detail'] or '无描述'} · {seg['duration_text']}"
        )

    return "\n".join(lines)


def generate(
    day: str,
    cfg: Config,
    storage: Storage,
    interval: int = 60,
    client: AIClient | None = None,
) -> dict:
    """调用 AI 生成当日总结，返回 summary/highlights/suggestions。"""
    digest = build_digest(day, storage, interval=interval)
    if not digest:
        raise AIError("这一天还没有可用的记录，先让它跑一会儿")

    active_client = client or AIClient(cfg)
    result = active_client.summarize_day(digest)
    storage.save_daily_summary(
        day,
        summary=result["summary"],
        highlights=result["highlights"],
        suggestions=result["suggestions"],
        model=result.get("model", ""),
    )
    return result


def fallback_summary(day: str, storage: Storage, interval: int = 60) -> dict:
    """没有 AI 时用本地统计生成一版朴素总结，保证看板不空着。"""
    overview = storage.overview(day, interval=interval)
    cats = storage.category_stats(day, interval=interval)
    segments = storage.segments(day, interval=interval)
    if not overview["records"]:
        return {
            "summary": "今天还没有采集到数据。",
            "highlights": [],
            "suggestions": [],
            "model": "local",
        }

    top_cat = cats[0] if cats else None
    parts = [
        f"今天从 {overview['first_ts']} 到 {overview['last_ts']} 共有 "
        f"{overview['records']} 条记录，累计约 {format_duration(overview['tracked_seconds'])}。"
    ]
    if top_cat:
        parts.append(
            f"占比最高的是「{top_cat['category']}」，"
            f"约 {int(top_cat['ratio'] * 100)}%；"
            f"最常做的是「{overview['top_activity']}」。"
        )
    parts.append(f"平均专注度 {overview['avg_focus']}/5。")

    highlights = []
    longest = max(segments, key=lambda s: s["seconds"], default=None)
    if longest:
        highlights.append(
            f"最长的一段专注在「{longest['activity']}」，持续 {longest['duration_text']}"
        )
    if overview["productive_seconds"]:
        highlights.append(
            f"有效产出约 {format_duration(overview['productive_seconds'])}"
        )

    suggestions = []
    if top_cat and top_cat["category"] == "娱乐" and top_cat["ratio"] > 0.35:
        suggestions.append("娱乐占比偏高，试着把连续娱乐控制在半小时以内")
    if overview["avg_focus"] and overview["avg_focus"] < 3:
        suggestions.append("专注度偏低，可以试试关掉不相关的窗口再开工")
    if not suggestions:
        suggestions.append("保持这个节奏，明天可以试着记录一下被打断的次数")

    return {
        "summary": "".join(parts),
        "highlights": highlights[:3],
        "suggestions": suggestions[:3],
        "model": "local",
    }


def _compress(segments: list[dict], limit: int) -> list[dict]:
    """时间段太多时均匀抽样，避免摘要过长。"""
    if len(segments) <= limit:
        return segments
    step = len(segments) / limit
    picked = [segments[int(i * step)] for i in range(limit)]
    return picked


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")
