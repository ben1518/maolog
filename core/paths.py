"""运行时资源定位：源码运行和 PyInstaller 打包后都能找到 assets/。

为什么需要这个文件：
- 源码运行时，assets 在仓库根目录，`Path(__file__).parent.parent / "assets"` 就对。
- 打包后 PyInstaller 把 `--add-data assets;assets` 解到 `sys._MEIPASS/assets`，
  而这个临时目录和 exe 所在目录不是同一个地方，`__file__` 也不在预期的层级。
- 配置、截图、数据库这些**要写入**的东西不能放 `_MEIPASS`（退出即删），
  必须放 exe 同级的 data/，所以两类目录要分开算。
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """只读资源（assets/）的根目录。"""
    if is_frozen():
        # PyInstaller 6.x 用 _MEIPASS 指向解包目录
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """可写数据（data/）的根目录。

    打包后放在 exe 同级，用户能直接看到截图和配置；
    源码运行时放仓库根目录，和现在保持一致。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def asset_dir() -> Path:
    return resource_root() / "assets"


def resource_path(*parts: str) -> Path:
    """拼一个只读资源的绝对路径。"""
    return asset_dir().joinpath(*parts)
