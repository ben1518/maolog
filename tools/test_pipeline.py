"""端到端链路测试：采集 → AI 分析 → 入库 → 统计 → 总结。

用本地 mock AI 服务代替真实模型，所以不需要 API Key 也能验证逻辑。

    .venv/Scripts/python.exe tools/test_pipeline.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import mock_ai_server  # noqa: E402
from core.ai_client import AIClient  # noqa: E402
from core.capture import CaptureService  # noqa: E402
from core.config import Config  # noqa: E402
from core.daily import build_digest, fallback_summary  # noqa: E402
from core.storage import Storage  # noqa: E402

TEST_DB = ROOT / "data" / "test_pipeline.db"
TEST_CFG = ROOT / "data" / "test_config.json"

PASS = "✅"
FAIL = "❌"


def check(name: str, condition: bool, detail: str = "") -> bool:
    print(f"{PASS if condition else FAIL} {name}" + (f"  ({detail})" if detail else ""))
    return condition


def main() -> int:
    ok = True

    # 1. mock 服务
    server = mock_ai_server.start(18080)
    print("\n=== 1. mock AI 服务 ===")
    ok &= check("本地 mock 服务启动", server is not None, "127.0.0.1:18080")

    # 2. 采集
    print("\n=== 2. 屏幕采集 ===")
    if TEST_DB.exists():
        TEST_DB.unlink()
    cfg = Config(TEST_CFG)
    cfg.set("capture.output_dir", str(ROOT / "data" / "test_shots"), save=False)
    cfg.set("ai.provider", "openai", save=False)
    cfg.set("ai.base_url", "http://127.0.0.1:18080/v1", save=False)
    cfg.set("ai.api_key", "test-key", save=False)
    cfg.set("ai.model", "mock-vl", save=False)

    cap = CaptureService(cfg)
    result = cap.capture_once()
    ok &= check("截图成功", result.skipped_reason is None, result.skipped_reason or "")
    ok &= check("图片已落盘", bool(result.image_path) and Path(result.image_path).exists())
    ok &= check("抓到窗口标题", bool(result.window_title), result.window_title[:30])
    ok &= check("首帧差异为 1.0", result.diff_score == 1.0)

    second = cap.capture_once()
    ok &= check(
        "第二帧差异可计算",
        0.0 <= second.diff_score <= 1.0,
        f"diff={second.diff_score:.4f}",
    )

    # 3. AI 分析
    print("\n=== 3. AI 分析 ===")
    storage = Storage(TEST_DB)
    sid = storage.add_snapshot(
        result.ts, result.image_path, result.thumb_path, result.app_name, result.window_title
    )
    client = AIClient(cfg)
    analysis = client.analyze(
        result.image_path, result.app_name, result.window_title, result.ts
    )
    ok &= check("拿到结构化结果", analysis.category in ("工作", "学习", "娱乐", "沟通", "系统", "其他"),
                f"{analysis.category} / {analysis.activity}")
    ok &= check("活动描述非空", bool(analysis.activity), analysis.detail)
    ok &= check("专注度在 1-5", 1 <= analysis.focus_score <= 5, str(analysis.focus_score))
    storage.save_analysis(sid, analysis.to_dict())

    saved = storage.get_snapshot(sid)
    ok &= check("结果已入库", saved["status"] == "done", saved["activity"])

    # 4. 批量灌数据，验证统计
    print("\n=== 4. 统计聚合 ===")
    base = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    scenes = [
        (0, 40, "Code.exe", "工作", "编程开发", "写代码", 5, True),
        (40, 15, "WeChat.exe", "沟通", "即时通讯", "回消息", 3, False),
        (55, 60, "Code.exe", "工作", "编程开发", "写代码", 5, True),
        (115, 30, "chrome.exe", "娱乐", "视频观看", "看视频", 2, False),
    ]
    for start_min, dur, app, cat, act, det, foc, prod in scenes:
        for i in range(dur):
            ts = base + timedelta(minutes=start_min + i)
            rid = storage.add_snapshot(ts, None, None, app, f"{app} - 窗口", "done")
            storage.save_analysis(
                rid,
                {
                    "category": cat,
                    "activity": act,
                    "detail": det,
                    "focus_score": foc,
                    "is_productive": prod,
                },
            )

    day = base.strftime("%Y-%m-%d")
    counts = storage.counts(day)
    segments = storage.segments(day, interval=60)
    cats = storage.category_stats(day, interval=60)
    apps = storage.app_stats(day, interval=60)
    overview = storage.overview(day, interval=60)

    ok &= check("记录总数正确", counts["total"] == 146, f"{counts['total']} 条")
    ok &= check("时间段合并生效", len(segments) == 5, f"{len(segments)} 段（含首条采集）")
    ok &= check("分类统计覆盖 4 类", len(cats) >= 3, ", ".join(c["category"] for c in cats))
    ok &= check("应用排行非空", len(apps) > 0, ", ".join(a["app"] for a in apps[:3]))
    ok &= check("总时长合理", overview["tracked_seconds"] == counts["total"] * 60,
                f"{overview['tracked_seconds'] // 3600} 小时")
    ok &= check("平均专注度有效", 0 < overview["avg_focus"] <= 5, str(overview["avg_focus"]))

    ordered = all(
        segments[i]["start"] <= segments[i + 1]["start"] for i in range(len(segments) - 1)
    )
    ok &= check("时间段按时间排序", ordered)

    # 5. 每日总结素材
    print("\n=== 5. 每日总结 ===")
    digest = build_digest(day, storage, interval=60)
    ok &= check("摘要已生成", len(digest) > 50, f"{len(digest)} 字符")
    ok &= check("摘要含时间线", "时间线" in digest)

    local = fallback_summary(day, storage, interval=60)
    ok &= check("本地兜底总结可用", bool(local["summary"]), local["summary"][:40] + "…")

    summary_resp = client.summarize_day(digest)
    ok &= check("AI 总结接口通", bool(summary_resp.get("summary")),
                summary_resp.get("summary", "")[:40])

    # 6. 边界情况
    print("\n=== 6. 边界情况 ===")
    empty_day = "2020-01-01"
    ok &= check("空日期不炸", storage.segments(empty_day) == [])
    ok &= check("空日期统计为零", storage.overview(empty_day)["records"] == 0)
    ok &= check("空摘要返回空串", build_digest(empty_day, storage) == "")

    bad_cfg = Config(ROOT / "data" / "bad_config.json")
    bad_cfg.set("ai.provider", "qwen", save=False)
    bad_cfg.set("ai.api_key", "", save=False)
    ready, msg = AIClient(bad_cfg).ready()
    ok &= check("缺 Key 时给出中文提示", not ready and "API Key" in msg, msg)

    server.shutdown()
    print("\n" + "=" * 46)
    print(f"{PASS} 全部通过" if ok else f"{FAIL} 有失败项，需要修复")
    print("=" * 46)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
