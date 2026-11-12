"""把手绘装饰线稿处理成可直接叠在界面上的素材。

和空状态插画用的是同一套思路：白底按亮度生成 alpha，但装饰元素尺寸小、
要在卡片角落高频出现，所以额外做了两件事：

1. **去留白**：按墨迹外框裁紧，否则摆到卡片角上会偏移一大截；
2. **统一线宽**：图像生成出来的线粗细不一，叠在一起显得杂乱。

输出两份：
- `xxx.png`       深色墨线，给浅色皮肤
- `xxx-light.png` 奶白线 + 加粗，给深色皮肤

用法：
    python tools/make_pet_assets.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "doodle" / "raw" / "pets"
DST = ROOT / "assets" / "doodle"

# 原始文件前缀 -> 语义名
MAPPING = {
    "cat_sit": "pet-cat.png",
    "dog_sit": "pet-dog.png",
    "cat_loaf": "pet-cat-lazy.png",
    "dog_sleep": "pet-dog-lazy.png",
    "cat_peek": "pet-cat-peek.png",
    "dog_peek": "pet-dog-peek.png",
}


def hex_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return tuple(int(v[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def ink_alpha(img: Image.Image, paper: int = 213) -> Image.Image:
    """按亮度生成 alpha：越暗越不透明，白底完全透明。

    paper 是"什么亮度以上算纸"。设得太低会把浅灰的辅助线留下，
    设得太高又会吃掉细线的浅色边缘，213 是这两张图的实测折中值。
    """
    gray = img.convert("L")
    return gray.point(lambda v: 0 if v >= paper else int(255 * (1 - v / paper)))


def trim(alpha: Image.Image, pad: int = 6) -> Image.Image:
    """按不透明区域裁紧，留一点呼吸边。"""
    box = alpha.getbbox()
    if not box:
        return alpha
    left, top, right, bottom = box
    return alpha.crop(
        (
            max(0, left - pad),
            max(0, top - pad),
            min(alpha.width, right + pad),
            min(alpha.height, bottom + pad),
        )
    )


def build(src: Path, dst: Path, ink: str, bold: bool, target_px: int = 160) -> tuple[int, int]:
    """生成素材。

    关键顺序：**先缩到目标尺寸、再膨胀加粗**。
    装饰图在界面上只显示 40~80px，而生成的线稿是 1024px 里 3px 的细线，
    直接缩下来会变成 0.14px——肉眼完全看不见。先缩后加粗，
    才能在缩小后仍保持 1px 左右的可见线宽。
    """
    img = Image.open(src).convert("RGB")
    alpha = ink_alpha(img)
    alpha = trim(alpha)

    # 先等比缩到目标尺寸（按长边）
    w, h = alpha.size
    scale = target_px / max(w, h)
    if scale < 1:
        alpha = alpha.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.LANCZOS,
        )

    # 再按最终尺寸决定加粗强度
    if bold:
        alpha = alpha.filter(ImageFilter.MaxFilter(3))
        alpha = alpha.filter(ImageFilter.GaussianBlur(0.45))
    else:
        alpha = alpha.filter(ImageFilter.MaxFilter(3))
        alpha = alpha.filter(ImageFilter.GaussianBlur(0.35))

    solid = Image.new("RGBA", alpha.size, (*hex_rgb(ink), 0))
    solid.putalpha(alpha)
    dst.parent.mkdir(parents=True, exist_ok=True)
    solid.save(dst)
    return solid.size


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ink", default="#3A342E", help="浅色皮肤的墨线色")
    parser.add_argument("--ink-light", default="#EDE6D2", help="深色皮肤的线色")
    args = parser.parse_args()

    if not SRC.exists():
        print(f"找不到原始目录：{SRC}")
        return 1

    files = sorted(SRC.glob("*.png"))
    if not files:
        print("原始目录里没有 png")
        return 1

    # 按前缀匹配语义名；匹配不上就按序号命名
    used: dict[str, Path] = {}
    for f in files:
        key = None
        for prefix in MAPPING:
            if f.name.startswith(prefix):
                key = prefix
                break
        if key and key not in used:
            used[key] = f

    if not used:
        # 兜底：按顺序分配
        order = list(MAPPING)
        for i, f in enumerate(files[: len(order)]):
            used[order[i]] = f

    for key, f in used.items():
        target = DST / MAPPING[key]
        size = build(f, target, args.ink, bold=False)
        light = DST / f"{target.stem}-light{target.suffix}"
        size2 = build(f, light, args.ink_light, bold=True)
        print(f"{f.name[:30]:32s} -> {target.name} {size}  /  {light.name} {size2}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
