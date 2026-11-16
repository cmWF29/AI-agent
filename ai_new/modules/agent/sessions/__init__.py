"""会话模块：会话记录与运行的纯计算。读写、驱动、等待都在 session-* 需求里。"""
from __future__ import annotations

from .private import _pure, _run_pure


def setup(ctx):
    pairs = [
        ("sessions.build", _pure.build),
        ("sessions.view", _pure.view),
        ("sessions.present", _pure.present),
        ("sessions.screen", _pure.screen),
        ("sessions.gone", _pure.gone),
        ("sessions.compact", _pure.compactp),
        ("sessions.appendmsg", _run_pure.appendmsg),
        ("sessions.mark", _run_pure.mark),
        ("sessions.finish", _run_pure.finish),
        ("sessions.reply", _run_pure.reply),
        ("sessions.statsp", _run_pure.statsp),
    ]
    for name, fn in pairs:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="sessions")
    return True
