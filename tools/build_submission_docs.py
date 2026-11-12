"""一键生成新版参赛方案说明书及全部提交材料模板（.docx + A4 .pdf）。

用法：
    .venv/Scripts/python.exe -B -X utf8 tools/build_submission_docs.py

复用原方案 .docx 的 Word 样式表/页脚/TOC 配置，用纯 Python OOXML
生成规范排版的新版 .docx；同时借助 PyQt6 WebEngine 生成等比例 A4 PDF。
"""

from __future__ import annotations

import base64
import html as html_lib
import mimetypes
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image
from PyQt6.QtCore import QEventLoop, QMarginsF, QUrl
from PyQt6.QtGui import QPageLayout, QPageSize
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SUBMIT_DIR = DOCS / "参赛提交材料"
STYLE_CACHE = ROOT / "tools" / "_docx_style_base.zip"
PROPOSAL_DOCX = DOCS / "楚师智学-参赛方案说明书.docx"

# A4 页面（2.54cm 边距下正文宽度 = 11906 - 2*1800 = 8306 dxa ≈ 5274310 EMU）
BODY_WIDTH_DXA = 8306
MAX_IMG_CX = 5274310

TOC_FIELD_BLOCK = (
    "<w:p>"
    "<w:pPr>"
    '<w:spacing w:after="240" w:line="360"/>'
    "</w:pPr>"
    '<w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    '<w:r><w:rPr><w:rFonts w:hint="eastAsia" w:eastAsia="宋体"/>'
    '<w:color w:val="808080"/><w:sz w:val="21"/></w:rPr>'
    "<w:t>目录将在打开文档时自动生成；若未显示页码，请右键此处选择「更新域」。</w:t></w:r>"
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    "</w:p>"
)

SECT_NO_FOOTER = (
    '<w:sectPr><w:type w:val="nextPage"/>'
    '<w:pgSz w:w="11906" w:h="16838"/>'
    '<w:pgMar w:top="1440" w:right="1800" w:bottom="1440" w:left="1800" '
    'w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>'
)

SECT_WITH_FOOTER = (
    '<w:sectPr><w:footerReference r:id="rId5" w:type="default"/>'
    '<w:pgSz w:w="11906" w:h="16838"/>'
    '<w:pgMar w:top="1440" w:right="1800" w:bottom="1440" w:left="1800" '
    'w:header="851" w:footer="992" w:gutter="0"/>'
    '<w:pgNumType w:start="1"/></w:sectPr>'
)


def ensure_style_cache() -> Path:
    """首次运行前将原 .docx 里的样式、主题、页脚缓存到轻量压缩包。"""
    if STYLE_CACHE.exists():
        return STYLE_CACHE
    if not PROPOSAL_DOCX.exists():
        raise FileNotFoundError(f"缺少样式基准文件：{PROPOSAL_DOCX}")
    with zipfile.ZipFile(PROPOSAL_DOCX, "r") as src, zipfile.ZipFile(
        STYLE_CACHE, "w", compression=zipfile.ZIP_DEFLATED
    ) as dst:
        for item in src.infolist():
            if item.filename.startswith("word/media/") or item.filename == "word/document.xml":
                continue
            dst.writestr(item.filename, src.read(item.filename))
    return STYLE_CACHE


def xml_esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def make_inline_drawing_run(rel_id: str, doc_id: int, img_path: Path, cx: int = 860000) -> str:
    with Image.open(img_path) as im:
        w, h = im.size
    cy = max(120000, int(cx * h / max(1, w)))
    return (
        "<w:r><w:drawing><wp:inline>"
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:docPr id="{doc_id}" name="{xml_esc(img_path.name)}"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:pic>"
        f'<pic:nvPicPr><pic:cNvPr id="{doc_id}" name="{xml_esc(img_path.name)}"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rel_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        "<pic:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</pic:spPr></pic:pic></a:graphicData></a:graphic>"
        "</wp:inline></w:drawing></w:r>"
    )


