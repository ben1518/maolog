"""外发审计与数据护照。

本模块只记录调用方提供的请求元数据，自身绝不发起网络请求。
实时 AI 调用接入前，需要由调用方在请求成功或失败后补写台账。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .safe_export import atomic_write_text, safe_output_path
from .v2_storage import V2Storage, format_timestamp

PURPOSE_FRAME = "画面识别"
PURPOSE_SUMMARY = "日终总结"
PURPOSE_TEST = "连接测试"
ALLOWED_PURPOSES = {PURPOSE_FRAME, PURPOSE_SUMMARY, PURPOSE_TEST}

PASSPORT_SCOPE_NOTE = (
    "本台账只覆盖本程序登记的外发，不覆盖用户手动上传到网盘、微信或其他软件的行为；"
    "已经外发的数据不能由本程序收回。"
)


def record_outbound(
    storage: V2Storage,
    ts: str | datetime,
    provider: str,
    model: str,
    byte_count: int,
    has_thumb: bool,
    purpose: str,
) -> int:
    if purpose not in ALLOWED_PURPOSES:
        raise ValueError("未知的外发用途")
    if not storage.outbound_allowed(purpose):
        raise PermissionError(f"已停止后续此类请求：{purpose}")
    try:
        byte_count = int(byte_count)
    except (TypeError, ValueError) as exc:
        raise ValueError("请求大小必须是整数") from exc
    if byte_count < 0:
        raise ValueError("请求大小不能为负数")
    return storage.record_outbound(
        format_timestamp(ts), provider, model, byte_count, has_thumb, purpose
    )


def set_future_outbound(storage: V2Storage, purpose: str, allowed: bool) -> None:
    """只改变后续请求策略，不声称能收回已经外发的数据。"""
    if purpose not in ALLOWED_PURPOSES:
        raise ValueError("未知的外发用途")
    storage.set_outbound_allowed(purpose, allowed)


def build_data_passport(
    storage: V2Storage,
    image_keep_days: int = 0,
    demo: bool = False,
    ledger_wired: bool = False,
    policy_enforcement: str = "off",
) -> dict[str, Any]:
    if image_keep_days < 0:
        raise ValueError("图片保留天数不能为负数")
    counts = storage.table_counts()
    events = storage.outbound_events(limit=200)
    recent = [
        {
            "ts": event["ts"],
            "provider": event.get("provider") or "",
            "model": event.get("model") or "",
            "bytes": event.get("bytes") or 0,
            "has_thumb": bool(event.get("has_thumb")),
            "purpose": event["purpose"],
        }
        for event in events[:20]
    ]
    return {
        "title": "数据护照（演示数据）" if demo else "数据护照",
        "demo": demo,
        "schema_version": 2,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "local_storage": {
            "location": "本机指定 SQLite 数据库",
            "snapshot_records": counts["snapshots"],
            "daily_summaries": counts["daily_summary"],
            "ai_judgments": counts["ai_use_daily"],
            "time_estimates": counts["time_estimate"],
            "outbound_policy_rows": counts["outbound_policy"],
            "outbound_records": counts["outbound_log"],
            "note": "快照记录可能包含应用名、窗口标题、截图路径；完整明细仅在本机。",
            "image_keep_days": image_keep_days,
            "image_keep_days_source": "调用方传入；本原型未读取主程序配置",
            "image_retention_text": (
                "永久保留，直到本人清理" if image_keep_days == 0 else f"保留 {image_keep_days} 天"
            ),
        },
        "outbound": {
            "recorded_total": counts["outbound_log"],
            "events_in_passport": len(events),
            "by_purpose": storage.outbound_purpose_counts(),
            "provider_models": storage.outbound_providers(),
            "recent_events": recent,
            "content_not_logged": ["提示词全文", "图片内容", "窗口标题全文", "模型原始返回"],
            "ledger_wired": ledger_wired,
            "policy_enforcement": policy_enforcement,
            "ledger_note": (
                "演示数据：只代表已登记的演示外发。"
                if demo
                else (
                    "已接入实时 AI 请求；只记录元数据，重试也按实际请求计数。"
                    if ledger_wired
                    else "本期原型尚未接入实时 AI 请求；数字只代表已登记的调用，不代表全部外发。"
                )
            ),
        },
        "outbound_policy": storage.outbound_policy_state(),
        "revocation": {
            "future": "可按用途停止后续请求",
            "local": "主程序可按日期删除快照与总结；v2 元数据清理接口尚未接入",
            "already_sent": "不可由本程序收回",
        },
        "scope_note": PASSPORT_SCOPE_NOTE,
    }


def export_data_passport(
    passport: dict[str, Any],
    output_path: Path,
    allowed_root: Path,
    overwrite: bool = False,
) -> Path:
    target = safe_output_path(output_path, ".json", allowed_root, overwrite)
    atomic_write_text(
        target, json.dumps(passport, ensure_ascii=False, indent=2)
    )
    return target
