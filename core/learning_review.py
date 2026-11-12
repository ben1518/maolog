"""把行为序列解读成学习复盘。

输入是 `core.attest.build_process_report` 产出的阶段序列，输出是给人看的
三件事：这段时间的节奏好在哪、卡在哪、下次可以怎么调。

这里只做解读，不新增采集，也不判断努力程度或内容质量。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

PREPARE_STAGES = {"阅读", "查阅"}
PRODUCE_STAGES = {"写作", "编程"}
ASK_STAGES = {"AI 对话"}
LEARN_STAGES = PREPARE_STAGES | PRODUCE_STAGES | ASK_STAGES | {"学习"}

# 中断超过这个长度就不再算「被打断」，而是「离开了」。
INTERRUPT_LIMIT_MINUTES = 20
# 低于这个时长的连续投入不单独拿出来说，避免把 3 分钟也夸成专注。
FOCUS_FLOOR_MINUTES = 20
# 动手前准备超过这个时长，才提示「启动偏慢」。
STARTUP_LIMIT_MINUTES = 25
# 每小时回访超过这个次数才算卡点。
REVISIT_LIMIT_PER_HOUR = 4.0

MINUTE = 60


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def _run_minutes(run: dict[str, Any], interval: int) -> int:
    """一个阶段段的时长：末次记录减首次记录，再补一个采样间隔。"""
    try:
        span = (_parse(run["end"]) - _parse(run["start"])).total_seconds()
    except (KeyError, ValueError):
        span = 0
    return max(0, int(round((span + interval) / MINUTE)))


def _clock(ts: str) -> str:
    return ts[11:16]


def _ratio(part: int, whole: int) -> float:
    return round(part / whole, 3) if whole else 0.0


def analyze_learning(report: dict[str, Any], interval: int = 60) -> dict[str, Any]:
    """从过程报告里提炼学习节奏。没有记录时返回一份空复盘，不编造结论。"""
    runs = report.get("runs") or []
    metrics = report.get("metrics") or {}
    if not runs:
        return {
            "headline": "这一段时间没有可用的记录",
            "summary": "没有记录就无法复盘。可以先确认这段时间程序是否在运行。",
            "strengths": [],
            "frictions": [],
            "suggestions": [],
            "metrics": _empty_metrics(),
            "has_data": False,
        }

    durations = [_run_minutes(run, interval) for run in runs]
    active = sum(durations)

    stage_minutes: dict[str, int] = {}
    for run, minutes in zip(runs, durations):
        stage = str(run.get("stage") or "其他")
        stage_minutes[stage] = stage_minutes.get(stage, 0) + minutes

    prepare = sum(stage_minutes.get(stage, 0) for stage in PREPARE_STAGES)
    produce = sum(stage_minutes.get(stage, 0) for stage in PRODUCE_STAGES)
    ask = sum(stage_minutes.get(stage, 0) for stage in ASK_STAGES)
    learn = sum(stage_minutes.get(stage, 0) for stage in LEARN_STAGES)

    # 连续学习段：中间没有「其他」阶段，也没有超出采样窗口的空档，才算一段完整投入。
    focus_minutes = 0
    focus_span: tuple[str, str] | None = None
    current_minutes = 0
    current_start: str | None = None
    current_end: str | None = None
    for run, minutes in zip(runs, durations):
        stage = str(run.get("stage") or "")
        broken = False
        if current_end is not None:
            try:
                if (_parse(run["start"]) - _parse(current_end)).total_seconds() > interval * 3:
                    broken = True
            except ValueError:
                broken = True
        if stage not in LEARN_STAGES or broken:
            current_minutes = 0
            current_start = None
            current_end = None
        if stage in LEARN_STAGES:
            if current_start is None:
                current_start = run["start"]
            current_minutes += minutes
            current_end = run["end"]
            if current_minutes > focus_minutes:
                focus_minutes = current_minutes
                focus_span = (current_start, current_end)
    if focus_minutes < FOCUS_FLOOR_MINUTES:
        focus_minutes = 0
        focus_span = None

    # 中断：两个学习段之间夹着一段「其他」，且离开时间不算太长。
    interruptions = 0
    away_minutes = 0
    away_long = 0
    for index in range(1, len(runs) - 1):
        previous, current, following = runs[index - 1], runs[index], runs[index + 1]
        if str(current.get("stage") or "") != "其他":
            continue
        if str(previous.get("stage") or "") not in LEARN_STAGES:
            continue
        if str(following.get("stage") or "") not in LEARN_STAGES:
            continue
        minutes = durations[index]
        if minutes <= INTERRUPT_LIMIT_MINUTES:
            interruptions += 1
            away_minutes += minutes
        else:
            away_long += 1
            away_minutes += minutes

    # 启动：第一条记录到第一次真正动手之间隔了多久。
    startup_minutes: int | None = None
    first_produce: str | None = None
    for run in runs:
        if str(run.get("stage") or "") in PRODUCE_STAGES:
            first_produce = run["start"]
            try:
                startup_minutes = max(
                    0, int((_parse(first_produce) - _parse(runs[0]["start"])).total_seconds() // MINUTE)
                )
            except ValueError:
                startup_minutes = None
            break

    revisits = int(metrics.get("document_revisits") or 0)
    revisit_rate = round(revisits / (active / MINUTE), 2) if active else 0.0
    switches = int(metrics.get("stage_switches") or 0)

    values = {
        "active_minutes": active,
        "learn_minutes": learn,
        "prepare_minutes": prepare,
        "produce_minutes": produce,
        "ai_minutes": ask,
        "produce_ratio": _ratio(produce, active),
        "focus_minutes": focus_minutes,
        "focus_start": _clock(focus_span[0]) if focus_span else None,
        "focus_end": _clock(focus_span[1]) if focus_span else None,
        "startup_minutes": startup_minutes,
        "first_produce_at": _clock(first_produce) if first_produce else None,
        "interruptions": interruptions,
        "away_minutes": away_minutes,
        "away_long": away_long,
        "revisits": revisits,
        "revisit_rate": revisit_rate,
        "stage_switches": switches,
        "dominant_stage": max(stage_minutes, key=stage_minutes.get) if stage_minutes else None,
        "stage_minutes": stage_minutes,
    }

    strengths = _pick_strengths(values)
    frictions = _pick_frictions(values)
    suggestions = _pick_suggestions(values, frictions)
    headline, summary = _headline(values, runs, strengths, frictions, report.get("data_gaps") or [])

    return {
        "headline": headline,
        "summary": summary,
        "strengths": strengths,
        "frictions": frictions,
        "suggestions": suggestions,
        "metrics": values,
        "has_data": True,
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "active_minutes": 0,
        "learn_minutes": 0,
        "prepare_minutes": 0,
        "produce_minutes": 0,
        "ai_minutes": 0,
        "produce_ratio": 0.0,
        "focus_minutes": 0,
        "focus_start": None,
        "focus_end": None,
        "startup_minutes": None,
        "first_produce_at": None,
        "interruptions": 0,
        "away_minutes": 0,
        "away_long": 0,
        "revisits": 0,
        "revisit_rate": 0.0,
        "stage_switches": 0,
        "dominant_stage": None,
        "stage_minutes": {},
    }


def _pick_strengths(values: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if values["focus_minutes"]:
        items.append(
            {
                "kind": "focus",
                "title": f"最长的一段连续了 {values['focus_minutes']} 分钟",
                "detail": (
                    f"从 {values['focus_start']} 到 {values['focus_end']}，"
                    "中间没有切换到非学习活动。这段时间的注意力是连着的。"
                ),
            }
        )
    if values["produce_ratio"] >= 0.5:
        items.append(
            {
                "kind": "produce",
                "title": f"动手时间占 {round(values['produce_ratio'] * 100)}%",
                "detail": "大部分记录落在写作或编程上，说明是真的在产出，不只是准备。",
            }
        )
    if values["ai_minutes"] and values["produce_minutes"] >= values["ai_minutes"]:
        items.append(
            {
                "kind": "ai_restraint",
                "title": "AI 用得比较克制",
                "detail": (
                    f"AI 对话约 {values['ai_minutes']} 分钟，"
                    f"自己动手约 {values['produce_minutes']} 分钟，主要工作仍在自己这边完成。"
                ),
            }
        )
    return items[:2]


def _pick_frictions(values: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if values["interruptions"] >= 3:
        average = round(values["away_minutes"] / max(1, values["interruptions"] + values["away_long"]))
        items.append(
            {
                "kind": "interrupt",
                "title": f"被打断 {values['interruptions']} 次",
                "detail": (
                    f"学习段之间夹进了 {values['away_minutes']} 分钟的其他活动，"
                    f"平均每次 {average} 分钟。频繁切换会让重新进入状态变慢。"
                ),
            }
        )
    elif values["away_long"]:
        items.append(
            {
                "kind": "away",
                "title": f"中途离开 {values['away_long']} 次",
                "detail": (
                    f"这些离开共占 {values['away_minutes']} 分钟，"
                    "单次超过 20 分钟的部分已按离开处理，不计入打断。"
                ),
            }
        )
    if values["startup_minutes"] is not None and values["startup_minutes"] >= STARTUP_LIMIT_MINUTES:
        items.append(
            {
                "kind": "startup",
                "title": f"动手前准备了 {values['startup_minutes']} 分钟",
                "detail": (
                    f"第一次进入写作或编程是 {values['first_produce_at']}。"
                    "准备时间长不一定不好，但如果每次都要这么久，容易停在「还在看资料」这一步。"
                ),
            }
        )
    if 0 < values["produce_ratio"] < 0.3:
        items.append(
            {
                "kind": "produce_low",
                "title": f"动手只占 {round(values['produce_ratio'] * 100)}%",
                "detail": (
                    f"记录里 {values['prepare_minutes']} 分钟在阅读和查阅，"
                    f"{values['produce_minutes']} 分钟在写作或编程。"
                ),
            }
        )
    if values["revisit_rate"] >= REVISIT_LIMIT_PER_HOUR:
        items.append(
            {
                "kind": "revisit",
                "title": f"每小时回访同一文档 {values['revisit_rate']:g} 次",
                "detail": (
                    "回访密集通常意味着两种情况之一：资料没放在手边，"
                    "或者写到一半需要反复核对同一个地方。"
                ),
            }
        )
    return items[:3]


def _pick_suggestions(
    values: dict[str, Any], frictions: list[dict[str, str]]
) -> list[dict[str, str]]:
    picked: list[dict[str, str]] = []
    kinds = {item.get("kind") for item in frictions}

    if "interrupt" in kinds:
        picked.append(
            {
                "title": "把这段学习放进一个不容易被打断的时段",
                "detail": "开始前关掉消息通知，或者把手机放到够不着的地方。一次打断的代价不只是那几分钟。",
            }
        )
    if "startup" in kinds:
        picked.append(
            {
                "title": "先写三行，再回头补资料",
                "detail": "下次开工先花五分钟列出三条要点，直接开始写。缺什么边写边补，比先看完所有资料更快进入状态。",
            }
        )
    if "revisit" in kinds:
        picked.append(
            {
                "title": "开工前把要用的资料一次开齐",
                "detail": "把 PDF、课件、参考网页放在同一个窗口组里，减少来回找的时间。",
            }
        )
    if "produce_low" in kinds:
        picked.append(
            {
                "title": "把任务拆成一个 25 分钟能做完的小块",
                "detail": "先做出一个能看的粗版本，再改。准备阶段没有明确的结束条件，很容易一直延长。",
            }
        )
    if "away" in kinds:
        picked.append(
            {
                "title": "把长任务切成两段",
                "detail": "一次坐太久容易中途走开。与其硬撑，不如事先留出休息，回来再接着做。",
            }
        )
    if not picked:
        if values["produce_minutes"]:
            picked.append(
                {
                    "title": "把这个时段固定下来",
                    "detail": "这次的节奏是稳的。同样的时间段再用几次，比较容易形成习惯。",
                }
            )
        else:
            picked.append(
                {
                    "title": "先给这段时间定一个具体产出",
                    "detail": "比如「写出方法部分的第一段」。有明确产出，记录里才看得到动手的痕迹。",
                }
            )
    return picked[:2]


def _headline(
    values: dict[str, Any],
    runs: list[dict[str, Any]],
    strengths: list[dict[str, str]],
    frictions: list[dict[str, str]],
    gaps: list[dict[str, Any]],
) -> tuple[str, str]:
    active = values["active_minutes"]
    produce = values["produce_minutes"]
    first, last = _clock(runs[0]["start"]), _clock(runs[-1]["end"])

    if produce:
        headline = f"有记录的 {active} 分钟里，动手时间 {produce} 分钟"
    else:
        headline = f"有记录的 {active} 分钟里，还没有进入动手阶段"

    parts = [f"从 {first} 到 {last}，"]
    if values["dominant_stage"]:
        parts.append(f"占比最多的是{values['dominant_stage']}。")
    if gaps:
        parts.append(f"中间有 {len(gaps)} 段没有记录的时间，已分开计算。")
    if strengths:
        parts.append(f"{strengths[0]['title']}。")
    if frictions:
        parts.append(f"需要留意的是：{frictions[0]['title']}。")
    else:
        parts.append("没有明显的卡点。")
    return headline, "".join(parts)