def parse_inline_runs(
    text: str,
    font_name: str = "宋体",
    base_sz: int = 24,
    base_color: str = "111111",
    sign_rel_id: str | None = None,
    sign_path: Path | None = None,
) -> str:
    """把行内 **粗体**、`代码` 与 {{SIGN}} 转成 OOXML <w:r>。"""
    text = text.replace("<br><br>", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    # 剥离 Markdown 链接 [text](url) 保留显示文字
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    tokens = re.split(r"(\*\*[^*]+\*\*|`[^`]+`|\{\{SIGN\}\})", text)
    runs: list[str] = []
    for tok in tokens:
        if not tok:
            continue
        if tok == "{{SIGN}}":
            if sign_rel_id and sign_path and sign_path.exists():
                runs.append(make_inline_drawing_run(sign_rel_id, 900, sign_path))
            continue
        bold = False
        color = base_color
        font = font_name
        sz = base_sz
        content = tok
        if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
            bold = True
            content = tok[2:-2]
        elif tok.startswith("`") and tok.endswith("`") and len(tok) > 2:
            font = "Consolas"
            color = "1A4A7A"
            sz = max(18, base_sz - 2)
            content = tok[1:-1]

        parts = content.split("\n")
        for idx, part in enumerate(parts):
            if idx > 0:
                runs.append("<w:r><w:br/></w:r>")
            if not part:
                continue
            b_xml = '<w:b w:val="1"/><w:bCs w:val="1"/>' if bold else ""
            runs.append(
                "<w:r>"
                "<w:rPr>"
                f'<w:rFonts w:hint="eastAsia" w:ascii="{font}" w:hAnsi="{font}" w:eastAsia="{font_name}" w:cs="{font_name}"/>'
                f"{b_xml}"
                f'<w:color w:val="{color}"/>'
                f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>'
                "</w:rPr>"
                f'<w:t xml:space="preserve">{xml_esc(part)}</w:t>'
                "</w:r>"
            )
    return "".join(runs)


def make_paragraph(
    text: str,
    *,
    style: str | None = None,
    align: str | None = None,
    first_line: int = 0,
    left_indent: int = 0,
    space_before: int = 0,
    space_after: int = 120,
    line: int = 380,
    font_name: str = "宋体",
    sz: int = 24,
    color: str = "111111",
    bold: bool = False,
    shade: str | None = None,
    left_border: str | None = None,
    sign_rel_id: str | None = None,
    sign_path: Path | None = None,
) -> str:
    ppr = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if left_border:
        ppr.append(f'<w:pBdr><w:left w:val="single" w:sz="18" w:space="12" w:color="{left_border}"/></w:pBdr>')
    if shade:
        ppr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>')
    ppr.append(f'<w:spacing w:before="{space_before}" w:after="{space_after}" w:line="{line}"/>')
    if first_line or left_indent:
        ind_attrs = []
        if first_line:
            ind_attrs.append(f'w:firstLine="{first_line}"')
        if left_indent:
            ind_attrs.append(f'w:left="{left_indent}"')
        ppr.append(f'<w:ind {" ".join(ind_attrs)}/>')
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    ppr_xml = f"<w:pPr>{''.join(ppr)}</w:pPr>"
    wrapped_text = f"**{text}**" if bold and not text.startswith("**") else text
    return f"<w:p>{ppr_xml}{parse_inline_runs(wrapped_text, font_name=font_name, base_sz=sz, base_color=color, sign_rel_id=sign_rel_id, sign_path=sign_path)}</w:p>"


def make_image_paragraph(rel_id: str, img_path: Path, doc_id: int) -> str:
    with Image.open(img_path) as im:
        w, h = im.size
    cx = min(MAX_IMG_CX, int(w * 9525 * 0.72))
    cx = max(cx, int(MAX_IMG_CX * 0.88)) if w >= 1200 else cx
    cy = max(100000, int(cx * h / max(1, w)))
    return (
        "<w:p>"
        '<w:pPr><w:spacing w:before="120" w:after="60"/><w:jc w:val="center"/></w:pPr>'
        "<w:r><w:drawing><wp:inline>"
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:docPr id="{doc_id}" name="{xml_esc(img_path.name)}"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:pic>"
        f'<pic:nvPicPr><pic:cNvPr id="{doc_id}" name="{xml_esc(img_path.name)}"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rel_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        "<pic:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</pic:spPr></pic:pic></a:graphicData></a:graphic>"
        "</wp:inline></w:drawing></w:r></w:p>"
    )


def make_table(
    rows: list[list[str]],
    sign_rel_id: str | None = None,
    sign_path: Path | None = None,
) -> str:
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)
    col_w = max(800, BODY_WIDTH_DXA // max(1, ncols))
    grid = "".join(f'<w:gridCol w:w="{col_w}"/>' for _ in range(ncols))
    trs: list[str] = []
    for r_idx, row in enumerate(rows):
        padded = row + [""] * (ncols - len(row))
        is_header = r_idx == 0
        tr_pr = '<w:trPr><w:tblHeader w:val="1"/></w:trPr>' if is_header else ""
        tcs: list[str] = []
        for cell in padded:
            fill = "e8eef5" if is_header else ("f8fafc" if r_idx % 2 == 0 else "ffffff")
            tc_xml = (
                "<w:tc><w:tcPr>"
                f'<w:tcW w:w="{col_w}" w:type="dxa"/>'
                '<w:tcBorders>'
                '<w:top w:val="single" w:color="b9c4d0" w:sz="6"/>'
                '<w:left w:val="single" w:color="b9c4d0" w:sz="6"/>'
                '<w:bottom w:val="single" w:color="b9c4d0" w:sz="6"/>'
                '<w:right w:val="single" w:color="b9c4d0" w:sz="6"/>'
                "</w:tcBorders>"
                f'<w:shd w:val="clear" w:fill="{fill}"/>'
                '<w:tcMar><w:top w:w="90" w:type="dxa"/><w:left w:w="130" w:type="dxa"/>'
                '<w:bottom w:w="90" w:type="dxa"/><w:right w:w="130" w:type="dxa"/></w:tcMar>'
                '<w:vAlign w:val="center"/>'
                "</w:tcPr>"
                + make_paragraph(
                    cell.strip(),
                    align="center" if is_header else "left",
                    space_after=40,
                    line=320,
                    font_name="黑体" if is_header else "宋体",
                    sz=21,
                    color="12355b" if is_header else "111111",
                    bold=is_header,
                    sign_rel_id=sign_rel_id,
                    sign_path=sign_path,
                )
                + "</w:tc>"
            )
            tcs.append(tc_xml)
        trs.append(f"<w:tr>{tr_pr}{''.join(tcs)}</w:tr>")
    return (
        "<w:tbl>"
        f'<w:tblPr><w:tblW w:w="{BODY_WIDTH_DXA}" w:type="dxa"/><w:tblLayout w:type="autofit"/></w:tblPr>'
        f"<w:tblGrid>{grid}</w:tblGrid>"
        + "".join(trs)
        + "</w:tbl>"
        + '<w:p><w:pPr><w:spacing w:after="100"/></w:pPr></w:p>'
    )


def parse_md_blocks(md_text: str) -> list[tuple[str, Any]]:
    """解析简化 Markdown 块级语法，供 .docx 与 HTML 渲染复用。"""
    lines = md_text.splitlines()
    blocks: list[tuple[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped == "---":
            blocks.append(("hr", ""))
            i += 1
            continue
        if stripped.startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            blocks.append(("code", "\n".join(code_lines)))
            continue
        if stripped.startswith("|") and "|" in stripped[1:]:
            tbl_rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row_s = lines[i].strip()
                cells = [c.strip() for c in row_s.strip("|").split("|")]
                if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                    i += 1
                    continue
                tbl_rows.append(cells)
                i += 1
            if tbl_rows:
                blocks.append(("table", tbl_rows))
            continue
        m_img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if m_img:
            blocks.append(("img", (m_img.group(1), m_img.group(2))))
            i += 1
            continue
        m_h = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if m_h:
            blocks.append((f"h{len(m_h.group(1))}", m_h.group(2).strip()))
            i += 1
            continue
        if stripped.startswith(">"):
            q_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(("quote", "\n".join(q_lines)))
            continue
        if re.match(r"^([-*]|\d+\.)\s+", stripped):
            items = []
            ordered = bool(re.match(r"^\d+\.\s+", stripped))
            while i < len(lines):
                cur = lines[i].strip()
                m_li = re.match(r"^([-*]|\d+\.)\s+(.+)$", cur)
                if not m_li:
                    break
                items.append(m_li.group(2).strip())
                i += 1
            blocks.append(("ol" if ordered else "ul", items))
            continue
        p_lines = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (
                not nxt
                or nxt == "---"
                or nxt.startswith("#")
                or nxt.startswith("|")
                or nxt.startswith(">")
                or nxt.startswith("```")
                or re.match(r"^!\[", nxt)
                or re.match(r"^([-*]|\d+\.)\s+", nxt)
            ):
                break
            p_lines.append(nxt)
            i += 1
        blocks.append(("p", " ".join(p_lines)))
    return blocks


def build_proposal_cover_and_toc() -> str:
    """构建方案说明书的独立封面与目录页。"""
    meta = [
        ("参赛主题", "主题一「AI 赋能校园」——校园应用创意方案"),
        ("参赛单位", "楚雄师范学院　计算机与智能技术学院"),
        ("参赛形式", "个人赛"),
        ("参赛人", "李政寰　　学号：20240524140　　班级：2024级数字媒体技术班"),
        ("指导教师", "无"),
        ("提交日期", "2026 年 11 月 16 日"),
    ]
    cover = [
        make_paragraph(
            "计算机与智能技术学院 · 首届「动感地带杯」AI 创新应用大赛",
            align="center",
            space_before=1400,
            space_after=480,
            font_name="黑体",
            sz=28,
            color="1A4A7A",
        ),
        make_paragraph(
            "楚师智学",
            align="center",
            space_after=240,
            font_name="黑体",
            sz=60,
            color="12355B",
            bold=True,
        ),
        make_paragraph(
            "基于屏幕感知与 MobileClaw 的主动式 AI 个人学业管理平台",
            align="center",
            space_after=900,
            font_name="宋体",
            sz=28,
            color="33506E",
        ),
    ]
    for k, v in meta:
        cover.append(
            make_paragraph(
                f"**{k}**：{v}",
                align="left",
                left_indent=1100,
                space_after=160,
                font_name="宋体",
                sz=22,
                color="1F2933",
            )
        )
    cover.append(f"<w:p><w:pPr>{SECT_NO_FOOTER}</w:pPr></w:p>")
    toc = [
        make_paragraph(
            "目　　录",
            align="center",
            space_before=240,
            space_after=360,
            font_name="黑体",
            sz=36,
            color="12355B",
            bold=True,
        ),
        TOC_FIELD_BLOCK,
        f"<w:p><w:pPr>{SECT_NO_FOOTER}</w:pPr></w:p>",
    ]
    return "".join(cover + toc)


def md_to_docx(
    md_path: Path,
    docx_path: Path,
    *,
    with_cover_toc: bool = False,
) -> None:
    ensure_style_cache()
    md_text = md_path.read_text(encoding="utf-8")
    blocks = parse_md_blocks(md_text)

    if with_cover_toc:
        # 方案书封面与元数据已在独立封面节绘制，正文从「摘要」开始
        for idx, (kind, val) in enumerate(blocks):
            if kind == "h2" and "摘要" in str(val):
                blocks = blocks[idx:]
                break

    media_files: list[tuple[str, str, Path]] = []
    body_xml: list[str] = [build_proposal_cover_and_toc()] if with_cover_toc else []
    img_counter = 0

    sign_path = ROOT / "tools" / "_signature_clean.png"
    sign_rel_id: str | None = None
    if "{{SIGN}}" in md_text and sign_path.exists():
        img_counter += 1
        sign_rel_id = f"rId{10 + img_counter}"
        media_files.append((sign_rel_id, f"media/image{img_counter}.png", sign_path))

    for kind, val in blocks:
        if kind == "hr":
            continue
        if kind == "h1":
            body_xml.append(
                make_paragraph(
                    val,
                    style="000006" if not with_cover_toc else None,
                    align="center" if not with_cover_toc else "left",
                    space_before=240,
                    space_after=240,
                    font_name="黑体",
                    sz=34,
                    color="12355B",
                    bold=True,
                )
            )
        elif kind == "h2":
            body_xml.append(
                make_paragraph(
                    val,
                    style="000006",
                    space_before=320,
                    space_after=160,
                    font_name="黑体",
                    sz=30,
                    color="12355B",
                    bold=True,
                )
            )
        elif kind == "h3":
            body_xml.append(
                make_paragraph(
                    val,
                    style="000007",
                    space_before=220,
                    space_after=120,
                    font_name="黑体",
                    sz=26,
                    color="1A4A7A",
                    bold=True,
                )
            )
        elif kind == "h4":
            body_xml.append(
                make_paragraph(
                    val,
                    style="000008",
                    space_before=160,
                    space_after=80,
                    font_name="黑体",
                    sz=24,
                    color="2A445E",
                    bold=True,
                )
            )
        elif kind == "p":
            is_caption = val.startswith("*图 ") or val.startswith("*表 ")
            clean = val.strip("*") if is_caption else val
            body_xml.append(
                make_paragraph(
                    clean,
                    align="center" if is_caption else "left",
                    first_line=0 if (is_caption or "{{SIGN}}" in clean) else 480,
                    space_after=140 if is_caption else 110,
                    font_name="宋体",
                    sz=20 if is_caption else 24,
                    color="556372" if is_caption else "111111",
                    sign_rel_id=sign_rel_id,
                    sign_path=sign_path,
                )
            )
        elif kind == "quote":
            for qline in str(val).splitlines():
                body_xml.append(
                    make_paragraph(
                        qline,
                        left_indent=320,
                        space_before=60,
                        space_after=60,
                        line=340,
                        font_name="宋体",
                        sz=22,
                        color="334155",
                        shade="F3F6FA",
                        left_border="5B8CFF",
                    )
                )
        elif kind == "code":
            for cline in str(val).splitlines():
                body_xml.append(
                    make_paragraph(
                        f"`{cline}`" if cline else " ",
                        left_indent=240,
                        space_before=20,
                        space_after=20,
                        line=300,
                        font_name="Consolas",
                        sz=19,
                        color="1E293B",
                        shade="F5F7FA",
                    )
                )
        elif kind in ("ul", "ol"):
            for idx, item in enumerate(val, start=1):
                prefix = f"{idx}. " if kind == "ol" else "• "
                body_xml.append(
                    make_paragraph(
                        prefix + item,
                        left_indent=420,
                        space_after=70,
                        font_name="宋体",
                        sz=24,
                    )
                )
        elif kind == "table":
            body_xml.append(make_table(val, sign_rel_id=sign_rel_id, sign_path=sign_path))
        elif kind == "img":
            alt, rel_src = val
            img_path = (md_path.parent / rel_src).resolve()
            if img_path.exists():
                img_counter += 1
                rid = f"rId{10 + img_counter}"
                arcname = f"media/image{img_counter}{img_path.suffix.lower()}"
                media_files.append((rid, arcname, img_path))
                body_xml.append(make_image_paragraph(rid, img_path, 100 + img_counter))
            else:
                body_xml.append(make_paragraph(f"[图片未找到：{alt}]", align="center", color="991B1B"))

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" mc:Ignorable="w14">'
        "<w:body>"
        + "".join(body_xml)
        + SECT_WITH_FOOTER
        + "</w:body></w:document>"
    )

    rels_base = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId0" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable" Target="fontTable.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>'
        '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
        '<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
        + "".join(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{arc}"/>'
            for rid, arc, _ in media_files
        )
        + "</Relationships>"
    )

    docx_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(STYLE_CACHE, "r") as base_zip, zipfile.ZipFile(
        docx_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as out_zip:
        for item in base_zip.infolist():
            if item.filename == "word/_rels/document.xml.rels":
                continue
            out_zip.writestr(item.filename, base_zip.read(item.filename))
        out_zip.writestr("word/_rels/document.xml.rels", rels_base.encode("utf-8"))
        out_zip.writestr("word/document.xml", document_xml.encode("utf-8"))
        for _, arc, img_path in media_files:
            out_zip.writestr(f"word/{arc}", img_path.read_bytes())
    print(f"[DOCX] -> {docx_path} ({docx_path.stat().st_size // 1024} KB)")


def md_to_html_for_pdf(md_path: Path, *, with_cover: bool = False) -> str:
    md_text = md_path.read_text(encoding="utf-8")
    blocks = parse_md_blocks(md_text)

    def inline_html(s: str) -> str:
        s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
        s = s.replace("<br><br>", "__BR____BR__").replace("<br/>", "__BR__").replace("<br>", "__BR__")
        esc = html_lib.escape(s)
        esc = esc.replace("__BR__", "<br/>")
        esc = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", esc)
        esc = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc)
        return esc

    body: list[str] = []
    if with_cover:
        # 收集一级、二级目录条目生成带锚点的独立目录页
        toc_items: list[tuple[str, str, list[tuple[str, str]]]] = []
        sec_idx = 0
        sub_idx = 0
        for kind, val in blocks:
            if kind == "h2":
                sec_idx += 1
                sub_idx = 0
                toc_items.append((f"sec-{sec_idx}", str(val), []))
            elif kind == "h3" and toc_items:
                sub_idx += 1
                toc_items[-1][2].append((f"sub-{sec_idx}-{sub_idx}", str(val)))

        toc_html = ['<div class="toc"><div class="toc-title">目　　录</div><ul class="toc-root">']
        for sid, title, subs in toc_items:
            toc_html.append(f'<li class="toc-h1"><a href="#{sid}">{inline_html(title)}</a>')
            if subs:
                toc_html.append('<ul class="toc-sub">')
                for sub_id, stitle in subs:
                    toc_html.append(f'<li class="toc-h2"><a href="#{sub_id}">{inline_html(stitle)}</a></li>')
                toc_html.append("</ul>")
            toc_html.append("</li>")
        toc_html.append('</ul></div><div style="page-break-after: always;"></div>')

        body.append(
            """
            <div class="cover">
              <div class="cover-org">计算机与智能技术学院 · 首届「动感地带杯」AI 创新应用大赛</div>
              <div class="cover-title">楚师智学</div>
              <div class="cover-sub">基于屏幕感知与 MobileClaw 的主动式 AI 个人学业管理平台</div>
              <div class="cover-meta">
                <div><b>参赛主题</b>：主题一「AI 赋能校园」——校园应用创意方案</div>
                <div><b>参赛单位</b>：楚雄师范学院　计算机与智能技术学院（个人赛）</div>
                <div><b>参赛人</b>：李政寰　学号：20240524140　班级：2024级数字媒体技术班</div>
                <div><b>指导教师</b>：无　　<b>提交日期</b>：2026 年 11 月 16 日</div>
              </div>
            </div>
            <div style="page-break-after: always;"></div>
            """
            + "".join(toc_html)
        )
        for idx, (kind, val) in enumerate(blocks):
            if kind == "h2" and "摘要" in str(val):
                blocks = blocks[idx:]
                break

    h2_counter = 0
    h3_counter = 0
    for kind, val in blocks:
        if kind == "hr":
            continue
        elif kind == "h1":
            body.append(f"<h1>{inline_html(val)}</h1>")
        elif kind == "h2":
            h2_counter += 1
            h3_counter = 0
            body.append(f'<h2 id="sec-{h2_counter}">{inline_html(val)}</h2>')
        elif kind == "h3":
            h3_counter += 1
            body.append(f'<h3 id="sub-{h2_counter}-{h3_counter}">{inline_html(val)}</h3>')
        elif kind == "h4":
            body.append(f"<h4>{inline_html(val)}</h4>")
        elif kind == "p":
            if val.startswith("*图 ") or val.startswith("*表 "):
                body.append(f'<p class="caption">{inline_html(val.strip("*"))}</p>')
            else:
                body.append(f"<p>{inline_html(val)}</p>")
        elif kind == "quote":
            body.append(f"<blockquote>{'<br/>'.join(inline_html(l) for l in str(val).splitlines())}</blockquote>")
        elif kind == "code":
            body.append(f"<pre>{html_lib.escape(val)}</pre>")
        elif kind in ("ul", "ol"):
            items = "".join(f"<li>{inline_html(it)}</li>" for it in val)
            body.append(f"<{kind}>{items}</{kind}>")
        elif kind == "table":
            ths = "".join(f"<th>{inline_html(c)}</th>" for c in val[0])
            trs = "".join(
                "<tr>" + "".join(f"<td>{inline_html(c)}</td>" for c in r) + "</tr>"
                for r in val[1:]
            )
            body.append(f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>")
        elif kind == "img":
            alt, rel_src = val
            img_path = (md_path.parent / rel_src).resolve()
            if img_path.exists():
                uri = img_path.as_uri()
                body.append(
                    f'<div class="fig"><img src="{uri}" alt="{html_lib.escape(alt)}"/></div>'
                )

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<style>
  @page {{ size: A4; margin: 22mm 20mm; }}
  body {{ font-family: "SimSun", "宋体", "Microsoft YaHei", serif; font-size: 11.5pt; line-height: 1.7; color: #111827; }}
  .cover {{ padding-top: 48mm; text-align: center; }}
  .cover-org {{ color: #1A4A7A; font-family: "SimHei", "Microsoft YaHei", sans-serif; font-size: 13pt; margin-bottom: 18mm; }}
  .cover-title {{ color: #12355B; font-family: "SimHei", "Microsoft YaHei", sans-serif; font-size: 32pt; font-weight: bold; margin-bottom: 6mm; }}
  .cover-sub {{ color: #33506E; font-size: 13.5pt; margin-bottom: 24mm; }}
  .cover-meta {{ width: 78%; margin: 0 auto; text-align: left; font-size: 11pt; line-height: 2.1; border-top: 2px solid #12355B; padding-top: 8mm; }}
  .toc {{ padding-top: 6mm; }}
  .toc-title {{ text-align: center; font-family: "SimHei", "Microsoft YaHei", sans-serif; font-size: 18pt; font-weight: bold; color: #12355B; margin-bottom: 10mm; }}
  .toc-root {{ list-style: none; padding-left: 0; margin: 0; }}
  .toc-h1 {{ font-family: "SimHei", "Microsoft YaHei", sans-serif; font-size: 12pt; margin: 6pt 0; }}
  .toc-sub {{ list-style: none; padding-left: 18pt; margin: 2pt 0 4pt; }}
  .toc-h2 {{ font-family: "SimSun", "宋体", serif; font-size: 10.5pt; margin: 3pt 0; }}
  .toc a {{ color: #1F2933; text-decoration: none; }}
  h1, h2, h3, h4 {{ font-family: "SimHei", "Microsoft YaHei", sans-serif; color: #12355B; page-break-after: avoid; }}
  h1 {{ text-align: center; font-size: 17pt; margin: 0 0 10pt; }}
  h2 {{ font-size: 14.5pt; border-bottom: 1px solid #d1d5db; padding-bottom: 3pt; margin-top: 16pt; }}
  h3 {{ font-size: 12.5pt; color: #1A4A7A; margin-top: 12pt; }}
  h4 {{ font-size: 11.5pt; color: #2A445E; margin-top: 10pt; }}
  p {{ margin: 5pt 0; text-indent: { '2em' if with_cover else '0' }; }}
  p.caption {{ text-align: center; text-indent: 0; font-size: 9.5pt; color: #4B5563; margin-bottom: 10pt; }}
  table {{ width: 100%; border-collapse: collapse; margin: 10pt 0; font-size: 10pt; page-break-inside: avoid; }}
  th, td {{ border: 1px solid #94A3B8; padding: 6pt 8pt; vertical-align: top; text-align: left; }}
  th {{ background: #E8EEF5; color: #12355B; font-family: "SimHei", "Microsoft YaHei", sans-serif; text-align: center; }}
  blockquote {{ margin: 8pt 0; padding: 7pt 11pt; border-left: 3pt solid #5B8CFF; background: #F3F6FA; color: #334155; font-size: 10.5pt; }}
  pre {{ background: #F5F7FA; border: 1px solid #E2E8F0; padding: 8pt 10pt; font-family: Consolas, monospace; font-size: 9.5pt; white-space: pre-wrap; }}
  code {{ font-family: Consolas, monospace; color: #1A4A7A; background: #F1F5F9; padding: 1pt 3pt; border-radius: 2pt; font-size: 10pt; }}
  .fig {{ text-align: center; margin: 10pt 0 4pt; page-break-inside: avoid; }}
  .fig img {{ max-width: 96%; max-height: 150mm; border: 1px solid #CBD5E1; border-radius: 4pt; }}
  hr {{ border: none; border-top: 1px dashed #CBD5E1; margin: 10pt 0; }}
</style></head><body>{''.join(body)}</body></html>"""


def render_pdfs(jobs: list[tuple[Path, Path, bool]]) -> None:
    import tempfile

    app = QApplication.instance() or QApplication(sys.argv)
    page = QWebEnginePage()
    page.settings().setAttribute(page.settings().WebAttribute.LocalContentCanAccessFileUrls, True)
    layout = QPageLayout(
        QPageSize(QPageSize.PageSizeId.A4),
        QPageLayout.Orientation.Portrait,
        QMarginsF(0, 0, 0, 0),
    )

    with tempfile.TemporaryDirectory(prefix="maolog_pdf_") as tmp_dir:
        for idx, (md_path, pdf_path, with_cover) in enumerate(jobs):
            html_str = md_to_html_for_pdf(md_path, with_cover=with_cover)
            tmp_html = Path(tmp_dir) / f"doc_{idx}.html"
            tmp_html.write_text(html_str, encoding="utf-8")
            done = [False]
            loop = QEventLoop()

            def on_loaded(ok: bool) -> None:
                def on_pdf(data: bytes) -> None:
                    pdf_path.write_bytes(data)
                    done[0] = True
                    loop.quit()

                page.printToPdf(on_pdf, layout)

            page.loadFinished.connect(on_loaded)
            page.load(QUrl.fromLocalFile(str(tmp_html)))
            if not done[0]:
                loop.exec()
            page.loadFinished.disconnect(on_loaded)
            print(f"[PDF]  -> {pdf_path} ({pdf_path.stat().st_size // 1024} KB)")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="生成参赛材料 Word 及方案说明书最终 PDF")
    parser.add_argument("--all-pdf", action="store_true", help="同时为附件 1/2/3 与过程记录导出 PDF")
    parser.add_argument("--no-pdf", action="store_true", help="仅生成 .docx，不导出方案书 PDF")
    args = parser.parse_args()

    ensure_style_cache()
    targets = [
        (DOCS / "楚师智学-参赛方案说明书.md", DOCS / "楚师智学-参赛方案说明书.docx", DOCS / "楚师智学-参赛方案说明书.pdf", True),
        (SUBMIT_DIR / "附件1-参赛报名及作品信息表.md", SUBMIT_DIR / "附件1-参赛报名及作品信息表.docx", SUBMIT_DIR / "附件1-参赛报名及作品信息表.pdf", False),
        (SUBMIT_DIR / "附件2-作品提交清单与自查说明.md", SUBMIT_DIR / "附件2-作品提交清单与自查说明.docx", SUBMIT_DIR / "附件2-作品提交清单与自查说明.pdf", False),
        (SUBMIT_DIR / "附件3-原创承诺书及AI工具使用声明.md", SUBMIT_DIR / "附件3-原创承诺书及AI工具使用声明.docx", SUBMIT_DIR / "附件3-原创承诺书及AI工具使用声明.pdf", False),
        (SUBMIT_DIR / "创作过程记录.md", SUBMIT_DIR / "创作过程记录.docx", SUBMIT_DIR / "创作过程记录.pdf", False),
    ]
    for md_p, docx_p, _, cover in targets:
        md_to_docx(md_p, docx_p, with_cover_toc=cover)
    if args.all_pdf:
        render_pdfs([(md_p, pdf_p, cover) for md_p, _, pdf_p, cover in targets])
    elif not args.no_pdf:
        # 创意方案书直接输出最终提交 PDF，附件 1/2/3 与过程记录保持可编辑 Word
        md_p, _, pdf_p, cover = targets[0]
        render_pdfs([(md_p, pdf_p, cover)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
