"""存储工具模块：目录、原子 JSON 读写、safe_id。无任何业务。

每个模块从 `ctx.storage.own(__file__)` 拿自己的数据目录；
本模块只提供能力，不认识任何模块的名字。
"""
from __future__ import annotations

from .private import _files, _idem, _panel


def setup(ctx):
    """装配入口：把存储面板挂到 ctx.storage，并挂上幂等台账的四个原语。"""
    ok = _panel.setup(ctx)
    _idem.register(ctx)
    return ok


def ensure_dir(path):
    return _files.ensure_dir(path)


def write_text_atomic(path, text):
    return _files.write_text_atomic(path, text)


def read_text(path):
    return _files.read_text(path)


def write_text(path, text):
    return _files.write_text(path, text)


def safe_id(text):
    return _files.safe_id(text)
