"""学习过程整理与复盘：把行为元数据变成学生能读懂的节奏说明。

底层职责是整理阶段序列与数据缺口，解读交给 `core.learning_review`。
不读取作业正文，不识别作者，不保存导出事件；默认不导出窗口标题和截图。
"""

from __future__ import annotations

import html
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .learning_review import analyze_learning
from .safe_export import atomic_write_text, safe_output_path, temporary_pdf_path
from .storage import Storage
from .v2_storage import format_timestamp, validate_range

BROWSER_APPS = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "360se.exe",
    "360chrome.exe",
    "qqbrowser.exe",
}
WRITING_APPS = {
    "winword.exe",
    "wps.exe",
    "wpswriter.exe",
    "wordpad.exe",
    "notepad.exe",
    "notepad++.exe",
    "typora.exe",
    "notion.exe",
    "obsidian.exe",
}
CODING_APPS = {
    "code.exe",
    "cursor.exe",
    "pycharm64.exe",
    "idea64.exe",
    "devenv.exe",
    "sublime_text.exe",
    "webstorm64.exe",
    "goland64.exe",
    "rider64.exe",
}
READING_APPS = {
    "acrobat.exe",
    "acrord32.exe",
    "sumatrapdf.exe",
    "foxitreader.exe",
    "foxitpdfreader.exe",
    "wpspdf.exe",
}
AI_DESKTOP_APPS = {
    "kimi.exe",
    "doubao.exe",
    "chatgpt.exe",
    "claude.exe",
    "wenxin.exe",
    "tongyi.exe",
    "deepseek.exe",
}
AI_APP_BRANDS = (
    "deepseek",
    "kimi",
    "doubao",
    "豆包",
    "chatgpt",
    "claude",
    "gemini",
    "yiyan",
    "tongyi",
    "yuanbao",
    "chatglm",
    "sparkdesk",
)
AI_BROWSER_NAMES = {
    "kimi": {"对话", "聊天", "助手", "ai", "moonshot", "深度求索"},
    "豆包": {"对话", "聊天", "助手", "ai"},
    "deepseek": {"对话", "聊天", "助手", "ai", "深度求索"},
    "chatgpt": {"对话", "聊天", "助手", "ai", "openai"},
    "claude": {"对话", "聊天", "助手", "ai", "anthropic"},
    "gemini": {"对话", "聊天", "助手", "ai", "google"},
    "文心一言": {"对话", "聊天", "助手", "ai"},
    "通义千问": {"对话", "聊天", "助手", "ai"},
    "腾讯元宝": {"对话", "聊天", "助手", "ai"},
    "元宝": {"对话", "聊天", "助手", "ai"},
    "智谱清言": {"对话", "聊天", "助手", "ai"},
    "讯飞星火": {"对话", "聊天", "助手", "ai"},
    "perplexity": {"对话", "聊天", "助手", "ai", "搜索"},
}
AI_HOSTS = (
    "chat.openai.com",
    "chatgpt.com",
    "kimi.moonshot.cn",
    "kimi.com",
    "doubao.com",
    "deepseek.com",
    "claude.ai",
    "gemini.google.com",
    "yiyan.baidu.com",
    "tongyi.aliyun.com",
    "yuanbao.tencent.com",
    "chatglm.cn",
    "xfyun.cn",
)

PROCESS_LIMITATIONS = [
    "本说明只覆盖所选电脑和时段，不包含手机、纸质材料或其他设备上的活动。",
    "回访次数来自窗口标题，不等于文件保存或修改次数。",
    "本地记录可以被有技术能力的用户编辑，本说明不用于判断作者或内容真实性。",
    "未识别到的 AI 使用不能被解释为没有使用 AI。",
]


def _app_name(row: dict[str, Any]) -> str:
    from .app_names import to_canonical_process_name

    name = str(row.get("app_name") or "").strip().casefold()
    return to_canonical_process_name(name)


def _window_title(row: dict[str, Any]) -> str:
    return str(row.get("window_title") or "").strip()


