"""MaoLog 的视觉令牌与全局样式。

两套皮肤，都是手绘风格：
- paper：米色纸面 + 墨蓝字，像本子上随手记的一页
- dark：深墨黑板面 + 奶白字，像夜里在灯下写的笔记

两套共用同一套手绘绘制代码（ui/doodle_paint.py），只有调色板和纸张纹理不同。
字体统一用随程序分发的霞鹜文楷。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from core.paths import asset_dir, data_root

ASSET_DIR = asset_dir()
_ARROW_DOWN = (ASSET_DIR / "arrow-down.svg").as_posix()
_ARROW_UP = (ASSET_DIR / "arrow-up.svg").as_posix()
_CHECK = (ASSET_DIR / "check.svg").as_posix()


def _read_skin_from_config() -> str:
    """读取配置里的皮肤设置。

    主题在导入时就要定型（样式表是模块级常量），所以这里直接读 JSON，
    不走 Config 类，避免循环导入。
    """
    try:
        path = data_root() / "data" / "config.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return str((data.get("ui") or {}).get("skin") or "")
    except Exception:
        pass
    return ""


def _resolve_skin() -> str:
    """环境变量优先（方便预览），其次读配置，默认日系手帐纸面风格（方案 A）。"""
    env = os.environ.get("MAO_DOODLE", "")
    if env == "1":
        return "paper"
    if env == "2":
        return "dark"
    if env == "0":
        return "paper"
    configured = _read_skin_from_config()
    if configured in ("paper", "dark"):
        return configured
    return "paper"


SKIN = _resolve_skin()
IS_DARK_SKIN = SKIN == "dark"
# 兼容旧代码：所有手绘相关分支都用这个开关
DOODLE_MODE = True

FONT_FAMILY = '"LXGW WenKai", "霞鹜文楷", "KaiTi", "楷体", "Microsoft YaHei", sans-serif'
FONT_DISPLAY = FONT_FAMILY
FONT_MONO = '"Cascadia Mono", "Consolas", monospace'

# 手绘皮肤里的"红笔"色，两套皮肤都保留这个强调角色
DOODLE_RED = "#C4503C" if IS_DARK_SKIN else "#B23A2A"

if IS_DARK_SKIN:
    # ---------------- 深色：深墨黑板面 ----------------
    # 取自用户指定的深色版配色
    BG_ROOT = "#1E1D20"      # 页面背景 更深一档，让卡片浮起来
    BG_CARD = "#2E2C31"      # 卡片背景
    BG_CARD_HOVER = "#3D3B40"
    BG_ELEVATED = "#423F45"
    BG_INSET = "#2C2A2E"

    # 手绘线条用暖白，边框取它的低透明度感
    BORDER = "#8A8279"
    BORDER_SOFT = "#57535A"

    TEXT_PRIMARY = "#E8E1D5"   # 暖白
    TEXT_SECONDARY = "#BDB6AB"
    TEXT_MUTED = "#8A8479"

    # 点缀黄色作为主强调
    ACCENT = "#F5CC68"
    ACCENT_HOVER = "#F8D782"
    ACCENT_DARK = "#40392A"
    ACCENT_SOFT = "#6A5A38"
    ON_ACCENT = "#242326"
    ACCENT_PRESSED = "#E0B955"
    SCROLL_HANDLE = "#57535A"
    SUCCESS = "#A6BE91"       # 点缀绿色
    WARNING = "#E8B067"
    DANGER = "#E88E85"        # 点缀粉色兼警示

    # 工作蓝 / 学习绿 / 娱乐粉 / 沟通紫（粉与蓝之间过渡）
    CATEGORY_COLORS = {
        "工作": "#82A9D6",     # 蓝色
        "学习": "#A6BE91",     # 绿色
        "娱乐": "#E88E85",     # 粉色
        "沟通": "#B49CD4",
        "系统": "#8A8479",
        "其他": "#6B6660",
    }

    _PAPER_TILE = (ASSET_DIR / "doodle" / "grain-dark.png").as_posix()
    # 线稿插画在深色底上要反相，否则看不见
    INVERT_ART = True
else:
    # ---------------- 浅色：米色纸面 ----------------
    # 与深色版同一套三色语言，只把纸色换成暖白
    BG_ROOT = "#FBF6F0"      # 偏粉的暖白
    BG_CARD = "#FFFFFF"
    BG_CARD_HOVER = "#F6F0E8"
    BG_ELEVATED = "#F0E9E0"
    BG_INSET = "#F9F4ED"

    BORDER = "#B3A99D"
    BORDER_SOFT = "#DCD4C9"

    TEXT_PRIMARY = "#3A3733"
    TEXT_SECONDARY = "#605A52"
    TEXT_MUTED = "#958D83"

    # 主强调用深一档的黄，白底上才够对比
    ACCENT = "#B8892E"
    ACCENT_HOVER = "#C99A3A"
    ACCENT_DARK = "#F7EFDD"
    ACCENT_SOFT = "#E6D8B8"
    ON_ACCENT = "#FFFFFF"
    ACCENT_PRESSED = "#A3781F"
    SCROLL_HANDLE = "#D3CABF"
    SUCCESS = "#5E8A5A"
    WARNING = "#B07C22"
    DANGER = "#C0645A"

    # 与深色同色相，压深一档适配白底
    CATEGORY_COLORS = {
        "工作": "#5A85B8",
        "学习": "#6B8E62",
        "娱乐": "#C87567",
        "沟通": "#9080B8",
        "系统": "#958D83",
        "其他": "#B3A99D",
    }

    _PAPER_TILE = (ASSET_DIR / "doodle" / "paper-tile.png").as_posix()
    INVERT_ART = False


def category_color(name: str | None) -> str:
    return CATEGORY_COLORS.get(name or "", CATEGORY_COLORS["其他"])


APP_QSS = f"""
* {{
    font-family: {FONT_FAMILY};
    outline: none;
}}

