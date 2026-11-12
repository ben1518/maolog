"""把 ImageGen 出的线稿处理成可用素材。

做法：白底线稿本质是「白底 + 灰阶线条」，所以直接按亮度生成 alpha，
再把颜色统一成一个墨色。好处是：
  1. 白底彻底消失，放到米色纸面上不会出现白方块；
  2. 六张图的线条颜色、透明边缘完全一致（手绘风最怕每张色调不一）；
  3. 想去掉多余留白，只保留主体附近。

用法：
    python tools/make_doodle_assets.py
    python tools/make_doodle_assets.py --ink "#2B4A7C"   # 换成蓝墨水
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "doodle" / "raw"
DST = ROOT / "assets" / "doodle"

# 原始文件 -> 语义名
MAPPING = {
    "desk.png": "empty-board.png",
    "person.png": "empty-summary.png",
    "ring.png": "ring-empty.png",
    "bars.png": "apps-empty.png",
    "notebook.png": "review-empty.png",
    "door.png": "splash.png",
}


def hex_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return tuple(int(v[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def to_line_art(path: Path, ink: tuple[int, int, int], margin_ratio: float = 0.04) -> Image.Image:
    im = Image.open(path).convert("RGB")
    # 亮度越低越「是线」，alpha 反比
    gray = im.convert("L")
    alpha = gray.point(lambda v: 255 - v)

    # 抬高下限：去掉极淡的水印和纸纹噪点，同时保线条边缘的过渡
    floor = 46
    alpha = alpha.point(lambda a: 0 if a < floor else min(255, int((a - floor) * 255 / (255 - floor))))

    out = Image.new("RGBA", im.size, (*ink, 0))
    out.putalpha(alpha)

    box = alpha.getbbox()
    if box:
        pad = int(max(im.size) * margin_ratio)
        left = max(0, box[0] - pad)
        top = max(0, box[1] - pad)
        right = min(im.width, box[2] + pad)
        bottom = min(im.height, box[3] + pad)
        out = out.crop((left, top, right, bottom))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ink", default="#22314F", help="线条颜色，默认深墨蓝")
    args = parser.parse_args()
    ink = hex_rgb(args.ink)

    if not SRC.exists():
        print(f"找不到原始目录：{SRC}")
        return 1

    made = 0
    for raw_name, out_name in MAPPING.items():
        src = SRC / raw_name
        if not src.exists():
            print(f"  跳过（缺失）{raw_name}")
            continue
        img = to_line_art(src, ink)
        out = DST / out_name
        img.save(out)
        print(f"  {raw_name:14s} -> {out_name:18s} {img.width}x{img.height}  {out.stat().st_size // 1024} KB")
        made += 1

    print(f"\n完成 {made} 张，墨色 {args.ink}，输出目录 {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
