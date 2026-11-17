"""知识模块：三层知识（public/project/ticket）的形状计算。

取数、落盘、检索范围全在需求里（`knowledge-*`）；本模块只做纯计算。
"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    """装配入口：注册纯函数。"""
    pairs = [
        ("knowledge.scope", _pure.scope),
        ("knowledge.doc", _pure.doc),
        ("knowledge.view", _pure.view),
        ("knowledge.present", _pure.present),
        ("knowledge.screen", _pure.screen),
        ("knowledge.overview", _pure.overview),
        ("knowledge.index", _pure.index),
        ("knowledge.search", _pure.search),
        ("knowledge.compose", _pure.compose),
        ("knowledge.removed", _pure.removed),
        ("knowledge.project_dir", _pure.project_dir),
        ("knowledge.project_prefix", _pure.project_prefix),
    ]
    for name, fn in pairs:
        ctx.api.register(name, _as_handler(fn), module="knowledge")
    ctx.api.register("knowledge.save", _route_save, "写知识：归一→算路径→append/覆盖→回执", module="knowledge")
    for name, desc, demand in [
        ("knowledge_read", "读一层知识文档", "knowledge-read"),
        ("knowledge_write", "写知识总结（不是交付件）", "knowledge-write"),
        ("knowledge_search", "按关键词搜知识", "knowledge-search"),
    ]:
        ctx.tools.register_demand(name, desc, [
            {"name": "layer", "type": "string", "desc": "public/project/ticket", "required": False},
            {"name": "name", "type": "string", "desc": "文档名（不含 .md）", "required": False},
            {"name": "project", "type": "string", "desc": "project 层必填", "required": False},
            {"name": "ticket", "type": "string", "desc": "ticket 层必填", "required": False},
            {"name": "content", "type": "string", "desc": "写入内容", "required": False},
            {"name": "query", "type": "string", "desc": "检索词", "required": False},
        ], demand=demand, module="knowledge")
    return True


def _route_save(ctx, payload):
    pid = ctx.api.call("store.id", {"value": payload.get("project")}, caller=None)
    tid = ctx.api.call("store.id", {"value": payload.get("ticket")}, caller=None)
    scope = ctx.api.call("knowledge.scope", {
        "layer": payload.get("layer"),
        "project": pid.get("id"),
        "ticket": tid.get("id")}, caller=None)
    if not scope.get("ok"):
        return scope
    nid = ctx.api.call("store.id", {"value": payload.get("name")}, caller=None)
    doc = ctx.api.call("knowledge.doc", {"prefix": scope.get("prefix"),
        "name": nid.get("id")}, caller=None)
    if not doc.get("ok"):
        return doc
    content = payload.get("content") or ""
    if payload.get("mode") == "append":
        effects = [{"kind": "append_text", "module": "agent/knowledge",
                    "path": doc.get("path"), "text": "\n\n" + content}]
    else:
        effects = [{"kind": "write_text", "module": "agent/knowledge",
                    "path": doc.get("path"), "text": content}]
    view = ctx.api.call("knowledge.view", {"path": doc.get("path"),
        "content": content}, caller=None)
    view["effects"] = effects
    return view


def _as_handler(fn):
    return lambda ctx, payload: fn(payload)
