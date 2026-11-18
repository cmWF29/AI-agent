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


def _cfg_paths(ctx):
    row = ctx.api.call("config.get", {"key": "artifacts.paths"}, caller=None)
    return row.get("value") or {}


def _msg_tpl(ctx):
    row = ctx.api.call("store.read", {
        "module": "agent/artifacts", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def _route_save(ctx, payload):
    paths = _cfg_paths(ctx)
    tpl = _msg_tpl(ctx)
    layer = payload.get("layer") or "ticket"
    pid_raw = payload.get("project")
    tid_raw = payload.get("ticket")
    if layer == "ticket":
        # 归属项目以工单记录为准，不采信模型传入的 project：漏填/错填时不能错位到 projects/item。
        tpaths = ctx.api.call("config.get", {"key": "tickets.paths"}, caller=None).get("value") or {}
        tr = tpaths.get("record") or ""
        row = ctx.api.call("store.read", {
            "module": "agent/tickets",
            "path": tr.format(id=tid_raw or "") if tr else (tid_raw or "")}, caller=None)
        rec = row.get("value")
        if rec and rec.get("project"):
            pid_raw = rec.get("project")
    pid = ctx.api.call("store.id", {"value": pid_raw}, caller=None)
    tid = ctx.api.call("store.id", {"value": tid_raw}, caller=None)
    base = ctx.api.call("artifacts.base", {
        "layer": layer,
        "project": pid.get("id"), "ticket": tid.get("id"),
        "paths": paths, "tpl": tpl}, caller=None)
    if not base.get("ok"):
        return base
    rel = ctx.api.call("artifacts.rel", {"base": base.get("base"),
        "path": payload.get("path"), "tpl": tpl}, caller=None)
    if not rel.get("ok"):
        return rel
    content = payload.get("content") or ""
    if payload.get("encoding") == "base64":
        hx = ctx.api.call("codec.hex_from_base64", {"text": content}, caller=None)
        effect = {"kind": "write_bytes", "module": "agent/artifacts",
                  "path": rel.get("path"), "hex": hx.get("hex")}
        size = len(str(hx.get("hex") or "")) // 2
    else:
        effect = {"kind": "write_text", "module": "agent/artifacts",
                  "path": rel.get("path"), "text": content}
        size = len(content.encode("utf-8"))
    out = ctx.api.call("artifacts.written", {"path": rel.get("path"),
        "size": size, "layer": layer}, caller=None)
    out["effects"] = [effect]
    return out