def _browser_ai_title(title: str) -> bool:
    text = title.casefold()
    if any(host in text for host in AI_HOSTS):
        return True
    parts = [
        part.strip().casefold()
        for part in re.split(r"\s+[-–—|｜]\s+", title)
        if part.strip()
    ]
    for part in parts:
        if part in AI_BROWSER_NAMES:
            return True
        if any(part == f"{brand}官网" for brand in AI_BROWSER_NAMES):
            return True
    if not parts:
        return False
    hints = AI_BROWSER_NAMES.get(parts[0])
    if hints is None:
        return False
    rest = " ".join(parts[1:]).casefold()
    return not rest or any(hint in rest for hint in hints)


def is_ai_window(row: dict[str, Any]) -> bool:
    """按进程判定；文档、IDE、阅读器标题一律不参与 AI 匹配。"""
    app = _app_name(row)
    if app in AI_DESKTOP_APPS:
        return True
    if app in BROWSER_APPS:
        return _browser_ai_title(_window_title(row))
    if app in WRITING_APPS or app in CODING_APPS or app in READING_APPS:
        return False
    return any(brand in app for brand in AI_APP_BRANDS)


def _is_local_productive_app(row: dict[str, Any]) -> bool:
    app = _app_name(row)
    return app in WRITING_APPS or app in CODING_APPS or app in READING_APPS


def is_local_productive(row: dict[str, Any]) -> bool:
    """只认文档、IDE 和 PDF 阅读器，浏览器与 AI 窗口不算本地思考。"""
    if is_ai_window(row):
        return False
    return _is_local_productive_app(row)


def snapshot_stage(row: dict[str, Any]) -> str:
    app = _app_name(row)
    activity = str(row.get("activity") or "")
    if is_ai_window(row):
        return "AI 对话"
    if app in READING_APPS or _window_title(row).casefold().endswith(".pdf"):
        return "阅读"
    if app in CODING_APPS:
        return "编程"
    if app in WRITING_APPS:
        return "写作"
    if app in BROWSER_APPS:
        return "查阅"
    if "编程" in activity or "调试" in activity:
        return "编程"
    if "文档" in activity or "写作" in activity:
        return "写作"
    if row.get("category") == "学习":
        return "学习"
    return "其他"


def _document_key(row: dict[str, Any]) -> str | None:
    if snapshot_stage(row) != "写作":
        return None
    title = _window_title(row)
    if not title:
        return None
    title = re.sub(r"^[\s*●•]+", "", title)
    title = re.sub(
        r"(?i)\s*[\[(（](兼容模式|只读|受保护的视图)[\])）]\s*", "", title
    )
    title = re.sub(
        r"(?i)\s*[-–—]\s*(microsoft word|word|wps office|wps|libreoffice writer)\s*$",
        "",
        title,
    )
    title = re.sub(r"(?i)\.(docx?|wps|md|txt)$", "", title.strip())
    title = " ".join(title.split()).casefold().strip(" .-_")
    return title or None


def _valid_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        try:
            row_time = format_timestamp(row["ts"])
        except (KeyError, ValueError):
            continue
        item = dict(row)
        item["ts"] = row_time
        result.append(item)
    return result


