"""频道模块：消息的纯计算（拼、取窗、算游标）。读写与通知在 channel-* 需求里。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    ctx.hooks.point("channel.posted", ("channel", "role", "message"))
    for name, fn in [
        ("channel.split", _pure.split),
        ("channel.make", _pure.make),
        ("channel.tail", _pure.tail),
        ("channel.since", _pure.since),
        ("channel.channels", _pure.channels),
        ("channel.bad", _pure.bad),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="channel")
    return True
