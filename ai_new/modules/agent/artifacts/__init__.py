"""交付件模块：分层路径与读取成形。落盘/取盘在 artifacts-* 需求里。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    for name, fn in [
        ("artifacts.base", _pure.base),
        ("artifacts.rel", _pure.rel),
        ("artifacts.written", _pure.written),
        ("artifacts.viewed", _pure.viewed),
        ("artifacts.decode", _pure.decode),
        ("artifacts.screen", _pure.screen),
        ("artifacts.stats", _pure.statsp),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="artifacts")
    ctx.api.register("artifacts.save", _route_save, "写交付件：分层→算路径→文本/二进制落盘→回执",
                     module="artifacts")
    for name, desc, demand in [
        ("artifact_write", "把交付件写到指定层（ticket/project/public）", "artifacts-write"),
        ("artifact_read", "读取交付件（只读）", "artifacts-read"),
    ]:
        ctx.tools.register_demand(name, desc, [
            {"name": "layer", "type": "string", "desc": "public/project/ticket", "required": False},
            {"name": "path", "type": "string", "desc": "相对路径", "required": True},
            {"name": "content", "type": "string", "desc": "写入内容", "required": False},
            {"name": "project", "type": "string", "desc": "project/ticket 层必填", "required": False},
            {"name": "ticket", "type": "string", "desc": "ticket 层必填", "required": False},
        ], demand=demand, module="artifacts")
    return True


def _route_save(ctx, payload):
    pid = ctx.api.call("store.id", {"value": payload.get("project")}, caller=None)
    tid = ctx.api.call("store.id", {"value": payload.get("ticket")}, caller=None)
    base = ctx.api.call("artifacts.base", {
        "layer": payload.get("layer"),
        "project": pid.get("id"), "ticket": tid.get("id")}, caller=None)
    if not base.get("ok"):
        return base
    rel = ctx.api.call("artifacts.rel", {"base": base.get("base"),
        "path": payload.get("path")}, caller=None)
    if not rel.get("ok"):
        return rel
    content = payload.get("content") or ""
    if payload.get("encoding") == "base64":
        hx = ctx.api.call("codec.hex_from_base64", {"text": content}, caller=None)
        w = ctx.api.call("store.write_bytes", {"module": "agent/artifacts",
            "path": rel.get("path"), "hex": hx.get("hex")}, caller=None)
    else:
        w = ctx.api.call("store.write_text", {"module": "agent/artifacts",
            "path": rel.get("path"), "text": content}, caller=None)
    return ctx.api.call("artifacts.written", {"path": rel.get("path"),
        "size": w.get("size"), "layer": payload.get("layer")}, caller=None)
