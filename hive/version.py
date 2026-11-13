"""版本号：优先读仓库根目录的 VERSION 文件（watchdog 回退时靠 git 版本对齐）。"""
from __future__ import annotations

import os

__version__ = "0.1.0"


def _read_version_file():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.path.dirname(here), "VERSION"),
        os.path.join(here, "VERSION"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                v = f.read().strip()
            if v:
                return v
        except OSError:
            continue
    return None


_file_version = _read_version_file()
if _file_version:
    __version__ = _file_version
