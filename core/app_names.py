"""应用程序友好显示名称解析模块。

把底层的可执行程序名（如 python.exe、Code.exe、chrome.exe）转换为用户可读的实际应用名称（如 MaoLog、Visual Studio Code、Google Chrome）。
支持：
  1. 常见应用内置映射表（覆盖开发、办公、浏览器、通讯、系统工具等）
  2. Windows PE 文件版本信息（FileDescription / ProductName）动态解析
  3. 自运行进程（MaoLog / 楚师智学）的智能识别
  4. 未知 .exe 程序的名称清洗与兜底
  5. 解析结果内存级缓存
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import re
from typing import Dict, Optional

# 内置常见程序名到应用展示名称的映射
KNOWN_APPS: Dict[str, str] = {
    # 常用开发与终端
    "python.exe": "Python",
    "pythonw.exe": "Python",
    "code.exe": "Visual Studio Code",
    "cursor.exe": "Cursor",
    "devenv.exe": "Visual Studio",
    "pycharm64.exe": "PyCharm",
    "pycharm.exe": "PyCharm",
    "idea64.exe": "IntelliJ IDEA",
    "idea.exe": "IntelliJ IDEA",
    "webstorm64.exe": "WebStorm",
    "webstorm.exe": "WebStorm",
    "goland64.exe": "GoLand",
    "goland.exe": "GoLand",
    "clion64.exe": "CLion",
    "clion.exe": "CLion",
    "rider64.exe": "Rider",
    "rider.exe": "Rider",
    "datagrip64.exe": "DataGrip",
    "datagrip.exe": "DataGrip",
    "sublime_text.exe": "Sublime Text",
    "notepad++.exe": "Notepad++",
    "hbuilderx.exe": "HBuilderX",
    "windowsterminal.exe": "Windows 终端",
    "powershell.exe": "PowerShell",
    "pwsh.exe": "PowerShell",
    "cmd.exe": "命令提示符",
    "git-bash.exe": "Git Bash",
    "mintty.exe": "Git Bash",
    "trae.exe": "Trae",
    "trae cn.exe": "Trae",
    "postman.exe": "Postman",
    "apifox.exe": "Apifox",
    "dbeaver.exe": "DBeaver",
    "navicat.exe": "Navicat",

    # 浏览器
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave",
    "opera.exe": "Opera",
    "360se.exe": "360安全浏览器",
    "360chrome.exe": "360极速浏览器",
    "qqbrowser.exe": "QQ浏览器",
    "sogouexplorer.exe": "搜狗浏览器",

    # 办公与写作
    "winword.exe": "Microsoft Word",
    "excel.exe": "Microsoft Excel",
    "powerpnt.exe": "Microsoft PowerPoint",
    "onenote.exe": "OneNote",
    "wps.exe": "WPS Office",
    "wpswriter.exe": "WPS 文字",
    "wpsoffice.exe": "WPS Office",
    "wpspdf.exe": "WPS PDF",
    "et.exe": "WPS 表格",
    "wpp.exe": "WPS 演示",
    "notepad.exe": "记事本",
    "wordpad.exe": "写字板",
    "typora.exe": "Typora",
    "obsidian.exe": "Obsidian",
    "notion.exe": "Notion",
    "acrobat.exe": "Adobe Acrobat",
    "acrord32.exe": "Adobe Reader",
    "sumatrapdf.exe": "SumatraPDF",
    "foxitreader.exe": "福昕阅读器",
    "foxitpdfreader.exe": "福昕阅读器",

    # 社交通讯与协作
    "wechat.exe": "微信",
    "weixin.exe": "微信",
    "wechatappex.exe": "微信小程序",
    "qq.exe": "QQ",
    "dingtalk.exe": "钉钉",
    "feishu.exe": "飞书",
    "workbuddy.exe": "WorkBuddy",
    "teams.exe": "Microsoft Teams",
    "slack.exe": "Slack",
    "zoom.exe": "Zoom",
    "wemeetapp.exe": "腾讯会议",
    "tencentmeeting.exe": "腾讯会议",

    # AI 客户端
    "kimi.exe": "Kimi",
    "doubao.exe": "豆包",
    "chatgpt.exe": "ChatGPT",
    "claude.exe": "Claude",
    "wenxin.exe": "文心一言",
    "tongyi.exe": "通义千问",
    "deepseek.exe": "DeepSeek",
    "deepseek harness.exe": "DeepSeek Harness",
    "gemini.exe": "Gemini",

    # 系统与实用工具
    "explorer.exe": "文件资源管理器",
    "snippingtool.exe": "截图工具",
    "screensketch.exe": "截图和草图",
    "taskmgr.exe": "任务管理器",
    "calculator.exe": "计算器",
    "calculatorapp.exe": "计算器",
    "regedit.exe": "注册表编辑器",
    "mmc.exe": "管理控制台",
    "control.exe": "控制面板",
    "systemsettings.exe": "Windows 设置",
    "applicationframehost.exe": "Windows 应用",

    # 影音与娱乐
    "cloudmusic.exe": "网易云音乐",
    "qqmusic.exe": "QQ音乐",
    "kugou.exe": "酷狗音乐",
    "potplayer64.exe": "PotPlayer",
    "potplayer.exe": "PotPlayer",
    "vlc.exe": "VLC",
    "bilibili.exe": "哔哩哔哩",
    "steam.exe": "Steam",
    "epicgameslauncher.exe": "Epic Games",
}

# 描述文本规格化（Windows 系统程序描述经常带冗余前缀）
_DESCRIPTION_NORMALIZATIONS = {
    "windows 命令处理程序": "命令提示符",
    "windows 资源管理器": "文件资源管理器",
    "windows explorer": "文件资源管理器",
}

# 反向映射：友好名称 -> 进程名（全小写）
_DISPLAY_TO_EXE: Dict[str, str] = {
    v.casefold(): k for k, v in KNOWN_APPS.items()
}
_EXTRA_ALIASES: Dict[str, str] = {
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "ppt": "powerpnt.exe",
    "vscode": "code.exe",
    "vs code": "code.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
}
_DISPLAY_TO_EXE.update(_EXTRA_ALIASES)


def to_canonical_process_name(name: str) -> str:
    """把展示名称转换回标准进程名（如 'Visual Studio Code' -> 'code.exe'）。"""
    if not name:
        return ""
    clean = name.strip().casefold()
    return _DISPLAY_TO_EXE.get(clean, clean)


# 缓存
_PE_DESC_CACHE: Dict[str, str] = {}
_RESOLVED_CACHE: Dict[tuple[str, str], str] = {}


def get_pe_file_description(file_path: str) -> str:
    """从 Windows 可执行文件中提取 FileDescription 或 ProductName。"""
    if not file_path or not os.path.exists(file_path):
        return ""
    norm_path = os.path.normpath(file_path).casefold()
    if norm_path in _PE_DESC_CACHE:
        return _PE_DESC_CACHE[norm_path]

    desc = ""
    try:
        version = ctypes.WinDLL("version", use_last_error=True)
        size = version.GetFileVersionInfoSizeW(file_path, None)
        if size:
            res = ctypes.create_string_buffer(size)
            if version.GetFileVersionInfoW(file_path, 0, size, res):
                langs = []
                p_trans = ctypes.c_void_p()
                trans_len = wintypes.UINT()
                sub_block = "\\VarFileInfo\\Translation"
                if version.VerQueryValueW(res, sub_block, ctypes.byref(p_trans), ctypes.byref(trans_len)):
                    if trans_len.value >= 4:
                        trans_arr = ctypes.cast(p_trans, ctypes.POINTER(wintypes.WORD))
                        for i in range(trans_len.value // 4):
                            langs.append(f"{trans_arr[i * 2]:04x}{trans_arr[i * 2 + 1]:04x}")

                # 补充常见语言代码页
                langs.extend(["080404b0", "040904b0", "040904E4", "000004b0", "04090000", "08040000"])
                for block in langs:
                    for key in ("FileDescription", "ProductName"):
                        sub_block_desc = f"\\StringFileInfo\\{block}\\{key}"
                        p_desc = ctypes.c_void_p()
                        desc_len = wintypes.UINT()
                        if version.VerQueryValueW(res, sub_block_desc, ctypes.byref(p_desc), ctypes.byref(desc_len)):
                            val = ctypes.wstring_at(p_desc).strip()
                            if val:
                                desc = val
                                break
                    if desc:
                        break
    except Exception:
        desc = ""

    _PE_DESC_CACHE[norm_path] = desc
    return desc


def _is_maolog_window(title: str) -> bool:
    """检查窗口标题是否属于本应用。"""
    if not title:
        return False
    t = title.casefold()
    return any(k in t for k in ("maolog", "毛记录", "楚师智学", "电脑使用看板", "ai 协作回看", "学习复盘", "用时校准", "数据护照"))


def resolve_app_display_name(
    raw_name: str,
    exe_path: Optional[str] = None,
    window_title: str = "",
    pid: Optional[int] = None,
) -> str:
    """把程序名/快照记录解析为面向用户展示的友好应用名称。
    
    参数:
      raw_name: 进程名或应用名（如 'python.exe', 'Code.exe', 'Python'）
      exe_path: 可选的可执行文件完整路径
      window_title: 可选的窗口标题（用于区分 python.exe 跑的具体程序等）
      pid: 可选的进程 ID（若等于当前进程，则直接判定为本应用）
    """
    raw = (raw_name or "").strip()
    if not raw or raw == "未知":
        return "未知"

    cache_key = (raw.casefold(), window_title.strip().casefold() if raw.casefold().startswith("python") else "")
    if cache_key in _RESOLVED_CACHE and not exe_path:
        return _RESOLVED_CACHE[cache_key]

    raw_lower = raw.casefold()

    # 1. 运行态判断：如果就是当前进程或标题属于本软件
    if pid is not None and pid == os.getpid():
        res = "楚师智学" if "楚师智学" in window_title else "MaoLog"
        _RESOLVED_CACHE[cache_key] = res
        return res

    # 2. 如果是 python.exe，根据窗口标题区分是 MaoLog 还是普通 Python 脚本/工具
    if raw_lower in ("python.exe", "pythonw.exe", "python"):
        if _is_maolog_window(window_title):
            res = "楚师智学" if "楚师智学" in window_title else "MaoLog"
            _RESOLVED_CACHE[cache_key] = res
            return res
        if "jupyter" in window_title.casefold():
            _RESOLVED_CACHE[cache_key] = "Jupyter Notebook"
            return "Jupyter Notebook"
        if "idle" in window_title.casefold():
            _RESOLVED_CACHE[cache_key] = "Python IDLE"
            return "Python IDLE"
        _RESOLVED_CACHE[cache_key] = "Python"
        return "Python"

    # 3. 查已知静态字典
    if raw_lower in KNOWN_APPS:
        res = KNOWN_APPS[raw_lower]
        _RESOLVED_CACHE[cache_key] = res
        return res

    # 4. 如果提供了可执行文件路径，尝试读取 PE 文件元信息
    if exe_path:
        pe_desc = get_pe_file_description(exe_path)
        if pe_desc:
            pe_clean = pe_desc.strip()
            norm = _DESCRIPTION_NORMALIZATIONS.get(pe_clean.casefold(), pe_clean)
            _RESOLVED_CACHE[cache_key] = norm
            return norm

    # 5. 如果 raw 本身已经不是 .exe，说明已经是处理好的应用名字
    if not raw_lower.endswith(".exe"):
        _RESOLVED_CACHE[cache_key] = raw
        return raw

    # 6. 未知 .exe 兜底：剥离 .exe 后缀并做基础整理
    clean = re.sub(r"(?i)\.exe$", "", raw).strip()
    # 替换多余下划线或短横线
    clean = clean.replace("_", " ").strip()
    res = clean or raw
    _RESOLVED_CACHE[cache_key] = res
    return res
