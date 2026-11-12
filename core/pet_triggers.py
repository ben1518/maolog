"""蘑菇小精灵关怀气泡触发引擎。

根据最近的采样、当日专注趋势与时间节点，产生非侵入式的手绘气泡关怀，
包含久坐关怀、高专注夸夸、分心轻提醒与温情问候。内置全局与场景级防打扰冷却机制。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, Optional

# 场景防打扰冷却记录 (场景名 -> 上次触发时间戳)
_LAST_TRIGGER_TIMES: Dict[str, float] = {}
_LAST_GLOBAL_TRIGGER: float = 0.0
_LAST_INTERACTIVE_TEXT: str = ""

# 全局气泡最小间隔（秒）：至少 15 分钟才可能主动冒一次气泡，避免干扰
MIN_GLOBAL_INTERVAL = 900
# 同类气泡最小间隔（秒）：40 分钟
MIN_SCENE_INTERVAL = 2400


def evaluate_pet_care(
    storage,
    day_str: str,
    interval: int = 60,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """评估当前是否需要弹出蘑菇小精灵关怀气泡。
    
    返回字典结构:
      - text: 气泡手绘文案
      - tone: 情绪类型 ("praise", "care", "remind", "greet")
      - duration_ms: 气泡显示时长（毫秒，默认 7000ms）
    若不满足触发条件或处于防打扰冷却期，返回 None。
    """
    global _LAST_GLOBAL_TRIGGER, _LAST_INTERACTIVE_TEXT
    now_ts = time.time()

    if not force:
        if now_ts - _LAST_GLOBAL_TRIGGER < MIN_GLOBAL_INTERVAL:
            return None

    now = datetime.now()
    now_hour = now.hour

    segments = storage.segments(day_str, interval=interval)
    overview = storage.overview(day_str, interval=interval)
    tracked_seconds = overview.get("tracked_seconds", 0)
    productive_seconds = overview.get("productive_seconds", 0)
    records_count = overview.get("records", 0)
    top_act = overview.get("top_activity") or ""

    # 如果用户主动点击小猫（force=True），构建数据感知+情绪关怀候选池并轮换展示
    if force:
        import random
        candidates = []
        if now_hour >= 23 or now_hour < 5:
            candidates.append({
                "trigger": "night",
                "tone": "care",
                "text": "夜深啦，把今天的学习收获梳理好，别熬太晚哦 🌙",
                "duration_ms": 6500,
            })
        if records_count > 0:
            mins = max(1, tracked_seconds // 60)
            candidates.append({
                "trigger": "stats",
                "tone": "praise",
                "text": f"今天蘑菇小精灵已经陪你记录了 {mins} 分钟（{records_count} 次采样）啦 🍄",
                "duration_ms": 6500,
            })
        if top_act:
            candidates.append({
                "trigger": "activity",
                "tone": "greet",
                "text": f"看你今天主要在「{top_act}」，节奏稳稳的，继续加油 ✨",
                "duration_ms": 6500,
            })
        candidates.extend([
            {
                "trigger": "interactive",
                "tone": "greet",
                "text": "蘑菇小精灵在旁边陪你自习，点「成就便签」可以生成今日手帐卡哦 🍄",
                "duration_ms": 6500,
            },
            {
                "trigger": "interactive",
                "tone": "care",
                "text": "保持专注的同时，也别忘了眨眨眼、喝口温水放松肩颈 🍵",
                "duration_ms": 6500,
            },
            {
                "trigger": "interactive",
                "tone": "praise",
                "text": "每一段投入的时间都会发光，小精灵替你守着进度条 🍄",
                "duration_ms": 6500,
            },
        ])
        filtered = [c for c in candidates if c["text"] != _LAST_INTERACTIVE_TEXT] or candidates
        chosen = random.choice(filtered)
        _LAST_INTERACTIVE_TEXT = chosen["text"]
        return chosen

    # 1. 检查久坐/超长专注（持续专注 >= 70 分钟且没有休息）
    consecutive_work_sec = 0
    for seg in reversed(segments):
        if seg.get("category") in ("工作", "学习"):
            consecutive_work_sec += seg.get("seconds", 0)
        else:
            break

    if consecutive_work_sec >= 70 * 60:
        if force or (now_ts - _LAST_TRIGGER_TIMES.get("sedentary", 0) >= MIN_SCENE_INTERVAL):
            mins = consecutive_work_sec // 60
            _LAST_TRIGGER_TIMES["sedentary"] = now_ts
            _LAST_GLOBAL_TRIGGER = now_ts
            return {
                "trigger": "sedentary",
                "tone": "care",
                "text": f"主人已经连续专注 {mins} 分钟啦，活动下肩颈、喝口水吧 🍵",
                "duration_ms": 7500,
            }

    # 2. 检查最近刚完成一段高专注心流（专注度 >= 4 且持续 >= 35 分钟）
    if segments:
        last_seg = segments[-1]
        sec = last_seg.get("seconds", 0)
        focus = last_seg.get("focus_score", 0)
        cat = last_seg.get("category", "")
        if cat in ("工作", "学习") and focus >= 4 and sec >= 35 * 60:
            if force or (now_ts - _LAST_TRIGGER_TIMES.get("flow", 0) >= MIN_SCENE_INTERVAL):
                mins = sec // 60
                _LAST_TRIGGER_TIMES["flow"] = now_ts
                _LAST_GLOBAL_TRIGGER = now_ts
                return {
                    "trigger": "flow",
                    "tone": "praise",
                    "text": f"太赞了！刚才这趟 {mins} 分钟的深度推进超扎实 🍄",
                    "duration_ms": 7000,
                }

    # 3. 检查白天摸鱼/分心偏离（最近 20 分钟连续处于娱乐状态）
    if 9 <= now_hour <= 22 and segments:
        consecutive_ent_sec = 0
        for seg in reversed(segments):
            if seg.get("category") == "娱乐":
                consecutive_ent_sec += seg.get("seconds", 0)
            else:
                break
        if consecutive_ent_sec >= 20 * 60:
            if force or (now_ts - _LAST_TRIGGER_TIMES.get("distracted", 0) >= MIN_SCENE_INTERVAL):
                _LAST_TRIGGER_TIMES["distracted"] = now_ts
                _LAST_GLOBAL_TRIGGER = now_ts
                return {
                    "trigger": "distracted",
                    "tone": "remind",
                    "text": "小精灵看你刷了一阵子视频啦，今天的主线目标继续冲一把？🍄",
                    "duration_ms": 7000,
                }

    # 4. 产出里程碑致意（达到 3h 或 5h）
    prod_hrs = productive_seconds / 3600.0
    if prod_hrs >= 3.0:
        if force or (now_ts - _LAST_TRIGGER_TIMES.get("milestone", 0) >= 7200):
            _LAST_TRIGGER_TIMES["milestone"] = now_ts
            _LAST_GLOBAL_TRIGGER = now_ts
            return {
                "trigger": "milestone",
                "tone": "praise",
                "text": f"今天已累计扎实推进 {prod_hrs:.1f} 小时，今天也很给力 ✨",
                "duration_ms": 7000,
            }

    # 5. 夜深关怀（23:00 以后）
    if now_hour >= 23 or now_hour < 2:
        if force or (now_ts - _LAST_TRIGGER_TIMES.get("night", 0) >= 3600):
            _LAST_TRIGGER_TIMES["night"] = now_ts
            _LAST_GLOBAL_TRIGGER = now_ts
            return {
                "trigger": "night",
                "tone": "care",
                "text": "夜深啦，把今天的学习收获梳理好，别熬太晚哦 🌙",
                "duration_ms": 7500,
            }

    # 如果 force=True（比如用户点击小猫交互互动）
    if force:
        greetings = [
            "蘑菇小精灵在旁边陪你自习，今天也要加油呀 🍄",
            "保持专注，每一小步都在把你带向远方 ✨",
            "累了就看看窗外，小精灵替你守着进度条 🍄",
        ]
        import random
        return {
            "trigger": "interactive",
            "tone": "greet",
            "text": random.choice(greetings),
            "duration_ms": 6000,
        }

    return None
