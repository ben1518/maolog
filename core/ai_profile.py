"""AI 协作画像：只描述窗口先后关系，支持证据查看和学生改判。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .attest import is_ai_window, is_local_productive
from .storage import Storage
from .v2_storage import V2Storage, format_timestamp, validate_range

MODE_THINK_FIRST = "先思后问"
MODE_INTERLEAVED = "边做边问"
MODE_DIRECT = "直接要答案"
MODE_UNKNOWN = "无法判断"
MODE_NO_AI = "未见AI窗口"
OVERRIDABLE_MODES = {
    MODE_THINK_FIRST,
    MODE_INTERLEAVED,
    MODE_DIRECT,
    MODE_UNKNOWN,
    MODE_NO_AI,
}

SWITCH_WINDOW_SECONDS = 300
PRIOR_LOCAL_SECONDS = 600
PRIOR_LOOKBACK_SECONDS = 1800
DIRECT_LOOKAHEAD_SECONDS = 900
DIRECT_MIN_SAMPLES = 10
DIRECT_MIN_SPAN_SECONDS = 900
DIRECT_MIN_COVERAGE = 0.7

AI_LIMITATIONS = [
    "规则只根据电脑窗口的先后关系作启发式判断，不衡量思维能力。",
    "手机端、其他设备和未被识别的 AI 工具不在判断范围内。",
    "学生可以查看依据并修改判断；修改只影响本机记录。",
]


def _rows_with_ts(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    valid = []
    dropped = 0
    for row in rows:
        item = dict(row)
        try:
            item["ts"] = format_timestamp(item["ts"])
        except (KeyError, ValueError):
            dropped += 1
            continue
        valid.append(item)
    return valid, dropped


def _label(row: dict[str, Any]) -> str:
    if is_ai_window(row):
        return "ai"
    if is_local_productive(row):
        return "local"
    return "other"


def _runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for row in rows:
        row_time = datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S")
        label = _label(row)
        if runs and runs[-1]["label"] == label:
            runs[-1]["last"] = row_time
            continue
        runs.append({"label": label, "first": row_time, "last": row_time})
    return runs


def _alternations(runs: list[dict[str, Any]]) -> tuple[int, list[dict[str, str]]]:
    """计算 AI 与本地窗口在五分钟内的切换，允许中间夹着其他窗口。"""
    count = 0
    segments: list[dict[str, str]] = []
    previous_relevant: dict[str, Any] | None = None
    for run in runs:
        if run["label"] == "other":
            continue
        if previous_relevant and {previous_relevant["label"], run["label"]} == {
            "ai",
            "local",
        }:
            gap = (run["first"] - previous_relevant["last"]).total_seconds()
            if gap <= SWITCH_WINDOW_SECONDS:
                count += 1
                segments.append(
                    {
                        "from": previous_relevant["last"].strftime("%H:%M"),
                        "to": run["first"].strftime("%H:%M"),
                    }
                )
        previous_relevant = run
    return count, segments


def _prior_local_seconds(rows: list[dict[str, Any]], interval: int) -> int:
    """只统计首个 AI 出现前的本地产出，允许中途短暂切到浏览器。"""
    first_ai = next(
        (row for row in rows if is_ai_window(row)),
        None,
    )
    if first_ai is None:
        return 0
    first_ai_time = datetime.strptime(first_ai["ts"], "%Y-%m-%d %H:%M:%S")
    lookback_start = first_ai_time - timedelta(seconds=PRIOR_LOOKBACK_SECONDS)
    total = 0
    previous_time: datetime | None = None
    for row in rows:
        row_time = datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S")
        if row_time >= first_ai_time:
            break
        if previous_time and row_time - previous_time > timedelta(seconds=interval * 3):
            total = 0
        if row_time >= lookback_start and is_local_productive(row):
            total += interval
        previous_time = row_time
    return total


def analyze_collaboration(
    storage: Storage,
    task_context: str,
    start_ts: str,
    end_ts: str,
    interval: int = 60,
) -> dict[str, Any]:
    if interval <= 0:
        raise ValueError("采样间隔必须大于 0")
    if not task_context.strip():
        raise ValueError("任务上下文不能为空")
    start, end = validate_range(start_ts, end_ts)
    selected_rows, dropped = _rows_with_ts(storage.snapshots_between(start, end))
    ai_rows = [row for row in selected_rows if is_ai_window(row)]
    ratio = len(ai_rows) / len(selected_rows) if selected_rows else 0.0
    runs = _runs(selected_rows)
    switches, switch_segments = _alternations(runs)
    prior_seconds = _prior_local_seconds(selected_rows, interval)
    notes: list[str] = []

    # 直接要答案要把观察窗向后延伸 15 分钟，否则“刚好截到 AI 结束”会误判。
    end_time = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
    lookahead_end = end_time + timedelta(seconds=DIRECT_LOOKAHEAD_SECONDS)
    lookahead_rows, lookahead_dropped = _rows_with_ts(
        storage.snapshots_between(
            end, lookahead_end.strftime("%Y-%m-%d %H:%M:%S")
        )
    )
    local_within_15min = False
    if ai_rows:
        last_ai = max(datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S") for row in ai_rows)
        # 必须同时看范围内和范围后：AI 结束后马上动笔常发生在同一个选择区间里。
        local_within_15min = any(
            is_local_productive(row)
            and timedelta(0)
            <= datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S") - last_ai
            <= timedelta(seconds=DIRECT_LOOKAHEAD_SECONDS)
            for row in selected_rows + lookahead_rows
        )
    ai_span_seconds = 0
    ai_active_seconds = len(ai_rows) * interval
    if ai_rows:
        first_ai = datetime.strptime(ai_rows[0]["ts"], "%Y-%m-%d %H:%M:%S")
        last_ai = datetime.strptime(ai_rows[-1]["ts"], "%Y-%m-%d %H:%M:%S")
        ai_span_seconds = int((last_ai - first_ai).total_seconds()) + interval

    expected_samples = max(
        1,
        int((end_time - datetime.strptime(start, "%Y-%m-%d %H:%M:%S")).total_seconds() / interval)
        + 1,
    )
    coverage = min(1.0, len(selected_rows) / expected_samples)

    direct_ready = (
        ratio >= 0.8
        and len(ai_rows) >= DIRECT_MIN_SAMPLES
        and ai_active_seconds >= DIRECT_MIN_SPAN_SECONDS
        and coverage >= DIRECT_MIN_COVERAGE
        and not local_within_15min
    )
    if not selected_rows:
        mode = MODE_UNKNOWN
        notes.append("所选范围没有可用的行为记录")
    elif not ai_rows:
        mode = MODE_NO_AI
        notes.append("未发现已知的电脑端 AI 窗口，但不能据此推断没有使用 AI")
    elif direct_ready:
        mode = MODE_DIRECT
    elif switches >= 3:
        mode = MODE_INTERLEAVED
    elif prior_seconds >= PRIOR_LOCAL_SECONDS:
        mode = MODE_THINK_FIRST
    else:
        mode = MODE_UNKNOWN
        notes.append("窗口序列未满足三种模式的判据")
    segments = [
        {
            "kind": {"ai": "AI", "local": "本地产出", "other": "其他"}[run["label"]],
            "start": run["first"].strftime("%H:%M"),
            "end": run["last"].strftime("%H:%M"),
        }
        for run in runs
    ]
    evidence = {
        "sample_count": len(selected_rows),
        "dropped_rows": dropped + lookahead_dropped,
        "coverage": round(coverage, 4),
        "ai_sample_count": len(ai_rows),
        "ai_sample_ratio": round(ratio, 4),
        "ai_span_seconds": ai_span_seconds,
        "ai_active_seconds": ai_active_seconds,
        "alternations_within_5min": switches,
        "alternation_segments": switch_segments,
        "prior_local_seconds": prior_seconds,
        "has_10min_prior_local_work": prior_seconds >= PRIOR_LOCAL_SECONDS,
        "local_within_15min_after_ai": local_within_15min,
        "thresholds": {
            "switch_window_seconds": SWITCH_WINDOW_SECONDS,
            "prior_local_seconds": PRIOR_LOCAL_SECONDS,
            "prior_lookback_seconds": PRIOR_LOOKBACK_SECONDS,
            "direct_lookahead_seconds": DIRECT_LOOKAHEAD_SECONDS,
            "direct_min_samples": DIRECT_MIN_SAMPLES,
            "direct_min_span_seconds": DIRECT_MIN_SPAN_SECONDS,
            "direct_min_coverage": DIRECT_MIN_COVERAGE,
        },
        "segments": segments,
        "notes": notes,
        "limitations": AI_LIMITATIONS.copy(),
    }
    return {
        "day": start[:10],
        "task_context": task_context.strip(),
        "start_ts": start,
        "end_ts": end,
        "mode": mode,
        "evidence": evidence,
        "overridden": 0,
    }


def save_collaboration(
    storage: V2Storage, judgment: dict[str, Any]
) -> tuple[int, bool]:
    if judgment.get("mode") not in OVERRIDABLE_MODES | {MODE_NO_AI}:
        raise ValueError("未知的 AI 协作模式")
    return storage.save_ai_judgment(judgment)


def override_collaboration(
    storage: V2Storage, judgment_id: int, new_mode: str
) -> dict[str, Any]:
    if new_mode not in OVERRIDABLE_MODES:
        raise ValueError("只能改为三种协作模式或无法判断")
    storage.override_ai_mode(judgment_id, new_mode)
    result = storage.get_ai_judgment(judgment_id)
    if result is None:
        raise ValueError("找不到要修改的判断")
    return result


def weekly_summary(judgments: list[dict[str, Any]]) -> dict[str, Any]:
    """只总结同一 ISO 周，避免跨周累积成人格标签。"""
    if not judgments:
        return {"sample_count": 0, "modes": {}, "note": "本周样本不足"}
    weeks = {
        datetime.strptime(item["day"], "%Y-%m-%d").isocalendar()[:2]
        for item in judgments
    }
    if len(weeks) != 1:
        raise ValueError("周度总结不能混入不同 ISO 周的数据")
    modes: dict[str, int] = {}
    for item in judgments:
        mode = item.get("mode") or MODE_UNKNOWN
        modes[mode] = modes.get(mode, 0) + 1
    return {
        "sample_count": len(judgments),
        "modes": modes,
        "note": "仅描述本周出现的模式，不形成跨周个人标签",
    }
