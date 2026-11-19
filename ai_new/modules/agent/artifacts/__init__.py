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
    ctx.api.register("artifacts.group", _as_handler(_pure.group),
                     "文档清单按公共/项目/工单三级分组成形；纯分组不读正文", module="artifacts")
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
            {"name": "doc_kind", "type": "string", "desc": "artifact=交付件 / non_artifact=非交付件", "required": False},
            {"name": "source", "type": "string", "desc": "llm / system / script", "required": False},
        ], demand=demand, module="artifacts")
    return True


def _cfg_paths(ctx):
    row = ctx.api.call("config.get", {"key": "artifacts.paths"}, caller=None)
    return row.get("value") or {}


def _msg_tpl(ctx):
    row = ctx.api.call("store.read", {
        "module": "agent/artifacts", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def _as_handler(fn):
    def handler(ctx, payload):
        payload = dict(payload or {})
        if "tpl" not in payload:
            payload["tpl"] = _msg_tpl(ctx)
        return fn(payload)
    return handler


def _cfg(ctx, key):
    row = ctx.api.call("config.get", {"key": key}, caller=None)
    return row.get("value")


def _route_save(ctx, payload):
    paths = _cfg_paths(ctx)
    tpl = _msg_tpl(ctx)
    tax = _cfg(ctx, "taxonomy") or {}
    layer = payload.get("layer") or "ticket"
    cls = _pure.classify({
        "doc_kind": payload.get("doc_kind"),
        "source": payload.get("source"),
        "doc_kinds": tax.get("doc_kinds") or [],
        "sources": tax.get("sources") or [],
        "tpl": tpl})
    if not cls.get("ok"):
        return cls
    doc_kind, source = cls.get("doc_kind"), cls.get("source")
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
    rel_path = rel.get("path") or ""
    if payload.get("encoding") == "base64":
        hx = ctx.api.call("codec.hex_from_base64", {"text": content}, caller=None)
        effect = {"kind": "write_bytes", "module": "agent/artifacts",
                  "path": rel_path, "hex": hx.get("hex")}
        size = len(str(hx.get("hex") or "")) // 2
    else:
        effect = {"kind": "write_text", "module": "agent/artifacts",
                  "path": rel_path, "text": content}
        size = len(content.encode("utf-8"))
    now = ctx.api.call("clock.now", {}, caller=None)
    entry = _pure.entry({
        "path": rel_path,
        "doc_kind": doc_kind,
        "source": source,
        "layer": layer,
        "project": pid.get("id") or "",
        "ticket": tid.get("id") or "",
        "name": rel_path.rsplit("/", 1)[-1],
        "now": now.get("iso"),
    })
    index_path = paths.get("index") or "index.yaml"
    old = ctx.api.call("store.read", {
        "module": "agent/artifacts", "path": index_path,
        "fallback": {"entries": []}}, caller=None)
    merged = _pure.index_upsert({
        "entries": (old.get("value") or {}).get("entries") or [],
        "entry": entry})
    out = ctx.api.call("artifacts.written", {"path": rel_path,
        "size": size, "layer": layer}, caller=None)
    out["doc_kind"] = doc_kind
    out["source"] = source
    out["effects"] = [effect, {"kind": "write", "module": "agent/artifacts",
                               "path": index_path, "value": merged}]
    return out
