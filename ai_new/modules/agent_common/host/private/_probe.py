"""机器读数实现（Linux /proc，Windows 退化到 psutil 缺省值）。"""
from __future__ import annotations

import os
import sys
import shutil
import importlib.util


# pip 规范名 → Python 导入名对照：安装清单写 pip 名，探测要按导入名 find_spec。
# key 已按 PEP 503 归一化（小写，-/_/. 统一为 -）；未收录的包名兜底连字符转下划线。
_IMPORT_MAP = {
    "pymupdf": "fitz",
    "python-docx": "docx",
    "python-pptx": "pptx",
    "python-dateutil": "dateutil",
    "python-multipart": "multipart",
    "beautifulsoup4": "bs4",
    "pyyaml": "yaml",
    "pillow": "PIL",
    "scikit-learn": "sklearn",
    "opencv-python": "cv2",
    "opencv-python-headless": "cv2",
}


def _norm_pkg(name):
    """pip 名归一化：小写，连字符/下划线/点统一成连字符，便于对照表查找。"""
    out = []
    for ch in str(name or "").strip().lower():
        out.append("-" if ch in ("-", "_", ".") else ch)
    return "".join(out)


def _import_name(pkg):
    """pip 规范名 → 探测用的导入名；对照表优先，未收录则连字符转下划线兜底。"""
    raw = str(pkg or "").strip()
    if not raw:
        return raw
    mapped = _IMPORT_MAP.get(_norm_pkg(raw))
    return mapped or raw.replace("-", "_")


def _mem():
    total = free = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    free = int(line.split()[1])
    except OSError:
        pass
    if total is None:
        try:  # 非 Linux：用 os.sysconf 的近似读数，拿不到就给空
            pages = os.sysconf("SC_PHYS_PAGES")
            avail = os.sysconf("SC_AVPHYS_PAGES")
            size = os.sysconf("SC_PAGE_SIZE")
            total, free = pages * size / 1024, avail * size / 1024
        except (ValueError, OSError, AttributeError):
            return {"total_mb": None, "free_mb": None}
    return {"total_mb": round(total / 1024, 1),
            "free_mb": round((free or 0) / 1024, 1)}


def _disk(root):
    try:
        du = shutil.disk_usage(str(root))
    except OSError:
        return {"total_gb": None, "free_gb": None}
    return {"total_gb": round(du.total / 1e9, 1), "free_gb": round(du.free / 1e9, 1)}


def _load():
    try:
        return {"load1": os.getloadavg()[0]}
    except (OSError, AttributeError):
        return {"load1": None}


def info(ctx):
    return {"ok": True, **_mem(), **_disk(ctx.root), **_load()}


def env(name):
    """读一个环境变量：部署差异是主机事实，不是某个模块的知识。"""
    return {"ok": True, "name": str(name or ""), "value": os.environ.get(str(name or ""))}


def which(ctx, payload):
    """探测一个 CLI 命令是否在 PATH：命令可用性是主机事实，归 host。"""
    cmd = str((payload or {}).get("name") or "").strip()
    found = bool(cmd) and shutil.which(cmd) is not None
    return {"ok": True, "name": cmd, "found": found}


def importable(ctx, payload):
    """探测一个 Python 包当前解释器能否导入；pip 名先对照成导入名再 find_spec。"""
    pkg = str((payload or {}).get("name") or "").strip()
    probe = _import_name(pkg)
    ok = False
    if probe:
        try:
            ok = importlib.util.find_spec(probe) is not None
        except (ImportError, ValueError, ModuleNotFoundError, AttributeError):
            ok = False
    return {"ok": True, "name": pkg, "importable": ok}


def executable(ctx):
    """当前解释器路径：装包要用同一个 Python，避免装进别的环境。"""
    return {"ok": True, "path": sys.executable}
