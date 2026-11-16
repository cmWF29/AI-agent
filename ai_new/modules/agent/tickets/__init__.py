"""工单模块：工单记录的纯计算。生命周期编排在 ticket-* 需求里。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    for name, fn in [
        ("tickets.newid", _pure.newid),
        ("tickets.build", _pure.build),
        ("tickets.validate_project", _pure.validate_project),
        ("tickets.threadp", _pure.threadp),
        ("tickets.view", _pure.view),
        ("tickets.screen", _pure.screen),
        ("tickets.roles", _pure.roles),
        ("tickets.note", _pure.note),
        ("tickets.bindrole", _pure.bindrole),
        ("tickets.bindpm", _pure.bindpm),
        ("tickets.bindchild", _pure.bindchild),
        ("tickets.closefin", _pure.closefin),
        ("tickets.pick", _pure.pick),
        ("tickets.files_filter", _pure.files_filter),
        ("tickets.err", _pure.err),
        ("tickets.stale", _pure.stale),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="tickets")
    return True
