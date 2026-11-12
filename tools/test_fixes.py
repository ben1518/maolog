"""专项测试：验证本次加固的五个点。

    .venv/Scripts/python.exe tools/test_fixes.py

重点不是"功能能用"，而是"危险操作在异常输入下会不会越界"。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import mock_ai_server  # noqa: E402
from core import housekeeping  # noqa: E402
from core.ai_client import (  # noqa: E402
    MAX_TOKENS_SUMMARY,
    AIClient,
    AIError,
    AIRateLimited,
    _extract_json,
)
from core.config import Config  # noqa: E402
from core.storage import Storage  # noqa: E402

PASS = "✅"
FAIL = "❌"
ok_all = True


def check(name: str, condition: bool, detail: str = "") -> None:
    global ok_all
    if not condition:
        ok_all = False
    print(f"{PASS if condition else FAIL} {name}" + (f"  ({detail})" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------- 1. max_tokens


def test_max_tokens() -> None:
    section("1. 总结请求的 max_tokens")
    server = mock_ai_server.start(18091)

    cfg = Config(ROOT / "data" / "test_fix_config.json")
    cfg.set("ai.provider", "openai", save=False)
    cfg.set("ai.base_url", "http://127.0.0.1:18091/v1", save=False)
    cfg.set("ai.api_key", "k", save=False)
    cfg.set("ai.model", "m", save=False)

    client = AIClient(cfg)
    captured: dict = {}
    original = client._session.post

    def spy(*args, **kwargs):
        captured.update(kwargs.get("json") or {})
        return original(*args, **kwargs)

    client._session.post = spy  # type: ignore[assignment]
    client.summarize_day("日期：2026-10-25\n时间线：09:00-10:00 编程开发")
    client._session.post = original  # type: ignore[assignment]

    check("总结请求带了 1500 token", captured.get("max_tokens") == MAX_TOKENS_SUMMARY,
          f"实际 {captured.get('max_tokens')}")
    server.shutdown()


# ------------------------------------------------------------ 2. 截断 JSON 修复


def test_json_repair() -> None:
    section("2. 截断 JSON 修复")
    complete = '{"summary":"今天在写代码","highlights":["a"],"suggestions":["b"]}'
    check("完整 JSON 正常解析", (_extract_json(complete) or {}).get("summary") == "今天在写代码")

    truncated = '{"summary":"今天主要在写代码，下午看了一段视频，整体节奏还可以'
    repaired = _extract_json(truncated)
    check("截断的字符串能被补全", repaired is not None and "今天主要在写代码" in str(repaired.get("summary")),
          str(repaired)[:60] if repaired else "None")

    half_array = '{"summary":"写代码","highlights":["专注两小时","完成看板'
    repaired2 = _extract_json(half_array)
    check("截断的数组能被补全", repaired2 is not None and repaired2.get("summary") == "写代码",
          str(repaired2)[:60] if repaired2 else "None")

    fenced = '```json\n{"summary":"x"}\n```'
    check("代码块包裹能剥掉", (_extract_json(fenced) or {}).get("summary") == "x")

    check("纯文字返回 None", _extract_json("抱歉我不理解") is None)
    check("空串返回 None", _extract_json("") is None)
    check("彻底乱码返回 None", _extract_json("{没有引号的垃圾内容") is None)


# --------------------------------------------------------------- 3. 清理安全边界


def test_housekeeping() -> None:
    section("3. 过期截图清理的安全边界")
    tmp = Path(tempfile.mkdtemp(prefix="mao_clean_"))
    shots = tmp / "shots"
    shots.mkdir()
    db = tmp / "t.db"
    storage = Storage(db)

    cfg = Config(tmp / "c.json")
    cfg.set("capture.output_dir", str(shots), save=False)

    # 造三天数据：10-01（该删）、10-24（该留）、10-20（有未分析记录，该跳过）
    for name in ("2020-01-01", "2026-10-24", "2026-10-20"):
        d = shots / name
        d.mkdir()
        (d / "a.jpg").write_bytes(b"x" * 1024)
        (d / "b.jpg").write_bytes(b"y" * 2048)
        (d / "notes.txt").write_bytes(b"keep me")  # 非图片，绝不能被删

    storage.add_snapshot(
        datetime(2026, 10, 20, 9, 0), str(shots / "2026-10-20" / "a.jpg"), None,
        "Code.exe", "标题", "pending",
    )

    today = date(2026, 10, 25)

    # 边界 A：keep_days = 0 必须什么都不做
    cfg.set("capture.keep_days", 0, save=False)
    r = housekeeping.plan(cfg, storage, today=today)
    check("keep_days=0 时清单为空", r["dirs"] == [], f"{len(r['dirs'])} 项")

    # 边界 B：keep_days = -5 也不能删
    cfg.set("capture.keep_days", -5, save=False)
    r = housekeeping.plan(cfg, storage, today=today)
    check("keep_days=-5 时清单为空", r["dirs"] == [])

    # 边界 C：盘根目录必须拒绝
    cfg.set("capture.keep_days", 7, save=False)
    cfg.set("capture.output_dir", str(Path("C:/")), save=False)
    r = housekeeping.plan(cfg, storage, today=today)
    check("盘根目录被拒绝", r["dirs"] == [], "; ".join(r["skipped"])[:60])

    # 边界 D：用户主目录必须拒绝
    cfg.set("capture.output_dir", str(Path.home()), save=False)
    r = housekeeping.plan(cfg, storage, today=today)
    check("用户主目录被拒绝", r["dirs"] == [])

    # 边界 E：正常配置下，只有真的过期且已分析完的才进清单
    cfg.set("capture.output_dir", str(shots), save=False)
    r = housekeeping.plan(cfg, storage, today=today)
    days = r["days"]
    check("过期且已完结的进入清单", "2020-01-01" in days, f"清单 {days}")
    check("未过期的不进清单", "2026-10-24" not in days)
    check("有未分析记录的被跳过", "2026-10-20" not in days)

    # 边界 F：执行后只删图片，txt 保留，目录因非空而留下
    result = housekeeping.execute(r, storage)
    left = shots / "2020-01-01" if (shots / "2020-01-01").exists() else None
    check("图片被删掉", result["removed_files"] >= 2, f"{result['removed_files']} 张")
    check("非图片文件被保留", not (shots / "2020-01-01" / "a.jpg").exists())
    check("未过期目录完好", (shots / "2026-10-24" / "a.jpg").exists())

    # 边界 G：数据库记录不删，只清路径
    day_rows = storage.day_snapshots("2026-10-20")
    check("未分析那天的记录还在", len(day_rows) == 1)

    # 边界 H：符号链接不跟随
    link = shots / "2020-02-02"
    try:
        link.symlink_to(shots / "2026-10-24", target_is_directory=True)
        r2 = housekeeping.plan(cfg, storage, today=today)
        check("符号链接目录被忽略", "2020-02-02" not in r2["days"])
    except (OSError, NotImplementedError):
        print("   （当前系统不支持建符号链接，跳过该项）")

    shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------- 4. 暂停记录回补相关查询


def test_paused_backlog() -> None:
    section("4. 暂停记录回补")
    tmp = Path(tempfile.mkdtemp(prefix="mao_paused_"))
    storage = Storage(tmp / "t.db")

    storage.add_snapshot(datetime(2026, 10, 25, 9, 0), None, None, "a.exe", "早", "paused")
    storage.add_snapshot(datetime(2026, 10, 25, 11, 0), None, None, "b.exe", "晚", "paused")
    storage.add_snapshot(datetime(2026, 10, 25, 10, 0), None, None, "c.exe", "新", "pending")

    backlog = storage.paused_backlog(limit=2)
    check("只取 paused 状态", len(backlog) == 2, f"{len(backlog)} 条")
    check("按时间倒序（新的先补）", backlog[0]["window_title"] == "晚",
          backlog[0]["window_title"] if backlog else "")
    check("计数准确", storage.count_status("paused") == 2)
    check("pending 不混进来", all(r["status"] == "paused" for r in backlog))

    storage.clear_image_paths("2026-10-25")
    check("清路径不影响记录数", len(storage.day_snapshots("2026-10-25")) == 3)

    shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------- 5. 异常类型


def test_rate_limit_type() -> None:
    section("5. 限流异常可区分")
    check("AIRateLimited 是 AIError 子类", issubclass(AIRateLimited, AIError))
    check("AIError 能直接构造", isinstance(AIError("x"), Exception))


def main() -> int:
    test_max_tokens()
    test_json_repair()
    test_housekeeping()
    test_paused_backlog()
    test_rate_limit_type()

    print("\n" + "=" * 46)
    print(f"{PASS} 全部通过" if ok_all else f"{FAIL} 有失败项")
    print("=" * 46)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
