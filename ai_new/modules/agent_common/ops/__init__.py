"""运维模块：总览、记录、日志的纯计算。读写走 store 需求。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    for name, fn in [
        ("ops.assemble", _pure.assemble),
        ("ops.record", _pure.record),
        ("ops.events", _pure.events),
        ("ops.tail", _pure.tail),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="ops")
    return True
