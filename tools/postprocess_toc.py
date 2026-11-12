"""后处理：把转换生成的静态目录文本替换成 Word 的 TOC 域。

为什么需要这一步：HTML 里的 <nav class="doc-toc"> 转成 docx 后只是普通段落列表，
既没有页码也不能点击跳转。换成 TOC 域之后，Word / WPS 打开按提示更新一次域，
就会生成带页码、可跳转的真实目录。

只改两处：document.xml 里的目录块、settings.xml 里的 updateFields 开关。
其余条目原样拷贝，不重新序列化 XML，避免破坏原有格式。

    .venv/Scripts/python.exe tools/postprocess_toc.py <docx>
"""

from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

TOC_FIELD = (
    '<w:p>'
    "<w:pPr>{sectPr}"
    '<w:spacing w:after="240" w:line="360"/>'
    "</w:pPr>"
    '<w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-2" \\h \\z \\u </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    '<w:r><w:rPr><w:rFonts w:hint="eastAsia" w:eastAsia="宋体"/>'
    '<w:color w:val="808080"/><w:sz w:val="21"/></w:rPr>'
    "<w:t>目录将在打开文档时自动生成；若没有出现，请右键此处选择「更新域」。</w:t></w:r>"
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    "</w:p>"
)


def patch_document(xml: str) -> tuple[str, bool]:
    """把「目　　录」之后的目录条目段落换成一个 TOC 域段落。"""
    marker = xml.find("目　　录")
    if marker == -1:
        return xml, False

    # 目录标题所在段落的结束位置
    head_end = xml.find("</w:p>", marker)
    if head_end == -1:
        return xml, False
    head_end += len("</w:p>")

    # 第一个正文一级标题（pStyle 000006 = heading 1）的起点
    body_start = -1
    for m in re.finditer(r'<w:p\b[^>]*>', xml[head_end:]):
        seg_end = xml.find("</w:p>", head_end + m.start())
        seg = xml[head_end + m.start() : seg_end if seg_end != -1 else len(xml)]
        if '<w:pStyle w:val="000006"/>' in seg or '<w:pStyle w:val="000006">' in seg:
            body_start = head_end + m.start()
            break
    if body_start == -1:
        return xml, False

    block = xml[head_end:body_start]

    # 目录节的分节符挂在最后一段上，删段落时必须把它救出来
    sect_matches = re.findall(r"<w:sectPr\b.*?</w:sectPr>", block, re.S)
    sect = sect_matches[-1] if sect_matches else ""

    new_block = TOC_FIELD.format(sectPr=sect)
    return xml[:head_end] + new_block + xml[body_start:], True


def patch_settings(xml: str) -> tuple[str, bool]:
    """开启打开时更新域，让目录自动生成。"""
    if "updateFields" in xml:
        return xml, False
    tag = '<w:updateFields w:val="true"/>'
    for anchor in ("<w:defaultTabStop", "<w:compat", "<w:rsids", "</w:settings>"):
        idx = xml.find(anchor)
        if idx != -1:
            if anchor == "</w:settings>":
                return xml[:idx] + tag + xml[idx:], True
            return xml[:idx] + tag + xml[idx:], True
    return xml, False


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python tools/postprocess_toc.py <docx 路径>")
        return 1

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"文件不存在：{target}")
        return 1

    backup = target.with_suffix(".bak.docx")
    shutil.copyfile(target, backup)

    with zipfile.ZipFile(target, "r") as src:
        items = [(i, src.read(i.filename)) for i in src.infolist()]

    changed = []
    out_items: list[tuple[zipfile.ZipInfo, bytes]] = []

    for info, data in items:
        if info.filename == "word/document.xml":
            text = data.decode("utf-8")
            new_text, ok = patch_document(text)
            if ok:
                changed.append("目录域")
                data = new_text.encode("utf-8")
        elif info.filename == "word/settings.xml":
            text = data.decode("utf-8")
            new_text, ok = patch_settings(text)
            if ok:
                changed.append("自动更新域")
                data = new_text.encode("utf-8")
        out_items.append((info, data))

    if not changed:
        print("没有需要改动的内容，保持原样")
        backup.unlink(missing_ok=True)
        return 0

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
        for info, data in out_items:
            dst.writestr(info, data)

    print(f"已替换：{'、'.join(changed)}")
    print(f"备份：{backup.name}")
    print(f"产物：{target}（{target.stat().st_size / 1024:.0f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
