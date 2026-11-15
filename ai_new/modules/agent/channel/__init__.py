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

    def _watch(ctx, payload):
        """SSE 轮询门面：不自己读盘，按游标委托 channel-since 需求回 {items, cursor}。"""
        cursor = payload.get("cursor") or 0
        res = ctx.demand_engine.run_callable("channel-since", {
            "channel": payload.get("channel") or "default",
            "cursor": cursor,
        })
        return res.get("result") or {"items": [], "cursor": cursor}

    ctx.api.register("channel.watch", _watch, module="channel", stream=True)
    return True
