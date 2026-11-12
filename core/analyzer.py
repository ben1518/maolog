"""采集与分析调度。

两条独立线程用数据库当队列解耦：
  RecorderWorker  按间隔截屏，判断是否需要 AI，需要就写入 pending
  AnalyzerWorker  轮询 pending，串行调用 AI，写回结果

分线程的好处：AI 一次要 5~15 秒，卡不住截屏节奏；截屏也不会拖慢 AI 请求。
"""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QMetaObject, QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot

from .ai_client import AIClient, AIError, AIRateLimited
from .capture import CaptureResult, CaptureService
from .config import Config
from .local_classifier import classify_window_locally, match_user_rule
from .storage import Storage

# 被限流后暂停多久再试，避免连续撞墙把记录判死
RATE_LIMIT_COOLDOWN = 25
# 极端情况下若工作线程因外部 C 阻塞未能在 2.5s 内退出，暂存引用防止 Qt 在销毁运行中 QThread 时崩溃
_ORPHAN_THREADS: list[QThread] = []


class RecorderWorker(QObject):
    """定时截屏 + 变化判定。"""

    captured = pyqtSignal(object)  # CaptureResult
    decision = pyqtSignal(str, str)  # (动作, 说明) 动作: queued / reused / skipped
    error = pyqtSignal(str)

    def __init__(self, cfg: Config, storage: Storage) -> None:
        super().__init__()
        self.cfg = cfg
        self.storage = storage
        self.capture = CaptureService(cfg)
        self._timer: QTimer | None = None
        self._running = False
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        """跨线程安全地请求停止（仅置标志，不在调用方线程碰 QTimer）。"""
        self._running = False
        self._stop_event.set()

    @pyqtSlot()
    def start(self) -> None:
        self._stop_event.clear()
        self._running = True
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.tick)
        self._timer.start(self.cfg.interval_seconds * 1000)
        # 启动后立刻采一帧，不用等一个完整周期
        QTimer.singleShot(300, self.tick)

    @pyqtSlot()
    def stop(self) -> None:
        self._running = False
        if self._timer is not None:
            self._timer.stop()

    @pyqtSlot(int)
    def update_interval(self, seconds: int) -> None:
        if self._timer is not None:
            self._timer.setInterval(max(10, seconds) * 1000)

    @pyqtSlot()
    def tick(self) -> None:
        if not self._running:
            return

        # 全局暂停
        if self.cfg.get("privacy.paused"):
            mode = self.cfg.get("privacy.paused_mode", "no_ai")
            if mode == "off":
                self.decision.emit("skipped", "已暂停采集")
                return

        try:
            result = self.capture.capture_once()
        except Exception:
            self.error.emit("采集出错：" + traceback.format_exc(limit=2))
            return

        self.captured.emit(result)

        if result.skipped_reason:
            reason_text = {
                "excluded_app": "该应用在排除名单中",
                "sensitive": "窗口标题含敏感词",
                "blank": "画面为纯色（可能锁屏）",
                "grab_failed": "截屏失败",
            }.get(result.skipped_reason, result.skipped_reason)
            self.decision.emit("skipped", reason_text)
            return

        paused = bool(self.cfg.get("privacy.paused"))
        reuse = self._can_reuse(result)

        if reuse is not None and not paused:
            snapshot_id = self.storage.add_snapshot(
                result.ts, result.image_path, result.thumb_path,
                result.app_name, result.window_title, status="done",
            )
            self.storage.save_analysis(snapshot_id, reuse)
            self.storage.mark_status(snapshot_id, "reused")
            self.decision.emit("reused", "画面无变化，沿用上次结论")
            return

        snapshot_id = self.storage.add_snapshot(
            result.ts, result.image_path, result.thumb_path,
            result.app_name, result.window_title,
            status="pending" if not paused else "paused",
        )
        if paused:
            self.decision.emit("skipped", "已暂停 AI 分析，截图已保存")
        else:
            self.decision.emit("queued", "已排队等待 AI 分析")
        _ = snapshot_id

    # ---------- 内部 ----------

    def _can_reuse(self, result: CaptureResult) -> dict | None:
        """画面几乎没变时，复用最近一次的结论，省 API 调用。"""
        if not self.cfg.get("capture.change_detection", True):
            return None

        threshold = float(self.cfg.get("capture.change_threshold", 0.035) or 0.035)
        if result.diff_score >= threshold:
            return None

        last = self.storage.last_analyzed()
        if not last:
            return None

        # 同一活动持续太久时强制重判一次，避免把"看了两小时视频"记成一条
        force_minutes = int(self.cfg.get("capture.force_reanalyze_minutes", 20) or 20)
        try:
            last_ts = datetime.strptime(last["ts"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, TypeError, ValueError):
            return None
        if datetime.now() - last_ts > timedelta(minutes=force_minutes):
            return None

        return {
            "category": last.get("category") or "其他",
            "activity": last.get("activity") or "",
            "detail": last.get("detail") or "",
            "focus_score": last.get("focus_score") or 3,
            "is_productive": bool(last.get("is_productive")),
            "model": last.get("ai_raw") and _model_of(last.get("ai_raw")) or "",
        }


class AnalyzerWorker(QObject):
    """轮询待分析队列，串行调用 AI。"""

    analyzed = pyqtSignal(int, object)  # (snapshot_id, AIResult)
    failed = pyqtSignal(int, str)
    status = pyqtSignal(str)  # 供状态栏显示的文案

    def __init__(self, cfg: Config, storage: Storage) -> None:
        super().__init__()
        self.cfg = cfg
        self.storage = storage
        self.client = AIClient(cfg)
        self._timer: QTimer | None = None
        self._running = False
        self._stop_event = threading.Event()
        self._busy = False
        self._cooldown_until = 0.0

    def request_stop(self) -> None:
        """跨线程安全地请求停止，并中止在途 AI 请求/重试等待。"""
        self._running = False
        self._stop_event.set()
        self.client.abort()

    @pyqtSlot()
    def start(self) -> None:
        self._stop_event.clear()
        self.client.reset_abort()
        self._running = True
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.poll)
        self._timer.start(3000)
        QTimer.singleShot(1500, self.poll)

    @pyqtSlot()
    def stop(self) -> None:
        self._running = False
        if self._timer is not None:
            self._timer.stop()

    @pyqtSlot()
    def poll(self) -> None:
        if not self._running or self._busy:
            return
        if time.monotonic() < self._cooldown_until:
            return
        if self.cfg.get("privacy.paused") and self.cfg.get("privacy.paused_mode", "no_ai") == "off":
            return

        ready, msg = self.client.ready()
        row = self._next_task()
        if row is None:
            if not ready:
                self.status.emit(f"{msg}（本地智能规则引擎护航中）")
            return

        app_name = row.get("app_name") or ""
        win_title = row.get("window_title") or ""

        # 1. 优先匹配用户手动保存的「本地纠偏记忆规则」
        matched_rule = match_user_rule(app_name, win_title)
        if matched_rule is not None:
            self.storage.save_analysis(row["id"], matched_rule)
            self.analyzed.emit(row["id"], matched_rule)
            self.status.emit(f"规则记忆命中：{matched_rule['activity']}")
            return

        # 2. 未配置 API Key 时，自动启用本地窗口语义分类兜底（开箱即用）
        if not ready:
            if self.cfg.get("ai.local_fallback", True):
                local_res = classify_window_locally(app_name, win_title)
                self.storage.save_analysis(row["id"], local_res)
                self.analyzed.emit(row["id"], local_res)
                self.status.emit(f"本地智能识别：{local_res['activity']}（免 Key 模式）")
            else:
                self.status.emit(msg)
            return

        # 原图可能已被保留天数策略清掉，别浪费一次调用
        image = row.get("image_path") or ""
        if not image or not Path(image).exists():
            if self.cfg.get("ai.local_fallback", True):
                local_res = classify_window_locally(app_name, win_title)
                self.storage.save_analysis(row["id"], local_res)
                self.analyzed.emit(row["id"], local_res)
                self.status.emit(f"原图已清理，按窗口标题补齐：{local_res['activity']}")
            else:
                self.storage.mark_status(row["id"], "expired", "原图已经不在了")
            return

        is_backfill = row.get("status") == "paused"
        self._busy = True
        try:
            self.storage.mark_status(row["id"], "analyzing")
            result = self.client.analyze(
                image_path=image,
                app_name=app_name,
                window_title=win_title,
                ts=_parse_ts(row.get("ts")),
            )
            self.storage.save_analysis(row["id"], result.to_dict())
            self.analyzed.emit(row["id"], result)
            if is_backfill:
                left = self.storage.count_status("paused")
                self.status.emit(f"已回补暂停期间的记录（还剩 {left} 条）")
            else:
                self.status.emit(f"已分析：{result.activity}（{result.duration_ms}ms）")
        except AIRateLimited as exc:
            # 限流不是这条记录的错，退回原状态等冷却，别把它判死
            self.storage.mark_status(row["id"], "paused" if is_backfill else "pending", str(exc))
            self._cooldown_until = time.monotonic() + RATE_LIMIT_COOLDOWN
            self.status.emit(f"{exc}，{RATE_LIMIT_COOLDOWN} 秒后自动继续")
        except AIError as exc:
            if self._stop_event.is_set():
                self.storage.mark_status(row["id"], "paused" if is_backfill else "pending", "")
            elif self.cfg.get("ai.local_fallback", True):
                local_res = classify_window_locally(app_name, win_title)
                self.storage.save_analysis(row["id"], local_res)
                self.analyzed.emit(row["id"], local_res)
                self.status.emit(f"AI 请求受限，已用本地规则兜底：{local_res['activity']}")
            else:
                self.storage.mark_status(row["id"], "failed", str(exc))
                self.failed.emit(row["id"], str(exc))
                self.status.emit(f"分析失败：{exc}")
        except Exception as exc:
            if self._stop_event.is_set():
                self.storage.mark_status(row["id"], "paused" if is_backfill else "pending", "")
            elif self.cfg.get("ai.local_fallback", True):
                local_res = classify_window_locally(app_name, win_title)
                self.storage.save_analysis(row["id"], local_res)
                self.analyzed.emit(row["id"], local_res)
                self.status.emit(f"AI 异常已用本地规则兜底：{local_res['activity']}")
            else:
                self.storage.mark_status(row["id"], "failed", repr(exc))
                self.failed.emit(row["id"], repr(exc))
                self.status.emit(f"分析异常：{exc.__class__.__name__}")
        finally:
            self._busy = False

    def _next_task(self) -> dict | None:
        """新任务优先；队列空了才回补暂停期间的记录。

        AI 一次 5~15 秒且全局串行，所以「空闲才回补」本身就是限速：
        恢复暂停后不会出现并发轰炸，也不会挤占实时分析。
        """
        batch = self.storage.pending(limit=1)
        if batch:
            return batch[0]
        if self.cfg.get("privacy.paused"):
            return None
        backlog = self.storage.paused_backlog(limit=1)
        return backlog[0] if backlog else None


