"""时间感知校准：只帮助本人对照“计划”和“实际”，不做打卡与排名。"""

from __future__ import annotations

from typing import Any

from .storage import Storage
from .v2_storage import V2Storage, parse_day

MINUTES_PER_DAY = 24 * 60


def _validate_minutes(value: int) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("分钟数必须是整数") from exc
    if minutes < 0 or minutes > MINUTES_PER_DAY:
        raise ValueError("分钟数必须在 0 到 1440 之间")
    return minutes


def set_plan(storage: V2Storage, day: str, minutes: int) -> None:
    parse_day(day)
    storage.set_planned_minutes(day, _validate_minutes(minutes))


def set_actual(storage: V2Storage, day: str, minutes: int) -> None:
    parse_day(day)
    storage.set_actual_minutes(day, _validate_minutes(minutes))


def productive_minutes_from_storage(
    storage: Storage, day: str, interval: int = 60
) -> int:
    """统计一期标记为有产出的学习与工作时长，避免漏掉写作和编程。"""
    parse_day(day)
    if interval <= 0:
        raise ValueError("采样间隔必须大于 0")
    overview = storage.overview(day, interval=interval)
    return int(overview["productive_seconds"]) // 60


def compare_estimate(storage: V2Storage, day: str) -> dict[str, Any]:
    parse_day(day)
    record = storage.get_time_estimate(day) or {}
    planned = record.get("planned_minutes")
    actual = record.get("actual_minutes")
    if planned is None and actual is None:
        return {"day": day, "status": "缺少估时和实际", "planned_minutes": None,
                "actual_minutes": None, "delta_minutes": None, "observation": ""}
    if planned is None:
        return {"day": day, "status": "缺少估时", "planned_minutes": None,
                "actual_minutes": actual, "delta_minutes": None, "observation": ""}
    if actual is None:
        return {"day": day, "status": "缺少实际", "planned_minutes": planned,
                "actual_minutes": None, "delta_minutes": None, "observation": ""}

    planned_value = int(planned)
    actual_value = int(actual)
    delta = planned_value - actual_value
    if actual_value == 0:
        if planned_value == 0:
            status = "一致"
            observation = "估时与实际都为零。"
        else:
            status = "高于实际"
            observation = "估了时间，但没有统计到学习类活动。"
    elif planned_value == 0:
        status = "低于实际"
        observation = "预计不学习，实际出现了学习活动。"
    elif delta > max(15, actual_value * 0.2):
        status = "高于实际"
        observation = "这次估时偏高，实际投入少于计划。"
    elif delta < -max(15, actual_value * 0.2):
        status = "低于实际"
        observation = "这次估时偏低，实际投入多于计划。"
    else:
        status = "接近"
        observation = "这次估时和实际比较接近。"
    return {
        "day": day,
        "status": status,
        "planned_minutes": planned_value,
        "actual_minutes": actual_value,
        "delta_minutes": delta,
        "observation": observation,
    }


def trend(storage: V2Storage, limit: int = 14) -> dict[str, Any]:
    records = list(reversed(storage.list_time_estimates(limit=limit)))
    comparisons = [
        compare_estimate(storage, item["day"])
        for item in records
        if item.get("planned_minutes") is not None and item.get("actual_minutes") is not None
    ]
    if not comparisons:
        return {
            "sample_count": 0,
            "high": 0,
            "low": 0,
            "near": 0,
            "same": 0,
            "observation": "还没有可对照的记录。",
        }
    counts = {"高于实际": 0, "低于实际": 0, "接近": 0, "一致": 0}
    for item in comparisons:
        if item["status"] in counts:
            counts[item["status"]] += 1
    if counts["高于实际"] > counts["低于实际"]:
        observation = "多数记录里估时高于实际，可以试着把计划写小一点。"
    elif counts["低于实际"] > counts["高于实际"]:
        observation = "多数记录里估时低于实际，任务可能比预想更花时间。"
    elif counts["高于实际"] == 0 and counts["低于实际"] == 0:
        observation = "目前多数记录估时接近实际。"
    else:
        observation = "估时偏高和偏低的天数接近，暂看不出固定方向。"
    return {
        "sample_count": len(comparisons),
        "high": counts["高于实际"],
        "low": counts["低于实际"],
        "near": counts["接近"],
        "same": counts["一致"],
        "observation": observation,
    }
