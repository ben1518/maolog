"""桌面悬浮桌宠与迷你 HUD（楚师蘑菇小精灵多态帧动画版）。

核心能力：
1. 独立无边框全透明置顶窗口（Frameless + StaysOnTop + Tool + NoDropShadow + WindowDoesNotAcceptFocus），
   通过 Windows DWM API 彻底移除系统外框与阴影，平时仅小精灵本体响应鼠标，四周完全穿透不挡视线，点击绝不激活后台主窗口。
2. 14 态「蘑菇小精灵」表情动作状态机与果冻物理动效（Squash & Stretch）：
   - 常态自习（idle）：Q弹果冻呼吸律动，定时触发挥手（wave）与扒桌星星眼（peek）微动作。
   - 暂停/休息（sleep_half <-> sleep_closed）：抱着月亮抱枕眨眼入睡双帧循环 + 飘起 Zzz 气泡。
   - AI 截屏识别（salute）：立正敬礼「收到！」+ 脉冲星光粒子。
   - 拖拽位移（run）：拖动瞬间切换「撒腿溜了」扬尘逃跑姿态，随拖拽方向倾斜。
   - 摸头互动连招：单击轮换「挥手 wave / 鞠躬谢谢 thanks / 敬礼 salute / 探头 peek」并触发 Q 弹果冻挤压；快速连戳触发「震惊菌盖飞起 shock」高跳动效！
   - 智能时段与关怀联动：饭点端碗「干饭 eat」、早八「早八魂 dizzy」、久坐/熬夜「困了 drowsy」、分心提醒「委屈 sad / 求求了 beg」。
"""

from __future__ import annotations

import ctypes
import math
import random
import sys
import time
from datetime import date, datetime
from typing import Dict, Optional

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
)
from PyQt6.QtWidgets import QMenu, QWidget

from core.pet_triggers import evaluate_pet_care
from core.storage import Storage, format_duration

from .doodle_paint import rough_path
from .doodle_pet import load_pet
from .theme import ASSET_DIR, IS_DARK_SKIN


def _remove_win11_frame_and_noactivate(hwnd: int) -> None:
    """在 Windows 10/11 下彻底移除 DWM 窗口外框与阴影，并设置 WS_EX_NOACTIVATE 防止点击唤起主窗口。"""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        dwmapi = ctypes.windll.dwmapi
        corner_pref = ctypes.c_int(1)  # DWMWCP_DONOTROUND
        dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(corner_pref), ctypes.sizeof(corner_pref)
        )
        border_none = ctypes.c_uint(0xFFFFFFFE)  # DWMWA_COLOR_NONE
        dwmapi.DwmSetWindowAttribute(
            hwnd, 34, ctypes.byref(border_none), ctypes.sizeof(border_none)
        )
        ncrp = ctypes.c_int(1)  # DWMNCRP_DISABLED
        dwmapi.DwmSetWindowAttribute(
            hwnd, 2, ctypes.byref(ncrp), ctypes.sizeof(ncrp)
        )
    except Exception:
        pass

    try:
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOOLWINDOW = 0x00000080
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        )
    except Exception:
        pass


