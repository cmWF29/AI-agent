"""运维模块：总览、记录、日志的纯计算。读写走 store 需求。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    for name, fn in [
        ("ops.assemble", _pure.assemble),
        ("ops.record", _pure.record),
        ("ops.events", _pure.events),
        ("ops.spans_events", _pure.spans_events),
        ("ops.merge_events", _pure.merge_events),
        ("ops.tail", _pure.tail),
        ("ops.export_path", _pure.export_path),
        ("ops.log_line", _pure.log_line),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="ops")
    return True
