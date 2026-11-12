"""演示模式与示例数据构建。

供 `tools/seed_demo.py` 与 `MaoLog.exe --demo` 共用：
在隔离的 demo.db 中生成当日全天学业/开发时间线、模拟缩略图、每日总结与 v2 复盘数据，
不读取也不修改用户的真实 activity.db。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

from .ai_profile import analyze_collaboration, save_collaboration
from .attest import build_process_report
from .outbound import PURPOSE_FRAME, PURPOSE_SUMMARY, PURPOSE_TEST, set_future_outbound
from .storage import Storage
from .time_estimate import productive_minutes_from_storage, set_actual, set_plan
from .v2_demo import seed_demo_outbound
from .v2_storage import V2Storage

# (开始时间, 持续分钟, 应用, 窗口标题, 分类, 活动, 详情, 专注度, 是否有产出)
DEMO_PLAN: list[tuple[str, int, str, str, str, str, str, int, int]] = [
    ("09:02", 43, "Code.exe", "mao - main.py - Visual Studio Code", "工作", "编程开发",
     "在 VS Code 里编写看板界面的时间轴组件", 5, 1),
    ("09:45", 9, "WeChat.exe", "微信", "沟通", "即时通讯",
     "与团队成员沟通比赛任务分工", 3, 0),
    ("09:54", 46, "Code.exe", "analyzer.py - Visual Studio Code", "工作", "编程开发",
     "调试屏幕采集线程与 AI 分析队列并发逻辑", 5, 1),
    ("10:40", 24, "chrome.exe", "PyQt6 QThread 跨线程通信 - 搜索", "学习", "查阅资料",
     "检索 PyQt6 跨线程安全信号与 SQLite WAL 写法", 4, 1),
    ("11:04", 31, "Code.exe", "settings_dialog.py - Visual Studio Code", "工作", "编程开发",
     "完善设置中心 AI 服务商与免 Key 本地引擎切换", 5, 1),
    ("11:35", 22, "WindowsTerminal.exe", "PowerShell", "工作", "程序调试",
     "运行自动化测试验证界面启动与记录落盘", 4, 1),
    ("14:03", 27, "WINWORD.EXE", "楚师智学_创意方案书.docx - Word", "工作", "文档写作",
     "梳理课程与校园场景下的 AI 学业管理方案", 4, 1),
    ("14:30", 38, "chrome.exe", "哔哩哔哩 - 科技区", "娱乐", "视频观看",
     "休息浏览视频内容（识别为娱乐分支时段）", 2, 0),
    ("15:08", 52, "Code.exe", "main_window.py - Visual Studio Code", "工作", "编程开发",
     "完善手帐看板每日总结卡片与状态反馈条", 5, 1),
    ("16:00", 18, "WeChat.exe", "微信", "沟通", "即时通讯",
     "回复校园交流群消息与资料核对", 3, 1),
    ("16:18", 49, "chrome.exe", "机器学习导论 - 第 3 讲 - 在线课堂", "学习", "网课学习",
     "观看在线课程回放并整理核心知识点", 4, 1),
    ("17:07", 33, "Code.exe", "theme.py - Visual Studio Code", "工作", "编程开发",
     "调整纸质手帐风与深色主题视觉细节", 5, 1),
    ("17:40", 16, "explorer.exe", "文件资源管理器", "系统", "文件管理",
     "按日期归档项目资料与实验数据", 3, 1),
]


def make_demo_shot(path: Path, app: str, title: str, category: str, detail: str) -> None:
    """绘制一张演示用屏幕缩略图，使时间轴回看界面完整可点击。"""
    palette = {
        "工作": ("#1E2430", "#5B8CFF"),
        "学习": ("#1B2A26", "#3DD9A0"),
        "娱乐": ("#2A211C", "#FF8F5C"),
        "沟通": ("#241F2E", "#B08CFF"),
        "系统": ("#22252B", "#8B94A3"),
    }
    bg, accent = palette.get(category, ("#202430", "#5B8CFF"))

    img = Image.new("RGB", (1280, 720), bg)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, 1280, 40], fill="#0F1218")
    d.ellipse([16, 15, 28, 27], fill="#FF6B6B")
    d.ellipse([36, 15, 48, 27], fill="#FFB547")
    d.ellipse([56, 15, 68, 27], fill="#3DD9A0")
    d.text((86, 14), f"{app}  -  {title}", fill="#9BA3AF")

    d.rectangle([0, 40, 210, 720], fill="#171B22")
    for i in range(9):
        d.rectangle([22, 78 + i * 34, 22 + random.randint(60, 150), 92 + i * 34], fill="#2A3040")

    y = 90
    for _ in range(15):
        width = random.randint(180, 760)
        color = accent if random.random() > 0.66 else "#333B4A"
        d.rectangle([250, y, 250 + width, y + 11], fill=color)
        y += 30

    d.rectangle([0, 690, 1280, 720], fill=accent)
    d.text((16, 699), f"{category} | {detail}", fill="#0F1218")

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=82)


def ensure_demo_day(db_path: Path, shots_dir: Path, force_reseed: bool = False) -> Storage:
    """确保 demo 数据库在当天有完整的演示数据与 v2 复盘记录。"""
    if force_reseed and db_path.exists():
        db_path.unlink()

    storage = Storage(db_path)
    day = datetime.now().strftime("%Y-%m-%d")
    if not force_reseed and storage.counts(day)["total"] > 0:
        return storage

    shots_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    random.seed(7)

    for start, minutes, app, title, cat, act, detail, focus, prod in DEMO_PLAN:
        begin = datetime.strptime(f"{day} {start}", "%Y-%m-%d %H:%M")
        img_path = shots_dir / f"{cat}_{act}_{start.replace(':', '')}.jpg"
        if not img_path.exists() or force_reseed:
            make_demo_shot(img_path, app, title, cat, detail)

        for i in range(max(1, minutes)):
            ts = begin + timedelta(seconds=i * 60)
            sid = storage.add_snapshot(
                ts=ts,
                image_path=str(img_path),
                thumb_path=None,
                app_name=app,
                window_title=title,
                status="done",
            )
            storage.save_analysis(
                sid,
                {
                    "category": cat,
                    "activity": act,
                    "detail": detail,
                    "focus_score": min(5, max(1, focus + rng.choice([0, 0, 0, -1]))),
                    "is_productive": bool(prod),
                },
            )

    storage.save_daily_summary(
        day=day,
        summary=(
            "今天整体投入保持高位，主要集中在核心模块开发（约 227 分钟）与专业课程/资料查阅（约 73 分钟）。"
            "上午多段连续编码聚焦稳定，下午 14:30 前后出现 1 段娱乐视频分心，但随后快速恢复至网课与功能收尾。"
        ),
        highlights=[
            "上午「编程开发」与「查阅资料」形成稳定连续块，产出专注度均在 4 分以上",
            "本地免 Key 双通道引擎与变化复用机制将额外推理调用压降至低频区间",
            "下午网课学习与方案梳理穿插推进，有效完成了当日核心任务闭环",
        ],
        suggestions=[
            "午休后娱乐分心约 38 分钟，可在开始前设置番茄阶段与估时校准目标",
            "高频沟通后建议预留 5 分钟收口缓冲，再切入深度编码或文档撰写",
        ],
        model="demo-local-summary",
    )

    v2 = V2Storage(db_path)
    day_dt = datetime.strptime(day, "%Y-%m-%d")
    start_ts = f"{day} 00:00:00"
    end_ts = f"{day} 23:59:59"
    set_plan(v2, day, 360)
    set_actual(v2, day, productive_minutes_from_storage(v2, day, interval=60))
    collab = analyze_collaboration(
        v2,
        task_context="楚师智学原型迭代与课程复习",
        start_ts=start_ts,
        end_ts=end_ts,
        interval=60,
    )
    save_collaboration(v2, collab)
    if v2.table_counts()["outbound_log"] == 0:
        for purpose in (PURPOSE_FRAME, PURPOSE_SUMMARY, PURPOSE_TEST):
            set_future_outbound(v2, purpose, True)
        seed_demo_outbound(v2, day_dt)
        for purpose in (PURPOSE_FRAME, PURPOSE_SUMMARY, PURPOSE_TEST):
            set_future_outbound(v2, purpose, False)
    build_process_report(v2, task_name="当日学业与开发", start_ts=start_ts, end_ts=end_ts, interval=60)

    return storage
