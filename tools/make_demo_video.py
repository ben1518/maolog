"""自动渲染「楚师智学（MaoLog）」1080P 高清原型演示视频（含配音、字幕与实机交互）。

参考《ClubCopilot社团智脑》视频规范，全部画面直接通过 PyQt6 实机离屏渲染采集，
搭配离线中文配音、轻柔环境配乐、平滑指针动效与底部浮动字幕条。

输出：
  Desktop/主题一-创意方案-楚师智学-李政寰-2024级数字媒体技术班/作品本体/原型演示视频/楚师智学_原型演示视频_1080P.mp4

用法：
  .venv/Scripts/python.exe -B -X utf8 tools/make_demo_video.py
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import QApplication, QTabWidget

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.achievements import extract_achievements  # noqa: E402
from core.config import Config  # noqa: E402
from core.storage import Storage  # noqa: E402
from core.v2_demo import build_demo_bundle  # noqa: E402
from ui.achievement_card import AchievementDialog  # noqa: E402
from ui.ai_profile_dialog import AIProfileDialog  # noqa: E402
from ui.desktop_pet import DesktopPetWindow  # noqa: E402
from ui.fonts import load_bundled_fonts  # noqa: E402
from ui.main_window import ImageViewer, MainWindow  # noqa: E402
from ui.settings_dialog import SettingsDialog  # noqa: E402
from ui.study_review_dialog import StudyReviewDialog  # noqa: E402
from ui.theme import APP_QSS  # noqa: E402
from ui.time_estimate_dialog import TimeEstimateDialog  # noqa: E402
from ui.v2_preview import V2PreviewWindow  # noqa: E402

VIDEO_W = 1920
VIDEO_H = 1080
FPS = 30

SUBMISSION_VIDEO = (
    Path.home()
    / "Desktop"
    / "主题一-创意方案-楚师智学-李政寰-2024级数字媒体技术班"
    / "作品本体"
    / "原型演示视频"
    / "楚师智学_原型演示视频_1080P.mp4"
)


@dataclass
class SceneSpec:
    key: str
    narration: str
    subtitle: str
    image_key: str
    cursor_from: tuple[float, float] | None = None
    cursor_to: tuple[float, float] | None = None
    click_at: float | None = None  # 0..1 normalized progress when click ripple triggers
    overlay_key: str | None = None
    overlay_scale: float = 0.88


SCENES: list[SceneSpec] = [
    SceneSpec(
        key="opening",
        narration="大家好，这是主题一参赛作品《楚师智学》。一个基于屏幕感知与 MobileClaw 的主动式个人学业管理平台。",
        subtitle="《楚师智学 · MaoLog》—— 基于屏幕感知与 MobileClaw 的主动式学业平台",
        image_key="opening_card",
    ),
    SceneSpec(
        key="dashboard_overview",
        narration="很多同学电脑前学了一整天，晚上却说不清时间去哪了。楚师智学无需打卡，在后台无感感知屏幕，生成温暖的手帐时间轴与日终总结。",
        subtitle="无感采集自动沉淀全天手帐看板：统计卡、分类环形图、应用排行与 AI 日终总结",
        image_key="main_all",
        cursor_from=(0.24, 0.22),
        cursor_to=(0.76, 0.72),
        click_at=0.55,
    ),
    SceneSpec(
        key="filter_work",
        narration="时间轴支持按工作、学习、娱乐、沟通、系统快速筛选与关键词定位，帮你一眼看清有效专注与时间黑洞。",
        subtitle="支持「工作 / 学习 / 娱乐 / 沟通 / 系统」六类一键筛选与实时搜索定位",
        image_key="main_work",
        cursor_from=(0.22, 0.34),
        cursor_to=(0.30, 0.34),
        click_at=0.35,
    ),
    SceneSpec(
        key="image_proof",
        narration="每条结论都不是黑箱。点击时间轴任意一段就能调出当时原图自证；遇到归类偏差，右键修改即可永久记住偏好。",
        subtitle="点击时间轴可回看原始屏幕画面（原图不出本机），右键纠偏自动记住习惯",
        image_key="main_all",
        overlay_key="image_viewer",
        overlay_scale=0.84,
        cursor_from=(0.34, 0.56),
        cursor_to=(0.56, 0.52),
        click_at=0.40,
    ),
    SceneSpec(
        key="pet_and_achieve",
        narration="右下角蘑菇小精灵会随学习状态呼吸互动，主动提醒休息，并一键生成手绘风格每日学业成就卡片。",
        subtitle="蘑菇小精灵桌面陪伴与一键生成每日手绘成就卡片，让坚持有正反馈",
        image_key="main_with_pet",
        overlay_key="achievement",
        overlay_scale=0.82,
        cursor_from=(0.86, 0.78),
        cursor_to=(0.54, 0.56),
        click_at=0.45,
    ),
    SceneSpec(
        key="study_review",
        narration="v2 版本把记录进一步提炼为学习过程复盘，自动诊断最长连续心流、打断次数与启动拖延，一键导出标准 PDF 报告。",
        subtitle="v2 学习过程复盘：自动识别阶段切换、连续心流与卡点，支持 HTML / PDF 导出",
        image_key="main_all",
        overlay_key="study_review",
        overlay_scale=0.84,
        cursor_from=(0.45, 0.40),
        cursor_to=(0.66, 0.80),
        click_at=0.65,
    ),
    SceneSpec(
        key="ai_profile",
        narration="针对同学高频使用 AI 的习惯，系统会启发式识别先思后问、边做边问还是直接要答案，并支持查看量化依据与手动改判。",
        subtitle="AI 协作画像：透明展示窗口切换依据，支持学生手动改判且保留机器原判",
        image_key="main_all",
        overlay_key="ai_profile",
        overlay_scale=0.84,
        cursor_from=(0.42, 0.38),
        cursor_to=(0.62, 0.66),
        click_at=0.50,
    ),
    SceneSpec(
        key="estimate_and_passport",
        narration="配合估时校准与数据护照面板，既能看清计划与实际投入偏差，也能按用途逐项开关外发权限，外发字节透明可查、随时阻断。",
        subtitle="估时校准对照计划偏差 + 实时外发台账与 JSON《数据护照》死守隐私底线",
        image_key="v2_passport",
        cursor_from=(0.36, 0.42),
        cursor_to=(0.68, 0.55),
        click_at=0.55,
    ),
    SceneSpec(
        key="nokey_and_mobileclaw",
        narration="软件内置本地免 Key 模式，无需 API Key 即可开箱运行；接入中国移动 MobileClaw 后，还可通过脱敏技能包自动推送每日学习规划。",
        subtitle="本地免 Key 规则引擎开箱即用 + MobileClaw 脱敏桥接技能包联动规划",
        image_key="settings_ai",
        overlay_key="mobileclaw_card",
        overlay_scale=0.86,
        cursor_from=(0.38, 0.45),
        cursor_to=(0.64, 0.62),
        click_at=0.45,
    ),
    SceneSpec(
        key="closing",
        narration="目前《楚师智学》已完成桌面端与单文件便携版封装，感谢各位评委老师审阅！",
        subtitle="《楚师智学（MaoLog）》—— 已完成便携版 EXE 封装与全套验证，感谢评委老师！",
        image_key="closing_card",
    ),
]


def _detect_windows_proxy() -> str | None:
    import os
    import winreg

    for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(k, "").strip()
        if v:
            return v if "://" in v else f"http://{v}"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            if enabled and server:
                s = str(server).strip()
                if "=" in s:
                    for part in s.split(";"):
                        if part.lower().startswith(("https=", "http=")):
                            s = part.split("=", 1)[1].strip()
                            break
                return s if "://" in s else f"http://{s}"
    except OSError:
        pass
    return None


def synthesize_tts_wav(text: str, out_wav: Path) -> float:
    """优先使用 edge-tts（zh-CN-XiaoxiaoNeural）合成自然中文旁白，失败时回退本地 SAPI。"""
    raw_audio = out_wav.with_name(out_wav.stem + "_raw.mp3")
    used_edge = False
    try:
        import asyncio
        import edge_tts

        proxy = _detect_windows_proxy()
        asyncio.run(
            edge_tts.Communicate(
                text,
                voice="zh-CN-XiaoxiaoNeural",
                rate="+2%",
                proxy=proxy,
            ).save(str(raw_audio))
        )
        if raw_audio.exists() and raw_audio.stat().st_size > 500:
            used_edge = True
    except Exception as exc:
        print(f"  [TTS 回退提示] edge-tts 调用失败 ({exc})，改用本地离线语音", flush=True)

    if not used_edge:
        raw_audio = out_wav.with_name(out_wav.stem + "_raw.wav")
        ps_script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "try { $s.SelectVoice('Microsoft Huihui Desktop') } catch {}; "
            "$s.Rate = 2; "
            f"$s.SetOutputToWaveFile('{raw_audio}'); "
            f"$s.Speak('{text.replace(chr(39), '')}'); "
            "$s.Dispose()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # 直接高精度重采样为 44100Hz 立体声并补极短停顿，避免 single-pass loudnorm 与反向裁剪引入电音失真
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(raw_audio),
            "-af",
            "afade=t=in:st=0:d=0.015,apad=pad_dur=0.40",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(out_wav),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    raw_audio.unlink(missing_ok=True)
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(out_wav),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return max(2.5, float(probe.stdout.strip()))


def build_audio_track(wav_files: list[Path], final_audio: Path, total_sec: float) -> None:
    """纯净串联全部旁白（不叠合成振荡底噪），高通滤除超低频杂音。"""
    _ = total_sec
    concat_txt = final_audio.with_suffix(".txt")
    concat_txt.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in wav_files),
        encoding="utf-8",
    )
    voice_wav = final_audio.with_name("voice_merged.wav")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-c:a",
            "pcm_s16le",
            str(voice_wav),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(voice_wav),
            "-af",
            "highpass=f=80",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(final_audio),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def render_parchment_card(
    top_tag: str,
    title: str,
    subtitle: str,
    bullets: list[str],
    footer: str,
) -> QImage:
    """绘制与《ClubCopilot》一致的开篇/致谢暖色手帐卡片。"""
    w, h = 1480, 840
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    card = QRectF(8, 8, w - 16, h - 16)
    p.setBrush(QColor("#FBF6EA"))
    p.setPen(QPen(QColor("#D8A85A"), 3))
    p.drawRoundedRect(card, 24, 24)

    p.setPen(QColor("#B6462F"))
    p.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.DemiBold))
    p.drawText(QRectF(80, 48, w - 160, 36), Qt.AlignmentFlag.AlignCenter, top_tag)

    p.setPen(QPen(QColor("#C85D44"), 2))
    p.drawLine(QPointF(96, 102), QPointF(w - 96, 102))

    p.setPen(QColor("#1F2630"))
    p.setFont(QFont("LXGW WenKai", 46, QFont.Weight.Bold))
    p.drawText(QRectF(80, 175, w - 160, 82), Qt.AlignmentFlag.AlignCenter, title)

    p.setPen(QColor("#288262"))
    p.setFont(QFont("Microsoft YaHei", 21, QFont.Weight.DemiBold))
    p.drawText(QRectF(80, 272, w - 160, 44), Qt.AlignmentFlag.AlignCenter, subtitle)

    y = 378
    p.setFont(QFont("Microsoft YaHei", 18))
    for line in bullets:
        p.setBrush(QColor("#1F2630"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(192, y + 16), 9, 9)
        p.setPen(QColor("#2A323D"))
        p.drawText(QRectF(220, y, w - 310, 42), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
        y += 66

    p.setPen(QColor("#6B7280"))
    p.setFont(QFont("Microsoft YaHei", 14))
    p.drawText(QRectF(80, h - 76, w - 160, 34), Qt.AlignmentFlag.AlignCenter, footer)
    p.end()
    return img


def render_mobileclaw_bridge_card() -> QImage:
    """绘制 MobileClaw 脱敏技能包数据流实时演示弹窗。"""
    w, h = 1120, 680
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    p.setBrush(QColor("#232227"))
    p.setPen(QPen(QColor("#D8A85A"), 2.5))
    p.drawRoundedRect(QRectF(4, 4, w - 8, h - 8), 20, 20)

    p.setPen(QColor("#F5EFEB"))
    p.setFont(QFont("Microsoft YaHei", 21, QFont.Weight.Bold))
    p.drawText(QRectF(36, 24, w - 72, 40), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "MobileClaw Bridge Skill · 脱敏数据流联调实况")

    p.setPen(QColor("#5FA876"))
    p.setFont(QFont("Microsoft YaHei", 14))
    p.drawText(QRectF(36, 66, w - 72, 28), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "scripts/export_bridge.py  →  严守隐私契约（无截图 · 无窗口标题 · 无原提示词）")

    sample_json = {
        "schema": "chushi-zhixue.mobileclaw-bridge.v1",
        "privacy_guarantee": {"raw_screenshots": False, "window_titles": False},
        "overview": {"records": 375, "tracked_minutes": 375.0, "avg_focus": 4.57},
        "learning_review": {
            "headline": "有记录的 375 分钟里，动手时间 295 分钟",
            "focus_minutes": 220,
            "stage_switches": 9,
        },
        "ai_collaboration": {"mode": "边做边问"},
        "time_estimate": {"planned_minutes": 420, "actual_minutes": 375},
    }
    p.setBrush(QColor("#17161A"))
    p.setPen(QPen(QColor("#434148"), 1.5))
    p.drawRoundedRect(QRectF(36, 112, 560, 520), 12, 12)
    p.setPen(QColor("#9CDCFE"))
    p.setFont(QFont("Consolas", 13))
    p.drawText(QRectF(56, 130, 520, 490), Qt.TextFlag.TextWordWrap,
               json.dumps(sample_json, ensure_ascii=False, indent=2))

    # 右侧 MobileClaw 规划输出卡
    p.setBrush(QColor("#2B2930"))
    p.setPen(QPen(QColor("#5FA876"), 1.8))
    p.drawRoundedRect(QRectF(624, 112, 460, 520), 12, 12)
    p.setPen(QColor("#E5A93C"))
    p.setFont(QFont("Microsoft YaHei", 15, QFont.Weight.Bold))
    p.drawText(QRectF(646, 130, 420, 40), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "MobileClaw · 2500万免费Token 建议推送")

    tips = (
        "1. 今日节奏亮点\n"
        "   下午 14:00-17:39 保持连续 220 分钟高专注输出，\n"
        "   「写作 + 编程」动手占比高达 79%，协作处于健康的\n"
        "   「边做边问」区间。\n\n"
        "2. 明日微调建议\n"
        "   • 将核心作业继续固定于 14:00-17:30 黄金块；\n"
        "   • 今日计划 420 分钟 vs 实际 375 分钟，明日规划\n"
        "     建议预留 45 分钟弹性缓冲。\n\n"
        "3. 触达渠道：支持微信 / 飞书晚间 22:00 自动推送"
    )
    p.setPen(QColor("#E8E1D5"))
    p.setFont(QFont("Microsoft YaHei", 14))
    p.drawText(QRectF(648, 184, 412, 420), Qt.TextFlag.TextWordWrap, tips)
    p.end()
    return img


def capture_live_screens(output_dir: Path) -> dict[str, QImage]:
    """用 WA_DontShowOnScreen 实机渲染 MaoLog 各界面与交互弹出状态。"""
    app = QApplication.instance() or QApplication(sys.argv)
    load_bundled_fonts()
    app.setStyleSheet(APP_QSS)

    demo_db = ROOT / "data" / "demo.db"
    storage = Storage(demo_db)
    cfg = Config(ROOT / "data" / "demo_config.json")
    cfg.set("ai.local_fallback", True, save=False)

    win = MainWindow(cfg, storage)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.resize(1380, 920)
    win.show()
    win.donut._anim.stop()
    win.donut.set_progress(1.0)
    for _ in range(6):
        app.processEvents()
    win.donut._anim.stop()
    win.donut.set_progress(1.0)

    def grab_img(widget) -> QImage:
        return widget.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    shots: dict[str, QImage] = {}
    shots["main_all"] = grab_img(win)

    # 筛选「工作」
    if "工作" in win._filter_pills:
        win._filter_pills["工作"].click()
        for _ in range(4):
            app.processEvents()
        shots["main_work"] = grab_img(win)
        win._filter_pills["全部"].click()
        for _ in range(4):
            app.processEvents()
    else:
        shots["main_work"] = shots["main_all"]

    # 带桌宠的主界面截图
    pet = DesktopPetWindow(cfg, storage)
    pet.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    pet.show()
    pet.show_bubble("今天已连续专注 220 分钟啦，注意喝口水休息一下~ 🍄", tone="praise", duration_ms=10000)
    for _ in range(4):
        app.processEvents()
    pet_img = grab_img(pet)
    main_pet = shots["main_all"].copy()
    pm = QPainter(main_pet)
    pm.drawImage(main_pet.width() - pet_img.width() - 18, main_pet.height() - pet_img.height() - 18, pet_img)
    pm.end()
    shots["main_with_pet"] = main_pet
    pet.close()

    # 原图回看弹出框
    segs = storage.segments(win._day_str(), interval=cfg.interval_seconds)
    seg0 = next((s for s in segs if s.get("image_path") and Path(s["image_path"]).exists()), None)
    img_path = seg0["image_path"] if seg0 else str(ROOT / "assets" / "figures" / "fig5_dashboard.png")
    cap_txt = (
        f"{seg0.get('start_text')} - {seg0.get('end_text')} · {seg0.get('activity')} · {seg0.get('detail')}"
        if seg0
        else "09:02 - 09:45 · 编程开发 · 在 VS Code 里写看板界面的时间轴组件"
    )
    viewer = ImageViewer(img_path, cap_txt)
    viewer.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    viewer.resize(1040, 700)
    viewer.show()
    for _ in range(4):
        app.processEvents()
    shots["image_viewer"] = grab_img(viewer)
    viewer.close()

    # 成就手帐卡片
    ach = extract_achievements(storage, win._day_str(), interval=cfg.interval_seconds)
    ach_dlg = AchievementDialog(None, ach)
    ach_dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    ach_dlg.show()
    for _ in range(4):
        app.processEvents()
    shots["achievement"] = grab_img(ach_dlg)
    ach_dlg.close()
    win.prepare_quit()
    win.close()

    # v2 模块（学习复盘、AI 协作、数据护照、估时）
    v2_db = ROOT / "data" / "v2_preview" / "v2_preview.db"
    bundle = build_demo_bundle(v2_db)
    v2_day = bundle["day"].strftime("%Y-%m-%d")
    v2_cfg = Config(ROOT / "data" / "v2_preview" / "preview_config.json")

    review_dlg = StudyReviewDialog(v2_cfg, bundle["storage"], v2_day)
    review_dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    review_dlg.resize(820, 760)
    review_dlg.show()
    for _ in range(4):
        app.processEvents()
    shots["study_review"] = grab_img(review_dlg)
    review_dlg.close()

    ai_dlg = AIProfileDialog(v2_cfg, bundle["storage"], v2_day)
    ai_dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    ai_dlg.resize(860, 760)
    ai_dlg.show()
    for _ in range(4):
        app.processEvents()
    shots["ai_profile"] = grab_img(ai_dlg)
    ai_dlg.close()

    v2_win = V2PreviewWindow(
        bundle["storage"], bundle["report"], bundle["judgment"], bundle["passport"], bundle["estimate"], output_dir
    )
    v2_win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    v2_win.resize(1260, 860)
    v2_win.show()
    tabs = v2_win.findChild(QTabWidget)
    if tabs is not None and tabs.count() >= 3:
        tabs.setCurrentIndex(2)
    for _ in range(5):
        app.processEvents()
    shots["v2_passport"] = grab_img(v2_win)
    v2_win.close()

    # 设置中心（含本地免 Key 开关）
    sdlg = SettingsDialog(cfg)
    sdlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    sdlg.resize(740, 620)
    sdlg.show()
    for _ in range(4):
        app.processEvents()
    shots["settings_ai"] = grab_img(sdlg)
    sdlg.close()

    # 卡片视图
    shots["opening_card"] = render_parchment_card(
        "楚雄师范学院计算机与智能技术学院 · 首届「动感地带杯」AI创新应用大赛",
        "楚师智学 · MaoLog",
        "参赛主题：主题一「AI赋能校园」—— 校园应用创意方案（个人学业管理平台）",
        [
            "核心定位：面向大学生自主学习的本地隐私优先主动式学业助手",
            "核心能力：手帐无感看板 · v2 学习过程复盘 · AI 协作画像 · 估时与数据护照",
            "技术特色：截屏前拦截 · 本地免 Key 规则兜底 · MobileClaw 脱敏桥接技能包",
        ],
        "记录每一段真实投入 · 主题一原型全景实机演示（1080P 高清版）",
    )
    shots["closing_card"] = render_parchment_card(
        "楚雄师范学院计算机与智能技术学院 · 首届「动感地带杯」AI创新应用大赛",
        "感谢各位评委老师审阅",
        "楚师智学（MaoLog） · 主题一：校园应用创意方案",
        [
            "主创人员：李政寰",
            "所在学院与班级：计算机与智能技术学院 · 2024级数字媒体技术班",
            "所用 AI 工具清单：中国移动 MobileClaw、通义千问 VL / 智谱 GLM-4V、本地免 Key 规则引擎",
        ],
        "本地优先 · 隐私可控 · 过程可回溯 · 已完成便携版 EXE 封装与全套测试",
    )
    shots["mobileclaw_card"] = render_mobileclaw_bridge_card()
    return shots


def draw_cursor_and_ripple(p: QPainter, x: float, y: float, ripple: float | None) -> None:
    if ripple is not None and 0.0 <= ripple <= 1.0:
        r = 10 + ripple * 36
        alpha = int((1.0 - ripple) * 210)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(229, 169, 60, alpha), 3))
        p.drawEllipse(QPointF(x, y), r, r)

    # 手绘风格高对比指针箭头
    arrow = QPolygonF(
        [
            QPointF(x, y),
            QPointF(x, y + 26),
            QPointF(x + 7, y + 20),
            QPointF(x + 13, y + 31),
            QPointF(x + 18, y + 29),
            QPointF(x + 12, y + 18),
            QPointF(x + 21, y + 18),
        ]
    )
    p.setBrush(QColor("#1A191D"))
    p.setPen(QPen(QColor("#FAF5EA"), 2.2))
    p.drawPolygon(arrow)


def draw_subtitle_pill(p: QPainter, text: str) -> None:
    font = QFont("Microsoft YaHei", 19, QFont.Weight.DemiBold)
    p.setFont(font)
    fm = QFontMetrics(font)
    tw = fm.horizontalAdvance(text)
    pill_w = min(VIDEO_W - 140, tw + 74)
    pill_h = 54
    px = (VIDEO_W - pill_w) / 2.0
    py = VIDEO_H - 74

    p.setBrush(QColor(24, 23, 28, 235))
    p.setPen(QPen(QColor("#D8A85A"), 1.6))
    p.drawRoundedRect(QRectF(px, py, pill_w, pill_h), 14, 14)

    p.setPen(QColor("#F7F3EB"))
    p.drawText(QRectF(px + 20, py, pill_w - 40, pill_h), int(Qt.AlignmentFlag.AlignCenter), text)


def compose_stage_frame(shots: dict[str, QImage], scene: SceneSpec, t_norm: float) -> QImage:
    """合成单帧 1920x1080 BGRA 图像。"""
    frame = QImage(VIDEO_W, VIDEO_H, QImage.Format.Format_ARGB32_Premultiplied)
    frame.fill(QColor("#17161B"))
    p = QPainter(frame)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # 背景渐变（沉稳暗色工作台）
    grad = QLinearGradient(0, 0, VIDEO_W, VIDEO_H)
    grad.setColorAt(0.0, QColor("#17161B"))
    grad.setColorAt(1.0, QColor("#211F26"))
    p.fillRect(QRectF(0, 0, VIDEO_W, VIDEO_H), grad)

    base = shots[scene.image_key]
    if scene.image_key in ("opening_card", "closing_card"):
        tx = (VIDEO_W - base.width()) / 2.0
        ty = (VIDEO_H - base.height()) / 2.0 - 10
        p.setBrush(QColor(0, 0, 0, 110))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(tx + 12, ty + 14, base.width() - 16, base.height() - 16), 24, 24)
        p.drawImage(QPointF(tx, ty), base)
    else:
        stage_w, stage_h = 1520, 920
        sx = (VIDEO_W - stage_w) / 2.0
        sy = 42.0
        p.setBrush(QColor(0, 0, 0, 120))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(sx + 8, sy + 12, stage_w, stage_h), 18, 18)

        scaled = base.scaled(
            stage_w,
            stage_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        bx = sx + (stage_w - scaled.width()) / 2.0
        by = sy + (stage_h - scaled.height()) / 2.0
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(bx, by, scaled.width(), scaled.height()), 14, 14)
        p.save()
        p.setClipPath(clip)
        p.drawImage(QPointF(bx, by), scaled)
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#57535A"), 2))
        p.drawRoundedRect(QRectF(bx, by, scaled.width(), scaled.height()), 14, 14)

        if scene.overlay_key and scene.overlay_key in shots:
            ov = shots[scene.overlay_key]
            # 对话框轻微压暗背景并柔和弹入
            appear = min(1.0, t_norm / 0.14)
            ease = 1.0 - (1.0 - appear) ** 3
            p.fillRect(QRectF(bx, by, scaled.width(), scaled.height()), QColor(12, 11, 14, int(145 * ease)))
            max_ow = int(stage_w * scene.overlay_scale)
            max_oh = int(stage_h * scene.overlay_scale)
            ov_scaled = ov.scaled(
                max_ow,
                max_oh,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            ox = bx + (scaled.width() - ov_scaled.width()) / 2.0
            oy = by + (scaled.height() - ov_scaled.height()) / 2.0 + (1.0 - ease) * 18.0
            p.setOpacity(ease)
            p.setBrush(QColor(0, 0, 0, 140))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(ox + 8, oy + 10, ov_scaled.width(), ov_scaled.height()), 14, 14)
            p.drawImage(QPointF(ox, oy), ov_scaled)
            p.setOpacity(1.0)

    if scene.cursor_from and scene.cursor_to:
        # 三次缓动移动鼠标指针
        move_p = min(1.0, max(0.0, (t_norm - 0.08) / 0.72))
        e = move_p * move_p * (3.0 - 2.0 * move_p)
        cx = (scene.cursor_from[0] + (scene.cursor_to[0] - scene.cursor_from[0]) * e) * VIDEO_W
        cy = (scene.cursor_from[1] + (scene.cursor_to[1] - scene.cursor_from[1]) * e) * VIDEO_H
        ripple = None
        if scene.click_at is not None and scene.click_at <= t_norm <= scene.click_at + 0.18:
            ripple = (t_norm - scene.click_at) / 0.18
        draw_cursor_and_ripple(p, cx, cy, ripple)

    draw_subtitle_pill(p, scene.subtitle)
    p.end()
    return frame


def blend_images(img_a: QImage, img_b: QImage, alpha: float) -> QImage:
    out = img_a.copy()
    p = QPainter(out)
    p.setOpacity(alpha)
    p.drawImage(0, 0, img_b)
    p.end()
    return out


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    if "--capture" in sys.argv:
        idx = sys.argv.index("--capture")
        shots_dir = Path(sys.argv[idx + 1])
        shots_dir.mkdir(parents=True, exist_ok=True)
        shots = capture_live_screens(shots_dir)
        for key, img in shots.items():
            img.save(str(shots_dir / f"{key}.png"))
        import os

        os._exit(0)

    SUBMISSION_VIDEO.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="maolog_vid_") as tmp:
        tmp_dir = Path(tmp)
        shots_dir = tmp_dir / "shots"
        print("[1/4] 正在采集实机 PyQt6 界面画面...", flush=True)
        subprocess.run(
            [sys.executable, "-u", "-B", "-X", "utf8", str(Path(__file__).resolve()), "--capture", str(shots_dir)],
            check=True,
        )
        shots: dict[str, QImage] = {}
        for p_img in shots_dir.glob("*.png"):
            shots[p_img.stem] = QImage(str(p_img)).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

        print("[2/4] 正在合成中文旁白与环境配乐...", flush=True)
        wav_files: list[Path] = []
        durations: list[float] = []
        for idx, sc in enumerate(SCENES):
            wpath = tmp_dir / f"seg_{idx:02d}.wav"
            dur = synthesize_tts_wav(sc.narration, wpath)
            wav_files.append(wpath)
            durations.append(dur)
            print(f"  - 片段 {idx:02d} ({sc.key}): {dur:.2f}s", flush=True)

        total_sec = sum(durations)
        audio_mix = tmp_dir / "final_audio.wav"
        build_audio_track(wav_files, audio_mix, total_sec)

        print(f"[3/4] 正在渲染 {total_sec:.1f}s @ 30fps 视频流 -> {SUBMISSION_VIDEO.name} ...", flush=True)
        ffmpeg_log = tmp_dir / "ffmpeg.log"
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "warning",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "bgra",
            "-s",
            f"{VIDEO_W}x{VIDEO_H}",
            "-r",
            str(FPS),
            "-i",
            "-",
            "-i",
            str(audio_mix),
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-level",
            "4.0",
            "-preset",
            "fast",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            "9500k",
            "-minrate",
            "9500k",
            "-maxrate",
            "9500k",
            "-bufsize",
            "19000k",
            "-x264-params",
            "nal-hrd=cbr",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            "-shortest",
            str(SUBMISSION_VIDEO),
        ]
        with open(ffmpeg_log, "w", encoding="utf-8") as log_f:
            proc = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=log_f,
            )
            assert proc.stdin is not None

            fade_frames = 8
            prev_last_frame: QImage | None = None
            for idx, (sc, dur) in enumerate(zip(SCENES, durations)):
                n_frames = max(15, round(dur * FPS))
                for f_idx in range(n_frames):
                    t_norm = f_idx / max(1, n_frames - 1)
                    frame = compose_stage_frame(shots, sc, t_norm)
                    if prev_last_frame is not None and f_idx < fade_frames:
                        frame = blend_images(prev_last_frame, frame, (f_idx + 1) / (fade_frames + 1))
                    b = frame.constBits().asstring(frame.sizeInBytes())
                    proc.stdin.write(b)
                    if f_idx == n_frames - 1:
                        prev_last_frame = frame
                print(f"  - 已编码场景 {idx + 1}/{len(SCENES)}: {sc.key} ({n_frames} 帧)", flush=True)

            proc.stdin.close()
            rc = proc.wait()
        if rc != 0:
            err = ffmpeg_log.read_text(encoding="utf-8", errors="ignore")
            raise RuntimeError(f"ffmpeg 编码失败 ({rc}): {err}")

    # 清除占位提示文件
    note_txt = SUBMISSION_VIDEO.parent / "视频放入说明.txt"
    note_txt.unlink(missing_ok=True)
    print(f"[4/4] 完成 -> {SUBMISSION_VIDEO} ({SUBMISSION_VIDEO.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
