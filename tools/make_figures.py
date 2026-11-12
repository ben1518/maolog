"""生成方案说明书用的六张图表。

手写 SVG → QSvgRenderer 转 PNG，配色沿用 ui/theme.py，保证图文一致。

    .venv/Scripts/python.exe tools/make_figures.py

输出到 assets/figures/。
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QByteArray  # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402
from PyQt6.QtSvg import QSvgRenderer  # noqa: E402

OUT_DIR = ROOT / "assets" / "figures"

FONT = "Microsoft YaHei"

BG = "#14161A"
CARD = "#1C1F25"
BORDER = "#2B313B"
TEXT = "#E9ECF1"
SUB = "#9BA3AF"
MUTED = "#6B7482"

ACCENT = "#5B8CFF"
GREEN = "#3DD9A0"
ORANGE = "#FFB547"
RED = "#FF6B6B"
PURPLE = "#B08CFF"
TEAL = "#4DD0E1"

# 放大倍数：2 倍超采样再输出，插入 Word 后缩放也不会糊
SCALE = 2


# ---------------------------------------------------------------- SVG 基础件


def defs() -> str:
    return (
        "<defs>"
        f'<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{SUB}"/></marker>'
        f'<marker id="ar-blue" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{ACCENT}"/></marker>'
        "</defs>"
    )


def rect(x, y, w, h, fill=CARD, stroke=BORDER, rx=16, sw=1.5, opacity=1.0) -> str:
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    o = f' opacity="{opacity}"' if opacity < 1 else ""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" ry="{rx}" '
        f'fill="{fill}"{s}{o}/>'
    )


def text(x, y, s, size=18, fill=TEXT, weight="normal", anchor="start") -> str:
    s = escape(str(s))
    return (
        f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
        f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}">{s}</text>'
    )


def line(x1, y1, x2, y2, color=SUB, width=2, marker=None, dash=None) -> str:
    m = f' marker-end="url(#{marker})"' if marker else ""
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
        f'stroke-width="{width}"{m}{d}/>'
    )


def svg_open(w, h) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
        f'<rect width="{w}" height="{h}" fill="{BG}"/>' + defs()
    )


# ---------------------------------------------------------------- 图 1：痛点映射


def fig1() -> tuple[str, int, int]:
    w, h = 1600, 700
    parts = [svg_open(w, h)]

    parts.append(text(60, 70, "校园里的三个真问题，对应三组能力", 30, TEXT, "bold"))
    parts.append(text(60, 106, "不是「又一个时间管理工具」，而是把「感知到的行为」直接接到「该做什么」上", 17, SUB))

    # 表头
    parts.append(text(200, 168, "学生真实处境", 16, RED, "bold", "middle"))
    parts.append(text(1120, 168, "楚师智学的解法", 16, ACCENT, "bold", "middle"))

    rows = [
        (
            "时间黑洞",
            "每天在电脑前坐六小时，",
            "睡前回想却说不出具体做了什么",
            "屏幕无感感知 + 时间轴看板",
            "每 60 秒一帧，自动归成可读的时间段",
            GREEN,
        ),
        (
            "资料过载",
            "课件、考研资料、网课散在各处，",
            "考前翻两小时找不到重点",
            "课程资料提炼 + 知识导图",
            "上传即出章节结构、速记卡片与模拟题",
            TEAL,
        ),
        (
            "规划断层",
            "学分、竞赛、履历三张皮，",
            "到大三才发现材料凑不齐",
            "学业路线 + 学分智能推荐",
            "从目标要求反向拆出学期行动路线图",
            PURPLE,
        ),
    ]

    top = 200
    card_h = 140
    gap = 30
    for i, (title, l1, l2, r_title, r_desc, r_color) in enumerate(rows):
        y = top + i * (card_h + gap)

        # 左：痛点
        parts.append(rect(60, y, 620, card_h, "#221A1E", "#3E2830"))
        parts.append(rect(76, y + 22, 5, 34, RED, None, 3))
        parts.append(text(96, y + 48, title, 22, "#FF8A8A", "bold"))
        parts.append(text(96, y + 84, l1, 15, SUB))
        parts.append(text(96, y + 110, l2, 15, SUB))

        # 箭头
        parts.append(line(700, y + card_h // 2, 800, y + card_h // 2, ACCENT, 2.5, "ar-blue"))

        # 右：解法
        parts.append(rect(820, y, 720, card_h, "#181E2B", "#26324A"))
        parts.append(rect(836, y + 22, 5, 34, r_color, None, 3))
        parts.append(text(856, y + 48, r_title, 22, r_color, "bold"))
        parts.append(text(856, y + 84, r_desc, 15, SUB))
        stage = ["已实现并实际运行", "二期规划", "三期规划"][i]
        parts.append(text(856, y + 112, f"当前状态：{stage}", 14, MUTED))

    parts.append("</svg>")
    return "".join(parts), w, h


# ---------------------------------------------------------------- 图 2：四层架构


def fig2() -> tuple[str, int, int]:
    w, h = 1600, 900
    parts = [svg_open(w, h)]

    parts.append(text(60, 70, "总体架构：四层，自下而上", 30, TEXT, "bold"))
    parts.append(text(60, 106, "层与层只通过接口说话：换模型、换存储、换端，都不影响其它层", 17, SUB))
    parts.append(text(60, 136, "↑ 数据与结论自下而上    ↓ 配置与控制自上而下", 14, MUTED))

    layers = [
        (
            "应用层",
            "学生看到的东西",
            ACCENT,
            ["时间轴看板", "知识导图", "学业路线图", "学分提醒"],
        ),
        (
            "Skills 层",
            "MobileClaw 技能编排",
            PURPLE,
            ["screen-perception", "material-digest", "academic-plan", "credit-match"],
        ),
        (
            "引擎层",
            "本地计算核心",
            GREEN,
            ["屏幕采集", "视觉识别", "统计聚合", "二次归纳"],
        ),
        (
            "数据层",
            "全部留在本机",
            ORANGE,
            ["SQLite 行为库", "截图归档", "向量知识库", "配置与密钥"],
        ),
    ]

    top = 160
    layer_h = 160
    gap = 22
    for i, (name, desc, color, items) in enumerate(layers):
        y = top + i * (layer_h + gap)
        parts.append(rect(60, y, 1480, layer_h, CARD, BORDER))
        # 左侧色条 + 层名
        parts.append(rect(60, y, 8, layer_h, color, None, 4))
        parts.append(text(100, y + 62, name, 24, color, "bold"))
        parts.append(text(100, y + 96, desc, 14, SUB))

        # 右侧四个方块
        bx = 380
        bw = 265
        for j, item in enumerate(items):
            x = bx + j * (bw + 20)
            parts.append(rect(x, y + 36, bw, 88, "#22262E", "#333A45", 12))
            parts.append(text(x + bw // 2, y + 88, item, 15, TEXT, "normal", "middle"))

    # 右侧不能再放箭头：卡片已占到 1540，箭头会被裁掉。改成标题里说明流向。
    parts.append(text(60, 136, "↑ 数据与结论自下而上    ↓ 配置与控制自上而下", 14, MUTED))

    parts.append("</svg>")
    return "".join(parts), w, h


# ---------------------------------------------------------------- 图 3：Skills 编排


def fig3() -> tuple[str, int, int]:
    w, h = 1600, 880
    parts = [svg_open(w, h)]

    parts.append(text(60, 70, "四个 Skills 如何在 MobileClaw 上协作", 30, TEXT, "bold"))
    parts.append(text(60, 106, "每个 Skill 只做一件事，由编排器按任务串起来；数据不离本机", 17, SUB))

    # 中心
    cx, cy = 800, 470
    parts.append(rect(cx - 200, cy - 70, 400, 140, "#1E2637", ACCENT, 18, 2))
    parts.append(text(cx, cy - 18, "MobileClaw 编排器", 22, ACCENT, "bold", "middle"))
    parts.append(text(cx, cy + 16, "任务规划 · 模型路由 · 本地执行", 14, SUB, "normal", "middle"))
    parts.append(text(cx, cy + 44, "MoMA 多模型调度", 13, MUTED, "normal", "middle"))

    skills = [
        (250, 210, "screen-perception", "屏幕感知", "截图 + 窗口标题", "时段 / 分类", GREEN),
        (1050, 210, "material-digest", "资料提炼", "课件 / PDF", "导图 / 自测", TEAL),
        (250, 650, "academic-plan", "学业规划", "履历 + 目标", "里程碑", PURPLE),
        (1050, 650, "credit-match", "学分匹配", "学分规则 + 活动", "推荐清单", ORANGE),
    ]

    for x, y, code, name, inp, outp, color in skills:
        parts.append(rect(x, y, 300, 150, CARD, "#343B48", 16))
        # 色条要内缩，否则直角边会戳出圆角轮廓
        parts.append(rect(x + 16, y + 3, 268, 5, color, None, 2.5))
        parts.append(text(x + 24, y + 46, name, 20, color, "bold"))
        parts.append(text(x + 24, y + 72, code, 13, MUTED))
        parts.append(text(x + 24, y + 106, f"输入：{inp}", 14, SUB))
        parts.append(text(x + 24, y + 130, f"输出：{outp}", 14, SUB))

        # 连线到中心
        sx = x + 300 if x < cx else x
        sy = y + 75
        tx = cx - 200 if x < cx else cx + 200
        parts.append(line(sx, sy, tx, cy + (18 if y < cy else -18), color, 2, None, "7 5"))

    # 底部说明
    parts.append(rect(60, 810, 1480, 1, BORDER, None, 0))
    parts.append(
        text(
            60,
            850,
            "隐私边界：原始截图与窗口标题始终留在本机，只有压缩后的缩略图会离开；"
            "向量知识库同样建在本地。",
            14,
            MUTED,
        )
    )

    parts.append("</svg>")
    return "".join(parts), w, h


# ---------------------------------------------------------------- 图 4：数据流


def fig4() -> tuple[str, int, int]:
    w, h = 1600, 620
    parts = [svg_open(w, h)]

    parts.append(text(60, 70, "一次完整的数据流：从一帧截图到一句建议", 30, TEXT, "bold"))
    parts.append(text(60, 106, "每个节点都产出可验证的中间结果，出问题能定位到具体一步", 17, SUB))

    nodes = [
        ("截屏", "mss 抓屏\n64×36 指纹", ACCENT),
        ("变化判定", "指纹比对\n差异小则复用", GREEN),
        ("视觉识别", "缩略图 + 窗口标题\n→ 结构化 JSON", PURPLE),
        ("入库", "SQLite\n行为流水", ORANGE),
        ("聚合", "时间段合并\n分类 / 应用统计", TEAL),
        ("归纳", "AI 二次总结\n亮点与建议", RED),
    ]

    n = len(nodes)
    box_w = 210
    gap = (1480 - n * box_w) // (n - 1)
    y = 210
    box_h = 150

    for i, (title, desc, color) in enumerate(nodes):
        x = 60 + i * (box_w + gap)
        parts.append(rect(x, y, box_w, box_h, CARD, "#343B48"))
        parts.append(rect(x + 14, y + 3, box_w - 28, 5, color, None, 2.5))
        parts.append(text(x + 20, y + 46, title, 20, color, "bold"))
        for k, ln in enumerate(desc.split("\n")):
            parts.append(text(x + 20, y + 84 + k * 26, ln, 14, SUB))
        # 序号
        parts.append(text(x + box_w - 22, y + 130, f"0{i + 1}", 13, MUTED, "normal", "end"))

        if i < n - 1:
            ax1 = x + box_w + 6
            ax2 = x + box_w + gap - 6
            parts.append(line(ax1, y + box_h // 2, ax2, y + box_h // 2, SUB, 2, "ar"))

    # 下方三条关键说明
    notes = [
        ("省调用", "画面几乎没变就不问 AI，直接沿用上一次结论并标记为「复用」", GREEN),
        ("可追溯", "每一段结论都能点开，看到当时的原始截图", ACCENT),
        ("可降级", "AI 不可用时退回本地统计规则，看板不会空白", ORANGE),
    ]
    ny = 440
    for i, (tag, desc, color) in enumerate(notes):
        x = 60 + i * 510
        parts.append(rect(x, ny, 470, 110, "#1A1E24", BORDER, 12))
        parts.append(rect(x + 20, ny + 22, 4, 24, color, None, 2))
        parts.append(text(x + 36, ny + 44, tag, 18, color, "bold"))
        parts.append(text(x + 20, ny + 82, desc, 14, SUB))

    parts.append("</svg>")
    return "".join(parts), w, h


# ---------------------------------------------------------------- 图 6：甘特图


def fig6() -> tuple[str, int, int]:
    w, h = 1600, 640
    parts = [svg_open(w, h)]

    parts.append(text(60, 70, "开发推进计划", 30, TEXT, "bold"))
    parts.append(text(60, 106, "一期已上线运行，二期补齐资料与规划能力，三期打通学分与校内数据", 17, SUB))

    months = ["2026.10", "11", "12", "2027.01", "02", "03", "04", "05", "06"]
    x0 = 420
    chart_w = 1120
    col_w = chart_w / len(months)
    label_w = 340

    # 表头
    parts.append(text(60, 186, "阶段 / 任务", 14, SUB, "bold"))
    for i, mth in enumerate(months):
        cx = x0 + i * col_w + col_w / 2
        parts.append(text(int(cx), 186, mth, 13, SUB, "normal", "middle"))

    head_bottom = 200
    # 纵向网格
    for i in range(len(months) + 1):
        gx = int(x0 + i * col_w)
        parts.append(line(gx, head_bottom, gx, h - 24, "#232830", 1))

    stages = [
        (
            "一期 + v2 复盘（已完成）",
            GREEN,
            [
                ("屏幕采集与隐私拦截", 0.0, 0.9),
                ("手帐看板 + 桌宠 + 免Key", 0.4, 1.0),
                ("v2 学习复盘 / AI画像 / 估时", 0.9, 0.8),
                ("数据护照 + MobileClaw桥接", 1.2, 0.6),
            ],
        ),
        (
            "二期（深化）",
            ACCENT,
            [
                ("资料解析与知识导图", 1.8, 1.5),
                ("学业履历与路径规划", 2.8, 1.5),
                ("全量 MobileClaw Skills 上架", 3.8, 1.4),
            ],
        ),
        (
            "三期（推广）",
            PURPLE,
            [
                ("第二课堂学分规则库", 4.8, 1.4),
                ("校内教务与试点反馈", 5.8, 1.4),
                ("跨院系复制推广", 6.8, 1.9),
            ],
        ),
    ]

    y = 230
    for stage_name, color, items in stages:
        parts.append(text(60, y + 4, stage_name, 17, color, "bold"))
        y += 32
        for name, start, span in items:
            parts.append(text(84, y + 20, name, 14, TEXT))
            bx = x0 + start * col_w
            bw = max(56.0, span * col_w)
            parts.append(rect(bx, y + 5, bw, 22, color, None, 7, 0.3))
            parts.append(rect(bx, y + 5, 4, 22, color, None, 2))
            y += 34
        y += 20

    # 今天的标记：2026-11-16 落在 11 月（index=1）的 55% 处
    today_x = int(x0 + 1.55 * col_w)
    parts.append(line(today_x, head_bottom, today_x, y - 10, ORANGE, 1.5, None, "5 4"))
    parts.append(text(today_x + 8, head_bottom + 18, "2026.11.16", 12, ORANGE))

    parts.append("</svg>")
    return "".join(parts), w, h


# ---------------------------------------------------------------- 渲染


def render(name: str, svg: str, w: int, h: int) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.png"
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise RuntimeError(f"{name} 的 SVG 无效")

    img = QImage(w * SCALE, h * SCALE, QImage.Format.Format_ARGB32)
    img.fill(QColor(BG))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    renderer.render(painter)
    painter.end()
    img.save(str(path))
    print(f"  {path.name:26s} {w}×{h}")
    return path


def copy_dashboard() -> None:
    """图 5 直接用真实看板截图，比手绘示意图有说服力。"""
    src = ROOT / "data" / "preview.png"
    dst = OUT_DIR / "fig5_dashboard.png"
    if not src.exists():
        print("  跳过 fig5：先跑 tools/preview_ui.py 生成看板截图")
        return
    import shutil

    shutil.copyfile(src, dst)
    print(f"  {dst.name:26s} 拷贝自 data/preview.png")


def main() -> int:
    # 必须持有引用，否则 QGuiApplication 被回收后 Qt 会直接退出
    app = QGuiApplication(sys.argv)  # noqa: F841
    print("生成图表：")
    for name, maker in (
        ("fig1_positioning", fig1),
        ("fig2_architecture", fig2),
        ("fig3_skills", fig3),
        ("fig4_dataflow", fig4),
        ("fig6_roadmap", fig6),
    ):
        svg, w, h = maker()
        render(name, svg, w, h)
    copy_dashboard()
    print(f"\n全部输出到 {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