def load_mushroom_sprites(target_size: int = 92) -> Dict[str, QImage]:
    """加载去底后的 14 张蘑菇小精灵透明贴图。"""
    sprite_dir = ASSET_DIR / "doodle" / "mushroom_sprites"
    names = [
        "idle",
        "wave",
        "salute",
        "thanks",
        "beg",
        "shock",
        "sleep_half",
        "sleep_closed",
        "drowsy",
        "sad",
        "eat",
        "dizzy",
        "run",
        "peek",
    ]
    out: Dict[str, QImage] = {}
    for name in names:
        p = sprite_dir / f"{name}.png"
        if p.exists():
            img = QImage(str(p))
            if not img.isNull():
                out[name] = img.scaled(
                    target_size,
                    target_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
    return out


class DesktopPetWindow(QWidget):
    """常驻桌面的蘑菇小精灵悬浮窗（多态帧动画 + Q弹果冻物理 + 无框穿透）。"""

    open_dashboard_requested = pyqtSignal()
    open_achievement_requested = pyqtSignal()
    open_review_requested = pyqtSignal()
    open_ai_profile_requested = pyqtSignal()
    toggle_pause_requested = pyqtSignal()
    capture_now_requested = pyqtSignal()
    visibility_changed = pyqtSignal(bool)

    WIN_W = 280
    WIN_H = 256
    SPRITE_SZ = 92

    def __init__(self, cfg, storage: Storage, parent: QWidget | None = None) -> None:
        super().__init__(None)
        self.cfg = cfg
        self.storage = storage

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setMouseTracking(True)
        self.setFixedSize(self.WIN_W, self.WIN_H)
        self.setWindowTitle("MaoLog 蘑菇小精灵")

        # 加载 14 张蘑菇小精灵贴图（若缺失则回退手绘猫）
        self._sprites = load_mushroom_sprites(self.SPRITE_SZ)
        self._fallback_img = load_pet("pet-cat.png", 76)

        # 状态与统计数据
        self._state = "running"  # running | analyzing | paused | error
        self._tracked_str = "0分钟"
        self._current_act = "陪伴自习中"
        self._focus_score = 0.0
        self._pat_count = 0
        self._last_pat_ts = 0.0

        # 动作与物理动画参数
        self._phase = 0.0
        self._hovered = False
        self._pose = "idle"
        self._pose_until = 0.0  # 临时动作持续到的 monotonic 时间戳
        self._squash = 0.0      # 果冻挤压系数 (+为压扁变宽，-为拉伸变高)
        self._squash_vel = 0.0  # 弹簧速度
        self._hop_y = 0.0       # 跳跃高度偏移 (负数为向上跳)
        self._hop_vel = 0.0
        self._tilt_offset = 0.0
        self._particles: list[dict] = []

        # 顶部气泡状态
        self._bubble_text = ""
        self._bubble_tone = "greet"
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self._clear_bubble)

        # 拖拽控制
        self._dragging = False
        self._drag_start_global = QPoint()
        self._win_start_pos = QPoint()
        self._last_drag_x = 0
        self._has_moved = False

        # 悬停快捷按钮热区 [(key, label, QRectF)]
        self._action_rects: list[tuple[str, str, QRectF]] = []
        self._hovered_action: Optional[str] = None

        # 动画计时器 (~25 FPS；静态呼吸时自动降频以减轻 DWM 重绘负担)
        self._idle_tick = 0
        self._applied_hwnd: int | None = None
        self._last_mask_key: tuple[bool, bool, bool] | None = None

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick_anim)
        self._anim_timer.start(40)

        # 数据同步计时器
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self.refresh_stats)
        self._sync_timer.start(10000)

        self._place_initial_position()
        self.refresh_stats()
        self._update_mask()
        self._apply_win_noactivate()

        # 启动后挥手问候
        QTimer.singleShot(
            2200,
            self._startup_greeting,
        )

    def _startup_greeting(self) -> None:
        self.trigger_pose("wave", duration_sec=3.2, hop=-8.0, squash=0.14)
        self.show_bubble(
            "嗨~ 我是蘑菇小精灵！点我互动，鼠标移上来可打开看板或便签 🍄",
            tone="greet",
            duration_ms=5500,
        )

    def _apply_win_noactivate(self) -> None:
        hwnd = int(self.winId())
        if hwnd and hwnd != self._applied_hwnd:
            self._applied_hwnd = hwnd
            _remove_win11_frame_and_noactivate(hwnd)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._update_mask()
        self._apply_win_noactivate()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._anim_timer.stop()
        self._sync_timer.stop()
        self._bubble_timer.stop()
        super().closeEvent(event)

    def _update_mask(self) -> None:
        """动态更新窗口命中区域：平时仅小精灵本体响应鼠标，四周完全穿透不挡底层点击。"""
        mask_key = (
            bool(self._hovered),
            bool(self._bubble_text),
            bool(self._particles),
        )
        if mask_key == self._last_mask_key:
            return
        self._last_mask_key = mask_key
        pet_box = QRect(int((self.WIN_W - 98) // 2), 82, 98, 98)
        region = QRegion(pet_box)
        if mask_key[0]:
            region = region.united(QRegion(QRect(16, 82, self.WIN_W - 32, 164)))
        if mask_key[1] or mask_key[2]:
            region = region.united(QRegion(QRect(6, 2, self.WIN_W - 12, 98)))
        self.setMask(region)

    # ---------- 位置与贴边 ----------

    def _place_initial_position(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.move(1000, 600)
            return
        avail = screen.availableGeometry()
        saved_x = self.cfg.get("ui.pet_x")
        saved_y = self.cfg.get("ui.pet_y")
        if isinstance(saved_x, int) and isinstance(saved_y, int):
            x = max(avail.left(), min(saved_x, avail.right() - self.WIN_W))
            y = max(avail.top(), min(saved_y, avail.bottom() - self.WIN_H))
            self.move(x, y)
        else:
            x = avail.right() - self.WIN_W - 18
            y = avail.bottom() - self.WIN_H - 16
            self.move(x, y)

    def _snap_to_screen_edge(self) -> None:
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        x, y = self.x(), self.y()
        x = max(avail.left() + 6, min(x, avail.right() - self.WIN_W - 6))
        y = max(avail.top() + 6, min(y, avail.bottom() - self.WIN_H - 6))
        if abs(x - avail.left()) < 36:
            x = avail.left() + 10
        elif abs((x + self.WIN_W) - avail.right()) < 36:
            x = avail.right() - self.WIN_W - 10
        self.move(x, y)
        self.cfg.set("ui.pet_x", x)
        self.cfg.set("ui.pet_y", y)

    # ---------- 动作触发与状态同步 ----------

    def trigger_pose(
        self,
        pose: str,
        duration_sec: float = 2.4,
        hop: float = -6.0,
        squash: float = 0.12,
    ) -> None:
        """触发一个带果冻弹跳物理的临时表情动作。"""
        self._pose = pose
        self._pose_until = time.monotonic() + duration_sec
        self._hop_vel = hop
        self._squash = squash
        self.update()

    def _current_sprite_key(self) -> str:
        # 1. 正在被拖拽移动：撒腿狂奔「溜了」
        if self._dragging and self._has_moved:
            return "run"

        # 2. 暂停记录：抱月亮枕眨眼睡觉双帧动画
        if self._state == "paused":
            # 每约 2.6 秒在半睁眼与闭眼熟睡之间平滑切换
            cycle = int(self._phase * 2.5) % 8
            return "sleep_half" if cycle == 0 else "sleep_closed"

        # 3. AI 正在截屏识别：立正敬礼「收到」
        if self._state == "analyzing":
            return "salute"

        # 4. 临时触发的互动或关怀动作（未过期）
        now_m = time.monotonic()
        if now_m < self._pose_until and self._pose in self._sprites:
            # 如果是委屈/求求了组合，交替闪烁更有表现力
            if self._pose == "beg_sad":
                return "beg" if int(self._phase * 4) % 2 == 0 else "sad"
            if self._pose == "wave":
                return "wave" if int(self._phase * 5) % 3 != 0 else "idle"
            return self._pose

        # 5. 时段感知与周期性微动作
        hour = datetime.now().hour
        minute = datetime.now().minute
        tick_bucket = int(self._phase * 1.5) % 36

        # 饭点（11:30-13:00 或 17:30-19:00）周期性端起菌子汤「干饭」
        is_meal = (hour == 11 and minute >= 30) or hour == 12 or (hour == 17 and minute >= 30) or hour == 18
        if is_meal and tick_bucket in (4, 5, 6, 7):
            return "eat"

        # 早八时段（07:00-08:40）偶尔冒出「早八魂」
        if (hour == 7 or (hour == 8 and minute <= 40)) and tick_bucket in (10, 11, 12):
            return "dizzy"

        # 深夜（>=23点 或 <5点）偶尔打瞌睡「困了」
        if (hour >= 23 or hour < 5) and tick_bucket in (8, 9, 10, 11):
            return "drowsy"

        # 正常自习时，每隔 ~10 秒做一次挥手或星星眼扒桌微动作
        if tick_bucket in (18, 19):
            return "wave"
        if tick_bucket in (29, 30):
            return "peek"

        return "idle"

    def set_engine_state(self, state: str, status_hint: str = "") -> None:
        if self.cfg.get("privacy.paused"):
            self._state = "paused"
        else:
            self._state = state
        if status_hint and state == "analyzing":
            self.trigger_pose("salute", duration_sec=2.5, hop=-5.0, squash=0.10)
            self._spawn_particle("✨", "#E5A93C")
        self.update()

    def on_analyzing_started(self) -> None:
        if not self.cfg.get("privacy.paused"):
            self._state = "analyzing"
            self.trigger_pose("salute", duration_sec=2.5, hop=-5.0, squash=0.10)
            self._spawn_particle("✨", "#5C9DFF")
            self.update()

    def on_analyzed_done(self, skip_refresh: bool = False) -> None:
        self._state = "paused" if self.cfg.get("privacy.paused") else "running"
        if not skip_refresh:
            self.refresh_stats()
        self.check_care_trigger(force=False)

    def refresh_stats(self) -> None:
        day_str = date.today().strftime("%Y-%m-%d")
        interval = self.cfg.interval_seconds
        overview = self.storage.overview(day_str, interval=interval)
        tracked_sec = overview.get("tracked_seconds", 0)
        self._tracked_str = format_duration(tracked_sec) if tracked_sec > 0 else "0分钟"
        self._focus_score = float(overview.get("avg_focus", 0.0) or 0.0)

        segments = self.storage.segments(day_str, interval=interval)
        invalid_labels = {"", "无法识别", "未知", "其他"}
        chosen_act = ""
        for seg in reversed(segments):
            cand = (seg.get("activity") or "").strip()
            if cand and cand not in invalid_labels:
                chosen_act = cand
                break
        if not chosen_act:
            top = (overview.get("top_activity") or "").strip()
            chosen_act = top if top not in invalid_labels else "陪伴自习中"
        if len(chosen_act) > 8:
            chosen_act = chosen_act[:8] + "…"
        self._current_act = chosen_act if segments else "等待首条记录"

        if self.cfg.get("privacy.paused"):
            self._state = "paused"
        elif self._state == "paused":
            self._state = "running"
        self.update()

    def check_care_trigger(self, force: bool = False) -> None:
        day_str = date.today().strftime("%Y-%m-%d")
        care = evaluate_pet_care(
            self.storage,
            day_str,
            interval=self.cfg.interval_seconds,
            force=force,
        )
        if care:
            trig = care.get("trigger", "")
            tone = care.get("tone", "greet")
            if not force:
                if trig in ("sedentary", "night"):
                    self.trigger_pose("drowsy", duration_sec=6.0, hop=-3.0, squash=0.08)
                elif trig == "distracted":
                    self.trigger_pose("beg_sad", duration_sec=6.0, hop=-6.0, squash=0.14)
                elif tone == "praise":
                    self.trigger_pose("thanks", duration_sec=5.5, hop=-7.0, squash=0.15)
            self.show_bubble(
                care["text"],
                tone=tone,
                duration_ms=care.get("duration_ms", 6000),
            )

    def show_bubble(self, text: str, tone: str = "greet", duration_ms: int = 6000) -> None:
        self._bubble_text = text
        self._bubble_tone = tone
        self._update_mask()
        self._bubble_timer.start(duration_ms)
        self.update()

    def _clear_bubble(self) -> None:
        self._bubble_text = ""
        self._update_mask()
        self.update()

    # ---------- 物理动画与粒子 ----------

    def _spawn_particle(self, symbol: str = "♥", color: str = "#D96B54") -> None:
        cx = self.WIN_W / 2.0 + random.uniform(-24, 24)
        cy = 104.0 + random.uniform(-10, 6)
        self._particles.append({
            "x": cx,
            "y": cy,
            "vy": random.uniform(1.1, 1.8),
            "vx": random.uniform(-0.45, 0.45),
            "text": symbol,
            "alpha": 255,
            "color": color,
        })

    def _tick_anim(self) -> None:
        if not self.isVisible():
            return
        self._phase = (self._phase + 0.11) % (math.tau * 20)

        # 睡眠状态冒 Zzz 气泡
        if self._state == "paused" and int(self._phase * 10) % 28 == 0 and len(self._particles) < 3:
            self._spawn_particle("Zzz", "#9E988D")

        # 弹簧果冻阻尼物理 (Squash & Stretch)
        spring_k = 0.28
        damping = 0.72
        accel = -spring_k * self._squash
        self._squash_vel = (self._squash_vel + accel) * damping
        self._squash += self._squash_vel
        if abs(self._squash) < 0.002 and abs(self._squash_vel) < 0.002:
            self._squash = 0.0
            self._squash_vel = 0.0

        # 跳跃重力回落
        if self._hop_y < 0.0 or self._hop_vel != 0.0:
            self._hop_y += self._hop_vel
            self._hop_vel += 1.25  # 重力加速度
            if self._hop_y >= 0.0:
                self._hop_y = 0.0
                if self._hop_vel > 2.5:
                    # 落地瞬间产生微小的果冻压扁反馈
                    self._squash = min(0.16, self._hop_vel * 0.018)
                self._hop_vel = 0.0

        # 更新飘升粒子
        alive = []
        for p in self._particles:
            p["y"] -= p["vy"]
            p["x"] += p["vx"]
            p["alpha"] = max(0, p["alpha"] - 9)
            if p["alpha"] > 0:
                alive.append(p)
        self._particles = alive
        self._update_mask()

        # 倾斜角回正
        if not self._dragging:
            if abs(self._tilt_offset) > 0.2:
                self._tilt_offset *= 0.76
            else:
                self._tilt_offset = 0.0

        # 有动态物理/交互/分析动效时保持 ~25 FPS；静止呼吸时降频为 ~6 FPS，避免分层透明窗体持续压榨 DWM
        active_fx = (
            self._hovered
            or self._dragging
            or bool(self._particles)
            or bool(self._bubble_text)
            or self._state == "analyzing"
            or self._hop_y < 0.0
            or self._hop_vel != 0.0
            or abs(self._squash) >= 0.002
            or abs(self._tilt_offset) >= 0.2
            or time.monotonic() < getattr(self, "_pose_until", 0.0)
        )
        if not active_fx:
            self._idle_tick = (self._idle_tick + 1) % 4
            if self._idle_tick != 0:
                return
        else:
            self._idle_tick = 0

        self.update()

    # ---------- 纯净无框绘制 ----------

    def _pet_rect(self) -> QRectF:
        bob = math.sin(self._phase * 1.4) * (1.2 if self._state == "paused" else 2.2)
        sz = float(self.SPRITE_SZ)
        return QRectF((self.WIN_W - sz) / 2.0, 86.0 + bob + self._hop_y, sz, sz)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 1. 顶部对话气泡
        if self._bubble_text:
            self._draw_bubble(painter)

        # 2. 小精灵脚下柔和阴影（随跳跃高度动态缩放）
        pet_r = self._pet_rect()
        shadow_scale = max(0.65, 1.0 + self._hop_y * 0.015)
        sw = 56.0 * shadow_scale
        sh = 9.0 * shadow_scale
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 42 if IS_DARK_SKIN else 24))
        painter.drawEllipse(QRectF((self.WIN_W - sw) / 2.0, 171.0 - sh / 2.0, sw, sh))

        # 3. 蘑菇小精灵本体（带底部锚点的果冻呼吸缩放 + 跳跃 + 歪头）
        key = self._current_sprite_key()
        img = self._sprites.get(key) or self._sprites.get("idle") or self._fallback_img
        if img is not None:
            painter.save()
            # 呼吸果冻微形变 + 互动弹性形变叠加
            breath_sq = math.sin(self._phase * 1.4) * (0.012 if self._state == "paused" else 0.022)
            total_sq = max(-0.22, min(0.25, breath_sq + self._squash))
            scale_x = 1.0 + total_sq
            scale_y = 1.0 - total_sq * 0.92

            # 以小精灵脚底中心为缩放锚点，让脚稳稳踩在地面上呼吸弹跳
            foot_x = pet_r.center().x()
            foot_y = pet_r.bottom() - 4.0
            painter.translate(foot_x, foot_y)
            painter.rotate(self._tilt_offset)
            painter.scale(scale_x, scale_y)
            painter.translate(-foot_x, -foot_y)

            painter.drawImage(pet_r, img)
            painter.restore()

        # 4. 互动粒子（爱心 / 星光 / 花朵 / Zzz）
        for p in self._particles:
            c = QColor(p["color"])
            c.setAlpha(int(p["alpha"]))
            painter.setPen(c)
            f_p = QFont("Microsoft YaHei", 10)
            f_p.setBold(True)
            painter.setFont(f_p)
            painter.drawText(QPointF(p["x"], p["y"]), p["text"])

        # 5. 仅当鼠标悬停在小精灵身上时，才浮现状态条与 4 个快捷胶囊
        self._action_rects.clear()
        if self._hovered:
            self._draw_hover_hud(painter)

        painter.end()

    def _draw_bubble(self, painter: QPainter) -> None:
        if IS_DARK_SKIN:
            bg = QColor(42, 40, 48, 242)
            text_col = QColor("#F4EFE6")
        else:
            bg = QColor(255, 253, 248, 246)
            text_col = QColor("#2B2823")

        tone_colors = {
            "praise": QColor("#D96B54"),
            "care": QColor("#5C9DFF" if IS_DARK_SKIN else "#2B72D6"),
            "remind": QColor("#E5A93C"),
            "greet": QColor("#D96B54" if IS_DARK_SKIN else "#C4503C"),
        }
        border_col = tone_colors.get(self._bubble_tone, tone_colors["greet"])

        font = QFont("Microsoft YaHei", 9)
        fm = QFontMetrics(font)
        bound = fm.boundingRect(0, 0, self.WIN_W - 40, 84, int(Qt.TextFlag.TextWordWrap), self._bubble_text)
        bw = max(160, min(self.WIN_W - 14, bound.width() + 26))
        bh = max(38, min(82, bound.height() + 18))
        bx = (self.WIN_W - bw) / 2.0
        by = max(3.0, 82.0 - bh - 5.0)

        box_rect = QRectF(bx, by, bw, bh)
        painter.setBrush(bg)
        painter.setPen(QPen(border_col, 1.5))
        painter.drawPath(rough_path(box_rect, radius=11.0, seed=29, amplitude=0.8))

        tail = QPainterPath()
        tx = self.WIN_W / 2.0 - 6.0
        ty = box_rect.bottom() - 1.0
        tail.moveTo(tx, ty)
        tail.lineTo(tx + 6.0, ty + 6.5)
        tail.lineTo(tx + 12.0, ty)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawPath(tail)

        painter.setPen(QPen(border_col, 1.4))
        painter.drawLine(QPointF(tx, ty), QPointF(tx + 6.0, ty + 6.5))
        painter.drawLine(QPointF(tx + 6.0, ty + 6.5), QPointF(tx + 12.0, ty))

        painter.setPen(text_col)
        painter.setFont(font)
        painter.drawText(
            QRectF(box_rect.x() + 11, box_rect.y() + 5, box_rect.width() - 22, box_rect.height() - 10),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap),
            self._bubble_text,
        )

    def _draw_hover_hud(self, painter: QPainter) -> None:
        if IS_DARK_SKIN:
            bg_pill = QColor(36, 34, 41, 235)
            border_pill = QColor("#5C5663")
            text_pri = QColor("#F2ECE1")
        else:
            bg_pill = QColor(255, 252, 246, 238)
            border_pill = QColor("#BFB3A2")
            text_pri = QColor("#2B2823")

        pill_r = QRectF(36.0, 178.0, self.WIN_W - 72.0, 26.0)
        painter.setBrush(bg_pill)
        painter.setPen(QPen(border_pill, 1.2))
        painter.drawRoundedRect(pill_r, 13.0, 13.0)

        if self._state == "paused":
            dot_col = QColor("#9E988D")
            status_str = f"已暂停 · {self._tracked_str}"
        elif self._state == "analyzing":
            dot_col = QColor("#5C9DFF")
            status_str = f"AI 识别中… · {self._tracked_str}"
        else:
            dot_col = QColor("#4CAF50")
            status_str = f"{self._tracked_str} · {self._current_act}"

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_col)
        painter.drawEllipse(QPointF(pill_r.left() + 13, pill_r.center().y()), 3.8, 3.8)

        painter.setPen(text_pri)
        f_pill = QFont("Microsoft YaHei", 8)
        f_pill.setBold(True)
        painter.setFont(f_pill)
        fm = QFontMetrics(f_pill)
        elided_status = fm.elidedText(status_str, Qt.TextElideMode.ElideRight, int(pill_r.width() - 28))
        painter.drawText(
            QRectF(pill_r.left() + 23, pill_r.top(), pill_r.width() - 28, pill_r.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided_status,
        )

        paused = bool(self.cfg.get("privacy.paused"))
        actions = [
            ("dashboard", "📊 看板"),
            ("achieve", "🍄 便签"),
            ("review", "📖 复盘"),
            ("pause", "▶️ 继续" if paused else "⏸️ 暂停"),
        ]
        bar_y = 210.0
        btn_w = 54.0
        btn_h = 24.0
        gap = 5.0
        total_w = len(actions) * btn_w + (len(actions) - 1) * gap
        start_x = (self.WIN_W - total_w) / 2.0

        f_btn = QFont("Microsoft YaHei", 8)
        f_btn.setBold(True)
        painter.setFont(f_btn)

        for idx, (key, label) in enumerate(actions):
            rx = start_x + idx * (btn_w + gap)
            rect = QRectF(rx, bar_y, btn_w, btn_h)
            self._action_rects.append((key, label, rect))

            is_hot = self._hovered_action == key
            fill = QColor("#D96B54") if is_hot else bg_pill
            pen_col = QColor("#D96B54") if is_hot else border_pill
            txt_col = QColor("#FFFFFF") if is_hot else text_pri

            painter.setBrush(fill)
            painter.setPen(QPen(pen_col, 1.2))
            painter.drawRoundedRect(rect, 8.0, 8.0)

            painter.setPen(txt_col)
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), label)

    # ---------- 鼠标交互 ----------

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self._update_mask()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._hovered_action = None
        self._update_mask()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            if self._bubble_text and pos.y() < 84:
                self._clear_bubble()
                event.accept()
                return

            for key, _, rect in self._action_rects:
                if rect.contains(pos):
                    self._trigger_action(key)
                    event.accept()
                    return

            self._dragging = True
            self._has_moved = False
            self._drag_start_global = event.globalPosition().toPoint()
            self._last_drag_x = self._drag_start_global.x()
            self._win_start_pos = self.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if self._dragging:
            cur_global = event.globalPosition().toPoint()
            delta = cur_global - self._drag_start_global
            if delta.manhattanLength() > 5:
                self._has_moved = True
                dx = cur_global.x() - self._last_drag_x
                self._last_drag_x = cur_global.x()
                self._tilt_offset = max(-14.0, min(14.0, dx * 0.8))
                self.move(self._win_start_pos + delta)
                if random.random() < 0.25 and len(self._particles) < 4:
                    self._spawn_particle("💨", "#B5AEA2")
            event.accept()
            return

        hot = None
        for key, _, rect in self._action_rects:
            if rect.contains(pos):
                hot = key
                break
        if hot != self._hovered_action:
            self._hovered_action = hot
            self.update()

        if hot or self._pet_rect().contains(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            if self._has_moved:
                self._snap_to_screen_edge()
                # 拖拽落地后敬礼「收到！」
                self.trigger_pose("salute", duration_sec=1.8, hop=-5.0, squash=0.14)
            else:
                self._on_pat_pet()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            for key, _, rect in self._action_rects:
                if rect.contains(pos):
                    return
            self._on_pat_pet(rapid=True)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        bg = "#28262C" if IS_DARK_SKIN else "#FFFCF7"
        fg = "#F2ECE1" if IS_DARK_SKIN else "#2B2823"
        bd = "#545058" if IS_DARK_SKIN else "#C8BEB0"
        menu.setStyleSheet(
            f"QMenu {{ background: {bg}; color: {fg}; border: 1px solid {bd}; border-radius: 8px; padding: 6px; }}"
            f"QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}"
            f"QMenu::item:selected {{ background: #D96B54; color: #FFFFFF; }}"
        )

        act_pat = QAction("🍄 摸摸蘑菇小精灵（互动）", menu)
        act_pat.triggered.connect(lambda: self._on_pat_pet(rapid=False))
        menu.addAction(act_pat)

        menu.addSeparator()

        act_dash = QAction("📊 打开主看板", menu)
        act_dash.triggered.connect(self.open_dashboard_requested.emit)
        menu.addAction(act_dash)

        act_ach = QAction("🍄 生成今日成就便签", menu)
        act_ach.triggered.connect(self.open_achievement_requested.emit)
        menu.addAction(act_ach)

        act_rev = QAction("📖 打开学习复盘", menu)
        act_rev.triggered.connect(self.open_review_requested.emit)
        menu.addAction(act_rev)

        act_ai = QAction("🤖 打开 AI 协作画像", menu)
        act_ai.triggered.connect(self.open_ai_profile_requested.emit)
        menu.addAction(act_ai)

        menu.addSeparator()

        act_cap = QAction("📸 立即截屏记录一张", menu)
        act_cap.triggered.connect(self.capture_now_requested.emit)
        menu.addAction(act_cap)

        paused = bool(self.cfg.get("privacy.paused"))
        act_pause = QAction("▶️ 继续记录" if paused else "⏸️ 暂停记录", menu)
        act_pause.triggered.connect(self.toggle_pause_requested.emit)
        menu.addAction(act_pause)

        menu.addSeparator()

        act_hide = QAction("🙈 隐藏桌面小精灵（可在顶栏/托盘恢复）", menu)
        act_hide.triggered.connect(self._hide_pet)
        menu.addAction(act_hide)

        menu.exec(event.globalPos())

    def _on_pat_pet(self, rapid: bool = False) -> None:
        now_t = time.monotonic()
        is_combo = rapid or (now_t - self._last_pat_ts < 0.55)
        self._last_pat_ts = now_t
        self._pat_count += 1

        if is_combo:
            # 快速连戳：触发「震惊菌盖飞起」高跳动效！
            self.trigger_pose("shock", duration_sec=2.6, hop=-12.0, squash=0.22)
            self._tilt_offset = random.choice([-12.0, 12.0])
            for _ in range(3):
                self._spawn_particle(random.choice(["❗", "✨", "🍄"]), "#E5A93C")
            self.show_bubble(
                "哇啊！！菌盖都要被你戳飞啦 🍄💥 继续元气满满冲刺吧！",
                tone="praise",
                duration_ms=5000,
            )
            return

        # 单击轮换丰富表情动作：挥手 -> 鞠躬谢谢 -> 敬礼收到 -> 扒桌探头 -> 端碗干饭
        cycle_poses = [
            ("wave", "🌸", "#D96B54", -7.0, 0.14),
            ("thanks", "♥", "#D96B54", -5.0, 0.16),
            ("salute", "✨", "#5C9DFF", -6.5, 0.13),
            ("peek", "✨", "#E5A93C", -4.0, 0.12),
            ("eat", "🍄", "#E5A93C", -5.0, 0.14),
        ]
        pose_name, sym, col, hop, sq = cycle_poses[(self._pat_count - 1) % len(cycle_poses)]
        self.trigger_pose(pose_name, duration_sec=3.0, hop=hop, squash=sq)
        self._tilt_offset = 9.0 if self._pat_count % 2 == 1 else -9.0
        for _ in range(2):
            self._spawn_particle(sym, col)
        self.check_care_trigger(force=True)

    def _trigger_action(self, key: str) -> None:
        if key == "dashboard":
            self.open_dashboard_requested.emit()
        elif key == "achieve":
            self.open_achievement_requested.emit()
        elif key == "review":
            self.open_review_requested.emit()
        elif key == "pause":
            self.toggle_pause_requested.emit()

    def _hide_pet(self) -> None:
        self.cfg.set("ui.desktop_pet", False)
        self.hide()
        self.visibility_changed.emit(False)
