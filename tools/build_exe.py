"""打包成 exe。

先装 pyinstaller，然后跑：
    .venv/Scripts/python.exe tools/build_exe.py

产物在 dist/MaoLog/MaoLog.exe。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICON = ASSETS / "icon.ico"


def make_icon() -> None:
    """与界面共用同一份品牌绘制代码，避免打包图标和托盘图标两套样子。"""
    sys.path.insert(0, str(ROOT))
    from ui.brand import save_brand_assets

    save_brand_assets(ASSETS)
    print(f"图标已生成 -> {ICON}")


def build(onefile: bool = False) -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("还没装 PyInstaller，先执行：")
        print(f"  {sys.executable} -m pip install pyinstaller")
        return 1

    make_icon()

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name", "MaoLog_便携版" if onefile else "MaoLog",
        "--add-data", f"{ASSETS};assets",
        "--icon", str(ICON),
        "--exclude-module", "winrt",
        "--exclude-module", "tinytag",
        "--exclude-module", "PyQt6.QtWebEngineWidgets",
        "--exclude-module", "PyQt6.QtWebEngineCore",
        "--exclude-module", "PyQt6.QtWebEngineQuick",
        "--exclude-module", "PyQt6.QtQuick",
        "--exclude-module", "PyQt6.QtQml",
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
    ]
    if onefile:
        cmd.append("--onefile")
    cmd.append(str(ROOT / "main.py"))

    mode_name = "单文件便携版" if onefile else "文件夹版"
    print(f"开始打包【{mode_name}】…（不含 QtWebEngine，几分钟内完成）")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("打包失败，看上面 PyInstaller 的输出")
        return result.returncode

    if onefile:
        target_path = ROOT / "dist" / "MaoLog_便携版.exe"
        print(f"\n完成 -> {target_path}")
        print("独立的单个 exe 文件，随意复制到桌面或 U 盘即可双击运行，首次启动会在同级目录建立 data/")
    else:
        target_path = ROOT / "dist" / "MaoLog" / "MaoLog.exe"
        print(f"\n完成 -> {target_path}")
        print("把这个文件夹整体拷走就能运行，首次启动会在同级目录建 data/")
    return 0


if __name__ == "__main__":
    is_onefile = "--onefile" in sys.argv
    sys.exit(build(onefile=is_onefile))
