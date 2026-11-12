"""过期截图清理。

这是整个项目里唯一会删文件的模块，所以规则全部写死在代码里，
不提供任何"自定义删除范围"的口子。任何一条不满足就整批放弃，宁可少删。

安全边界：
  1. keep_days <= 0 直接返回（0 表示永久保留，负数也不许钻空子）
  2. 只处理名字严格是 YYYY-MM-DD 的直接子目录，不递归、不跟随符号链接
  3. 根目录必须是"有深度"的普通目录：拒绝盘根、拒绝用户主目录
  4. 只删 .jpg/.jpeg/.png；目录只在空的时候才删
  5. 该日期还有没分析完的记录时整日跳过（图删了就没法分析了）
  6. 数据库记录一律保留，只把 image_path / thumb_path 置空
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .capture import THUMB_ROOT
from .config import Config
from .storage import Storage

LOGGER = logging.getLogger("mao.housekeeping")

DAY_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
# C:\Users\xxx\shots 这种至少要有 3 段，C:\shots 和盘根一律拒绝
MIN_ROOT_DEPTH = 3


def plan(cfg: Config, storage: Storage, today: date | None = None) -> dict[str, Any]:
    """只算清单，一个文件都不动。"""
    keep = int(cfg.get("capture.keep_days", 0) or 0)
    if keep <= 0:
        return _empty("未开启自动清理（原图永久保留）")

    today = today or date.today()
    cutoff = today - timedelta(days=keep)

    roots: list[Path] = []
    output_dir = cfg.get("capture.output_dir") or ""
    if output_dir:
        roots.append(Path(output_dir))
    roots.append(THUMB_ROOT)

    skipped: list[str] = []
    candidates: list[dict[str, Any]] = []

    for root in roots:
        if not root.exists():
            continue
        usable = _usable_root(root)
        if usable is None:
            skipped.append(f"目录不安全，已跳过：{root}")
            continue
        try:
            entries = sorted(usable.iterdir())
        except OSError as exc:
            skipped.append(f"目录读不了，已跳过：{root}（{exc}）")
            continue

        for entry in entries:
            if entry.is_symlink() or not entry.is_dir():
                continue
            if not DAY_DIR_RE.match(entry.name):
                continue
            day = _parse_day(entry.name)
            if day is None or day > cutoff:
                continue
            files, size = _scan(entry)
            candidates.append(
                {"day": entry.name, "path": entry, "files": files, "bytes": size}
            )

    days = sorted({c["day"] for c in candidates})
    busy = storage.unresolved_days(days)
    for day in sorted(busy):
        skipped.append(f"{day} 还有没分析完的记录，先留着")

    usable_dirs = [c for c in candidates if c["day"] not in busy]
    return {
        "keep_days": keep,
        "cutoff": cutoff.strftime("%Y-%m-%d"),
        "dirs": usable_dirs,
        "days": sorted({c["day"] for c in usable_dirs}),
        "files": sum(c["files"] for c in usable_dirs),
        "bytes": sum(c["bytes"] for c in usable_dirs),
        "skipped": skipped,
    }


def execute(report: dict[str, Any], storage: Storage) -> dict[str, Any]:
    """按清单删。删之前每一项都复查一遍，防止中途被换掉。"""
    removed_files = 0
    removed_bytes = 0
    skipped = list(report.get("skipped") or [])
    done_days: set[str] = set()
    cutoff_text = report.get("cutoff") or ""

    for item in report.get("dirs") or []:
        path: Path = item["path"]
        if not _still_safe(path, cutoff_text):
            skipped.append(f"{path.name} 复查不通过，放弃")
            continue

        cleaned = True
        try:
            for f in path.iterdir():
                if f.is_symlink() or not f.is_file():
                    continue
                if f.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                try:
                    size = f.stat().st_size
                    f.unlink()
                    removed_files += 1
                    removed_bytes += size
                except OSError as exc:
                    cleaned = False
                    LOGGER.warning("删不掉 %s：%s", f, exc)
            try:
                path.rmdir()  # 非空会抛错，正好留着
            except OSError:
                cleaned = False
        except OSError as exc:
            cleaned = False
            LOGGER.warning("处理目录失败 %s：%s", path, exc)

        if cleaned:
            done_days.add(item["day"])

    for day in done_days:
        storage.clear_image_paths(day)

    return {
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
        "removed_days": len(done_days),
        "skipped": skipped,
    }


def run(cfg: Config, storage: Storage, today: date | None = None) -> dict[str, Any]:
    """算清单 + 执行，一步到位。"""
    report = plan(cfg, storage, today)
    if not report["dirs"]:
        report.update({"removed_files": 0, "removed_bytes": 0, "removed_days": 0})
        return report
    result = execute(report, storage)
    result["keep_days"] = report["keep_days"]
    result["cutoff"] = report["cutoff"]
    return result


# ---------- 内部 ----------


def _empty(reason: str) -> dict[str, Any]:
    return {
        "keep_days": 0,
        "cutoff": "",
        "dirs": [],
        "days": [],
        "files": 0,
        "bytes": 0,
        "skipped": [reason] if reason else [],
    }


def _usable_root(root: Path) -> Path | None:
    """根目录白名单校验，通不过绝不往下走。"""
    try:
        resolved = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_dir():
        return None
    # 盘根（C:\ 这种）
    if resolved == Path(resolved.anchor):
        return None
    try:
        if resolved == Path.home().resolve():
            return None
    except OSError:
        pass
    # 深度不够，比如 C:\shots
    if len(resolved.parts) < MIN_ROOT_DEPTH:
        return None
    return resolved


def _still_safe(path: Path, cutoff_text: str) -> bool:
    if not cutoff_text:
        return False
    if path.is_symlink() or not path.is_dir():
        return False
    if not DAY_DIR_RE.match(path.name):
        return False
    day = _parse_day(path.name)
    if day is None:
        return False
    try:
        cutoff = datetime.strptime(cutoff_text, "%Y-%m-%d").date()
    except ValueError:
        return False
    return day <= cutoff


def _parse_day(name: str) -> date | None:
    try:
        return datetime.strptime(name, "%Y-%m-%d").date()
    except ValueError:
        return None


def _scan(directory: Path) -> tuple[int, int]:
    files = 0
    total = 0
    try:
        for f in directory.iterdir():
            if f.is_symlink() or not f.is_file():
                continue
            if f.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            try:
                total += f.stat().st_size
                files += 1
            except OSError:
                continue
    except OSError:
        return 0, 0
    return files, total
