"""v2 原型的独立数据层。

只在调用方明确指定的数据库中创建 v2 新表，不改一期表结构。
预览和测试应使用独立数据库，避免把演示数据写入真实记录。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .storage import Storage

TS_FORMAT = "%Y-%m-%d %H:%M:%S"
DAY_FORMAT = "%Y-%m-%d"

V2_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_use_daily (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    day           TEXT NOT NULL,
    task_context  TEXT NOT NULL,
    start_ts      TEXT NOT NULL,
    end_ts        TEXT NOT NULL,
    mode          TEXT,
    original_mode TEXT,
    evidence_json TEXT,
    overridden    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_use_daily_day ON ai_use_daily(day);

CREATE TABLE IF NOT EXISTS outbound_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    provider    TEXT,
    model       TEXT,
    bytes       INTEGER,
    has_thumb   INTEGER NOT NULL DEFAULT 0,
    purpose     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbound_log_ts ON outbound_log(ts);

CREATE TABLE IF NOT EXISTS outbound_policy (
    purpose    TEXT PRIMARY KEY,
    allowed    INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS time_estimate (
    day             TEXT PRIMARY KEY,
    planned_minutes INTEGER,
    actual_minutes  INTEGER
);
"""

V2_UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_use_task_day
    ON ai_use_daily(day, task_context);