QMainWindow, QDialog {{ background: {BG_ROOT}; }}
QWidget#Root {{ background: {BG_ROOT}; }}

QFrame#Card {{
    background: {BG_CARD};
    border: 1px solid {BORDER_SOFT};
    border-radius: 16px;
}}
QFrame#InsightCard {{
    background: {BG_CARD};
    border: 1px solid {ACCENT_SOFT};
    border-radius: 16px;
}}
QFrame#SessionCard {{
    background: {BG_INSET};
    border: 1px solid {BORDER_SOFT};
    border-radius: 12px;
}}
QFrame#SourceRail {{
    background: {BG_CARD};
    border: 1px solid {BORDER_SOFT};
    border-radius: 16px;
}}
QFrame#SourceRow {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 11px;
}}
QFrame#SourceRow[active="true"] {{
    background: {BG_ELEVATED};
    border-color: {ACCENT_SOFT};
}}
QFrame#SourceRow:hover {{ background: {BG_CARD_HOVER}; }}
QLabel#SourceIcon {{
    background: {ACCENT_DARK};
    color: {ACCENT};
    border: 1px solid {ACCENT_SOFT};
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel#SourceName {{ color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 600; }}
QLabel#SourceBadge {{
    color: {TEXT_SECONDARY};
    background: {BG_ELEVATED};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
    padding: 2px 6px;
    font-size: 9px;
}}
QCheckBox#SourceToggle {{ color: {TEXT_SECONDARY}; font-size: 11px; }}
QLabel#SourceDot {{ color: {TEXT_MUTED}; font-size: 12px; }}
QLabel#RailNote {{
    color: {TEXT_MUTED};
    font-size: 10px;
    line-height: 1.5;
    padding: 10px 12px;
    border-top: 1px dashed {BORDER_SOFT};
}}
QToolButton#IconButton {{
    background: transparent;
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER_SOFT};
    border-radius: 18px;
    font-size: 18px;
}}
QToolButton#IconButton:hover {{ color: {TEXT_PRIMARY}; border-color: {ACCENT_SOFT}; }}
QFrame#ProviderConnection {{
    background: {BG_INSET};
    border: 1px solid {BORDER_SOFT};
    border-radius: 16px;
}}
QLabel#ProviderMark {{
    background: {BG_ELEVATED};
    color: {ACCENT};
    border: 1px solid {ACCENT_SOFT};
    border-radius: 13px;
    font-size: 12px;
    font-weight: 600;
}}
QFrame#WebPlayerToolbar {{
    background: {BG_ELEVATED};
    border-bottom: 1px solid {BORDER_SOFT};
}}
QProgressBar#WebProgress {{
    background: transparent;
    border: none;
}}
QProgressBar#WebProgress::chunk {{ background: {ACCENT}; }}
QPushButton#DangerGhost {{
    background: transparent;
    color: {DANGER};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
    padding: 7px 11px;
}}
QPushButton#DangerGhost:hover {{ border-color: {DANGER}; background: {BG_CARD_HOVER}; }}
QFrame#DateNavigator {{
    background: {BG_INSET};
    border: 1px solid {BORDER_SOFT};
    border-radius: 11px;
}}
QFrame#TopDivider {{ background: {BORDER_SOFT}; border: none; max-height: 1px; }}

