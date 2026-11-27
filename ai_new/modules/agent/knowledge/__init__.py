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
    ctx.api.register("knowledge.doc_meta", _route_doc_meta,
                     "只读：读文档版本元数据（版本/作者/更新时间/修订历史）；路径越界即拒",
                     module="knowledge")
    for name, fn in pairs:
        ctx.api.register(name, _as_handler(fn), module="knowledge")
    ctx.api.register("knowledge.save", _route_save, "写知识：归一→算路径→append/覆盖→回执", module="knowledge")
    # 读写分参：读/搜不暴露 content，避免模型误把只读工具当写口。
    read_params = [
        {"name": "layer", "type": "string", "desc": "public/project/ticket", "required": False},
        {"name": "name", "type": "string", "desc": "文档名（不含 .md）", "required": False},
        {"name": "project", "type": "string", "desc": "project 层必填", "required": False},
        {"name": "ticket", "type": "string", "desc": "ticket 层必填", "required": False},
    ]
    write_params = read_params + [
        {"name": "content", "type": "string", "desc": "写入内容", "required": True},
    ]
    search_params = read_params + [
        {"name": "query", "type": "string", "desc": "检索词", "required": False},
    ]
    ctx.tools.register_demand("knowledge_read", "读一层知识文档",
                              read_params, demand="knowledge-read", module="knowledge")
    ctx.tools.register_demand("knowledge_write", "写知识总结（不是交付件）",
                              write_params, demand="knowledge-write", module="knowledge")
    ctx.tools.register_demand("knowledge_search", "按关键词搜知识",
                              search_params, demand="knowledge-search", module="knowledge")
    return True


def _cfg(ctx, key):
    row = ctx.api.call("config.get", {"key": key}, caller=None)
    return row.get("value")


def _route_save(ctx, payload):
    tpl = _msg_tpl(ctx)
    paths = _cfg_paths(ctx)
    tax = _cfg(ctx, "taxonomy") or {}
    layer = payload.get("layer") or "public"
    pid = ctx.api.call("store.id", {"value": payload.get("project")}, caller=None)
    tid = ctx.api.call("store.id", {"value": payload.get("ticket")}, caller=None)
    scope = ctx.api.call("knowledge.scope", {
        "layer": layer,
        "project": pid.get("id"),
        "ticket": tid.get("id"), "paths": paths, "tpl": tpl}, caller=None)
    if not scope.get("ok"):
        return scope
    nid = ctx.api.call("store.id", {"value": payload.get("name")}, caller=None)
    doc = ctx.api.call("knowledge.doc", {"prefix": scope.get("prefix"),
        "name": nid.get("id"), "paths": paths, "tpl": tpl}, caller=None)
    if not doc.get("ok"):
        return doc
    content = payload.get("content") or ""
    rel_path = doc.get("path") or ""
    now = ctx.api.call("clock.now", {}, caller=None)

    author = payload.get("author") or ""
    # 版本令牌：优先 base_version，回退 version；force 为显式覆盖，跳过令牌比对（仍记修订）。
    token = payload.get("base_version")
    if token is None:
        token = payload.get("version")
    force = bool(payload.get("force"))
    mode = payload.get("mode") or "overwrite"

    # 正文落盘走文档修订闭环：跨进程锁内完成「读版本 → 令牌强校验 → 落正文 → 记修订历史」。
    # 令牌不符由 store.doc_revision 回 409 冲突，不落正文、不静默覆盖。
    rev = ctx.api.call("store.doc_revision", {
        "module": "agent/knowledge", "path": rel_path, "mode": mode,
        "text": ("\n\n" + content) if mode == "append" else content,
        "author": author, "version": token, "force": force}, caller=None)

    if not rev.get("ok"):
        code = rev.get("code") or "conflict"
        conflict_tpl = tpl.get("conflict") or ""
        token_required_tpl = tpl.get("token_required") or ""
        hint_tpl = tpl.get("conflict_hint") or ""
        tpl_text = token_required_tpl if code == "token_required" else conflict_tpl
        return {"ok": False, "code": code, "status": 409,
                "current_version": rev.get("current_version"),
                "current_author": rev.get("current_author"),
                "current_updated": rev.get("current_updated", ""),
                "token": token,
                "requester": {"version": token, "author": author},
                "forced": force,
                "error": tpl_text.format(
                    current_version=rev.get("current_version"),
                    current_author=rev.get("current_author"),
                    token=token) if tpl_text else "",
                "hint": hint_tpl}

    entry = _pure.entry({
        "path": rel_path,
        "source": tax.get("knowledge_source") or "llm",
        "layer": layer,
        "project": pid.get("id") or "",
        "ticket": tid.get("id") or "",
        "name": rel_path.rsplit("/", 1)[-1],
        "now": now.get("iso"),
    })
    index_path = paths.get("index") or "index.yaml"
    old = ctx.api.call("store.read", {
        "module": "agent/knowledge", "path": index_path,
        "fallback": {"entries": []}}, caller=None)
    merged = _pure.index_upsert({
        "entries": (old.get("value") or {}).get("entries") or [],
        "entry": entry})
    effects = [{"kind": "write", "module": "agent/knowledge",
                "path": index_path, "value": merged}]
    view = ctx.api.call("knowledge.view", {"path": rel_path,
        "content": content}, caller=None)
    view["effects"] = effects
    view["revision"] = {"version": rev.get("version"), "author": rev.get("author"),
                         "updated": rev.get("updated"), "chars": rev.get("chars"),
                         "history": rev.get("history") or [], "forced": force}
    return view


def _route_doc_meta(ctx, payload):
    """只读：读文档版本元数据；先做越界校验，路径落在知识模块数据根之内才读。"""
    rel = str(payload.get("path") or "")
    chk = ctx.api.call("store.resolve_doc",
                       {"module": "agent/knowledge", "path": rel}, caller=None)
    if not chk.get("ok"):
        return chk
    meta_rel = rel[:-3] + ".meta.yaml" if rel.endswith(".md") else rel + ".meta.yaml"
    row = ctx.api.call("store.read", {
        "module": "agent/knowledge", "path": meta_rel,
        "fallback": {"version": 0, "author": "", "updated": "", "history": []}}, caller=None)
    meta = row.get("value") or {}
    return {"ok": True, "version": meta.get("version", 0),
            "author": meta.get("author", ""), "updated": meta.get("updated", ""),
            "history": meta.get("history") or []}


def _as_handler(fn):
    def handler(ctx, payload):
        payload = dict(payload or {})
        if "tpl" not in payload:
            payload["tpl"] = _msg_tpl(ctx)
        return fn(payload)
    return handler


def _msg_tpl(ctx):
    """消息模板表：知识模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent/knowledge", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def _cfg_paths(ctx):
    row = ctx.api.call("config.get", {"key": "knowledge.paths"}, caller=None)
    return row.get("value") or {}