"""


def parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    if not isinstance(value, str):
        raise ValueError("时间必须是 datetime 或字符串")
    text = value.strip()
    for fmt in (TS_FORMAT, "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError("时间格式应为 YYYY-MM-DD HH:MM:SS")


def format_timestamp(value: str | datetime) -> str:
    return parse_timestamp(value).strftime(TS_FORMAT)


def parse_day(value: str) -> datetime:
    try:
        return datetime.strptime(value, DAY_FORMAT)
    except (TypeError, ValueError) as exc:
        raise ValueError("日期格式应为 YYYY-MM-DD") from exc


def validate_range(start_ts: str | datetime, end_ts: str | datetime) -> tuple[str, str]:
    start = parse_timestamp(start_ts)
    end = parse_timestamp(end_ts)
    if end < start:
        raise ValueError("结束时间不能早于开始时间")
    return start.strftime(TS_FORMAT), end.strftime(TS_FORMAT)


class V2Storage(Storage):
    """在一期 Storage 上增加 v2 表；构造时必须显式给出数据库路径。"""

    def __init__(self, db_path: Path) -> None:
        super().__init__(Path(db_path))
        with self._write_lock, self._conn() as conn:
            conn.executescript(V2_SCHEMA)
            # 旧原型留下的死表：只存任务名与区间，新版不再使用，也不能作为隐性导出历史保留。
            conn.execute("DROP TABLE IF EXISTS attest_session")
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(ai_use_daily)").fetchall()
            }
            if "original_mode" not in columns:
                conn.execute("ALTER TABLE ai_use_daily ADD COLUMN original_mode TEXT")
            # 旧键允许同一天同任务多行；建唯一索引前先保留改判行/最新行。
            conn.execute(
                """DELETE FROM ai_use_daily WHERE id IN (
                       SELECT id FROM (
                           SELECT id, ROW_NUMBER() OVER (
                               PARTITION BY day, task_context
                               ORDER BY overridden DESC, id DESC
                           ) AS row_no
                           FROM ai_use_daily
                       ) WHERE row_no > 1
                   )"""
            )
            conn.executescript(V2_UNIQUE_INDEX)
            now = datetime.now().strftime(TS_FORMAT)
            for purpose in ("画面识别", "日终总结", "连接测试"):
                conn.execute(
                    "INSERT OR IGNORE INTO outbound_policy (purpose, allowed, updated_at) "
                    "VALUES (?, 0, ?)",
                    (purpose, now),
                )

    def snapshots_between(self, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        start, end = validate_range(start_ts, end_ts)
        return super().snapshots_between(start, end)

    def save_ai_judgment(self, judgment: dict[str, Any]) -> tuple[int, bool]:
        """保存机器判断；同一任务同一天的刷新都保留学生改判。

        刷新时结束时间会变（“到现在为止”），所以键用任务 + 日期，不用精确区间。
        返回 (记录 id, 是否保留了已有改判)。
        """
        start, end = validate_range(judgment["start_ts"], judgment["end_ts"])
        task = str(judgment.get("task_context") or "").strip()
        if not task:
            raise ValueError("任务上下文不能为空")
        day = start[:10]
        evidence = json.dumps(judgment.get("evidence") or {}, ensure_ascii=False)
        mode = judgment["mode"]
        with self._write_lock, self._conn() as conn:
            existing = conn.execute(
                "SELECT id, overridden FROM ai_use_daily WHERE day=? AND task_context=?",
                (day, task),
            ).fetchone()
            if existing and existing["overridden"]:
                return int(existing["id"]), True
            if existing:
                conn.execute(
                    """UPDATE ai_use_daily
                       SET start_ts=?, end_ts=?, mode=?, original_mode=?,
                           evidence_json=?, updated_at=?
                       WHERE id=?""",
                    (
                        start,
                        end,
                        mode,
                        mode,
                        evidence,
                        datetime.now().strftime(TS_FORMAT),
                        existing["id"],
                    ),
                )
                return int(existing["id"]), False
            cursor = conn.execute(
                """INSERT INTO ai_use_daily
                   (day, task_context, start_ts, end_ts, mode, original_mode, evidence_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (day, task, start, end, mode, mode, evidence),
            )
            return int(cursor.lastrowid), False

    def get_ai_judgment(self, judgment_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM ai_use_daily WHERE id=?", (judgment_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        try:
            result["evidence"] = json.loads(result.get("evidence_json") or "{}")
        except json.JSONDecodeError:
            result["evidence"] = {"notes": ["依据记录格式损坏"]}
        return result

    def list_ai_judgments(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM ai_use_daily ORDER BY start_ts DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self.get_ai_judgment(int(row["id"])) for row in rows]

    def override_ai_mode(self, judgment_id: int, new_mode: str) -> None:
        current = self.get_ai_judgment(judgment_id)
        if current is None:
            raise ValueError("找不到要修改的判断")
        evidence = current.get("evidence") or {}
        original_mode = current.get("original_mode") or current.get("mode")
        evidence["override_from"] = current.get("mode")
        evidence["original_mode"] = original_mode
        evidence["override_note"] = "由学生本人修改"
        with self._write_lock, self._conn() as conn:
            cursor = conn.execute(
                """UPDATE ai_use_daily
                   SET mode=?, original_mode=?, evidence_json=?, overridden=1, updated_at=?
                   WHERE id=?""",
                (
                    new_mode,
                    original_mode,
                    json.dumps(evidence, ensure_ascii=False),
                    datetime.now().strftime(TS_FORMAT),
                    judgment_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("修改判断失败，记录可能已被删除")

    def record_outbound(
        self,
        ts: str | datetime,
        provider: str,
        model: str,
        byte_count: int,
        has_thumb: bool,
        purpose: str,
    ) -> int:
        if int(byte_count) < 0:
            raise ValueError("请求大小不能为负数")
        provider_text = str(provider or "").strip()
        model_text = str(model or "").strip()
        if not provider_text or not model_text:
            raise ValueError("服务商和模型名不能为空")
        with self._write_lock, self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO outbound_log (ts, provider, model, bytes, has_thumb, purpose)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    format_timestamp(ts),
                    provider_text,
                    model_text,
                    int(byte_count),
                    1 if has_thumb else 0,
                    purpose,
                ),
            )
            return int(cursor.lastrowid)

    def outbound_events(self, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM outbound_log
                   ORDER BY ts DESC, id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_outbound_allowed(self, purpose: str, allowed: bool) -> None:
        with self._write_lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO outbound_policy (purpose, allowed, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(purpose) DO UPDATE SET
                     allowed=excluded.allowed, updated_at=excluded.updated_at""",
                (purpose, 1 if allowed else 0, datetime.now().strftime(TS_FORMAT)),
            )

    def outbound_allowed(self, purpose: str) -> bool:
        """没有明确授权的用途一律拒绝，避免新增用途时默认放行。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT allowed FROM outbound_policy WHERE purpose=?", (purpose,)
            ).fetchone()
        return False if row is None else bool(row["allowed"])

    def outbound_policy_state(self) -> dict[str, bool]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT purpose, allowed FROM outbound_policy ORDER BY purpose"
            ).fetchall()
        return {row["purpose"]: bool(row["allowed"]) for row in rows}

    def outbound_purpose_counts(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT purpose, COUNT(*) AS c FROM outbound_log GROUP BY purpose"
            ).fetchall()
        return {row["purpose"]: int(row["c"]) for row in rows}

    def outbound_providers(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT provider, model FROM outbound_log ORDER BY provider, model"
            ).fetchall()
        return [f"{row['provider'] or '未记录'} / {row['model'] or '未记录'}" for row in rows]

    def set_planned_minutes(self, day: str, minutes: int) -> None:
        normalized = parse_day(day).strftime(DAY_FORMAT)
        with self._write_lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO time_estimate (day, planned_minutes) VALUES (?, ?)
                   ON CONFLICT(day) DO UPDATE SET planned_minutes=excluded.planned_minutes""",
                (normalized, int(minutes)),
            )

    def set_actual_minutes(self, day: str, minutes: int) -> None:
        normalized = parse_day(day).strftime(DAY_FORMAT)
        with self._write_lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO time_estimate (day, actual_minutes) VALUES (?, ?)
                   ON CONFLICT(day) DO UPDATE SET actual_minutes=excluded.actual_minutes""",
                (normalized, int(minutes)),
            )

    def get_time_estimate(self, day: str) -> dict[str, Any] | None:
        parse_day(day)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM time_estimate WHERE day=?", (day,)
            ).fetchone()
        return dict(row) if row else None

    def list_time_estimates(self, limit: int = 31) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 366))
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM time_estimate ORDER BY day DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_day_v2(self, day: str) -> dict[str, int]:
        """只删除指定日期的 v2 元数据，不碰一期快照与图片。"""
        normalized = parse_day(day).strftime(DAY_FORMAT)
        with self._write_lock, self._conn() as conn:
            ai_count = conn.execute(
                "SELECT COUNT(*) AS c FROM ai_use_daily WHERE day=?", (normalized,)
            ).fetchone()["c"]
            outbound_count = conn.execute(
                "SELECT COUNT(*) AS c FROM outbound_log WHERE substr(ts, 1, 10)=?",
                (normalized,),
            ).fetchone()["c"]
            estimate_count = conn.execute(
                "SELECT COUNT(*) AS c FROM time_estimate WHERE day=?", (normalized,)
            ).fetchone()["c"]
            conn.execute("DELETE FROM ai_use_daily WHERE day=?", (normalized,))
            conn.execute(
                "DELETE FROM outbound_log WHERE substr(ts, 1, 10)=?", (normalized,)
            )
            conn.execute("DELETE FROM time_estimate WHERE day=?", (normalized,))
        return {
            "ai_judgments": int(ai_count),
            "outbound_records": int(outbound_count),
            "time_estimates": int(estimate_count),
        }

    def table_counts(self) -> dict[str, int]:
        allowed = {
            "snapshots",
            "daily_summary",
            "ai_use_daily",
            "outbound_log",
            "outbound_policy",
            "time_estimate",
        }
        result: dict[str, int] = {}
        with self._conn() as conn:
            for table in sorted(allowed):
                row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
                result[table] = int(row["c"])
        return result