QLabel {{ color: {TEXT_PRIMARY}; background: transparent; }}
QLabel#Title {{ font-size: 23px; font-weight: 600; letter-spacing: 1px; }}
QLabel#BrandCaption {{ color: {ACCENT}; font-size: 10px; font-weight: 600; letter-spacing: 2px; }}
QLabel#Subtitle {{ color: {TEXT_MUTED}; font-size: 11px; letter-spacing: 0.5px; }}
QLabel#SectionTitle {{ font-size: 14px; font-weight: 600; letter-spacing: 0.3px; color: {TEXT_PRIMARY}; }}
QLabel#SectionEyebrow {{ color: {TEXT_MUTED}; font-size: 11px; letter-spacing: 1px; }}
QLabel#Muted {{ color: {TEXT_MUTED}; font-size: 12px; }}
QLabel#BigNumber {{
    font-family: {FONT_MONO};
    font-size: 27px;
    font-weight: 500;
    color: {TEXT_PRIMARY};
}}
QLabel#CardLabel {{ color: {TEXT_SECONDARY}; font-size: 12px; }}
QLabel#DateLabel {{ color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 500; }}
QPushButton#DateButton {{
    background: transparent;
    color: {TEXT_PRIMARY};
    border: none;
    border-radius: 8px;
    padding: 0 8px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#DateButton:hover {{
    background: {BG_ELEVATED};
    color: {ACCENT};
}}
QLabel#AccentBadge {{
    color: {ACCENT};
    background: {ACCENT_DARK};
    border: 1px solid {ACCENT_SOFT};
    border-radius: 9px;
    padding: 4px 9px;
    font-size: 11px;
}}
QLabel#StatusBadge {{
    color: {TEXT_SECONDARY};
    background: {BG_CARD};
    border: 1px solid {BORDER_SOFT};
    border-radius: 9px;
    padding: 4px 9px;
    font-size: 11px;
}}
QLabel#SongTitle {{ font-size: 21px; font-weight: 600; color: {TEXT_PRIMARY}; }}
QLabel#SongArtist {{ color: {TEXT_SECONDARY}; font-size: 12.5px; }}
QLabel#LyricLine {{ color: {ACCENT}; font-size: 12.5px; font-weight: 500; }}
QLabel#MonoMuted {{ color: {TEXT_MUTED}; font-size: 11px; font-family: {FONT_MONO}; }}
QLabel#SystemNote {{
    color: {TEXT_SECONDARY};
    background: {BG_INSET};
    border: 1px solid {BORDER_SOFT};
    border-radius: 10px;
    padding: 11px 13px;
    font-size: 12px;
}}

