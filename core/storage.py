"""数据层：SQLite 读写。

表结构：
  snapshots      每次采集一条，含窗口信息、图片路径和 AI 分析结果
  daily_summary  每天一条 AI 总结

并发策略：每次操作独立开连接（WAL 模式），避免 Qt 多线程共享连接出问题。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from .app_names import resolve_app_display_name
from .config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    day           TEXT NOT NULL,
    image_path    TEXT,
    thumb_path    TEXT,
    app_name      TEXT,
    window_title  TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    category      TEXT,
    activity      TEXT,
    detail        TEXT,
    focus_score   INTEGER,
    is_productive INTEGER,
    ai_raw        TEXT,
    error         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_snapshots_day    ON snapshots(day);
CREATE INDEX IF NOT EXISTS idx_snapshots_status ON snapshots(status);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts     ON snapshots(ts);

CREATE TABLE IF NOT EXISTS daily_summary (
    day          TEXT PRIMARY KEY,
    summary      TEXT,
    highlights   TEXT,
    suggestions  TEXT,
    model        TEXT,
    created_at   TEXT,
    updated_at   TEXT
);
"""


class Storage:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        with self._conn() as conn:
            # WAL 与同步级别只需在建库/首连时设置一次，避免每次查询反复抢写锁
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
            if conn.in_transaction:
                conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    # ---------- 写入 ----------

    def add_snapshot(
        self,
        ts: datetime,
        image_path: str | None,
        thumb_path: str | None,
        app_name: str,
        window_title: str,
        status: str = "pending",
    ) -> int:
        with self._write_lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO snapshots
                   (ts, day, image_path, thumb_path, app_name, window_title, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts.strftime("%Y-%m-%d %H:%M:%S"),
                    ts.strftime("%Y-%m-%d"),
                    image_path,
                    thumb_path,
                    app_name,
                    window_title,
                    status,
                ),
            )
            return int(cur.lastrowid)

    def save_analysis(self, snapshot_id: int, result: dict[str, Any]) -> None:
        """写入 AI 分析结果。result 需含 category/activity/detail/focus/productive。"""
        with self._write_lock, self._conn() as conn:
            conn.execute(
                """UPDATE snapshots SET
                     status='done', category=?, activity=?, detail=?,
                     focus_score=?, is_productive=?, ai_raw=?, error=NULL
                   WHERE id=?""",
                (
                    result.get("category", "其他"),
                    result.get("activity", ""),
                    result.get("detail", ""),
                    _clamp_int(result.get("focus_score"), 1, 5, 3),
                    1 if result.get("is_productive") else 0,
                    json.dumps(result, ensure_ascii=False),
                    snapshot_id,
                ),
            )

    def mark_status(self, snapshot_id: int, status: str, error: str | None = None) -> None:
        with self._write_lock, self._conn() as conn:
            conn.execute(
                "UPDATE snapshots SET status=?, error=? WHERE id=?",
                (status, error, snapshot_id),
            )

    def delete_snapshots(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._write_lock, self._conn() as conn:
            conn.executemany("DELETE FROM snapshots WHERE id=?", [(i,) for i in ids])

    def update_snapshots_manual(
        self,
        ids: list[int],
        category: str,
        activity: str,
        detail: str,
        focus_score: int | None = None,
        is_productive: bool | None = None,
    ) -> int:
        """人工校准一批快照记录，并在 ai_raw 中标记 manual=True。"""
        if not ids:
            return 0
        cat = (category or "其他").strip() or "其他"
        act = (activity or "未分类").strip() or "未分类"
        det = (detail or "").strip()
        if focus_score is None:
            focus_score = 4 if cat in ("学习", "工作") else (2 if cat == "娱乐" else 3)
        if is_productive is None:
            is_productive = cat in ("学习", "工作")
        f_score = _clamp_int(focus_score, 1, 5, 3)
        prod_int = 1 if is_productive else 0
        raw_payload = json.dumps(
            {
                "category": cat,
                "activity": act,
                "detail": det,
                "focus_score": f_score,
                "is_productive": bool(is_productive),
                "model": "manual-calibrated",
                "manual": True,
            },
            ensure_ascii=False,
        )
        placeholders = ",".join("?" for _ in ids)
        with self._write_lock, self._conn() as conn:
            cur = conn.execute(
                f"""UPDATE snapshots SET
                      status='done', category=?, activity=?, detail=?,
                      focus_score=?, is_productive=?, ai_raw=?, error=NULL
                    WHERE id IN ({placeholders})""",
                (cat, act, det, f_score, prod_int, raw_payload, *ids),
            )
            return int(cur.rowcount or 0)

    def apply_rule_to_day(
        self,
        day: str,
        app_name: str,
        title_keyword: str,
        category: str,
        activity: str,
        detail_prefix: str = "",
    ) -> int:
        """将新保存的本地规则回溯应用到当天匹配的记录上。"""
        rows = self.day_snapshots(day)
        app_norm = (app_name or "").strip().lower()
        kw_norm = (title_keyword or "").strip().lower()
        matched_ids: list[int] = []
        for r in rows:
            r_app = (r.get("app_name") or "").strip().lower()
            r_title = (r.get("window_title") or "").strip()
            if app_norm and r_app != app_norm:
                continue
            if kw_norm and kw_norm not in r_title.lower():
                continue
            matched_ids.append(int(r["id"]))
        if not matched_ids:
            return 0
        detail = detail_prefix.strip() or f"{activity}（规则回溯校准）"
        return self.update_snapshots_manual(
            matched_ids,
            category=category,
            activity=activity,
            detail=detail,
        )

    def delete_day(self, day: str) -> list[str]:
        """删除某天数据，返回需要一并删掉的图片路径。"""
        with self._write_lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT image_path, thumb_path FROM snapshots WHERE day=?", (day,)
            ).fetchall()
            conn.execute("DELETE FROM snapshots WHERE day=?", (day,))
            conn.execute("DELETE FROM daily_summary WHERE day=?", (day,))
        paths: list[str] = []
        for r in rows:
            for key in ("image_path", "thumb_path"):
                if r[key]:
                    paths.append(r[key])
        return paths

    # ---------- 查询 ----------

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        return dict(row) if row else None

    def last_analyzed(self) -> dict[str, Any] | None:
        """最近一条已分析完成的记录，用于画面未变化时复用结论。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE status IN ('done','reused') "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def pending(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM snapshots WHERE status='pending' ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def paused_backlog(self, limit: int = 1) -> list[dict[str, Any]]:
        """暂停期间落库的记录。

        按时间倒序：最新的先补，用户先看到最近的时间线，而且新图更可能还在。
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM snapshots WHERE status='paused' ORDER BY ts DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_status(self, status: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM snapshots WHERE status=?", (status,)
            ).fetchone()
        return int(row["c"]) if row else 0

    def clear_image_paths(self, day: str) -> None:
        """原图被清理后把路径置空；记录本身保留，统计不受影响。"""
        with self._write_lock, self._conn() as conn:
            conn.execute(
                "UPDATE snapshots SET image_path=NULL, thumb_path=NULL "
                "WHERE day=? AND (image_path IS NOT NULL OR thumb_path IS NOT NULL)",
                (day,),
            )

    def unresolved_days(self, days: list[str]) -> set[str]:
        """这些日期里还有没分析完的记录（这些天不能删图）。"""
        if not days:
            return set()
        placeholders = ",".join("?" for _ in days)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT day FROM snapshots WHERE day IN ({placeholders}) "
                "AND status IN ('pending','analyzing','paused')",
                tuple(days),
            ).fetchall()
        return {r["day"] for r in rows}

    def day_snapshots(self, day: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM snapshots WHERE day=? ORDER BY ts, id", (day,)
            ).fetchall()
        return [dict(r) for r in rows]

    def snapshots_between(self, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM snapshots WHERE ts BETWEEN ? AND ? ORDER BY ts, id",
                (start_ts, end_ts),
            ).fetchall()
        return [dict(r) for r in rows]

    def analyzed_day(self, day: str) -> list[dict[str, Any]]:
        """当天所有有分析结论的记录（含复用），按时间排序。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM snapshots WHERE day=? AND status IN ('done','reused') "
                "ORDER BY ts, id",
                (day,),
            ).fetchall()
        return [dict(r) for r in rows]

    def days_with_data(self, limit: int = 30) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT day FROM snapshots ORDER BY day DESC LIMIT ?", (limit,)
            ).fetchall()
        return [r["day"] for r in rows]

    def all_days_with_data(self) -> set[str]:
        """返回库中所有产生过快照记录的日期集合。"""
        with self._conn() as conn:
            rows = conn.execute("SELECT DISTINCT day FROM snapshots").fetchall()
        return {r["day"] for r in rows if r["day"]}

    def earliest_day(self) -> str | None:
        """数据库中记录的最早日期，若无记录则返回 None。"""
        with self._conn() as conn:
            row = conn.execute("SELECT MIN(day) AS min_day FROM snapshots").fetchone()
            if row and row["min_day"]:
                return str(row["min_day"])
        return None

    def counts(self, day: str) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) c FROM snapshots WHERE day=? GROUP BY status", (day,)
            ).fetchall()
        data = {r["status"]: r["c"] for r in rows}
        data["total"] = sum(data.values())
        return data

    # ---------- 统计聚合 ----------

    def segments(self, day: str, gap_factor: float = 2.5, interval: int = 60) -> list[dict[str, Any]]:
        """把连续同活动的记录合并成时间段，用于时间轴甘特图。

        合并条件：分类 + 活动 + 详情完全相同，且两条记录间隔不超过
        interval * gap_factor 秒。
        """
        rows = self.analyzed_day(day)
        if not rows:
            return []

        gap_limit = timedelta(seconds=interval * gap_factor)
        segments: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        current_last: datetime | None = None

        for row in rows:
            try:
                ts = datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError):
                continue
            key = (row.get("category"), row.get("activity"), row.get("detail"))

            if current is not None and current_last is not None:
                same = current["_key"] == key and (ts - current_last) <= gap_limit
                if same:
                    current["end"] = ts
                    current["count"] += 1
                    current["_ids"].append(row["id"])
                    if _is_manual(row.get("ai_raw")):
                        current["is_manual"] = True
                    current_last = ts
                    continue

            if current is not None:
                segments.append(_finish(current, interval))

            current = {
                "_key": key,
                "_ids": [row["id"]],
                "start": ts,
                "end": ts,
                "count": 1,
                "category": row.get("category") or "其他",
                "activity": row.get("activity") or "",
                "detail": row.get("detail") or "",
                "app_name": row.get("app_name") or "",
                "window_title": row.get("window_title") or "",
                "focus_score": row.get("focus_score") or 0,
                "is_productive": row.get("is_productive") or 0,
                "image_path": row.get("image_path"),
                "is_manual": _is_manual(row.get("ai_raw")),
            }
            current_last = ts

        if current is not None:
            segments.append(_finish(current, interval))
        return segments

    def category_stats(self, day: str, interval: int = 60) -> list[dict[str, Any]]:
        rows = self.analyzed_day(day)
        bucket: dict[str, int] = {}
        for r in rows:
            cat = r.get("category") or "其他"
            bucket[cat] = bucket.get(cat, 0) + 1
        total = sum(bucket.values()) or 1
        out = [
            {
                "category": cat,
                "count": cnt,
                "seconds": cnt * interval,
                "ratio": cnt / total,
            }
            for cat, cnt in bucket.items()
        ]
        out.sort(key=lambda x: -x["count"])
        return out

    def app_stats(self, day: str, interval: int = 60, limit: int = 8) -> list[dict[str, Any]]:
        rows = self.analyzed_day(day)
        bucket: dict[str, int] = {}
        for r in rows:
            raw_app = (r.get("app_name") or "未知").strip() or "未知"
            title = (r.get("window_title") or "").strip()
            app = resolve_app_display_name(raw_app, window_title=title)
            bucket[app] = bucket.get(app, 0) + 1
        out = [
            {"app": app, "count": cnt, "seconds": cnt * interval}
            for app, cnt in bucket.items()
        ]
        out.sort(key=lambda x: -x["count"])
        return out[:limit]

    def overview(self, day: str, interval: int = 60) -> dict[str, Any]:
        rows = self.analyzed_day(day)
        if not rows:
            return {
                "records": 0,
                "tracked_seconds": 0,
                "productive_seconds": 0,
                "avg_focus": 0.0,
                "top_activity": "",
                "app_count": 0,
                "first_ts": "",
                "last_ts": "",
            }
        scores = [r["focus_score"] for r in rows if r.get("focus_score")]
        productive = sum(1 for r in rows if r.get("is_productive"))
        activity_bucket: dict[str, int] = {}
        for r in rows:
            act = r.get("activity") or "未分类"
            activity_bucket[act] = activity_bucket.get(act, 0) + 1
        top_activity = max(activity_bucket.items(), key=lambda kv: kv[1])[0] if activity_bucket else ""
        app_names = {
            resolve_app_display_name(r.get("app_name") or "", window_title=r.get("window_title") or "")
            for r in rows
            if (r.get("app_name") or "").strip()
        }
        return {
            "records": len(rows),
            "tracked_seconds": len(rows) * interval,
            "productive_seconds": productive * interval,
            "avg_focus": round(sum(scores) / len(scores), 2) if scores else 0.0,
            "top_activity": top_activity,
            "app_count": len(app_names),
            "first_ts": rows[0]["ts"][11:16],
            "last_ts": rows[-1]["ts"][11:16],
        }

    # ---------- 每日总结 ----------

    def save_daily_summary(
        self,
        day: str,
        summary: str,
        highlights: list[str],
        suggestions: list[str],
        model: str,
    ) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._write_lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO daily_summary (day, summary, highlights, suggestions, model, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(day) DO UPDATE SET
                     summary=excluded.summary,
                     highlights=excluded.highlights,
                     suggestions=excluded.suggestions,
                     model=excluded.model,
                     updated_at=excluded.updated_at""",
                (
                    day,
                    summary,
                    json.dumps(highlights, ensure_ascii=False),
                    json.dumps(suggestions, ensure_ascii=False),
                    model,
                    now,
                    now,
                ),
            )

    def get_daily_summary(self, day: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM daily_summary WHERE day=?", (day,)).fetchone()
        if not row:
            return None
        data = dict(row)
        for key in ("highlights", "suggestions"):
            try:
                data[key] = json.loads(data.get(key) or "[]")
            except json.JSONDecodeError:
                data[key] = []
        return data


def _finish(seg: dict[str, Any], interval: int) -> dict[str, Any]:
    """收尾一个时间段，算出时长。"""
    seg.pop("_key", None)
    ids = seg.pop("_ids", [])
    seg["ids"] = ids
    duration = max(interval, seg["count"] * interval)
    seg["seconds"] = duration
    seg["duration_text"] = format_duration(duration)
    seg["start_text"] = seg["start"].strftime("%H:%M")
    seg["end_text"] = (seg["end"] + timedelta(seconds=interval)).strftime("%H:%M")
    return seg


def format_duration(seconds: int) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h and m:
        return f"{h}小时{m}分"
    if h:
        return f"{h}小时"
    if m:
        return f"{m}分钟"
    return "不到1分钟"


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _is_manual(ai_raw: str | None) -> bool:
    if not ai_raw:
        return False
    try:
        data = json.loads(ai_raw)
        return bool(data.get("manual")) or data.get("model") == "manual-calibrated"
    except (json.JSONDecodeError, TypeError):
        return False
