"""链路追踪模块：开/关 span 与按 trace 查询。

实现全在 private/；对外只有 setup。
"""
from __future__ import annotations

from .private import _trace


def setup(ctx):
    return _trace.setup(ctx)
