"""应用内字体加载。

手绘皮肤靠的是一套能随程序分发的楷体：系统自带的「楷体/华文行楷」是
Windows 分发的，打进 exe 分发有授权风险。这里用霞鹜文楷（SIL OFL），
可以商用、可以嵌入。

字体体积不小（Regular 约 26 MB，Medium 约 24 MB），所以只在文件存在时才加载，
缺文件时自动回落到系统楷体，不会因为少一个文件就起不来。
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase

from core.paths import asset_dir

FONT_DIR = asset_dir() / "fonts"

# 文件名 -> 期望的字重。加载后按家族名 + 字重登记，Qt 才能正确选字重，
# 否则 Medium 会被当成另一个家族，bold 还是靠合成。
FONT_FILES = {
    "LXGWWenKai-Regular.ttf": QFont.Weight.Normal,
    "LXGWWenKai-Medium.ttf": QFont.Weight.DemiBold,
}

PREFERRED_FAMILIES = ["LXGW WenKai", "霞鹜文楷"]


def load_bundled_fonts() -> list[str]:
    """把 assets/fonts 下的字体注册进 Qt，返回成功加载的家族名。"""
    loaded: list[str] = []
    if not FONT_DIR.exists():
        return loaded

    for name in FONT_FILES:
        path = FONT_DIR / name
        if not path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        loaded.extend(families)

    seen: set[str] = set()
    unique = [f for f in loaded if not (f in seen or seen.add(f))]
    return unique


def available_family() -> str:
    """返回一个当前可用的手写风格家族名，找不到就回落到楷体。"""
    families = QFontDatabase.families()
    for family in PREFERRED_FAMILIES:
        if family in families:
            return family
    return "KaiTi"


def has_bold_weight() -> bool:
    """是否真的加载了更重的字重（用于决定要不要让 Qt 合成粗体）。"""
    return (FONT_DIR / "LXGWWenKai-Medium.ttf").exists()
