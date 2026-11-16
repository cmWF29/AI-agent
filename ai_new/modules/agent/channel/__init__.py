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
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="channel")
    ctx.api.register("channel.post", _route_post, "发消息：读历史→拼消息→追加→emit", module="channel")
    ctx.api.register("channel.read_since", _route_read_since, "按游标取新消息（遍历在能力内）", module="channel")
    ctx.api.register("channel.read_tail", _route_read_tail, "取最近 N 条（遍历在能力内）", module="channel")

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


def _read_rows(ctx, channel_id):
    """读整频道并逐行解码：外层只有一次顺序读，逐行解码是能力内部的事。"""
    txt = ctx.api.call("store.read_text", {
        "module": "agent/channel",
        "path": "channels/%s.jsonl" % (channel_id or "")}, caller=None)
    split = ctx.api.call("channel.split", {"text": txt.get("value")}, caller=None)
    rows = []
    for line in split.get("lines") or []:
        obj = ctx.api.call("codec.json_decode", {"text": line}, caller=None)
        if obj.get("ok") is not False:
            rows.append(obj.get("value"))
    return rows


def _route_post(ctx, payload):
    cid = ctx.api.call("store.id", {"value": payload.get("channel")}, caller=None)
    rows = _read_rows(ctx, cid.get("id"))
    now = ctx.api.call("clock.now", {}, caller=None)
    rec = ctx.api.call("channel.make", {
        "channel": cid.get("id"), "role": payload.get("role"),
        "content": payload.get("content"), "rows": rows, "ts": now.get("ts")}, caller=None)
    enc = ctx.api.call("codec.json_encode", {"value": rec}, caller=None)
    ctx.api.call("store.append_text", {
        "module": "agent/channel",
        "path": "channels/%s.jsonl" % (cid.get("id") or ""),
        "text": (enc.get("text") or "") + "\n"}, caller=None)
    posted = {"channel": rec.get("channel"), "role": rec.get("role"),
              "content": rec.get("content")}
    if getattr(ctx, "hooks", None) is not None:
        ctx.hooks.emit("channel.posted", posted)
    return rec


def _route_read_since(ctx, payload):
    cid = ctx.api.call("store.id", {"value": payload.get("channel")}, caller=None)
    rows = _read_rows(ctx, cid.get("id"))
    return ctx.api.call("channel.since", {"rows": rows, "cursor": payload.get("cursor")},
                        caller=None)


def _route_read_tail(ctx, payload):
    cid = ctx.api.call("store.id", {"value": payload.get("channel")}, caller=None)
    rows = _read_rows(ctx, cid.get("id"))
    return ctx.api.call("channel.tail", {"channel": cid.get("id"), "rows": rows,
                                        "limit": payload.get("limit")}, caller=None)

