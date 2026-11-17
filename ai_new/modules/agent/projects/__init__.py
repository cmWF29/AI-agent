"""项目模块：项目档案。只有纯函数，取数/落盘由需求完成。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    """装配入口：注册纯函数；组合逻辑在 demand_engine/data/demands/projects-*.json。"""
    for name, fn in [
        ("projects.build", _pure.build),
        ("projects.view", _pure.view),
        ("projects.present", _pure.present),
        ("projects.screen", _pure.screen),
        ("projects.tree", _pure.tree),
        ("projects.archive", _pure.archive),
        ("projects.missing", _pure.missing),
        ("projects.conflict", _pure.conflict),
        ("projects.deleted", _pure.deleted),
        ("projects.renamed", _pure.renamed),
    ]:
        ctx.api.register(name, _as_handler(fn), module="projects")
    ctx.api.register("projects.create", _route_create, "新建项目：归一→造档→查重→落盘→回执", module="projects")
    ctx.api.register("projects.remove", _route_remove, "删除项目：purge 真删，否则归档", module="projects")
    ctx.api.register("projects.rename", _route_rename, "项目改名：查重→迁档→工单引用改挂", module="projects")
    return True


def _route_create(ctx, payload):
    pid = ctx.api.call("store.id", {"value": payload.get("name")}, caller=None)
    now = ctx.api.call("clock.now", {}, caller=None)
    rec = ctx.api.call("projects.build", {
        "id": pid.get("id"), "name": payload.get("name"),
        "created": now.get("ts"), "default_backend": payload.get("default_backend")}, caller=None)
    ex = ctx.api.call("store.exists", {"module": "agent/projects",
        "path": pid.get("id") + ".yaml"}, caller=None)
    if ex.get("exists"):
        return ctx.api.call("projects.conflict", {"id": pid.get("id")}, caller=None)
    view = ctx.api.call("projects.view", {"rec": rec}, caller=None)
    view["effects"] = [{"kind": "write", "module": "agent/projects",
                        "path": pid.get("id") + ".yaml", "value": rec}]
    return view


def _purge_tickets(ctx, pid):
    """真删项目时清掉它名下的工单：工单必属项目，不能留指向空项目的孤儿单。

    返回 (effects, 被删工单 id 集合)；会话只记 ticket 不记 project，要靠这组 id 回扫。
    """
    effects = []
    ticket_ids = []
    listed = ctx.api.call("store.glob", {
        "module": "agent/tickets", "pattern": "tickets/T-*/ticket.yaml"}, caller=None)
    for rel in listed.get("items") or []:
        segs = str(rel).split("/")
        if len(segs) != 3:
            continue
        row = ctx.api.call("store.read", {
            "module": "agent/tickets", "path": rel}, caller=None)
        if ((row.get("value") or {}).get("project")) != pid:
            continue
        ticket_ids.append(segs[1])
        effects.append({"kind": "remove_dir", "module": "agent/tickets",
                        "path": "tickets/%s" % segs[1]})
    return effects, ticket_ids


def _purge_sessions(ctx, ticket_ids):
    """清掉挂在被删工单上的 PM/角色会话；会话记录只记 ticket，按工单集合匹配。"""
    if not ticket_ids:
        return []
    ids = set(ticket_ids)
    effects = []
    listed = ctx.api.call("store.glob", {
        "module": "agent/sessions", "pattern": "sessions/*.yaml"}, caller=None)
    for rel in listed.get("items") or []:
        row = ctx.api.call("store.read", {
            "module": "agent/sessions", "path": rel}, caller=None)
        if (row.get("value") or {}).get("ticket") in ids:
            effects.append({"kind": "remove", "module": "agent/sessions", "path": rel})
    return effects


def _purge_ticket_knowledge(ctx, ticket_ids):
    """清掉被删工单的 ticket 层知识；该层前缀是 tickets/<tid>，不在项目知识树下。"""
    return [{"kind": "remove_dir", "module": "agent/knowledge",
             "path": "tickets/%s" % tid} for tid in ticket_ids]


def _purge_project_tree(ctx, module, pid):
    """清掉项目在产物/知识层的整棵前缀目录；目录不存在时 remove_dir 自报未删，不报错。"""
    return [{"kind": "remove_dir", "module": module, "path": "projects/%s" % pid}]


def _route_remove(ctx, payload):
    pid = ctx.api.call("store.id", {"value": payload.get("id")}, caller=None)
    row = ctx.api.call("store.read", {"module": "agent/projects",
        "path": pid.get("id") + ".yaml"}, caller=None)
    if payload.get("purge") is True:
        ticket_effects, ticket_ids = _purge_tickets(ctx, pid.get("id"))
        effects = list(ticket_effects)
        effects += _purge_sessions(ctx, ticket_ids)
        effects += _purge_ticket_knowledge(ctx, ticket_ids)
        effects += _purge_project_tree(ctx, "agent/artifacts", pid.get("id"))
        effects += _purge_project_tree(ctx, "agent/knowledge", pid.get("id"))
        effects.append({"kind": "remove", "module": "agent/projects",
                        "path": pid.get("id") + ".yaml"})
        out = ctx.api.call("projects.deleted", {"id": pid.get("id")}, caller=None)
        out["effects"] = effects
        return out
    now = ctx.api.call("clock.now", {}, caller=None)
    rec = ctx.api.call("projects.archive", {"rec": row.get("value"),
        "now": now.get("ts")}, caller=None)
    view = ctx.api.call("projects.view", {"rec": rec}, caller=None)
    view["effects"] = [{"kind": "write", "module": "agent/projects",
                        "path": pid.get("id") + ".yaml", "value": rec}]
    return view


def _route_rename(ctx, payload):
    """改名闭环：定位旧档→查重→造新档→落新档→删旧档→工单引用改挂。分岔全在能力内部。"""
    old = ctx.api.call("store.id", {"value": payload.get("id")}, caller=None).get("id")
    row = ctx.api.call("store.read", {"module": "agent/projects",
        "path": old + ".yaml"}, caller=None)
    if row.get("value") is None:
        return ctx.api.call("projects.missing", {"id": old}, caller=None)
    new_id = ctx.api.call("store.id", {"value": payload.get("name")}, caller=None).get("id")
    if new_id != old:
        ex = ctx.api.call("store.exists", {"module": "agent/projects",
            "path": new_id + ".yaml"}, caller=None)
        if ex.get("exists"):
            return ctx.api.call("projects.conflict", {"id": new_id}, caller=None)
    now = ctx.api.call("clock.now", {}, caller=None)
    rec = ctx.api.call("projects.renamed", {
        "rec": row.get("value"), "id": new_id, "name": payload.get("name"),
        "default_backend": payload.get("default_backend"),
        "now": now.get("ts")}, caller=None)
    effects = [{"kind": "write", "module": "agent/projects",
                "path": new_id + ".yaml", "value": rec}]
    if new_id != old:
        effects.append({"kind": "remove", "module": "agent/projects",
                        "path": old + ".yaml"})
        moved = ctx.api.call("tickets.rebind", {"from": old, "to": new_id,
            "now": now.get("ts")}, caller=None)
        effects.extend((moved or {}).get("effects") or [])
    view = ctx.api.call("projects.view", {"rec": rec}, caller=None)
    view["effects"] = effects
    return view


def _as_handler(fn):
    """装配适配：纯函数只收 payload，路由协议仍是 fn(ctx, payload)。"""
    return lambda ctx, payload: fn(payload)
