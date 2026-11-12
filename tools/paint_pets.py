"""给线稿自动填色，做出马克笔涂色的效果。

思路：
1. 从画面边缘做一次洪水填充，得到"外部背景"；
2. 剩下的 alpha=0 区域就是被线稿围住的内部空洞；
3. 按空洞大小分配颜色——大的当身体，小的当耳朵/肚皮；
4. 填色层放在墨线下面，边缘做一点内缩，避免盖住线。

为什么不用简单的"整体染色"：那样就是个剪影，能看到线但看不到"涂"的痕迹。
分区填色才会出现一坨一坨、颜色深浅不一的手涂感。
"""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "assets" / "doodle"


def find_regions(alpha: Image.Image, threshold: int = 60) -> tuple[set, list[list[tuple[int, int]]]]:
    """把 alpha 图分成"外部背景"和"若干内部空洞"。

    用 BFS 从四边灌水：能灌到的是外部，灌不到的就是被线围住的内部。
    """
    w, h = alpha.size
    ap = alpha.load()
    solid = lambda x, y: ap[x, y] >= threshold  # noqa: E731

    outside = set()
    queue = deque()
    for x in range(w):
        for y in (0, h - 1):
            if not solid(x, y) and (x, y) not in outside:
                outside.add((x, y))
                queue.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not solid(x, y) and (x, y) not in outside:
                outside.add((x, y))
                queue.append((x, y))

    while queue:
        cx, cy = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in outside and not solid(nx, ny):
                outside.add((nx, ny))
                queue.append((nx, ny))

    # 剩下的空区域就是内部
    visited = set(outside)
    regions: list[list[tuple[int, int]]] = []
    for y in range(h):
        for x in range(w):
            if (x, y) in visited or solid(x, y):
                continue
            comp = []
            q = deque([(x, y)])
            visited.add((x, y))
            while q:
                cx, cy = q.popleft()
                comp.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if (
                        0 <= nx < w
                        and 0 <= ny < h
                        and (nx, ny) not in visited
                        and not solid(nx, ny)
                    ):
                        visited.add((nx, ny))
                        q.append((nx, ny))
            if len(comp) > 12:  # 太小的点状空洞不填
                regions.append(comp)

    regions.sort(key=len, reverse=True)
    return outside, regions


def hex_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return tuple(int(v[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def fill_pet(
    src: Path,
    dst: Path,
    ink: str,
    palette: list[str],
    outline: bool = True,
) -> tuple[int, int, int]:
    """返回 (宽, 高, 填色区域数)。"""
    base = Image.open(src).convert("RGBA")
    w, h = base.size
    alpha = base.split()[-1]

    _, regions = find_regions(alpha)

    # 填色层：从大到小分配颜色，最大的用第一个色
    paint = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(paint)
    for index, comp in enumerate(regions):
        color = hex_rgb(palette[index % len(palette)])
        for x, y in comp:
            paint.putpixel((x, y), (*color, 255))

    # 边缘内缩一点，让墨线露出来
    if outline:
        shrunk = paint.split()[-1].filter(ImageFilter.MinFilter(3))
        paint.putalpha(shrunk)

    # 墨线层叠在上面
    result = Image.alpha_composite(paint, base)

    dst.parent.mkdir(parents=True, exist_ok=True)
    result.save(dst)
    return w, h, len(regions)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--light-palette",
        default="#F5E3BC,#EFD3A6,#E8C8B4,#F0DCC0",
        help="浅色皮肤的填色（奶油黄系）",
    )
    parser.add_argument(
        "--dark-palette",
        default="#4A4030,#3E372C,#4A3A38,#443B33",
        help="深色皮肤的填色（低饱和深色，不刺眼）",
    )
    args = parser.parse_args()

    light = args.light_palette.split(",")
    dark = args.dark_palette.split(",")

    # 浅色版和深色版必须各自从**自己的线稿**填色：
    # 以前用同一个源填两次，结果深色版也是浅黄底，在深底上糊成一片。
    targets = [
        ("pet-cat.png", "pet-cat.png", "pet-cat-light.png"),
        ("pet-dog.png", "pet-dog.png", "pet-dog-light.png"),
        ("pet-cat-lazy.png", "pet-cat-lazy.png", "pet-cat-lazy-light.png"),
    ]

    for light_src_name, light_name, dark_name in targets:
        light_src = SRC_DIR / light_src_name
        dark_src = SRC_DIR / "_line" / dark_name
        if not light_src.exists():
            print(f"跳过（不存在）：{light_src_name}")
            continue
        n1 = fill_pet(light_src, SRC_DIR / light_name, "#3A342E", light)
        if dark_src.exists():
            n2 = fill_pet(dark_src, SRC_DIR / dark_name, "#EDE6D2", dark)
        else:
            n2 = n1
        print(
            f"{light_src_name:20s} 浅色 {n1[0]}x{n1[1]} 填 {n1[2]} 块  |  "
            f"深色 {n2[0]}x{n2[1]} 填 {n2[2]} 块"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