QPushButton {{
    background: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 14px;
    min-height: 20px;
    font-size: 12px;
}}
QPushButton:hover {{ background: {BG_CARD_HOVER}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT_DARK}; }}
QPushButton:disabled {{
    color: {TEXT_MUTED};
    background: {BG_INSET};
    border-color: {BORDER_SOFT};
}}
QPushButton:focus {{ border: 1px solid {ACCENT}; }}
QPushButton#Primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: {ON_ACCENT};
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#Primary:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#Primary:disabled {{ background: {ACCENT_SOFT}; border-color: {ACCENT_SOFT}; color: {TEXT_MUTED}; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid {BORDER_SOFT}; }}
QPushButton#Ghost:hover {{ background: {BG_CARD_HOVER}; border-color: {BORDER}; }}
QPushButton#Danger {{ background: transparent; border: 1px solid #593A36; color: {DANGER}; }}
QPushButton#Danger:hover {{ background: {BG_CARD_HOVER}; }}
QPushButton#IconButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 0px;
    font-family: "Segoe UI Symbol", sans-serif;
    font-size: 18px;
    color: {TEXT_SECONDARY};
}}
QPushButton#IconButton:hover {{ background: {BG_ELEVATED}; color: {TEXT_PRIMARY}; }}
QPushButton#IconButton:disabled {{ color: {TEXT_MUTED}; background: transparent; }}
QPushButton#ScrollHint {{
    background: {BG_ELEVATED};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 3px 9px;
    min-height: 0px;
    font-size: 11px;
}}
QPushButton#ScrollHint:hover {{ color: {ACCENT}; border-color: {ACCENT_SOFT}; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QDateEdit, QTimeEdit {{
    background: {BG_INSET};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 8px 10px;
    color: {TEXT_PRIMARY};
    font-size: 13px;
    selection-background-color: {ACCENT_SOFT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus,
QDateEdit:focus, QTimeEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled,
QDateEdit:disabled, QTimeEdit:disabled {{ color: {TEXT_MUTED}; background: {BG_INSET}; }}
QComboBox, QSpinBox, QDateEdit, QTimeEdit {{ padding-right: 30px; }}
QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 28px;
    background: transparent;
    border: none;
    border-left: 1px solid {BORDER_SOFT};
    border-top-right-radius: 9px;
    border-bottom-right-radius: 9px;
}}
QComboBox::down-arrow, QDateEdit::down-arrow {{
    image: url({_ARROW_DOWN});
    width: 10px;
    height: 6px;
}}
QComboBox QAbstractItemView {{
    background: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 9px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_SOFT};
    padding: 5px;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDateEdit::up-button, QDateEdit::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {{
    subcontrol-origin: border;
    width: 20px;
    background: {BG_INSET};
    border-left: 1px solid {BORDER_SOFT};
}}
QSpinBox::up-button, QDateEdit::up-button, QTimeEdit::up-button {{
    subcontrol-position: top right;
    border-bottom: 1px solid {BORDER_SOFT};
    border-top-right-radius: 9px;
}}
QSpinBox::down-button, QDateEdit::down-button, QTimeEdit::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: 9px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDateEdit::up-button:hover, QDateEdit::down-button:hover,
QTimeEdit::up-button:hover, QTimeEdit::down-button:hover {{
    background: {BG_ELEVATED};
}}
QSpinBox::up-arrow, QDateEdit::up-arrow, QTimeEdit::up-arrow {{
    image: url({_ARROW_UP}); width: 8px; height: 5px;
}}
QSpinBox::down-arrow, QDateEdit::down-arrow, QTimeEdit::down-arrow {{
    image: url({_ARROW_DOWN}); width: 8px; height: 5px;
}}
QCalendarWidget {{ background: {BG_CARD}; color: {TEXT_PRIMARY}; }}
QCalendarWidget QWidget {{ alternate-background-color: {BG_CARD}; }}
QCalendarWidget QToolButton {{
    color: {TEXT_PRIMARY}; background: transparent;
    border: none; border-radius: 6px; padding: 4px 8px;
}}
QCalendarWidget QToolButton:hover {{ background: {BG_ELEVATED}; }}
QCalendarWidget QAbstractItemView:enabled {{
    background: {BG_INSET}; color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_SOFT}; selection-color: {ACCENT};
    outline: none;
}}
QCalendarWidget QSpinBox {{ padding-right: 18px; }}

