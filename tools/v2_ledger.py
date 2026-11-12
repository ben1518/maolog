"""管理 v2 真实外发台账。

默认关闭；开启后 AI 请求会写入外发元数据（不含提示词/图片内容）。
本工具只操作 v2 表，不删除一期快照和截图。

    .venv/Scripts/python.exe tools/v2_ledger.py status
    .venv/Scripts/python.exe tools/v2_ledger.py enable
    .venv/Scripts/python.exe tools/v2_ledger.py policy 画面识别 off
    .venv/Scripts/python.exe tools/v2_ledger.py passport
    .venv/Scripts/python.exe tools/v2_ledger.py cleanup 2026-10-27 --yes
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config import DB_PATH, Config  # noqa: E402
from core.outbound import (  # noqa: E402
    ALLOWED_PURPOSES,
    build_data_passport,
    export_data_passport,
    set_future_outbound,
)
from core.v2_runtime import (  # noqa: E402
    enforcement_enabled,
    get_v2_storage,
    ledger_enabled,
)

EXPORT_DIR = ROOT / "data" / "v2_exports"


def _storage(cfg: Config):
    if not ledger_enabled(cfg):
        raise SystemExit("外发台账尚未开启，先执行：tools/v2_ledger.py enable")
    return get_v2_storage(cfg)


def _status(cfg: Config) -> int:
    enabled = ledger_enabled(cfg)
    print(f"台账状态：{'开启' if enabled else '关闭'}")
    print(f"按用途拦截：{'开启' if enforcement_enabled(cfg) else '关闭（只记录）'}")
    print(f"数据库：{cfg.get('v2.db_path') or DB_PATH}")
    if not enabled:
        print("说明：关闭时不会创建 v2 表，也不会写任何请求记录。")
        return 0
    storage = get_v2_storage(cfg)
    counts = storage.table_counts()
    print(f"已登记外发：{counts['outbound_log']} 条")
    print(f"AI 判断：{counts['ai_use_daily']} 条；估时：{counts['time_estimate']} 条")
    for purpose, allowed in storage.outbound_policy_state().items():
        print(f"  - {purpose}：{'允许' if allowed else '停止'}")
    return 0


def _enable(cfg: Config, enforce: bool) -> int:
    cfg.set("v2.outbound_ledger", True)
    cfg.set("v2.enforce_outbound", enforce)
    storage = get_v2_storage(cfg)
    for purpose in sorted(ALLOWED_PURPOSES):
        set_future_outbound(storage, purpose, True)
    print("外发台账已开启。")
    print("三类用途默认允许；如不希望某类请求继续外发，可用 policy 关闭。")
    print(f"按用途拦截：{'开启' if enforce else '关闭（只记录，不改变一期 AI 行为）'}")
    print("重新启动 MaoLog 后生效。")
    return 0


def _disable(cfg: Config) -> int:
    cfg.set("v2.outbound_ledger", False)
    cfg.set("v2.enforce_outbound", False)
    print("外发台账已关闭。已有台账数据仍保留，可用 cleanup 按日删除。")
    print("重新启动 MaoLog 后生效。")
    return 0


def _policy(cfg: Config, purpose: str, action: str) -> int:
    if purpose not in ALLOWED_PURPOSES:
        raise SystemExit(f"未知用途：{purpose}；可选：{'、'.join(sorted(ALLOWED_PURPOSES))}")
    storage = _storage(cfg)
    set_future_outbound(storage, purpose, action == "on")
    state = "允许" if action == "on" else "停止"
    print(f"{purpose}：{state}。")
    if not enforcement_enabled(cfg):
        print("注意：当前只记录不拦截；需 enable --enforce 后才会真正阻止请求。")
    return 0


def _passport(cfg: Config) -> int:
    storage = _storage(cfg)
    passport = build_data_passport(
        storage,
        image_keep_days=int(cfg.get("capture.keep_days", 0) or 0),
        ledger_wired=True,
        policy_enforcement="on" if enforcement_enabled(cfg) else "off",
    )
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"数据护照_实盘_{datetime.now():%Y%m%d_%H%M%S}.json"
    path = export_data_passport(passport, EXPORT_DIR / name, EXPORT_DIR, overwrite=False)
    print(f"已导出：{path}")
    print(f"登记外发：{passport['outbound']['recorded_total']} 条")
    return 0


def _cleanup(cfg: Config, day: str, confirmed: bool) -> int:
    if not confirmed:
        raise SystemExit("按日删除需要显式确认：在命令末尾加 --yes")
    storage = _storage(cfg)
    result = storage.delete_day_v2(day)
    total = sum(result.values())
    print(f"{day}：已删除 {total} 条 v2 元数据。")
    print(
        f"AI 判断 {result['ai_judgments']} 条，外发记录 {result['outbound_records']} 条，"
        f"估时 {result['time_estimates']} 条。"
    )
    print("一期快照、日终总结和截图未删除；需要时请使用主程序的按日删除。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="管理 v2 真实外发台账")
    parser.add_argument("--config", type=Path, help="指定配置文件，默认 data/config.json")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="查看状态与记录数")
    enable = sub.add_parser("enable", help="开启外发台账")
    enable.add_argument("--enforce", action="store_true", help="同时按用途开关拦截请求")
    sub.add_parser("disable", help="关闭外发台账")
    policy = sub.add_parser("policy", help="设置某类用途是否允许")
    policy.add_argument("purpose", choices=sorted(ALLOWED_PURPOSES))
    policy.add_argument("action", choices=("on", "off"))
    sub.add_parser("passport", help="导出实盘数据护照")
    cleanup = sub.add_parser("cleanup", help="删除某日 v2 元数据")
    cleanup.add_argument("day")
    cleanup.add_argument("--yes", action="store_true", help="确认删除")
    args = parser.parse_args()

    cfg = Config(args.config) if args.config else Config()
    if args.command == "status":
        return _status(cfg)
    if args.command == "enable":
        return _enable(cfg, args.enforce)
    if args.command == "disable":
        return _disable(cfg)
    if args.command == "policy":
        return _policy(cfg, args.purpose, args.action)
    if args.command == "passport":
        return _passport(cfg)
    if args.command == "cleanup":
        return _cleanup(cfg, args.day, args.yes)
    return 1


if __name__ == "__main__":
    sys.exit(main())
