"""屏幕采集。

一次采集做四件事：
  1. 读前台窗口标题 + 进程名（ctypes 调 user32，零额外依赖）
  2. mss 截屏（比 PIL.ImageGrab 快一个数量级）
  3. 缩放压缩后落盘，同时生成 UI 用的小缩略图
  4. 算画面指纹做变化检测，供上层决定要不要重新调 AI

隐私相关的拦截都在这一层：排除进程、敏感关键词命中时直接不截图。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import local

import mss
from PIL import Image

from .app_names import resolve_app_display_name
from .config import Config, DATA_DIR

THUMB_ROOT = DATA_DIR / "thumbs"
# 画面指纹尺寸，64x36 已经足够区分"换了个界面"和"只是鼠标动了一下"
SIG_SIZE = (64, 36)


@dataclass
class CaptureResult:
    ts: datetime
    app_name: str = ""
    window_title: str = ""
    image_path: str | None = None
    thumb_path: str | None = None
    signature: bytes | None = None
    # 与上一帧的平均差异（0~1）。首帧或无法比较时给 1.0
    diff_score: float = 1.0
    # None 表示正常采集；有值表示本次被跳过，值即原因
    skipped_reason: str | None = None


class _WinApi:
    """前台窗口信息读取封装。"""

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._available = True

    def active_window_info(self) -> tuple[str, str, str]:
        """返回 (底层进程名, 窗口标题, 友好应用名)。"""
        if not self._available:
            return "", "", ""
        try:
            hwnd = self._user32.GetForegroundWindow()
            if not hwnd:
                return "", "", ""
            length = self._user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            self._user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value

            pid = wintypes.DWORD()
            self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            app = ""
            exe_path = ""
            pid_val = pid.value if pid.value else None
            if pid_val:
                try:
                    import psutil

                    proc = psutil.Process(pid_val)
                    app = proc.name() or ""
                    # UWP 应用（如照片、设置）真实进程在子进程里，取父进程更好读
                    if app.lower() in ("applicationframehost.exe", "textinputhost.exe"):
                        parent = proc.parent()
                        if parent is not None:
                            app = parent.name() or app
                    try:
                        exe_path = proc.exe() or ""
                    except Exception:
                        exe_path = ""
                except Exception:
                    app = ""
            display_name = resolve_app_display_name(app, exe_path=exe_path, window_title=title, pid=pid_val)
            return app, title, display_name
        except Exception:
            self._available = False
            return "", "", ""

    def active_window(self) -> tuple[str, str]:
        """向后兼容返回 (友好应用名, 窗口标题)。"""
        app, title, display = self.active_window_info()
        return display or app, title


class CaptureService:
    """屏幕采集服务，内部维护上一帧指纹。"""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._local = local()
        self._win = _WinApi()
        self._last_sig: bytes | None = None

    # ---------- 对外入口 ----------

    def capture_once(self) -> CaptureResult:
        now = datetime.now()
        proc, title, display_name = self._win.active_window_info()
        app = display_name or proc

        # 隐私拦截 1：排除进程或应用名
        excludes = [x.lower() for x in (self.cfg.get("capture.exclude_apps") or [])]
        if (proc and proc.lower() in excludes) or (display_name and display_name.lower() in excludes):
            return CaptureResult(now, app, title, skipped_reason="excluded_app")

        # 隐私拦截 2：窗口标题命中敏感词
        keywords = self.cfg.get("privacy.sensitive_keywords") or []
        if title and any(k and k in title for k in keywords):
            return CaptureResult(now, app, title, skipped_reason="sensitive")

        image = self._grab_screen()
        if image is None:
            return CaptureResult(now, app, title, skipped_reason="grab_failed")

        # 全黑/全白画面（锁屏、休眠、UAC）没有分析价值
        if _is_blank(image):
            return CaptureResult(now, app, title, skipped_reason="blank")

        signature = _signature(image)
        # 先跟上一帧比，再更新指纹——顺序不能反，否则永远是零差异
        diff_score = _mean_abs_diff(signature, self._last_sig) if self._last_sig else 1.0
        image_path = self._save_image(image, now, app)
        thumb_path = self._save_thumb(image, now)
        self._last_sig = signature

        return CaptureResult(
            ts=now,
            app_name=app,
            window_title=title,
            image_path=image_path,
            thumb_path=thumb_path,
            signature=signature,
            diff_score=diff_score,
        )

    # ---------- 内部实现 ----------

    def _grab_screen(self) -> Image.Image | None:
        try:
            sct = getattr(self._local, "sct", None)
            if sct is None:
                sct = mss.mss()
                self._local.sct = sct

            monitor_index = int(self.cfg.get("capture.monitor", 1) or 0)
            monitors = sct.monitors
            if monitor_index >= len(monitors):
                monitor_index = 0
            raw = sct.grab(monitors[monitor_index])
            # mss 给的是 BGRA，用 BGRX 通道顺序直接丢掉 alpha
            return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        except Exception:
            # 显示器配置变化后缓存的 mss 实例会失效，清掉下次重建
            self._local.sct = None
            return None

    def _save_image(self, image: Image.Image, ts: datetime, app: str) -> str:
        """按日期归档原图，返回绝对路径字符串。"""
        out_root = self.cfg.output_dir
        day_dir = out_root / ts.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        max_width = int(self.cfg.get("capture.max_width", 2560) or 0)
        img = image
        if max_width and image.width > max_width:
            ratio = max_width / image.width
            img = image.resize(
                (max_width, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS
            )

        stem = _unique_stem(day_dir, ts.strftime("%H%M%S"), _safe_app(app))
        path = day_dir / f"{stem}.jpg"
        quality = int(self.cfg.get("capture.jpeg_quality", 92) or 92)
        # subsampling=0 (4:4:4) 关闭色度抽样，显著提升深色背景下代码与文字边缘清晰度
        img.save(path, "JPEG", quality=quality, subsampling=0, optimize=True, progressive=True)
        return str(path)

    def _save_thumb(self, image: Image.Image, ts: datetime) -> str:
        day_dir = THUMB_ROOT / ts.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        thumb = image.copy()
        thumb.thumbnail((640, 640), Image.Resampling.LANCZOS)
        path = day_dir / f"{ts.strftime('%H%M%S')}_{_rand4()}.jpg"
        thumb.save(path, "JPEG", quality=88, subsampling=0)
        return str(path)


# ---------- 工具函数 ----------

def _signature(image: Image.Image) -> bytes:
    small = image.convert("L").resize(SIG_SIZE, Image.Resampling.BILINEAR)
    return small.tobytes()


def _mean_abs_diff(a: bytes, b: bytes) -> float:
    """两张指纹的平均绝对差，归一化到 0~1。"""
    if len(a) != len(b) or not a:
        return 1.0
    total = 0
    for x, y in zip(a, b):
        total += abs(x - y)
    return total / (len(a) * 255.0)


def _is_blank(image: Image.Image) -> bool:
    """纯黑/纯白画面判定：缩到极小后看灰度极值。"""
    small = image.convert("L").resize((32, 18), Image.Resampling.BILINEAR)
    lo, hi = small.getextrema()
    return (hi - lo) < 6


def _safe_app(app: str) -> str:
    if not app:
        return "unknown"
    name = app.rsplit(".", 1)[0]
    keep = "".join(ch for ch in name if ch.isalnum() or ch in "-_")
    return keep[:24] or "unknown"


def _rand4() -> str:
    import random

    return f"{random.randint(0, 9999):04d}"


def _unique_stem(day_dir: Path, base: str, app: str) -> str:
    stem = f"{base}_{app}"
    candidate = stem
    n = 1
    while (day_dir / f"{candidate}.jpg").exists():
        candidate = f"{stem}_{n}"
        n += 1
    return candidate