def build_process_report(
    storage: Storage,
    task_name: str,
    start_ts: str,
    end_ts: str,
    interval: int = 60,
) -> dict[str, Any]:
    """只读生成报告，不写任务表、不写导出历史。"""
    task_name = task_name.strip()
    if not task_name:
        raise ValueError("任务名不能为空")
    if len(task_name) > 100:
        raise ValueError("任务名不能超过 100 个字符")
    if interval <= 0:
        raise ValueError("采样间隔必须大于 0")
    start, end = validate_range(start_ts, end_ts)
    rows = _valid_rows(storage.snapshots_between(start, end))
    analyzed = [row for row in rows if row.get("status") in ("done", "reused")]
    gap_limit = timedelta(seconds=interval * 3)

    gaps: list[dict[str, str]] = []
    if rows:
        first_time = datetime.strptime(rows[0]["ts"], "%Y-%m-%d %H:%M:%S")
        selection_start = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        if first_time - selection_start > gap_limit:
            gaps.append(
                {
                    "start": start,
                    "end": rows[0]["ts"],
                    "note": "所选范围开头没有足够记录，不作活动推断",
                }
            )
    for previous, current in zip(rows, rows[1:]):
        previous_time = datetime.strptime(previous["ts"], "%Y-%m-%d %H:%M:%S")
        current_time = datetime.strptime(current["ts"], "%Y-%m-%d %H:%M:%S")
        if current_time - previous_time > gap_limit:
            gaps.append(
                {
                    "start": previous["ts"],
                    "end": current["ts"],
                    "note": "该间隔没有足够记录，不作活动推断",
                }
            )
    if rows:
        last_time = datetime.strptime(rows[-1]["ts"], "%Y-%m-%d %H:%M:%S")
        selection_end = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
        if selection_end - last_time > gap_limit:
            gaps.append(
                {
                    "start": rows[-1]["ts"],
                    "end": end,
                    "note": "所选范围结尾没有足够记录，不作活动推断",
                }
            )

    runs: list[dict[str, Any]] = []
    for row in analyzed:
        stage = snapshot_stage(row)
        row_time = datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S")
        if runs:
            previous_time = datetime.strptime(runs[-1]["_last_ts"], "%Y-%m-%d %H:%M:%S")
            if runs[-1]["stage"] == stage and row_time - previous_time <= gap_limit:
                runs[-1]["end"] = row["ts"]
                runs[-1]["_last_ts"] = row["ts"]
                runs[-1]["samples"] += 1
                continue
        runs.append(
            {
                "stage": stage,
                "start": row["ts"],
                "end": row["ts"],
                "_last_ts": row["ts"],
                "samples": 1,
            }
        )
    for run in runs:
        run.pop("_last_ts", None)

    document_visits: Counter[str] = Counter()
    previous_document: str | None = None
    for row in analyzed:
        document = _document_key(row)
        if document and document != previous_document:
            document_visits[document] += 1
        previous_document = document
    revisits = sum(max(0, count - 1) for count in document_visits.values())

    if analyzed:
        first_day = datetime.strptime(analyzed[0]["ts"][:10], "%Y-%m-%d")
        last_day = datetime.strptime(analyzed[-1]["ts"][:10], "%Y-%m-%d")
        span_days = (last_day - first_day).days + 1
    else:
        span_days = 0
    stage_switches = sum(
        1 for first, second in zip(runs, runs[1:]) if first["stage"] != second["stage"]
    )
    incomplete = len(rows) - len(analyzed)
    quality_notes = []
    if not rows:
        quality_notes.append("所选范围没有任何屏幕记录")
    elif not analyzed:
        quality_notes.append("所选范围没有可用的分析记录")
    if incomplete:
        quality_notes.append(f"有 {incomplete} 条记录尚无分析结论，未纳入过程序列")

    report = {
        "task_name": task_name,
        "start_ts": start,
        "end_ts": end,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "runs": runs,
        "metrics": {
            "span_days": span_days,
            "stage_switches": stage_switches,
            "document_revisits": revisits,
            "ai_sessions": sum(1 for run in runs if run["stage"] == "AI 对话"),
            "source_records": len(analyzed),
        },
        "data_gaps": gaps,
        "quality_notes": quality_notes,
        "limitations": PROCESS_LIMITATIONS.copy(),
        "student_note": "由本程序依据本机记录生成，导出前请本人核对并按需删改。",
    }
    report["review"] = analyze_learning(report, interval)
    return report


