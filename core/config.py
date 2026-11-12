"""配置管理。

配置存于 data/config.json，支持默认值深合并，改动即时落盘。
所有路径都是绝对路径，避免工作目录漂移导致截图找不到。
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

from core.paths import data_root

APP_ROOT = data_root()
DATA_DIR = APP_ROOT / "data"
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "activity.db"

# 活动分类（AI 只能在这几类里选，便于统计口径统一）
CATEGORIES = ["工作", "学习", "娱乐", "沟通", "系统", "其他"]

DEFAULT_CONFIG: dict[str, Any] = {
    "capture": {
        # 采集间隔（秒）
        "interval_seconds": 60,
        # 截图存放根目录，程序会自动按日期建子目录
        "output_dir": str(DATA_DIR / "screenshots"),
        # 原图保留天数，0 表示永久保留
        "keep_days": 0,
        # 画面变化检测：画面没变就不重复调用 AI，直接复用上次结论
        "change_detection": True,
        # 帧差均值阈值（0~1），越小越敏感
        "change_threshold": 0.035,
        # 长时间画面未变化时，最多复用多少分钟后强制重新分析
        "force_reanalyze_minutes": 20,
        # 存盘前缩放到这个宽度（0 = 不缩放，保留原图尺寸）
        "max_width": 2560,
        "jpeg_quality": 92,
        # 多显示器时截第几块，0 = 全部屏幕拼合，1 = 主屏，2 = 第二屏...
        "monitor": 1,
        # 这些进程的前台画面不采集（隐私保护）
        "exclude_apps": ["KeePass.exe", "1Password.exe", "Bitwarden.exe"],
    },
    "ai": {
        # provider: qwen | zhipu | openai | ollama
        "provider": "qwen",
        "api_key": "",
        "model": "qwen-vl-max-latest",
        # 自定义端点（openai / ollama 用），留空则用 provider 默认
        "base_url": "",
        "timeout": 90,
        # 未配置 API Key 或 AI 请求受限时，是否自动启用本地窗口语义规则引擎识别（免 Key 可用）
        "local_fallback": True,
    },
    "privacy": {
        # 全局暂停开关
        "paused": False,
        # 暂停模式：no_ai = 只停 AI 分析（照常截图存盘）；off = 连截图也停
        "paused_mode": "no_ai",
        # 窗口标题包含这些关键词时不采集，原图也不落盘
        "sensitive_keywords": ["密码", "登录密码", "身份证", "银行卡", "支付密码"],
    },
    "ui": {
        "start_minimized": False,
        # 关闭窗口时最小化到托盘而不是退出
        "close_to_tray": True,
        # 外观：dark = 手绘深色（默认），paper = 手绘米色纸面
        "skin": "dark",
    },
    "v2": {
        # 默认关闭：不建 v2 表、不写任何外发台账
        "outbound_ledger": False,
        # 开启台账后是否按用途开关拦截请求；默认只记录，不改变一期行为
        "enforce_outbound": False,
        # 留空则使用 data/activity.db
        "db_path": "",
    },
}


class Config:
    """线程安全的配置容器。"""

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
        self.load()

    # ---------- 读写 ----------

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self.save()
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # 配置损坏时回退到默认值，并把坏文件留档
                try:
                    self.path.with_suffix(".json.bak").write_text(
                        self.path.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                except OSError:
                    pass
                self._data = copy.deepcopy(DEFAULT_CONFIG)
                self.save()
                return
            self._data = _deep_merge(copy.deepcopy(DEFAULT_CONFIG), raw)

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(self.path)

    # ---------- 访问 ----------

    def get(self, dotted: str, default: Any = None) -> Any:
        """用点号路径取值，如 cfg.get("capture.interval_seconds")。"""
        with self._lock:
            node: Any = self._data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return node

    def set(self, dotted: str, value: Any, save: bool = True) -> None:
        with self._lock:
            parts = dotted.split(".")
            node = self._data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
            if save:
                self.save()

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def update(self, patch: dict[str, Any]) -> None:
        with self._lock:
            self._data = _deep_merge(self._data, patch)
            self.save()

    # ---------- 便捷属性 ----------

    @property
    def output_dir(self) -> Path:
        p = Path(self.get("capture.output_dir", str(DATA_DIR / "screenshots")))
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def interval_seconds(self) -> int:
        try:
            return max(10, int(self.get("capture.interval_seconds", 60)))
        except (TypeError, ValueError):
            return 60


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """把 patch 合并进 base：字典递归合并，其他类型直接覆盖。"""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


# 全局单例，各处 import 直接用
config = Config()
