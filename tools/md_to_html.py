"""把方案说明书的 Markdown 转成符合 html-to-doc 规范的 HTML。

这份转换器只服务本项目的文档结构（标题、段落、列表、表格、代码块、引用、图片），
不是通用 Markdown 解析器。关键规范来自 doc-formatter §2.5：

  · 正文字体第一项必须是宋体，字号 12pt（小四），首行缩进 2em
  · 章节标题必须用 h1~h3，否则目录收不到
  · 封面标题禁用 h1~h6（会被 TOC 当成第一条）
  · 目录用 nav.doc-toc，必须独占一个 section
  · 页眉页脚页码写在 @page 里

    .venv/Scripts/python.exe tools/md_to_html.py <输入.md> <输出.html> <图片目录>
"""

from __future__ import annotations

import base64
import re
import shutil
import sys
from pathlib import Path

TITLE = "楚师智学"
SUBTITLE = "基于屏幕感知与 MobileClaw 的主动式 AI 个人学业管理平台"

COVER_META = [
    ("参赛主题", "主题一「AI 赋能校园」——校园应用创意方案"),
    ("参赛单位", "楚雄师范学院　计算机与智能技术学院"),
    ("参赛形式", "个人赛"),
    ("参赛人", "[待填：姓名]　　学号：[待填]　　班级：[待填]"),
    ("指导教师", "[待填]"),
    ("提交日期", "2026 年 11 月"),
]