class RecorderEngine:
    """把两条工作线程包起来，给 UI 提供 start / stop / 暂停 接口。"""

    def __init__(self, cfg: Config, storage: Storage) -> None:
        self.cfg = cfg
        self.storage = storage

        self.recorder = RecorderWorker(cfg, storage)
        self.analyzer = AnalyzerWorker(cfg, storage)

        self.recorder_thread = QThread()
        self.analyzer_thread = QThread()
        self.recorder.moveToThread(self.recorder_thread)
        self.analyzer.moveToThread(self.analyzer_thread)

        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.recorder_thread.start()
        self.analyzer_thread.start()
        QTimer.singleShot(0, self.recorder.start)
        QTimer.singleShot(0, self.analyzer.start)
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        # 先从调用方线程安全地置停机标志并中止在途 HTTP 请求，再让各自工作线程停 QTimer
        self.recorder.request_stop()
        self.analyzer.request_stop()
        if self.recorder_thread.isRunning():
            QMetaObject.invokeMethod(
                self.recorder, "stop", Qt.ConnectionType.QueuedConnection
            )
        if self.analyzer_thread.isRunning():
            QMetaObject.invokeMethod(
                self.analyzer, "stop", Qt.ConnectionType.QueuedConnection
            )
        self.recorder_thread.quit()
        self.analyzer_thread.quit()
        if not self.recorder_thread.wait(2500):
            _ORPHAN_THREADS.append(self.recorder_thread)
        if not self.analyzer_thread.wait(2500):
            _ORPHAN_THREADS.append(self.analyzer_thread)

    # ---------- 转发信号，方便 UI 直接连 ----------

    @property
    def captured(self):
        return self.recorder.captured

    @property
    def decision(self):
        return self.recorder.decision

    @property
    def analyzed(self):
        return self.analyzer.analyzed

    @property
    def failed(self):
        return self.analyzer.failed

    @property
    def status(self):
        return self.analyzer.status

    @property
    def recorder_error(self):
        return self.recorder.error


# ---------- 工具函数 ----------


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _model_of(raw: str) -> str:
    import json

    try:
        data = json.loads(raw)
        return str(data.get("model") or "")
    except (json.JSONDecodeError, TypeError):
        return ""
