"""频道模块：消息的纯计算（拼、取窗、算游标）。读写与通知在 channel-* 需求里。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    # 通知型：回复生成耗时才长，不能在发消息的请求里等它
    ctx.hooks.point("channel.posted", ("channel", "role", "message"), defer=True)
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
    ctx.api.register("channel.reply", _route_reply, "网页消息→对话→回复写回同一频道", module="channel")

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


def _cfg_paths(ctx):
    row = ctx.api.call("config.get", {"key": "logs.paths"}, caller=None)
    return row.get("value") or {}


def _read_rows(ctx, channel_id):
    """读整频道并逐行解码：外层只有一次顺序读，逐行解码是能力内部的事。"""
    t = _cfg_paths(ctx).get("channel") or ""
    txt = ctx.api.call("store.read_text", {
        "module": "agent/logs",
        "path": t.format(id=channel_id or "") if t else (channel_id or "")}, caller=None)
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
    t = _cfg_paths(ctx).get("channel") or ""
    rel_path = t.format(id=cid.get("id") or "") if t else (cid.get("id") or "")
    body_effect = {"kind": "append_text", "module": "agent/logs",
                   "path": rel_path,
                   "text": (enc.get("text") or "") + "\n"}
    log_rec = ctx.api.call("logs.record", {
        "path": rel_path, "kind": "channel", "layer": "public",
        "project": "", "ticket": "", "name": cid.get("id")}, caller=None)
    effects = [body_effect] + (log_rec.get("effects") or [])
    posted = {"channel": rec.get("channel"), "role": rec.get("role"),
              "content": rec.get("content")}
    if getattr(ctx, "hooks", None) is not None:
        ctx.hooks.emit("channel.posted", posted)
    rec["effects"] = effects
    return rec


def _route_read_since(ctx, payload):
    cid = ctx.api.call("store.id", {"value": payload.get("channel")}, caller=None)
    rows = _read_rows(ctx, cid.get("id"))
    return ctx.api.call("channel.since", {"rows": rows, "cursor": payload.get("cursor")},
                        caller=None)


def _route_read_tail(ctx, payload):
    cid = ctx.api.call("store.id", {"value": payload.get("channel")}, caller=None)
    rows = _read_rows(ctx, cid.get("id"))
    default_limit = payload.get("default_limit")
    if default_limit is None:
        default_limit = ctx.api.call("config.get", {"key": "channel.default_limit"},
                                     caller=None).get("value")
    max_limit = payload.get("max_limit")
    if max_limit is None:
        max_limit = ctx.api.call("config.get", {"key": "channel.max_limit"},
                                 caller=None).get("value")
    return ctx.api.call("channel.tail", {"channel": cid.get("id"), "rows": rows,
                                        "limit": payload.get("limit"),
                                        "default_limit": default_limit,
                                        "max_limit": max_limit}, caller=None)


def _msg_tpl(ctx):
    """消息模板表：频道模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent/channel", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


async def _route_reply(ctx, payload):
    """网页回复闭环：只回复用户消息，取历史、跑对话编排、把结果写回同一频道。

    协程轨：llm-chat 直连事件循环 await，read_tail/post 同步路由经执行器桥接。
    """
    if payload.get("role") != "user":
        return {"ok": True, "skipped": True}
    history = await ctx.api.acall("channel.read_tail", {
        "channel": payload.get("channel")}, caller=None)
    messages = list(history.get("messages") or [])
    messages.append({"role": "user", "content": payload.get("content")})
    reply = await ctx.runtime.acall("llm-chat", {"messages": messages})
    answer = reply or {}
    if answer.get("ok") is False:
        t = _msg_tpl(ctx).get("llm_failed") or ""
        err = answer.get("error") or ""
        role, content = "system", t.format(error=err) if t else ""
    else:
        role, content = "assistant", answer.get("content") or ""
    return await ctx.api.acall("channel.post", {
        "channel": payload.get("channel"), "role": role, "content": content}, caller=None)

