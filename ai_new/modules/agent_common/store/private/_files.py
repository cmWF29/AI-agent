"""纯函数文件工具。"""
from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path


def replace_file(src, dst, attempts=50):
    """原子改名；Windows 上杀软/读句柄短暂占用目标时退避重试，不把并发放大成写失败。"""
    delay = 0.002
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or i + 1 >= attempts:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.05)


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return Path(path)


def write_text_atomic(path, text):
    """先写临时文件再改名：断电/并发都不会留下半个文件。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        replace_file(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return p


def write_bytes_atomic(path, data):
    """二进制原子写：临时文件 + 原子改名，掉电不留半个文件。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        replace_file(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return p


def read_text(path):
    return Path(path).read_text(encoding="utf-8")


def write_text(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def safe_id(text):
    t = (text or "").strip().lower()
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff._-]+", "-", t)
    t = re.sub(r"-+", "-", t).strip(".-")
    return t or "item"


def write_bytes(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def append_text_atomic(path, text):
    """追加写走「读全量 → 临时文件 → 原子改名」：不留半截文件。

    这只防半截落盘，不替代互斥锁；并发写同一文档的临界区要由调用方经
    文档级锁包住。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(existing)
            f.write(text)
        replace_file(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return p


def remove_tree(path):
    import shutil
    shutil.rmtree(str(path), ignore_errors=True)


def pack(dest, entries):
    """entries: [(目录, 归档前缀)]；把目录内容压进 dest（zip）。"""
    import zipfile
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(dest), "w", zipfile.ZIP_DEFLATED) as zf:
        for root, arc in entries:
            root = Path(root)
            if not root.is_dir():
                continue
            for item in sorted(root.rglob("*")):
                if item.is_file():
                    rel = item.relative_to(root).as_posix()
                    zf.write(str(item), (arc.rstrip("/") + "/" + rel).lstrip("/"))
    return dest


def modules_root():
    """仓库里的 modules 根（从本文件往上找）。"""
    for parent in Path(__file__).resolve().parents:
        if parent.name == "modules":
            return parent
    raise ValueError("找不到 modules 根")
