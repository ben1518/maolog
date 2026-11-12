"""本地窗口语义分类器与「用户纠偏记忆」闭环引擎。

核心作用：
1. 存储与匹配用户在时间轴上右键校准过的「窗口分类记忆规则」（data/user_rules.json），
   实现「手动纠偏一次 → 后续同应用/窗口关键词自动精准归类」的个性化闭环。
2. 当用户未配置大模型 API Key、校园网断网或 API 限流时，基于前台应用友好名与窗口标题语义，
   实时完成本地分类，做到零配置开箱即用、离线也能完整生成时间轴、饼图与学习复盘。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .app_names import resolve_app_display_name
from .config import DATA_DIR

RULES_PATH = DATA_DIR / "user_rules.json"

CATEGORIES: List[str] = ["学习", "工作", "娱乐", "沟通", "系统", "其他"]

# 常用预设活动标签（供右键快速选择或补全）
PRESET_ACTIVITIES: Dict[str, List[str]] = {
    "学习": ["课程学习", "文献阅读", "查阅资料", "算法刷题", "论文研读", "AI 协作对话", "实验复现"],
    "工作": ["编程开发", "文档写作", "项目推进", "数据处理", "演示制作", "调试代码"],
    "沟通": ["学术讨论", "日常沟通", "消息回复", "群组协作"],
    "娱乐": ["视频观看", "音乐收听", "游戏休闲", "社媒浏览"],
    "系统": ["文件管理", "环境配置", "系统操作"],
    "其他": ["桌面停留", "日常操作"],
}


def load_user_rules(path: Path = RULES_PATH) -> List[Dict[str, Any]]:
    """读取本地保存的用户纠偏规则列表。"""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def save_user_rule(
    app_name: str,
    title_keyword: str,
    category: str,
    activity: str,
    focus_score: Optional[int] = None,
    is_productive: Optional[bool] = None,
    detail_prefix: str = "",
    path: Path = RULES_PATH,
) -> Dict[str, Any]:
    """新增或更新一条用户纠偏规则。"""
    rules = load_user_rules(path)
    app_clean = resolve_app_display_name(app_name or "").strip()
    kw_clean = (title_keyword or "").strip()

    if is_productive is None:
        is_productive = category in ("工作", "学习")
    if focus_score is None:
        focus_score = 4 if is_productive else 2

    new_rule = {
        "app_name": app_clean,
        "title_keyword": kw_clean,
        "category": category,
        "activity": activity.strip() or ("课程学习" if category == "学习" else "编程开发"),
        "detail_prefix": (detail_prefix or "").strip(),
        "focus_score": int(focus_score),
        "is_productive": bool(is_productive),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 若已有相同 (app_name, title_keyword) 的规则则覆盖更新，并置顶
    filtered = [
        r
        for r in rules
        if not (
            (r.get("app_name") or "").lower() == app_clean.lower()
            and (r.get("title_keyword") or "").lower() == kw_clean.lower()
        )
    ]
    filtered.insert(0, new_rule)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(filtered[:100], ensure_ascii=False, indent=2), encoding="utf-8")
    return new_rule


def match_user_rule(
    app_name: str,
    window_title: str,
    path: Path = RULES_PATH,
) -> Optional[Dict[str, Any]]:
    """匹配用户纠偏规则：优先匹配同时带关键词的精细规则，再匹配仅应用级规则。"""
    rules = load_user_rules(path)
    if not rules:
        return None
    disp_app = resolve_app_display_name(app_name or "", window_title=window_title or "").lower()
    raw_app = (app_name or "").strip().lower()
    title_low = (window_title or "").strip().lower()

    # 第一轮：精确匹配应用 + 窗口标题关键词
    for r in rules:
        r_app = (r.get("app_name") or "").strip().lower()
        r_kw = (r.get("title_keyword") or "").strip().lower()
        if not r_kw:
            continue
        app_ok = (not r_app) or (r_app in (disp_app, raw_app))
        if app_ok and r_kw in title_low:
            return _rule_to_result(r, disp_app, window_title)

    # 第二轮：仅匹配应用名（无关键词限制的全局应用规则）
    for r in rules:
        r_app = (r.get("app_name") or "").strip().lower()
        r_kw = (r.get("title_keyword") or "").strip().lower()
        if r_app and not r_kw and r_app in (disp_app, raw_app):
            return _rule_to_result(r, disp_app, window_title)

    return None


def _rule_to_result(rule: Dict[str, Any], disp_app: str, window_title: str) -> Dict[str, Any]:
    cat = rule.get("category") or "学习"
    act = rule.get("activity") or "自主学习"
    short_title = _clean_title(window_title, disp_app)
    detail = f"{short_title}" if short_title else f"使用 {rule.get('app_name') or disp_app}"
    return {
        "category": cat,
        "activity": act,
        "detail": detail[:25],
        "focus_score": int(rule.get("focus_score", 4 if cat in ("工作", "学习") else 2)),
        "is_productive": bool(rule.get("is_productive", cat in ("工作", "学习"))),
        "model": "user_rule",
        "manual": True,
    }


def _clean_title(window_title: str, app_name: str = "") -> str:
    t = (window_title or "").strip()
    if not t:
        return ""
    # 去掉常见浏览器尾巴
    for suffix in (
        " - Microsoft Edge",
        " - Google Chrome",
        " - Mozilla Firefox",
        " - Visual Studio Code",
        " - Word",
        " - PowerPoint",
        " - Excel",
        " - WPS Office",
    ):
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
    t = re.sub(r"\s+-\s+个人\s*-\s*Microsoft​?\s*Edge.*$", "", t)
    return t[:24]


def classify_window_locally(
    app_name: str,
    window_title: str,
    rules_path: Path = RULES_PATH,
) -> Dict[str, Any]:
    """结合用户纠偏记忆与校园场景启发式规则，对窗口进行本地智能分类。"""
    # 1. 优先命中用户手动校准过的记忆规则
    matched = match_user_rule(app_name, window_title, path=rules_path)
    if matched is not None:
        return matched

    disp = resolve_app_display_name(app_name or "", window_title=window_title or "")
    disp_low = disp.lower()
    title = (window_title or "").strip()
    title_low = title.lower()
    clean_t = _clean_title(title, disp)

    # 2. IDE 与编程开发工具
    code_apps = {
        "visual studio code", "cursor", "pycharm", "intellij idea", "webstorm",
        "clion", "goland", "android studio", "visual studio", "sublime text",
        "windows 终端", "powershell", "命令提示符", "git", "antigravity",
        "deepseek harness", "maolog",
    }
    if disp_low in code_apps or any(k in disp_low for k in ("code", "pycharm", "idea", "studio", "terminal")):
        return {
            "category": "工作",
            "activity": "编程开发",
            "detail": (f"编写 {clean_t}" if clean_t else f"使用 {disp} 开发")[:25],
            "focus_score": 4,
            "is_productive": True,
            "model": "local_rule",
        }

    # 3. AI 助手对话窗口识别
    ai_keywords = (
        "deepseek", "chatgpt", "claude", "kimi", "豆包", "doubao",
        "通义千问", "qwen", "智谱", "清言", "文心一言", "腾讯元宝", "gemini",
    )
    if any(k in title_low or k in disp_low for k in ai_keywords):
        return {
            "category": "学习",
            "activity": "AI 协作对话",
            "detail": (clean_t or f"使用 {disp} 研讨")[:25],
            "focus_score": 4,
            "is_productive": True,
            "model": "local_rule",
        }

    # 4. 学术文献与笔记软件
    study_apps = {
        "zotero", "cajviewer", "adobe acrobat", "foxit reader", "sumatrapdf",
        "obsidian", "notion", "typora", "onenote", "anki", "xmind", "matlab",
    }
    if disp_low in study_apps or title_low.endswith(".pdf"):
        return {
            "category": "学习",
            "activity": "文献与笔记",
            "detail": (clean_t or f"使用 {disp} 研读")[:25],
            "focus_score": 4,
            "is_productive": True,
            "model": "local_rule",
        }

    # 5. Office / WPS 文档写作
    office_apps = {"microsoft word", "microsoft excel", "microsoft powerpoint", "wps office", "语雀", "飞书文档", "腾讯文档"}
    if disp_low in office_apps or any(ext in title_low for ext in (".docx", ".doc", ".pptx", ".xlsx")):
        return {
            "category": "工作",
            "activity": "文档写作",
            "detail": (clean_t or f"使用 {disp} 编辑文档")[:25],
            "focus_score": 4,
            "is_productive": True,
            "model": "local_rule",
        }

    # 6. 浏览器或视频中的学习/开发关键词 vs 娱乐关键词
    study_title_kws = (
        "知网", "cnki", "万方", "arxiv", "scholar", "课程", "教程", "公开课",
        "慕课", "mooc", "学习通", "雨课堂", "智慧树", "学堂在线", "leetcode",
        "力扣", "洛谷", "牛客", "github", "gitlab", "gitee", "stackoverflow",
        "csdn", "掘金", "文档", "documentation", "docs", "论文", "实验",
        "考研", "四六级", "复习", "算法", "数据结构", "python", "java", "c++",
        "机器学习", "深度学习", "人工智能", "数学", "英语", "讲义", "作业",
    )
    ent_title_kws = (
        "bilibili", "哔哩哔哩", "抖音", "小红书", "微博", "快手", "虎牙", "斗鱼",
        "爱奇艺", "腾讯视频", "优酷", "芒", "番剧", "电影", "综艺", "游戏",
        "直播", "搞笑", "vlog", "吃播", "音乐",
    )
    if any(k in title_low for k in study_title_kws):
        act = "课程视频学习" if any(v in title_low for v in ("bilibili", "哔哩哔哩", "慕课", "mooc", "公开课", "教程", "课程")) else "查阅资料"
        return {
            "category": "学习",
            "activity": act,
            "detail": (clean_t or "在线课程与资料学习")[:25],
            "focus_score": 4,
            "is_productive": True,
            "model": "local_rule",
        }

    if any(k in title_low or k in disp_low for k in ent_title_kws) or disp_low in {"steam", "网易云音乐", "qq音乐", "spotify", "potplayer"}:
        return {
            "category": "娱乐",
            "activity": "视频观看" if "音乐" not in disp_low else "音乐收听",
            "detail": (clean_t or f"在 {disp} 休闲")[:25],
            "focus_score": 2,
            "is_productive": False,
            "model": "local_rule",
        }

    # 7. 即时通讯软件
    chat_apps = {"微信", "qq", "tim", "钉钉", "飞书", "企业微信", "telegram", "discord", "outlook"}
    if disp_low in chat_apps:
        return {
            "category": "沟通",
            "activity": "日常沟通",
            "detail": f"使用 {disp} 沟通交流"[:25],
            "focus_score": 2,
            "is_productive": False,
            "model": "local_rule",
        }

    # 8. 系统与文件管理
    if disp_low in {"文件资源管理器", "任务管理器", "系统设置", "控制面板"}:
        return {
            "category": "系统",
            "activity": "文件管理",
            "detail": (clean_t or f"{disp}")[:25],
            "focus_score": 2,
            "is_productive": False,
            "model": "local_rule",
        }

    # 9. 浏览器通用查阅兜底
    if any(b in disp_low for b in ("edge", "chrome", "firefox", "浏览器", "arc", "brave")):
        return {
            "category": "学习",
            "activity": "查阅资料",
            "detail": (clean_t or f"使用 {disp} 浏览网页")[:25],
            "focus_score": 3,
            "is_productive": True,
            "model": "local_rule",
        }

    return {
        "category": "工作",
        "activity": "软件操作",
        "detail": (clean_t or f"使用 {disp}")[:25],
        "focus_score": 3,
        "is_productive": True,
        "model": "local_rule",
    }