QCheckBox {{ color: {TEXT_PRIMARY}; font-size: 13px; spacing: 9px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid {BORDER}; background: {BG_INSET};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url({_CHECK}); }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 3px; }}
QScrollBar::handle:vertical {{ background: {SCROLL_HANDLE}; border-radius: 4px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; }}
QScrollBar::handle:horizontal {{ background: {SCROLL_HANDLE}; border-radius: 4px; min-width: 32px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QToolTip {{
    background: {BG_ELEVATED}; color: {TEXT_PRIMARY};
    border: 1px solid {BORDER}; border-radius: 7px;
    padding: 7px 10px; font-size: 12px;
}}
QTabWidget::pane {{ border: none; background: {BG_CARD}; top: 8px; }}
QTabBar::tab {{
    background: transparent; color: {TEXT_SECONDARY};
    padding: 10px 18px; margin-right: 4px;
    border: 1px solid transparent; border-radius: 9px;
    font-size: 13px;
}}
QTabBar::tab:selected {{ background: {ACCENT_DARK}; border-color: {ACCENT_SOFT}; color: {ACCENT}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT_PRIMARY}; background: {BG_CARD_HOVER}; }}
QMenu {{
    background: {BG_ELEVATED}; border: 1px solid {BORDER};
    border-radius: 10px; padding: 6px; color: {TEXT_PRIMARY};
}}
QMenu::item {{ padding: 8px 22px 8px 14px; border-radius: 6px; font-size: 13px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}
"""


# 边框改由 doodle_paint.paint_rough_frame 画，QSS 只留底色
if True:
    APP_QSS += f"""
    QFrame#Card, QFrame#InsightCard {{ border: none; background: transparent; }}
    QFrame#DateNavigator {{ border: none; background: transparent; }}

    /* 标签页：不要胶囊，改成下划线，像本子上的分隔页 */
    QTabBar::tab {{
        background: transparent;
        color: {TEXT_MUTED};
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0;
        padding: 8px 16px 7px 16px;
        margin-right: 10px;
        font-size: 13.5px;
    }}
    QTabBar::tab:selected {{
        color: {TEXT_PRIMARY};
        border-bottom: 2px solid {TEXT_PRIMARY};
        background: transparent;
    }}
    QTabBar::tab:hover:!selected {{
        color: {TEXT_PRIMARY};
        background: transparent;
    }}
    QTabWidget::pane {{ border: none; background: transparent; }}

    /* 纸面上的表单：不要盒子，只要一条横线 */
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDateEdit, QTimeEdit {{
        background: transparent;
        border: none;
        border-bottom: 1.5px solid {BORDER};
        border-radius: 0;
        padding: 6px 2px;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
    QSpinBox:focus, QDateEdit:focus, QTimeEdit:focus {{
        border-bottom: 2px solid {ACCENT};
    }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {BG_CARD};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT_DARK};
    }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border: 1.5px solid {BORDER};
        border-radius: 2px;
        background: {BG_CARD};
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}

    /* 兜底系统弹窗样式：万一第三方组件唤起 QMessageBox 也保持手帐暖色调 */
    QMessageBox {{
        background-color: {BG_CARD};
    }}
    QMessageBox QLabel {{
        color: {TEXT_PRIMARY};
        font-size: 13px;
        line-height: 1.5;
    }}
    """
