"""v2 学生自保侧原型测试。

覆盖：
  - 过程存证：范围、空数据、缺口、阶段、回访、HTML/PDF、隐私边界
  - AI 协作：三种模式、未知、未见 AI、保存幂等、改判保留
  - 数据护照：外发登记、用途开关、导出
  - 估时校准：计算、边界、趋势

    .venv/Scripts/python.exe tools/test_v2.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QDate  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from core.ai_client import AIClient, AIError  # noqa: E402
from core.ai_profile import (  # noqa: E402
    MODE_DIRECT,
    MODE_INTERLEAVED,
    MODE_NO_AI,
    MODE_THINK_FIRST,
    MODE_UNKNOWN,
    analyze_collaboration,
    override_collaboration,
    save_collaboration,
    weekly_summary,
)
from core.attest import (  # noqa: E402
    _document_key,
    build_process_report,
    export_process_html,
    export_process_pdf,
    is_ai_window,
    is_local_productive,
    snapshot_stage,
)
from core.learning_review import analyze_learning  # noqa: E402
from core.config import Config  # noqa: E402
from core.storage import Storage  # noqa: E402
from core.outbound import (  # noqa: E402
    PURPOSE_FRAME,
    PURPOSE_SUMMARY,
    PURPOSE_TEST,
    build_data_passport,
    export_data_passport,
    record_outbound,
    set_future_outbound,
)
from core.v2_demo import build_demo_bundle  # noqa: E402
from core.v2_runtime import (  # noqa: E402
    get_outbound_ledger,
    get_v2_storage,
    ledger_enabled,
    reset_cache,
)
from core.time_estimate import (  # noqa: E402
    compare_estimate,
    productive_minutes_from_storage,
    set_actual,
    set_plan,
    trend,
)
from core.v2_storage import V2Storage  # noqa: E402
from ui.ai_profile_dialog import AIProfileDialog  # noqa: E402
from ui.study_review_dialog import StudyReviewDialog  # noqa: E402
from ui.time_estimate_dialog import TimeEstimateDialog  # noqa: E402
from ui.v2_preview import V2PreviewWindow  # noqa: E402
from ui.v2_settings import (  # noqa: E402
    V2SettingsDialog,
    apply_settings,
    cleanup_v2_day,
    export_live_passport,
    load_policy_state,
)

PASS = "✅"
FAIL = "❌"
DAY = "2026-10-20"


def check(name: str, condition: bool, detail: str = "") -> bool:
    print(f"{PASS if condition else FAIL} {name}" + (f"  ({detail})" if detail else ""))
    return condition


def add_scene(
    storage: V2Storage,
    day: str,
    start: str,
    minutes: int,
    app: str,
    title: str,
    category: str = "工作",
    activity: str = "文档写作",
    status: str = "done",
) -> None:
    begin = datetime.strptime(f"{day} {start}", "%Y-%m-%d %H:%M")
    for index in range(minutes):
        snapshot_id = storage.add_snapshot(
            ts=begin + timedelta(minutes=index),
            image_path="C:/secret/截图.jpg",
            thumb_path=None,
            app_name=app,
            window_title=title,
            status=status,
        )
        if status == "done":
            storage.save_analysis(
                snapshot_id,
                {
                    "category": category,
                    "activity": activity,
                    "detail": f"细节不应进入报告 {title}",
                    "focus_score": 4,
                    "is_productive": True,
                },
            )


def seed_main(storage: V2Storage) -> None:
    add_scene(storage, DAY, "09:00", 30, "WINWORD.EXE", "课程论文-初稿.docx - Word")
    add_scene(storage, DAY, "09:30", 10, "chrome.exe", "中国知网 - 检索", "学习", "查阅资料")
    add_scene(storage, DAY, "09:40", 20, "WINWORD.EXE", "课程论文-初稿.docx - Word")
    add_scene(storage, DAY, "10:00", 15, "chrome.exe", "Kimi - 对话", "学习", "AI 对话")
    add_scene(storage, DAY, "10:15", 20, "WINWORD.EXE", "课程论文-初稿.docx - Word")
    add_scene(storage, DAY, "10:35", 30, "Code.exe", "main.py - Visual Studio Code")
    add_scene(storage, DAY, "11:05", 5, "chrome.exe", "DeepSeek - 对话", "学习", "AI 对话")
    add_scene(storage, DAY, "14:00", 20, "WINWORD.EXE", "课程论文-定稿.docx - Word", status="done")


def seed_modes(storage: V2Storage) -> None:
    # 先思后问：先写 12 分钟，再用 AI 5 分钟，再写 13 分钟
    add_scene(storage, "2026-10-21", "09:00", 12, "WINWORD.EXE", "方案.docx - Word")
    add_scene(storage, "2026-10-21", "09:12", 5, "chrome.exe", "Kimi - 对话", "学习", "AI 对话")
    add_scene(storage, "2026-10-21", "09:17", 13, "WINWORD.EXE", "方案.docx - Word")

    # 边做边问：每分钟本地产出与 AI 交替
    for index in range(3):
        add_scene(storage, "2026-10-22", f"10:{index * 2:02d}", 1, "Code.exe", "x.py - Code")
        add_scene(
            storage, "2026-10-22", f"10:{index * 2 + 1:02d}", 1,
            "chrome.exe", "ChatGPT", "学习", "AI 对话",
        )
    add_scene(storage, "2026-10-22", "10:06", 1, "Code.exe", "x.py - Code")

    # 直接要答案：整段都是 AI，跨度达到 15 分钟，之后没有本地产出
    add_scene(storage, "2026-10-23", "14:00", 16, "chrome.exe", "豆包", "学习", "AI 对话")

    # 无法判断：只有 1 分钟本地产出，之后 AI，再之后其他
    add_scene(storage, "2026-10-24", "15:00", 1, "Code.exe", "a.py - Code")
    add_scene(storage, "2026-10-24", "15:01", 1, "chrome.exe", "Kimi - 对话", "学习", "AI 对话")
    add_scene(storage, "2026-10-24", "15:02", 1, "explorer.exe", "文件夹", "系统", "文件管理")

    # 未见 AI 窗口
    add_scene(storage, "2026-10-25", "16:00", 20, "WINWORD.EXE", "作业.docx - Word")

    # 只有 2 分钟 AI：样本不足，不能判“直接要答案”
    add_scene(storage, "2026-10-26", "17:00", 2, "chrome.exe", "Kimi - 对话", "学习", "AI 对话")

    # 范围截断：AI 到 09:15，Word 在 09:20（观察窗内），不能判“直接要答案”
    add_scene(storage, "2026-10-27", "09:00", 16, "chrome.exe", "豆包", "学习", "AI 对话")
    add_scene(storage, "2026-10-27", "09:20", 10, "WINWORD.EXE", "作业.docx - Word")

    # 30 秒采样：10 条本地产出只有 5 分钟，不满足 10 分钟门槛
    add_scene(storage, "2026-10-28", "08:00", 10, "Code.exe", "x.py - Code")
    add_scene(storage, "2026-10-28", "08:10", 20, "chrome.exe", "DeepSeek - 对话", "学习", "AI 对话")

    # 范围内 AI 结束后 1 分钟就动笔：不能被判成“直接要答案”
    add_scene(storage, "2026-10-29", "09:00", 60, "chrome.exe", "豆包", "学习", "AI 对话")
    add_scene(storage, "2026-10-29", "10:00", 10, "WINWORD.EXE", "作业.docx - Word")

    # 高 AI 占比但覆盖稀疏，却多次交替：应判“边做边问”，不能因覆盖不足一律无法判断
    for hour in range(9, 17):
        add_scene(storage, "2026-10-30", f"{hour:02d}:00", 4, "chrome.exe", "DeepSeek - 对话", "学习", "AI 对话")
        add_scene(storage, "2026-10-30", f"{hour:02d}:04", 1, "Code.exe", "x.py - Code")


def test_attest(storage: V2Storage, temp: Path, app: QApplication) -> bool:
    ok = True
    print("\n=== 1. 学习过程与复盘 ===")
    report = build_process_report(
        storage, "课程论文写作", f"{DAY} 09:00:00", f"{DAY} 15:00:00"
    )
    stages = [run["stage"] for run in report["runs"]]
    ok &= check("报告能识别阶段序列", stages[:6] == ["写作", "查阅", "写作", "AI 对话", "写作", "编程"],
                " / ".join(stages))
    ok &= check("阶段交替计数正确", report["metrics"]["stage_switches"] == len(stages) - 1,
                str(report["metrics"]["stage_switches"]))
    ok &= check("同一文档回访被计数", report["metrics"]["document_revisits"] >= 2,
                str(report["metrics"]["document_revisits"]))
    ok &= check("中断被标为数据缺口", len(report["data_gaps"]) >= 1,
                report["data_gaps"][0]["start"] if report["data_gaps"] else "无")
    ok &= check("报告不含累计投入时长", "seconds" not in json.dumps(report, ensure_ascii=False))
    ok &= check("报告不含原始截图路径", "C:/secret" not in json.dumps(report, ensure_ascii=False))
    ok &= check("报告不含分析细节原文", "细节不应进入报告" not in json.dumps(report, ensure_ascii=False))

    html_path = export_process_html(report, temp / "过程.html", temp)
    html = html_path.read_text(encoding="utf-8")
    ok &= check("HTML 导出成功", html_path.exists() and len(html) > 800, f"{len(html)} 字符")
    ok &= check("HTML 不含截图路径", "C:/secret" not in html)
    ok &= check("HTML 不含窗口标题", "课程论文-初稿.docx" not in html)
    ok &= check("HTML 以学习复盘开头", "学习复盘" in html and "这段时间的节奏" in html)

    review = report["review"]
    ok &= check(
        "复盘能给出结论",
        review["has_data"] is True and bool(review["headline"]),
        review["headline"],
    )
    ok &= check(
        "动手时长按采样间隔补齐",
        review["metrics"]["produce_minutes"] == 120,
        str(review["metrics"]["produce_minutes"]),
    )
    ok &= check(
        "连续投入不跨数据空档",
        review["metrics"]["focus_minutes"] == 130,
        str(review["metrics"]["focus_minutes"]),
    )
    ok &= check(
        "复盘至少给一条建议",
        bool(review["suggestions"]),
        review["suggestions"][0]["title"] if review["suggestions"] else "无",
    )
    ok &= check(
        "复盘不评价内容原创性",
        not any(
            word in json.dumps(review, ensure_ascii=False)
            for word in ("抄袭", "原创", "代写", "作弊")
        ),
    )

    malicious = dict(report)
    malicious["task_name"] = '<script>alert("x")</script>'
    malicious_html = export_process_html(
        malicious, temp / "转义.html", temp
    ).read_text(encoding="utf-8")
    ok &= check("任务名经过 HTML 转义", "<script>alert" not in malicious_html and "&lt;script&gt;" in malicious_html)

    pdf_path = export_process_pdf(report, temp / "过程说明.pdf", temp)
    head = pdf_path.read_bytes()[:5]
    ok &= check("PDF 真实生成", pdf_path.exists() and pdf_path.stat().st_size > 1000, f"{pdf_path.stat().st_size} 字节")
    ok &= check("PDF 文件头正确", head == b"%PDF-", head.decode("ascii", "ignore"))

    try:
        export_process_pdf(report, temp / "过程说明.pdf", temp)
        ok &= check("PDF 默认拒绝覆盖", False)
    except FileExistsError:
        ok &= check("PDF 默认拒绝覆盖", True)
    try:
        export_process_html(report, temp / "过程.html", temp)
        ok &= check("HTML 默认拒绝覆盖", False)
    except FileExistsError:
        ok &= check("HTML 默认拒绝覆盖", True)
    try:
        export_process_html(report, temp.parent / "越界.html", temp)
        ok &= check("导出越界路径被拒", False)
    except ValueError:
        ok &= check("导出越界路径被拒", True)

    code_row = {"app_name": "Code.exe", "window_title": "deepseek_client.py - Visual Studio Code"}
    word_row = {"app_name": "WINWORD.EXE", "window_title": "豆包运营方案.docx - Word"}
    chrome_row = {"app_name": "chrome.exe", "window_title": "毕业论文模板 - 知乎"}
    pdf_row = {"app_name": "Acrobat.exe", "window_title": "论文.pdf"}
    harness_row = {"app_name": "DeepSeek Harness.exe", "window_title": "蝴蝶点开分离子集报错 — DeepSeek Harness"}
    kimi_site_row = {"app_name": "msedge.exe", "window_title": "Kimi 官网 - Kimi"}
    ok &= check("IDE 文件名含 deepseek 不算 AI", is_ai_window(code_row) is False and snapshot_stage(code_row) == "编程")
    ok &= check("Word 标题含豆包不算 AI", is_ai_window(word_row) is False and snapshot_stage(word_row) == "写作")
    ok &= check("AI 包装客户端能被识别", is_ai_window(harness_row) is True and snapshot_stage(harness_row) == "AI 对话")
    ok &= check("浏览器末段品牌也能识别", is_ai_window(kimi_site_row) is True)
    ok &= check("浏览器查阅不算本地产出", is_local_productive(chrome_row) is False)
    ok &= check("PDF 阅读器识别为阅读", snapshot_stage(pdf_row) == "阅读")
    ok &= check("Word 未保存星号不影响回访键", _document_key({"app_name": "WINWORD.EXE", "window_title": "* 论文.docx - Word"}) == "论文")
    ok &= check("内部连字符不被误删", _document_key({"app_name": "WINWORD.EXE", "window_title": "实验 - 数据.docx - Word"}) == "实验 - 数据")

    empty = build_process_report(
        storage, "空任务", "2020-01-01 09:00:00", "2020-01-01 18:00:00"
    )
    ok &= check("空范围不报错", empty["runs"] == [] and empty["metrics"]["source_records"] == 0)
    ok &= check("空范围说明原因", bool(empty["quality_notes"]), empty["quality_notes"][0])

    for label, action in [
        ("空任务名被拒", lambda: build_process_report(storage, " ", f"{DAY} 09:00:00", f"{DAY} 10:00:00")),
        ("结束早于开始被拒", lambda: build_process_report(storage, "x", f"{DAY} 10:00:00", f"{DAY} 09:00:00")),
        ("采样间隔为零被拒", lambda: build_process_report(storage, "x", f"{DAY} 09:00:00", f"{DAY} 10:00:00", 0)),
    ]:
        try:
            action()
            ok &= check(label, False)
        except ValueError:
            ok &= check(label, True)

    counts_before = storage.table_counts()
    export_process_html(report, temp / "再导出.html", temp)
    export_process_pdf(report, temp / "再导出.pdf", temp)
    counts_after = storage.table_counts()
    ok &= check("导出不改变任何数据表", counts_before == counts_after,
                f"{counts_before} -> {counts_after}")
    return ok


def test_learning_review() -> bool:
    ok = True
    print("\n=== 2. 学习复盘解读 ===")

    def run(stage: str, start: str, end: str) -> dict:
        return {"stage": stage, "start": f"{DAY} {start}:00", "end": f"{DAY} {end}:00"}

    def report_of(runs: list[dict], revisits: int = 0, gaps: list[dict] | None = None) -> dict:
        return {
            "runs": runs,
            "metrics": {
                "document_revisits": revisits,
                "stage_switches": max(0, len(runs) - 1),
            },
            "data_gaps": gaps or [],
        }

    interrupted = analyze_learning(
        report_of(
            [
                run("写作", "09:00", "09:19"),
                run("其他", "09:20", "09:24"),
                run("写作", "09:25", "09:39"),
                run("其他", "09:40", "09:44"),
                run("写作", "09:45", "09:59"),
                run("其他", "10:00", "10:04"),
                run("写作", "10:05", "10:19"),
            ]
        ),
        60,
    )
    ok &= check(
        "三次短离开计为打断",
        interrupted["metrics"]["interruptions"] == 3,
        str(interrupted["metrics"]["interruptions"]),
    )
    ok &= check(
        "打断后给对应建议",
        any("打断" in item["title"] for item in interrupted["suggestions"]),
        interrupted["suggestions"][0]["title"] if interrupted["suggestions"] else "无",
    )

    away = analyze_learning(
        report_of(
            [
                run("写作", "09:00", "09:09"),
                run("其他", "09:10", "09:49"),
                run("写作", "09:50", "09:59"),
            ]
        ),
        60,
    )
    ok &= check(
        "超过 20 分钟的离开不计打断",
        away["metrics"]["interruptions"] == 0 and away["metrics"]["away_long"] == 1,
        f"打断 {away['metrics']['interruptions']} / 离开 {away['metrics']['away_long']}",
    )

    startup = analyze_learning(
        report_of([run("查阅", "09:00", "09:39"), run("写作", "09:40", "09:59")]), 60
    )
    ok &= check(
        "动手前准备时长被识别",
        startup["metrics"]["startup_minutes"] == 40,
        str(startup["metrics"]["startup_minutes"]),
    )
    ok &= check(
        "准备过久给对应建议",
        any("先写三行" in item["title"] for item in startup["suggestions"]),
        startup["suggestions"][0]["title"] if startup["suggestions"] else "无",
    )

    split = analyze_learning(
        report_of([run("写作", "09:00", "09:29"), run("写作", "14:00", "14:29")]), 60
    )
    ok &= check(
        "连续投入不跨空档累加",
        split["metrics"]["focus_minutes"] == 30,
        str(split["metrics"]["focus_minutes"]),
    )

    gap_note = analyze_learning(
        report_of(
            [run("写作", "09:00", "09:29"), run("写作", "14:00", "14:29")],
            gaps=[{"start": f"{DAY} 09:29:00", "end": f"{DAY} 14:00:00", "note": "空档"}],
        ),
        60,
    )
    ok &= check(
        "有断档时在结论里说明",
        "没有记录的时间" in gap_note["summary"],
        gap_note["summary"],
    )

    empty = analyze_learning({"runs": [], "metrics": {}}, 60)
    ok &= check(
        "无记录时不编造结论",
        empty["has_data"] is False
        and empty["strengths"] == []
        and empty["frictions"] == []
        and empty["suggestions"] == [],
    )
    return ok


def test_ai(storage: V2Storage) -> bool:
    ok = True
    print("\n=== 3. AI 协作画像 ===")
    cases = [
        ("2026-10-21", "先思后问", MODE_THINK_FIRST),
        ("2026-10-22", "边做边问", MODE_INTERLEAVED),
        ("2026-10-24", "无法判断", MODE_UNKNOWN),
        ("2026-10-25", "未见 AI 窗口", MODE_NO_AI),
        ("2026-10-26", "AI 样本不足", MODE_UNKNOWN),
        ("2026-10-27", "范围截断不误判", MODE_UNKNOWN),
    ]
    for day, label, expected in cases:
        result = analyze_collaboration(
            storage, label, f"{day} 08:00:00", f"{day} 23:00:00"
        )
        ok &= check(f"{label}识别", result["mode"] == expected, result["mode"])

    direct = analyze_collaboration(
        storage, "直接", "2026-10-23 14:00:00", "2026-10-23 14:20:00"
    )
    ok &= check("直接要答案识别", direct["mode"] == MODE_DIRECT, direct["mode"])
    sparse = analyze_collaboration(
        storage, "稀疏", "2026-10-23 08:00:00", "2026-10-23 23:00:00"
    )
    ok &= check("整天稀疏数据不判直接要答案", sparse["mode"] == MODE_UNKNOWN, sparse["mode"])
    sparse_switch = analyze_collaboration(
        storage, "稀疏交替", "2026-10-30 08:00:00", "2026-10-30 18:00:00"
    )
    ok &= check(
        "覆盖不足但多次交替仍能判边做边问",
        sparse_switch["mode"] == MODE_INTERLEAVED,
        f"{sparse_switch['mode']} / 覆盖 {sparse_switch['evidence']['coverage']:.0%}",
    )

    short = analyze_collaboration(
        storage, "短样本", "2026-10-28 08:00:00", "2026-10-28 09:00:00", interval=30
    )
    ok &= check(
        "30 秒采样不虚增先思时长",
        short["mode"] == MODE_UNKNOWN and short["evidence"]["prior_local_seconds"] == 300,
        f"{short['mode']} / {short['evidence']['prior_local_seconds']} 秒",
    )
    truncated = analyze_collaboration(
        storage, "截断", "2026-10-27 09:00:00", "2026-10-27 09:15:00"
    )
    ok &= check(
        "观察窗能看到范围后的本地产出",
        truncated["evidence"]["local_within_15min_after_ai"] is True,
    )
    after_ai = analyze_collaboration(
        storage, "范围内动笔", "2026-10-29 09:00:00", "2026-10-29 10:10:00"
    )
    ok &= check(
        "范围内 AI 后动笔不判直接要答案",
        after_ai["mode"] != MODE_DIRECT
        and after_ai["evidence"]["local_within_15min_after_ai"] is True,
        after_ai["mode"],
    )

    think = analyze_collaboration(
        storage, "先思", "2026-10-21 08:00:00", "2026-10-21 23:00:00"
    )
    ok &= check("保留判断依据", think["evidence"]["has_10min_prior_local_work"] is True)
    ok &= check("依据里没有窗口标题", "方案.docx" not in json.dumps(think, ensure_ascii=False))

    judgment_id, preserved = save_collaboration(storage, think)
    ok &= check("首次保存成功", judgment_id > 0 and preserved is False)
    again_id, preserved = save_collaboration(storage, think)
    ok &= check("刷新不新增重复记录", again_id == judgment_id and preserved is False)
    ok &= check("同一范围只有一条判断", len(storage.list_ai_judgments()) == 1,
                str(len(storage.list_ai_judgments())))

    changed = override_collaboration(storage, judgment_id, MODE_UNKNOWN)
    ok &= check("学生改判已保存", changed["mode"] == MODE_UNKNOWN and changed["overridden"] == 1)
    different_range = dict(think)
    different_range["end_ts"] = "2026-10-21 23:01:00"
    refreshed_id, preserved = save_collaboration(storage, different_range)
    refreshed = storage.get_ai_judgment(refreshed_id)
    ok &= check(
        "结束时间变化后改判仍保留",
        preserved is True and refreshed["mode"] == MODE_UNKNOWN and refreshed_id == judgment_id,
        refreshed["mode"],
    )
    ok &= check("改判保留原模式", refreshed["original_mode"] == MODE_THINK_FIRST)

    second = override_collaboration(storage, judgment_id, MODE_DIRECT)
    ok &= check(
        "二次改判不覆盖机器原判",
        second["original_mode"] == MODE_THINK_FIRST
        and second["evidence"].get("override_from") == MODE_UNKNOWN,
        f"{second['original_mode']} / {second['evidence'].get('override_from')}",
    )
    no_ai = override_collaboration(storage, judgment_id, MODE_NO_AI)
    ok &= check("可以改判为未见 AI 窗口", no_ai["mode"] == MODE_NO_AI)

    try:
        override_collaboration(storage, judgment_id, "优秀")
        ok &= check("非法模式被拒", False)
    except ValueError:
        ok &= check("非法模式被拒", True)

    same_week = [
        analyze_collaboration(storage, "a", "2026-10-21 08:00:00", "2026-10-21 23:00:00"),
        analyze_collaboration(storage, "b", "2026-10-22 08:00:00", "2026-10-22 23:00:00"),
    ]
    week = weekly_summary(same_week)
    ok &= check("同周摘要可用", week["sample_count"] == 2 and bool(week["modes"]))
    try:
        weekly_summary(
            same_week
            + [analyze_collaboration(storage, "c", "2026-11-02 08:00:00", "2026-11-02 23:00:00")]
        )
        ok &= check("跨周摘要被拒", False)
    except ValueError:
        ok &= check("跨周摘要被拒", True)

    empty = analyze_collaboration(storage, "空", "2020-01-01 08:00:00", "2020-01-01 23:00:00")
    ok &= check("无数据时无法判断", empty["mode"] == MODE_UNKNOWN)
    return ok


def test_outbound(storage: V2Storage, temp: Path) -> bool:
    ok = True
    print("\n=== 4. 数据护照 ===")
    ok &= check(
        "新库默认停止全部外发",
        all(storage.outbound_allowed(p) is False for p in (PURPOSE_FRAME, PURPOSE_SUMMARY, PURPOSE_TEST)),
    )
    try:
        record_outbound(storage, "2026-10-20 09:00:00", "qwen", "x", 10, True, PURPOSE_FRAME)
        ok &= check("未授权时拒绝外发登记", False)
    except PermissionError:
        ok &= check("未授权时拒绝外发登记", True)
    for purpose in (PURPOSE_FRAME, PURPOSE_SUMMARY, PURPOSE_TEST):
        set_future_outbound(storage, purpose, True)

    record_outbound(storage, "2026-10-20 09:05:00", "qwen", "qwen-vl-max", 1200, True, PURPOSE_FRAME)
    record_outbound(storage, "2026-10-20 21:00:00", "qwen", "qwen-vl-max", 300, False, PURPOSE_SUMMARY)
    record_outbound(storage, "2026-10-20 09:00:00", "ollama", "qwen2.5vl", 0, False, PURPOSE_TEST)
    ok &= check("外发登记成功", len(storage.outbound_events()) == 3)

    for label, action in [
        ("未知用途被拒", lambda: record_outbound(storage, "2026-10-20 10:00:00", "x", "y", 1, False, "偷偷上传")),
        ("负数大小被拒", lambda: record_outbound(storage, "2026-10-20 10:00:00", "x", "y", -1, False, PURPOSE_FRAME)),
        ("非数字大小被拒", lambda: record_outbound(storage, "2026-10-20 10:00:00", "x", "y", "abc", False, PURPOSE_FRAME)),
        ("空服务商被拒", lambda: record_outbound(storage, "2026-10-20 10:00:00", "", "y", 1, False, PURPOSE_FRAME)),
    ]:
        try:
            action()
            ok &= check(label, False)
        except ValueError:
            ok &= check(label, True)

    set_future_outbound(storage, PURPOSE_FRAME, False)
    try:
        record_outbound(storage, "2026-10-20 11:00:00", "qwen", "x", 10, True, PURPOSE_FRAME)
        ok &= check("停止后拒绝同类外发", False)
    except PermissionError:
        ok &= check("停止后拒绝同类外发", True)
    set_future_outbound(storage, PURPOSE_FRAME, True)
    ok &= check("只影响同类用途", storage.outbound_allowed(PURPOSE_SUMMARY) is True)

    passport = build_data_passport(storage, image_keep_days=7)
    ok &= check("护照统计外发总数", passport["outbound"]["recorded_total"] == 3,
                str(passport["outbound"]["recorded_total"]))
    ok &= check("护照含三种用途", len(passport["outbound"]["by_purpose"]) == 3)
    ok &= check("护照说明不可收回", "不可" in passport["revocation"]["already_sent"])
    ok &= check("护照含覆盖范围声明", "不覆盖用户手动上传" in passport["scope_note"])
    ok &= check("护照不含提示词内容", "SECRET_PROMPT" not in json.dumps(passport, ensure_ascii=False))
    ok &= check(
        "护照列出本机其他 v2 记录",
        "ai_judgments" in passport["local_storage"]
        and "time_estimates" in passport["local_storage"],
    )
    ok &= check("护照标明台账未接实时请求", passport["outbound"]["ledger_wired"] is False)
    ok &= check("护照列出外发开关状态", len(passport["outbound_policy"]) == 3)

    path = export_data_passport(passport, temp / "护照.json", temp)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    ok &= check("护照 JSON 可解析", loaded["title"] == "数据护照")
    try:
        export_data_passport(passport, temp / "护照.json", temp)
        ok &= check("护照默认拒绝覆盖", False)
    except FileExistsError:
        ok &= check("护照默认拒绝覆盖", True)
    try:
        export_data_passport(passport, temp / "护照.txt", temp)
        ok &= check("非 JSON 后缀被拒", False)
    except ValueError:
        ok &= check("非 JSON 后缀被拒", True)
    return ok


def test_estimate(storage: V2Storage) -> bool:
    ok = True
    print("\n=== 5. 估时校准 ===")
    day = "2026-10-20"
    set_plan(storage, day, 180)
    set_actual(storage, day, 60)
    result = compare_estimate(storage, day)
    ok &= check("估时高于实际被识别", result["status"] == "高于实际" and result["delta_minutes"] == 120,
                str(result["delta_minutes"]))

    set_actual(storage, day, 175)
    ok &= check("接近时不当成偏差", compare_estimate(storage, day)["status"] == "接近")
    set_actual(storage, day, 240)
    ok &= check("估时低于实际被识别", compare_estimate(storage, day)["status"] == "低于实际")

    productive = productive_minutes_from_storage(storage, day)
    ok &= check("统计学习与工作类产出分钟", productive > 30, f"{productive} 分钟")

    set_plan(storage, "2026-10-21", 0)
    set_actual(storage, "2026-10-21", 0)
    ok &= check("零小时不除零", compare_estimate(storage, "2026-10-21")["status"] == "一致")

    for label, action in [
        ("负分钟被拒", lambda: set_plan(storage, day, -1)),
        ("超过一天被拒", lambda: set_plan(storage, day, 1441)),
        ("非法日期被拒", lambda: set_plan(storage, "2026-13-01", 60)),
    ]:
        try:
            action()
            ok &= check(label, False)
        except ValueError:
            ok &= check(label, True)

    week = trend(storage, limit=14)
    ok &= check("趋势统计可生成", week["sample_count"] >= 2 and "observation" in week)
    ok &= check("估时表按天覆盖", len(storage.list_time_estimates()) == 2)
    return ok


def test_live_ledger(temp: Path) -> bool:
    ok = True
    print("\n=== 6. 实时外发台账 ===")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {"message": {"content": "正常"}, "finish_reason": "stop"}
                ]
            }

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def post(self, *_args, **_kwargs):
            self.calls += 1
            return FakeResponse()

    reset_cache()
    cfg = Config(temp / "live_cfg.json")
    cfg.set("ai.provider", "openai", save=False)
    cfg.set("ai.api_key", "sk-test", save=False)
    cfg.set("ai.model", "gpt-test", save=False)
    cfg.set("v2.outbound_ledger", False, save=False)
    ok &= check("默认关闭时没有台账对象", ledger_enabled(cfg) is False and get_outbound_ledger(cfg) is None)

    cfg.set("v2.outbound_ledger", True, save=False)
    cfg.set("v2.enforce_outbound", False, save=False)
    cfg.set("v2.db_path", str(temp / "live.db"), save=False)
    client = AIClient(cfg)
    fake = FakeSession()
    client._session = fake
    ok &= check("连接测试成功", client.test_connection() == "正常")
    live = get_v2_storage(cfg)
    events = live.outbound_events()
    ok &= check(
        "真实请求已写入台账",
        len(events) == 1
        and events[0]["purpose"] == PURPOSE_TEST
        and events[0]["model"] == "gpt-test"
        and events[0]["bytes"] > 0,
        f"{len(events)} 条 / {events[0]['purpose'] if events else '无'}",
    )
    with live._conn() as conn:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(outbound_log)").fetchall()
        }
    ok &= check(
        "台账不含提示词与图片列",
        not ({"prompt", "content", "window_title", "image"} & columns),
        ",".join(sorted(columns)),
    )

    # 打开拦截后，未允许的用途必须在发请求前被拒绝。
    set_future_outbound(live, PURPOSE_TEST, False)
    cfg.set("v2.enforce_outbound", True, save=False)
    blocked_client = AIClient(cfg)
    blocked_session = FakeSession()
    blocked_client._session = blocked_session
    try:
        blocked_client.test_connection()
        ok &= check("拦截开启后阻止未允许请求", False)
    except AIError as exc:
        ok &= check(
            "拦截开启后阻止未允许请求",
            "已停止" in str(exc) and blocked_session.calls == 0,
            str(exc),
        )
    set_future_outbound(live, PURPOSE_TEST, True)
    allowed_client = AIClient(cfg)
    allowed_session = FakeSession()
    allowed_client._session = allowed_session
    ok &= check("允许后恢复请求", allowed_client.test_connection() == "正常" and allowed_session.calls == 1)
    reset_cache()
    return ok


def test_live_cleanup(temp: Path) -> bool:
    ok = True
    print("\n=== 7. v2 按日清理 ===")
    db_path = temp / "cleanup.db"
    storage = V2Storage(db_path)
    for purpose in (PURPOSE_FRAME, PURPOSE_SUMMARY, PURPOSE_TEST):
        set_future_outbound(storage, purpose, True)
    add_scene(storage, "2026-10-20", "09:00", 2, "Code.exe", "x.py - Code")
    record_outbound(
        storage, "2026-10-20 09:05:00", "qwen", "qwen-vl-max", 100, True, PURPOSE_FRAME
    )
    set_plan(storage, "2026-10-20", 120)
    set_actual(storage, "2026-10-20", 60)
    set_plan(storage, "2026-10-21", 90)
    set_actual(storage, "2026-10-21", 60)
    storage.save_ai_judgment(
        {
            "day": "2026-10-20",
            "task_context": "清理任务",
            "start_ts": "2026-10-20 09:00:00",
            "end_ts": "2026-10-20 10:00:00",
            "mode": "无法判断",
            "evidence": {},
        }
    )
    record_outbound(
        storage, "2026-10-21 09:05:00", "qwen", "qwen-vl-max", 100, True, PURPOSE_FRAME
    )
    snapshots_before = storage.table_counts()["snapshots"]
    result = storage.delete_day_v2("2026-10-20")
    counts = storage.table_counts()
    ok &= check(
        "按日删除只清 v2 元数据",
        result == {"ai_judgments": 1, "outbound_records": 1, "time_estimates": 1}
        and counts["snapshots"] == snapshots_before
        and counts["outbound_log"] == 1,
        f"{result} / 快照 {counts['snapshots']} / 剩余外发 {counts['outbound_log']}",
    )
    ok &= check(
        "其他日期不受影响",
        [item["day"] for item in storage.list_time_estimates()] == ["2026-10-21"],
    )
    return ok


def test_v2_settings(temp: Path) -> bool:
    ok = True
    print("\n=== 8. 设置面板与护照 ===")
    reset_cache()
    cfg = Config(temp / "ui_cfg.json")
    cfg.set("v2.db_path", str(temp / "ui_ledger.db"))
    cfg.set("v2.outbound_ledger", False)
    db_path = temp / "ui_ledger.db"

    apply_settings(cfg, False, False, {p: True for p in (PURPOSE_FRAME, PURPOSE_SUMMARY, PURPOSE_TEST)})
    ok &= check("关闭保存不创建数据库", db_path.exists() is False and ledger_enabled(cfg) is False)
    ok &= check("关闭时策略显示为默认允许", all(load_policy_state(cfg).values()))

    try:
        apply_settings(
            cfg,
            True,
            False,
            {PURPOSE_FRAME: True, PURPOSE_SUMMARY: True, PURPOSE_TEST: True, "偷偷上传": True},
        )
        ok &= check("未知用途被拒", False)
    except ValueError:
        ok &= check("未知用途被拒", True)

    apply_settings(
        cfg,
        True,
        False,
        {PURPOSE_FRAME: False, PURPOSE_SUMMARY: True, PURPOSE_TEST: True},
    )
    state = get_v2_storage(cfg).outbound_policy_state()
    ok &= check("保存后创建台账并写入策略", db_path.exists() and state[PURPOSE_FRAME] is False)
    ok &= check("保存后开启台账", ledger_enabled(cfg) is True and cfg.get("v2.enforce_outbound") is False)

    record_outbound(
        get_v2_storage(cfg),
        "2026-10-20 09:00:00",
        "qwen",
        "qwen-vl-max",
        100,
        True,
        PURPOSE_SUMMARY,
    )
    set_plan(get_v2_storage(cfg), "2026-10-20", 90)
    set_actual(get_v2_storage(cfg), "2026-10-20", 60)

    export_dir = temp / "passport_out"
    path = export_live_passport(cfg, export_dir)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    ok &= check(
        "设置面板导出实盘护照",
        path.exists()
        and loaded["demo"] is False
        and loaded["outbound"]["ledger_wired"] is True
        and loaded["outbound"]["recorded_total"] == 1,
    )

    dialog = V2SettingsDialog(cfg)
    ok &= check("设置面板读到已开启状态", dialog.check_enabled.isChecked())
    ok &= check("设置面板读到用途策略", dialog.policy_boxes[PURPOSE_FRAME].isChecked() is False)
    dialog.check_enabled.setChecked(False)
    ok &= check("关闭后导出与清理按钮禁用", dialog.btn_export.isEnabled() is False and dialog.btn_cleanup.isEnabled() is False)
    ok &= check("设置面板可保存关闭状态", dialog._save() is True and ledger_enabled(cfg) is False)

    apply_settings(
        cfg,
        True,
        False,
        {PURPOSE_FRAME: True, PURPOSE_SUMMARY: True, PURPOSE_TEST: True},
    )
    result = cleanup_v2_day(cfg, "2026-10-20")
    ok &= check(
        "面板清理只删 v2 元数据",
        result["outbound_records"] == 1 and result["time_estimates"] == 1,
        str(result),
    )
    apply_settings(
        cfg,
        False,
        False,
        {PURPOSE_FRAME: True, PURPOSE_SUMMARY: True, PURPOSE_TEST: True},
    )
    try:
        cleanup_v2_day(cfg, "2026-10-20")
        ok &= check("关闭台账后拒绝清理", False)
    except ValueError:
        ok &= check("关闭台账后拒绝清理", True)
    reset_cache()
    return ok


def test_study_review_dialog(temp: Path) -> bool:
    ok = True
    print("\n=== 9. 主窗口学习复盘入口 ===")
    plain_db = temp / "plain_activity.db"
    plain = Storage(plain_db)
    add_scene(plain, "2026-10-20", "09:00", 2, "Code.exe", "x.py - Code")
    cfg = Config(temp / "review_cfg.json")

    dialog = StudyReviewDialog(cfg, plain, "2026-10-20")
    html = dialog.preview.toHtml()
    ok &= check(
        "学习复盘能预览普通快照",
        "学习复盘" in html
        and "这段时间的节奏" in html
        and dialog.btn_pdf.isEnabled()
        and dialog.btn_html.isEnabled(),
    )
    ok &= check("无听歌记录不生成听歌章节", "听歌与专注" not in html)
    conn = sqlite3.connect(plain_db)
    try:
        v2_tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND "
                "(name LIKE 'ai_use%' OR name LIKE 'outbound%' OR name='time_estimate')"
            )
        ]
    finally:
        conn.close()
    ok &= check("生成预览不创建 v2 表", v2_tables == [], ",".join(v2_tables))
    dialog.close()

    empty_dialog = StudyReviewDialog(cfg, plain, "2026-10-19")
    ok &= check(
        "空日期禁用导出",
        empty_dialog.btn_pdf.isEnabled() is False and empty_dialog.btn_html.isEnabled() is False,
    )
    empty_dialog.close()
    return ok


def test_ai_dialog(temp: Path) -> bool:
    ok = True
    print("\n=== 10. 主窗口 AI 协作入口 ===")
    db_path = temp / "ai_dialog.db"
    plain = Storage(db_path)
    add_scene(plain, "2026-10-22", "09:00", 12, "WINWORD.EXE", "方案.docx - Word")
    add_scene(plain, "2026-10-22", "09:12", 5, "chrome.exe", "Kimi - 对话", "学习", "AI 对话")
    add_scene(plain, "2026-10-22", "09:17", 13, "WINWORD.EXE", "方案.docx - Word")
    cfg = Config(temp / "ai_dialog_cfg.json")

    dialog = AIProfileDialog(cfg, plain, "2026-10-22")
    ok &= check(
        "实时分析得到先思后问",
        dialog.judgment is not None and dialog.judgment["mode"] == MODE_THINK_FIRST,
        dialog.judgment["mode"] if dialog.judgment else "无",
    )
    ok &= check("依据完整可展示", "首个 AI 之前" in dialog.evidence.toHtml())
    conn = sqlite3.connect(db_path)
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_use_daily'"
        ).fetchone()
    finally:
        conn.close()
    ok &= check("只看不保存不建 v2 表", table is None)

    dialog._save_only()
    ok &= check("保存后写入本机判断", dialog.judgment_id is not None)
    dialog.mode_combo.setCurrentText(MODE_UNKNOWN)
    dialog._save_override()
    stored = dialog._v2_store().get_ai_judgment(dialog.judgment_id)
    ok &= check(
        "改判保存且保留机器原判",
        stored is not None
        and stored["mode"] == MODE_UNKNOWN
        and stored["original_mode"] == MODE_THINK_FIRST,
    )
    ok &= check("保存后出现本周汇总", "本周已保存 1 个任务时段" in dialog.week_label.text(),
                dialog.week_label.text())
    dialog.close()

    empty = AIProfileDialog(cfg, plain, "2026-10-19")
    ok &= check(
        "空日期不能保存",
        empty.btn_save.isEnabled() is False and empty.btn_override.isEnabled() is False,
    )
    empty.close()
    return ok


def test_time_dialog(temp: Path) -> bool:
    ok = True
    print("\n=== 11. 主窗口估时校准入口 ===")
    db_path = temp / "estimate_dialog.db"
    plain = Storage(db_path)
    add_scene(plain, "2026-10-20", "09:00", 2, "Code.exe", "x.py - Code")
    cfg = Config(temp / "estimate_dialog_cfg.json")

    dialog = TimeEstimateDialog(cfg, plain, "2026-10-20")
    ok &= check("实际产出按学习工作统计", dialog.actual_label.text() == "2 分钟", dialog.actual_label.text())
    conn = sqlite3.connect(db_path)
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='time_estimate'"
        ).fetchone()
    finally:
        conn.close()
    ok &= check("只看不保存不建估时表", table is None)

    dialog.plan_spin.setValue(120)
    dialog._save()
    stored = dialog._v2_store().get_time_estimate("2026-10-20")
    ok &= check(
        "保存计划同时结算实际",
        stored is not None
        and stored["planned_minutes"] == 120
        and stored["actual_minutes"] == 2,
        str(stored),
    )
    ok &= check("偏差状态可解释", "高于实际" in dialog.status_label.text(), dialog.status_label.text())
    ok &= check("近期记录已更新", "可对照 1 天" in dialog.trend_label.text(), dialog.trend_label.text())

    dialog.plan_spin.setValue(2)
    dialog._save()
    ok &= check("计划接近实际被识别", "接近" in dialog.status_label.text(), dialog.status_label.text())

    dialog.date_edit.setDate(QDate.fromString("2026-10-19", "yyyy-MM-dd"))
    ok &= check(
        "无记录日期给出明确状态",
        dialog.actual_label.text() == "0 分钟" and "还没有保存过计划" in dialog.status_label.text(),
    )
    dialog.close()
    return ok


def test_demo_bundle(temp: Path) -> bool:
    ok = True
    print("\n=== 12. 隔离演示模式 ===")
    db_path = temp / "demo.db"
    bundle = build_demo_bundle(db_path)
    storage = bundle["storage"]
    counts = storage.table_counts()
    ok &= check(
        "演示库生成过程与判断",
        db_path.exists() and counts["snapshots"] > 0 and counts["ai_use_daily"] == 1,
        str(counts),
    )
    ok &= check(
        "演示护照标记为 demo",
        bundle["passport"]["demo"] is True
        and bundle["passport"]["outbound"]["recorded_total"] == 17,
    )
    ok &= check(
        "演示外发策略回到关闭",
        all(value is False for value in storage.outbound_policy_state().values()),
    )
    first_count = counts["snapshots"]
    second = build_demo_bundle(db_path)
    second_counts = second["storage"].table_counts()
    ok &= check(
        "重复打开不重复灌数据",
        second_counts["snapshots"] == first_count and second_counts["ai_use_daily"] == 1,
        str(second_counts),
    )

    window = V2PreviewWindow(
        bundle["storage"],
        bundle["report"],
        bundle["judgment"],
        bundle["passport"],
        bundle["estimate"],
        temp / "demo_exports",
        demo_mode=True,
    )
    ok &= check("演示看板可构建且带隔离标记", window.demo_mode is True)
    window.close()
    return ok


def test_migration(temp: Path) -> bool:
    ok = True
    print("\n=== 13. 旧库升级边界 ===")
    db_path = temp / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE ai_use_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT NOT NULL,
            task_context TEXT,
            start_ts TEXT NOT NULL,
            end_ts TEXT NOT NULL,
            mode TEXT,
            evidence_json TEXT,
            overridden INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE attest_session (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT,
            start_ts TEXT,
            end_ts TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO ai_use_daily (day, task_context, start_ts, end_ts, mode, overridden) "
        "VALUES ('2026-10-20', '旧任务', '2026-10-20 09:00:00', '2026-10-20 10:00:00', '先思后问', 0)"
    )
    conn.execute(
        "INSERT INTO ai_use_daily (day, task_context, start_ts, end_ts, mode, overridden) "
        "VALUES ('2026-10-20', '旧任务', '2026-10-20 09:00:00', '2026-10-20 11:00:00', '直接要答案', 1)"
    )
    conn.execute("INSERT INTO attest_session (task_name) VALUES ('旧导出记录')")
    conn.commit()
    conn.close()

    migrated = V2Storage(db_path)
    judgments = migrated.list_ai_judgments()
    ok &= check(
        "旧库重复键自动去重并保留改判行",
        len(judgments) == 1 and judgments[0]["mode"] == "直接要答案",
        f"{len(judgments)} 条 / {judgments[0]['mode'] if judgments else '无'}",
    )
    ok &= check("旧库存取不因唯一索引崩溃", migrated.outbound_allowed(PURPOSE_FRAME) is False)
    with migrated._conn() as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='attest_session'"
        ).fetchone()
    ok &= check("旧任务表被清理", table is None)
    return ok


def main() -> int:
    ok = True
    app = QApplication.instance() or QApplication(sys.argv)
    with tempfile.TemporaryDirectory(prefix="mao_v2_test_") as folder:
        temp = Path(folder)
        storage = V2Storage(temp / "v2_test.db")
        ok &= check("独立数据库已建立", (temp / "v2_test.db").exists())
        counts = storage.table_counts()
        ok &= check(
            "v2 表全部建立",
            all(
                name in counts
                for name in ("ai_use_daily", "outbound_log", "outbound_policy", "time_estimate")
            ),
        )
        seed_main(storage)
        seed_modes(storage)
        ok &= test_attest(storage, temp, app)
        ok &= test_learning_review()
        ok &= test_ai(storage)
        ok &= test_outbound(storage, temp)
        ok &= test_estimate(storage)
        ok &= test_live_ledger(temp)
        ok &= test_live_cleanup(temp)
        ok &= test_v2_settings(temp)
        ok &= test_study_review_dialog(temp)
        ok &= test_ai_dialog(temp)
        ok &= test_time_dialog(temp)
        ok &= test_demo_bundle(temp)
        ok &= test_migration(temp)
        ok &= check("真实 activity.db 未被测试引用", str(storage.db_path).startswith(str(temp)))

    print("\n" + "=" * 46)
    print(f"{PASS} 全部通过" if ok else f"{FAIL} 有失败项，需要修复")
    print("=" * 46)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