def report_to_html(
    report: dict[str, Any], compact: bool = False, dark: bool = False
) -> str:
    """生成完全本地、无外部资源的 HTML；所有任务输入均转义。

    compact 只用于应用内预览：指标卡改 2×2、字号略小，避免横向滚动。
    dark 用于深色主题预览：适配深色背景下的文字、表格与指标卡配色。
    """
    esc = lambda value: html.escape(str(value), quote=True)
    task = esc(report["task_name"])
    review = report.get("review") or {}
    learning = review.get("metrics") or {}
    run_rows = "".join(
        '<tr><td width="20%">{}</td><td width="36%">{}</td>'
        '<td width="44%">{}</td></tr>'.format(
            esc(run["stage"]), esc(run["start"]), esc(run["end"])
        )
        for run in report["runs"]
    ) or '<tr><td colspan="3">没有可整理的过程记录</td></tr>'
    gap_items = "".join(
        f"<li>{esc(gap['start'])} 至 {esc(gap['end'])}：{esc(gap['note'])}</li>"
        for gap in report["data_gaps"]
    )
    quality_items = "".join(f"<li>{esc(note)}</li>" for note in report["quality_notes"])
    limitation_items = "".join(f"<li>{esc(note)}</li>" for note in report["limitations"])

    def review_block(items: list[dict[str, str]], empty_text: str) -> str:
        if not items:
            return f'<p class="note">{esc(empty_text)}</p>'
        return "<ul>" + "".join(
            f"<li><b>{esc(item['title'])}</b><br>{esc(item['detail'])}</li>"
            for item in items
        ) + "</ul>"

    metric_values = (
        (learning.get("active_minutes", 0), "有记录的分钟"),
        (learning.get("focus_minutes") or "—", "最长连续投入（分钟）"),
        (f"{round(float(learning.get('produce_ratio') or 0) * 100)}%", "动手时间占比"),
        (learning.get("interruptions", 0), "被打断次数"),
    )
    number_size = "+2" if compact else "+3"
    label_size = "-2" if compact else "-1"
    cell_width = "50%" if compact else "25%"
    if dark:
        body_bg = "#2E2C31"
        body_color = "#E8E1D5"
        h_color = "#F5EFEB"
        meta_color = "#A8A298"
        border_color = "#57535A"
        th_bg = "#3D3B40"
        num_color = "#F5EFEB"
        label_color = "#A8A298"
        sub_color = "#F5EFEB"
    else:
        body_bg = "#ffffff"
        body_color = "#222222"
        h_color = "#111111"
        meta_color = "#555555"
        border_color = "#bbbbbb"
        th_bg = "#eef1f5"
        num_color = "#111111"
        label_color = "#555555"
        sub_color = "#111111"

    metric_cells = [
        f'<td width="{cell_width}" align="center">'
        f'<font size="{number_size}" color="{num_color}"><b>{esc(value)}</b></font>'
        f'<br><font size="{label_size}" color="{label_color}">{esc(label)}</font></td>'
        for value, label in metric_values
    ]
    if compact:
        metric_rows = (
            "<tr>" + "".join(metric_cells[:2]) + "</tr><tr>" + "".join(metric_cells[2:]) + "</tr>"
        )
    else:
        metric_rows = "<tr>" + "".join(metric_cells) + "</tr>"
    body_px = 12 if compact else 14
    title_px = 20 if compact else 25
    section_px = 15 if compact else 19
    sub_px = 13 if compact else 15
    lead_px = 13 if compact else 16
    cell_padding = 4 if compact else 6
    line_height = 1.5 if compact else 1.65
    section_gap = 14 if compact else 24
    if compact:
        header_html = (
            f'<p class="meta">{esc(report["start_ts"][:16])} 至 '
            f'{esc(report["end_ts"][:16])}　任务：{task}</p>'
        )
    else:
        header_html = (
            f'<p class="h1">学习复盘</p>\n'
            f'<p class="meta">任务：{task}<br>'
            f'范围：{esc(report["start_ts"])} 至 {esc(report["end_ts"])}<br>\n'
            f'生成：{esc(report["generated_at"])}　{esc(report["student_note"])}</p>'
        )
    media_css = ""
    if not dark:
        media_css = """
@media (prefers-color-scheme: dark) {
  body { background: #1E1D20; color: #E8E1D5; }
  p, li, .summary { color: #E8E1D5; }
  .h1, .sec, .lead, b, th { color: #F5EFEB; }
  .sec { border-bottom-color: #57535A; }
  .sub { color: #E8E1D5; }
  .meta, .note { color: #A8A298; }
  table { border-color: #57535A; }
  th, td { border-color: #57535A; color: #E8E1D5; }
  th { background: #3D3B40; }
}
@media print {
  body { background: #ffffff !important; color: #111111 !important; }
  .h1, .sec, .sub, .lead, b, p, li, td, th { color: #111111 !important; }
  .meta, .note { color: #555555 !important; }
  th { background: #eef1f5 !important; }
  table, th, td { border-color: #bbbbbb !important; }
}"""

    # 指标卡用基础 table 布局，浏览器与打印视图都不依赖 flex。
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>学习复盘 - {task}</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;background:{body_bg};color:{body_color};font-size:{body_px}px;line-height:{line_height}}}
p{{margin:4px 0;color:{body_color}}}
.h1{{font-size:{title_px}px;font-weight:bold;color:{h_color};margin:0 0 8px}}
.sec{{font-size:{section_px}px;font-weight:bold;color:{h_color};margin:{section_gap}px 0 6px;border-bottom:1px solid {border_color};padding-bottom:3px}}
.sub{{font-size:{sub_px}px;font-weight:bold;color:{sub_color};margin:10px 0 2px}}
.meta,.note{{color:{meta_color}}}
.lead{{font-size:{lead_px}px;font-weight:bold;color:{h_color};margin:2px 0}}
.summary{{margin:0 0 6px;color:{body_color}}}
ul{{margin:2px 0 4px;color:{body_color}}}
li{{margin-bottom:2px;color:{body_color}}}
b{{color:{h_color}}}
table{{border-collapse:collapse;border-color:{border_color}}}
th,td{{border:1px solid {border_color};padding:{cell_padding}px;text-align:left;color:{body_color}}}
th{{background:{th_bg};color:{h_color}}}
.boundary{{padding:2px 10px}}{media_css}
</style></head><body>
{header_html}
<p class="sec">一、这段时间的节奏</p>
<p class="lead">{esc(review.get('headline', '没有可用的复盘结论'))}</p>
<p class="summary">{esc(review.get('summary', ''))}</p>
<p class="sub">值得保留</p>
{review_block(review.get('strengths') or [], '这段记录里还没有足够长的连续投入，先把节奏跑起来。')}
<p class="sub">值得留意</p>
{review_block(review.get('frictions') or [], '没有发现明显的卡点。')}
<p class="sub">下次可以试</p>
{review_block(review.get('suggestions') or [], '保持现在的安排即可。')}
<p class="sec">二、过程结构</p>
<table width="100%" cellspacing="0" cellpadding="{cell_padding + 2}" border="1">
{metric_rows}</table>
<p></p>
<table width="100%" cellspacing="0" cellpadding="6" border="1">
<thead><tr bgcolor="{th_bg}"><th width="20%">阶段</th><th width="36%">开始</th>
<th width="44%">最后记录</th></tr></thead>
<tbody>{run_rows}</tbody></table>
<p class="sec">三、数据完整性</p>
<ul>{quality_items}{gap_items}</ul>
<p class="sec">四、边界说明</p>
<div class="boundary"><ul>{limitation_items}</ul></div>
<p class="note">本文件由本地行为元数据生成，不含作业正文，不默认包含截图和窗口标题全文。
复盘结论只描述行为节奏，不评价努力程度，也不判断内容是否为本人所写。</p>
</body></html>"""


def export_process_html(
    report: dict[str, Any],
    output_path: Path,
    allowed_root: Path,
    overwrite: bool = False,
) -> Path:
    target = safe_output_path(output_path, ".html", allowed_root, overwrite)
    atomic_write_text(target, report_to_html(report))
    return target


def export_process_pdf(
    report: dict[str, Any],
    output_path: Path,
    allowed_root: Path,
    overwrite: bool = False,
) -> Path:
    """用 QPainter 直接绘制 A4 PDF，避免 Qt 富文本引擎的表格兼容问题。"""
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import (
        QColor,
        QFont,
        QFontMetrics,
        QGuiApplication,
        QPageSize,
        QPainter,
        QPdfWriter,
    )

    if QGuiApplication.instance() is None:
        raise RuntimeError("导出 PDF 前需要先创建 QApplication")
    target = safe_output_path(output_path, ".pdf", allowed_root, overwrite)
    temp_path = temporary_pdf_path(target)

    writer = QPdfWriter(str(temp_path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setResolution(96)
    writer.setTitle(f"学习复盘 - {report['task_name']}")
    painter = QPainter(writer)
    if not painter.isActive():
        temp_path.unlink(missing_ok=True)
        raise RuntimeError("PDF 绘制器启动失败")

    width = writer.width()
    height = writer.height()
    margin = 50
    content_width = width - margin * 2
    dark = QColor("#1a1a1a")
    muted = QColor("#555555")
    line_color = QColor("#b8b8b8")
    header_fill = QColor("#eef1f5")
    metric_fill = QColor("#f7f8fa")

    body_font = QFont("Microsoft YaHei", 9)
    small_font = QFont("Microsoft YaHei", 8)
    bold_font = QFont("Microsoft YaHei", 9)
    bold_font.setBold(True)
    section_font = QFont("Microsoft YaHei", 12)
    section_font.setBold(True)
    title_font = QFont("Microsoft YaHei", 20)
    title_font.setBold(True)
    lead_font = QFont("Microsoft YaHei", 12)
    lead_font.setBold(True)
    metric_font = QFont("Microsoft YaHei", 18)
    metric_font.setBold(True)

    def start_page() -> float:
        painter.fillRect(0, 0, width, height, QColor("#ffffff"))
        painter.setPen(dark)
        return float(margin)

    def new_page() -> float:
        writer.newPage()
        return start_page()

    def wrapped_lines(text: str, font: QFont, max_width: float) -> list[str]:
        metrics = QFontMetrics(font)
        lines: list[str] = []
        current = ""
        for char in text:
            candidate = current + char
            if current and metrics.horizontalAdvance(candidate) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines or [""]

    def draw_paragraph(
        text: str, y: float, font: QFont, color: QColor = dark, indent: float = 0
    ) -> float:
        painter.setFont(font)
        painter.setPen(color)
        metrics = QFontMetrics(font)
        for line in wrapped_lines(text, font, content_width - indent):
            if y > height - margin - 24:
                y = new_page()
            painter.drawText(
                QRectF(margin + indent, y, content_width - indent, metrics.height()),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                line,
            )
            y += metrics.height() + 3
        return y

    def draw_section(title: str, y: float) -> float:
        # 预留标题加三到四行的空间，避免标题落在页脚、正文被推到下一页。
        if y > height - margin - 130:
            y = new_page()
        y += 10
        painter.setFont(section_font)
        painter.setPen(dark)
        painter.drawText(int(margin), int(y + 18), title)
        y += 26
        painter.setPen(line_color)
        painter.drawLine(int(margin), int(y), int(width - margin), int(y))
        return y + 10

    def draw_items(
        heading: str, items: list[dict[str, str]], y: float, empty_text: str
    ) -> float:
        if y > height - margin - 80:
            y = new_page()
        y = draw_paragraph(heading, y + 6, lead_font, dark)
        if not items:
            return draw_paragraph(f"· {empty_text}", y, body_font, muted, indent=8)
        for item in items:
            if y > height - margin - 56:
                y = new_page()
            y = draw_paragraph(f"· {item['title']}", y, bold_font, dark, indent=8)
            y = draw_paragraph(item["detail"], y, body_font, muted, indent=20)
            y += 2
        return y

    y = start_page()
    painter.setFont(title_font)
    painter.setPen(dark)
    painter.drawText(int(margin), int(y + 26), "学习复盘")
    y += 40
    y = draw_paragraph(f"任务：{report['task_name']}", y, body_font)
    y = draw_paragraph(
        f"范围：{report['start_ts']} 至 {report['end_ts']}", y, body_font
    )
    y = draw_paragraph(
        f"生成：{report['generated_at']}　{report['student_note']}", y, small_font, muted
    )

    review = report.get("review") or {}
    learning = review.get("metrics") or {}
    y = draw_section("一、这段时间的节奏", y)
    y = draw_paragraph(str(review.get("headline") or "没有可用的复盘结论"), y, lead_font, dark)
    y = draw_paragraph(str(review.get("summary") or ""), y, body_font, dark)
    y += 4
    y = draw_items(
        "值得保留",
        review.get("strengths") or [],
        y,
        "这段记录里还没有足够长的连续投入，先把节奏跑起来。",
    )
    y = draw_items("值得留意", review.get("frictions") or [], y, "没有发现明显的卡点。")
    y = draw_items("下次可以试", review.get("suggestions") or [], y, "保持现在的安排即可。")

    y = draw_section("二、过程结构", y)
    metric_items = [
        (learning.get("active_minutes", 0), "有记录的分钟"),
        (learning.get("focus_minutes") or "—", "最长连续投入（分钟）"),
        (f"{round(float(learning.get('produce_ratio') or 0) * 100)}%", "动手时间占比"),
        (learning.get("interruptions", 0), "被打断次数"),
    ]
    box_width = content_width / 4
    box_height = 62
    for index, (value, label) in enumerate(metric_items):
        x = margin + index * box_width
        painter.setPen(line_color)
        painter.setBrush(metric_fill)
        painter.drawRect(QRectF(x, y, box_width, box_height))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setFont(metric_font)
        painter.setPen(dark)
        painter.drawText(
            QRectF(x, y + 3, box_width, 34),
            int(Qt.AlignmentFlag.AlignCenter),
            str(value),
        )
        painter.setFont(small_font)
        painter.setPen(muted)
        painter.drawText(
            QRectF(x + 3, y + 37, box_width - 6, 20),
            int(Qt.AlignmentFlag.AlignCenter),
            label,
        )
    y += box_height + 12

    columns = [0.20, 0.36, 0.44]
    headers = ["阶段", "开始", "最后记录"]
    row_height = 23
    metrics_body = QFontMetrics(body_font)

    def draw_table_header(y_pos: float) -> float:
        painter.setPen(line_color)
        painter.setBrush(header_fill)
        painter.drawRect(QRectF(margin, y_pos, content_width, row_height))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setFont(bold_font)
        painter.setPen(dark)
        x_pos = margin
        for ratio, header in zip(columns, headers):
            painter.drawText(
                QRectF(x_pos + 5, y_pos, content_width * ratio - 8, row_height),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                header,
            )
            x_pos += content_width * ratio
        return y_pos + row_height

    y = draw_table_header(y)
    for run in report["runs"]:
        if y + row_height > height - margin - 20:
            y = new_page()
            y = draw_table_header(y)
        values = [run["stage"], run["start"], run["end"]]
        painter.setFont(body_font)
        painter.setPen(line_color)
        painter.drawRect(QRectF(margin, y, content_width, row_height))
        painter.setPen(dark)
        x_pos = margin
        for ratio, value in zip(columns, values):
            painter.drawText(
                QRectF(x_pos + 5, y, content_width * ratio - 8, row_height),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                metrics_body.elidedText(value, Qt.TextElideMode.ElideRight, int(content_width * ratio - 8)),
            )
            x_pos += content_width * ratio
        y += row_height
    if not report["runs"]:
        y = draw_paragraph("没有可整理的过程记录。", y + 4, body_font, muted)

    y = draw_section("三、数据完整性", y)
    notes = report["quality_notes"] + [
        f"{gap['start']} 至 {gap['end']}：{gap['note']}"
        for gap in report["data_gaps"]
    ]
    for note in notes or ["所选范围的数据完整，没有需要特别说明的缺口。"]:
        y = draw_paragraph(f"· {note}", y, body_font, dark)

    y = draw_section("四、边界说明", y)
    for limitation in report["limitations"]:
        y = draw_paragraph(f"· {limitation}", y, body_font, dark)

    y += 8
    y = draw_paragraph(
        "本文件由本地行为元数据生成，不含作业正文，不默认包含截图和窗口标题全文。",
        y,
        small_font,
        muted,
    )
    y = draw_paragraph(
        "复盘结论只描述行为节奏，不评价努力程度，也不判断内容是否为本人所写。",
        y,
        small_font,
        muted,
    )
    painter.end()
    if not temp_path.exists() or temp_path.stat().st_size == 0:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError("PDF 导出失败，未生成有效文件")
    temp_path.replace(target)
    return target