CSS = """
@page {
  margin: 2.5cm 2.5cm 2.5cm 2.5cm;
  @bottom-center { content: counter(page); }
}
@page cover { @bottom-center { content: none; } }
section[role="cover"] { page: cover; }

body {
  font-family: "宋体", SimSun, serif;
  font-size: 12pt;
  line-height: 1.7;
  color: #000000;
}

/* ---------- 封面 ---------- */
.cover-wrap { padding-top: 4.5cm; }
.cover-org {
  font-family: "黑体", SimHei, sans-serif;
  font-size: 14pt;
  color: #1a4a7a;
  letter-spacing: 0.1em;
  margin-bottom: 2.2cm;
  text-align: center;
}
.cover-title {
  font-family: "黑体", SimHei, sans-serif;
  font-size: 30pt;
  font-weight: bold;
  color: #12355b;
  text-align: center;
  margin: 0 0 0.6cm 0;
  letter-spacing: 0.06em;
}
.cover-subtitle {
  font-size: 14pt;
  color: #33506e;
  text-align: center;
  margin: 0 auto 2.6cm auto;
  line-height: 1.6;
  text-indent: 0;
}
.cover-rule {
  width: 60%;
  margin: 0 auto 1.4cm auto;
  border-top: 2px solid #12355b;
}
.cover-meta { width: 66%; margin: 0 auto; }
.cover-meta-row {
  font-size: 11pt;
  color: #1f2933;
  margin-bottom: 0.42em;
  text-indent: 0;
  border-bottom: 1px solid #dfe3e8;
  padding-bottom: 0.3em;
}
.cover-meta-key {
  font-family: "黑体", SimHei, sans-serif;
  color: #5a6b7d;
  letter-spacing: 0.12em;
}

/* ---------- 目录 ---------- */
.toc-page { padding-top: 1cm; }
.toc-title {
  font-family: "黑体", SimHei, sans-serif;
  font-size: 18pt;
  font-weight: bold;
  text-align: center;
  margin-bottom: 1.1cm;
  text-indent: 0;
}
.toc-list, .toc-list ol { list-style: none; padding-left: 0; margin: 0; }
.toc-list li {
  font-size: 11.5pt;
  margin-bottom: 0.46em;
  text-indent: 0;
}
.toc-list > li > a { font-family: "黑体", SimHei, sans-serif; color: #000000; text-decoration: none; }
.toc-list ol { margin-top: 0.3em; }
.toc-list ol li { padding-left: 1.8em; font-size: 11pt; color: #333333; }
.toc-list a { color: #333333; text-decoration: none; }

/* ---------- 正文 ---------- */
.body-wrap { }
h1 {
  font-family: "黑体", SimHei, sans-serif;
  font-size: 18pt;
  font-weight: bold;
  color: #12355b;
  margin: 1.1cm 0 0.5cm 0;
  padding-bottom: 0.18cm;
  border-bottom: 1.5pt solid #12355b;
  text-indent: 0;
  page-break-after: avoid;
}
h2 {
  font-family: "黑体", SimHei, sans-serif;
  font-size: 14pt;
  font-weight: bold;
  color: #1a4a7a;
  margin: 0.8cm 0 0.35cm 0;
  text-indent: 0;
  page-break-after: avoid;
}
h3 {
  font-family: "黑体", SimHei, sans-serif;
  font-size: 12.5pt;
  font-weight: bold;
  color: #1f2933;
  margin: 0.55cm 0 0.28cm 0;
  text-indent: 0;
  page-break-after: avoid;
}
p {
  text-indent: 2em;
  margin: 0 0 0.55em 0;
  text-align: justify;
}
strong { font-weight: bold; }
ul, ol { margin: 0 0 0.55em 0; padding-left: 2.6em; }
li { text-indent: 0; margin-bottom: 0.22em; line-height: 1.65; }

blockquote {
  margin: 0.5em 0 0.7em 0;
  padding: 0.45em 0.9em;
  border-left: 3pt solid #b9d0e8;
  background: #f4f7fb;
  text-indent: 0;
}
blockquote p { text-indent: 0; margin: 0.2em 0; }

pre {
  font-family: "Consolas", monospace;
  font-size: 9.5pt;
  line-height: 1.5;
  background: #f6f8fa;
  border: 1pt solid #dfe3e8;
  padding: 0.5em 0.8em;
  margin: 0.5em 0 0.7em 0;
  white-space: pre-wrap;
  text-indent: 0;
}
code { font-family: "Consolas", monospace; font-size: 10pt; }

table {
  width: 100%;
  border-collapse: collapse;
  margin: 0.45em 0 0.85em 0;
  font-size: 10.5pt;
}
th, td {
  border: 1pt solid #b9c4d0;
  padding: 0.3em 0.5em;
  text-indent: 0;
  line-height: 1.5;
  vertical-align: top;
}
th {
  background: #e8eef5;
  font-family: "黑体", SimHei, sans-serif;
  font-weight: bold;
  text-align: center;
}

.fig { text-align: center; margin: 0.6em 0 0.2em 0; text-indent: 0; }
.fig img { width: 100%; }
.fig-caption {
  text-align: center;
  font-size: 10pt;
  color: #4a5a6a;
  text-indent: 0;
  margin: 0.15em 0 0.9em 0;
}
"""


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(text: str) -> str:
    """处理行内标记：加粗、行内代码。"""
    text = esc(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def convert_body(md: str, img_dir: Path) -> tuple[str, list[tuple[str, list[str]]]]:
    """返回正文 HTML 和目录结构 [(一级标题, [二级标题...])]。"""
    lines = md.splitlines()
    out: list[str] = []
    toc: list[tuple[str, list[str]]] = []

    i = 0
    in_code = False
    code_buf: list[str] = []
    in_quote = False
    quote_buf: list[str] = []
    list_buf: list[str] = []
    list_tag = ""
    table_buf: list[str] = []
    section_no = 0
    started = False  # 摘要之前的内容（标题、元信息）跳过
    skip_next_caption = False

    def flush_list() -> None:
        nonlocal list_buf, list_tag
        if list_buf:
            out.append(f"<{list_tag}>" + "".join(f"<li>{x}</li>" for x in list_buf) + f"</{list_tag}>")
            list_buf = []
            list_tag = ""

    def flush_quote() -> None:
        nonlocal quote_buf, in_quote
        if quote_buf:
            inner = "".join(f"<p>{x}</p>" for x in quote_buf)
            out.append(f"<blockquote>{inner}</blockquote>")
            quote_buf = []
        in_quote = False

    def flush_table() -> None:
        nonlocal table_buf
        if not table_buf:
            return
        rows = [r for r in table_buf if not re.match(r"^\|[\s:\-\|]+\|$", r.strip())]
        html = ["<table>"]
        for idx, row in enumerate(rows):
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            tag = "th" if idx == 0 else "td"
            html.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
        html.append("</table>")
        out.append("".join(html))
        table_buf = []

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        # 代码块
        if stripped.startswith("```"):
            if in_code:
                out.append("<pre>" + esc("\n".join(code_buf)) + "</pre>")
                code_buf = []
                in_code = False
            else:
                flush_list()
                flush_quote()
                flush_table()
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(raw)
            i += 1
            continue

        # 表格
        if stripped.startswith("|"):
            flush_list()
            flush_quote()
            table_buf.append(stripped)
            i += 1
            continue
        elif table_buf:
            flush_table()

        # 引用
        if stripped.startswith(">"):
            flush_list()
            quote_buf.append(inline(stripped.lstrip("> ").strip()))
            in_quote = True
            i += 1
            continue
        elif in_quote:
            flush_quote()

        # 空行
        if not stripped:
            flush_list()
            i += 1
            continue

        # 分隔线
        if re.match(r"^-{3,}$", stripped):
            flush_list()
            i += 1
            continue

        # 图片
        m_img = re.match(r"^!\[(.*?)\]\((.+?)\)$", stripped)
        if m_img:
            flush_list()
            alt, src = m_img.group(1), m_img.group(2)
            fname = Path(src).name
            # 转换服务读不到本地相对路径，必须把图内联成 data URI
            local = img_dir / fname
            if local.exists():
                b64 = base64.b64encode(local.read_bytes()).decode("ascii")
                out.append(
                    f'<div class="fig"><img src="data:image/png;base64,{b64}" '
                    f'alt="{esc(alt)}"/></div>'
                )
            else:
                out.append(f'<div class="fig"><img src="images/{fname}" alt="{esc(alt)}"/></div>')
            skip_next_caption = True
            i += 1
            continue

        # 图片说明（紧跟图片的 *斜体行*）
        if skip_next_caption and stripped.startswith("*") and stripped.endswith("*"):
            out.append(f'<p class="fig-caption">{inline(stripped.strip("*"))}</p>')
            skip_next_caption = False
            i += 1
            continue
        skip_next_caption = False

        # 标题
        if stripped.startswith("# "):
            # 文档大标题，封面已用，正文跳过
            i += 1
            continue

        if stripped.startswith("## "):
            flush_list()
            text = stripped[3:].strip()
            if text == "摘要":
                started = True
            if not started:
                i += 1
                continue
            section_no += 1
            toc.append((text, []))
            out.append(f'<h1 id="section-{section_no}">{inline(text)}</h1>')
            i += 1
            continue

        if stripped.startswith("### "):
            flush_list()
            text = stripped[4:].strip()
            if toc:
                toc[-1][1].append(text)
            out.append(f"<h2>{inline(text)}</h2>")
            i += 1
            continue

        if stripped.startswith("#### "):
            flush_list()
            text = stripped[5:].strip()
            out.append(f"<h3>{inline(text)}</h3>")
            i += 1
            continue

        # 列表
        m_ul = re.match(r"^[-*]\s+(.*)$", stripped)
        m_ol = re.match(r"^\d+\.\s+(.*)$", stripped)
        if m_ul or m_ol:
            tag = "ul" if m_ul else "ol"
            if list_tag and list_tag != tag:
                flush_list()
            list_tag = tag
            list_buf.append(inline((m_ul or m_ol).group(1)))
            i += 1
            continue

        # 普通段落
        flush_list()
        out.append(f"<p>{inline(stripped)}</p>")
        i += 1

    flush_list()
    flush_quote()
    flush_table()
    if in_code and code_buf:
        out.append("<pre>" + esc("\n".join(code_buf)) + "</pre>")

    return "\n".join(out), toc


def build_toc(toc: list[tuple[str, list[str]]]) -> str:
    items = []
    for idx, (title, subs) in enumerate(toc, start=1):
        sub_html = ""
        if subs:
            sub_html = "<ol>" + "".join(
                f'<li><a href="#section-{idx}">{esc(s)}</a></li>' for s in subs
            ) + "</ol>"
        items.append(f'<li><a href="#section-{idx}">{esc(title)}</a>{sub_html}</li>')
    return "".join(items)


def main() -> int:
    if len(sys.argv) < 4:
        print("用法：python tools/md_to_html.py <输入.md> <输出.html> <图片源目录>")
        return 1

    md_path = Path(sys.argv[1])
    html_path = Path(sys.argv[2])
    img_dir = Path(sys.argv[3])

    md = md_path.read_text(encoding="utf-8")
    body, toc = convert_body(md, img_dir)

    # 图片复制到 HTML 同级 images/
    out_images = html_path.parent / "images"
    out_images.mkdir(parents=True, exist_ok=True)
    copied = 0
    for fig in img_dir.glob("*.png"):
        shutil.copyfile(fig, out_images / fig.name)
        copied += 1

    meta_html = "".join(
        f'<p class="cover-meta-row"><span class="cover-meta-key">{k}　</span>{esc(v)}</p>'
        for k, v in COVER_META
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="docx-page-size" content="A4"/>
<title>{esc(TITLE)}</title>
<style>{CSS}</style>
</head>
<body>

<section role="cover">
  <div class="cover-wrap">
    <p class="cover-org">计算机与智能技术学院 · 首届「动感地带杯」AI 创新应用大赛</p>
    <p class="cover-title">{esc(TITLE)}</p>
    <p class="cover-subtitle">{esc(SUBTITLE)}</p>
    <div class="cover-rule"></div>
    <div class="cover-meta">
      {meta_html}
    </div>
  </div>
</section>

<section role="cover">
  <div class="toc-page">
    <p class="toc-title">目　　录</p>
    <ol class="toc-list">{build_toc(toc)}</ol>
  </div>
</section>

<section role="body" data-page-restart="1">
  <div class="body-wrap">
{body}
  </div>
</section>

</body>
</html>
"""

    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")

    print(f"已生成 {html_path}")
    print(f"  一级标题 {len(toc)} 个，二级标题 {sum(len(s) for _, s in toc)} 个")
    print(f"  复制图片 {copied} 张 -> {out_images}")
    print(f"  HTML 大小 {len(html) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
