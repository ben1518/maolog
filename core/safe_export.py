"""导出路径边界与原子写入。

调用方必须显式给出允许目录，避免把任务名拼进路径后写到任意位置。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def safe_output_path(
    output_path: Path,
    suffix: str,
    allowed_root: Path,
    overwrite: bool = False,
) -> Path:
    path = Path(output_path)
    if path.suffix.casefold() != suffix.casefold():
        raise ValueError(f"导出文件必须使用 {suffix} 后缀")
    root = Path(allowed_root).resolve()
    target = path.resolve()
    if not target.is_relative_to(root):
        raise ValueError("导出路径超出允许目录")
    if target.exists() and not overwrite:
        raise FileExistsError("目标文件已存在；如需替换请显式允许覆盖")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def atomic_write_text(target: Path, content: str) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.stem}_", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temp_name, target)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


def temporary_pdf_path(target: Path) -> Path:
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.stem}_", suffix=".pdf.tmp", dir=str(target.parent)
    )
    os.close(fd)
    return Path(temp_name)
