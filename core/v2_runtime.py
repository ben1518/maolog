"""v2 运行时开关：把真实 AI 外发写入台账。

默认关闭。关闭时不创建 V2Storage，也不碰 activity.db。
开启后也只记录元数据，不记录提示词、图片内容或窗口标题。
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import DB_PATH, Config
from .outbound import ALLOWED_PURPOSES
from .v2_storage import V2Storage

LOGGER = logging.getLogger("mao.v2_runtime")
_STORAGE_CACHE: dict[str, V2Storage] = {}


def ledger_enabled(cfg: Config) -> bool:
    return bool(cfg.get("v2.outbound_ledger", False))


def enforcement_enabled(cfg: Config) -> bool:
    return ledger_enabled(cfg) and bool(cfg.get("v2.enforce_outbound", False))


def v2_db_path(cfg: Config) -> Path:
    configured = str(cfg.get("v2.db_path", "") or "").strip()
    return Path(configured) if configured else DB_PATH


def get_v2_storage(cfg: Config) -> V2Storage:
    path = v2_db_path(cfg)
    key = str(path.resolve())
    if key not in _STORAGE_CACHE:
        _STORAGE_CACHE[key] = V2Storage(path)
    return _STORAGE_CACHE[key]


def v2_table_exists(path: Path, table: str) -> bool:
    """只读检查，不创建数据库或表。"""
    if table not in {"ai_use_daily", "time_estimate", "outbound_log"}:
        raise ValueError(f"不允许检查的表名：{table}")
    path = Path(path)
    if not path.exists():
        return False
    try:
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("PRAGMA query_only=ON")
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return row is not None


class OutboundLedger:
    """AIClient 使用的最小接口；任何写入失败都不能阻断正常 AI 调用。"""

    def __init__(self, cfg: Config, storage: V2Storage) -> None:
        self.cfg = cfg
        self.storage = storage
        self.enforce = enforcement_enabled(cfg)

    def allow(self, purpose: str) -> bool:
        if purpose not in ALLOWED_PURPOSES:
            return False
        if not self.enforce:
            return True
        return self.storage.outbound_allowed(purpose)

    def record(
        self,
        purpose: str,
        provider: str,
        model: str,
        byte_count: int,
        has_thumb: bool,
    ) -> bool:
        if purpose not in ALLOWED_PURPOSES:
            return False
        try:
            self.storage.record_outbound(
                ts=datetime.now(),
                provider=provider,
                model=model,
                byte_count=byte_count,
                has_thumb=has_thumb,
                purpose=purpose,
            )
            return True
        except Exception as exc:  # 只记录模式下台账不能影响主流程
            LOGGER.warning("外发台账写入失败：%s", exc.__class__.__name__)
            return False


def get_outbound_ledger(cfg: Config) -> OutboundLedger | None:
    if not ledger_enabled(cfg):
        return None
    try:
        return OutboundLedger(cfg, get_v2_storage(cfg))
    except Exception as exc:
        LOGGER.warning("外发台账初始化失败：%s", exc.__class__.__name__)
        return None


def reset_cache() -> None:
    """测试或切换数据库后清缓存。"""
    _STORAGE_CACHE.clear()
