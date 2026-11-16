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
    ctx.api.call("store.write", {"module": "agent/projects",
        "path": pid.get("id") + ".yaml", "value": rec}, caller=None)
    return ctx.api.call("projects.view", {"rec": rec}, caller=None)


def _route_remove(ctx, payload):
    pid = ctx.api.call("store.id", {"value": payload.get("id")}, caller=None)
    row = ctx.api.call("store.read", {"module": "agent/projects",
        "path": pid.get("id") + ".yaml"}, caller=None)
    if payload.get("purge") is True:
        ctx.api.call("store.remove", {"module": "agent/projects",
            "path": pid.get("id") + ".yaml"}, caller=None)
        return ctx.api.call("projects.deleted", {"id": pid.get("id")}, caller=None)
    now = ctx.api.call("clock.now", {}, caller=None)
    rec = ctx.api.call("projects.archive", {"rec": row.get("value"),
        "now": now.get("ts")}, caller=None)
    ctx.api.call("store.write", {"module": "agent/projects",
        "path": pid.get("id") + ".yaml", "value": rec}, caller=None)
    return ctx.api.call("projects.view", {"rec": rec}, caller=None)


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
    ctx.api.call("store.write", {"module": "agent/projects",
        "path": new_id + ".yaml", "value": rec}, caller=None)
    if new_id != old:
        ctx.api.call("store.remove", {"module": "agent/projects",
            "path": old + ".yaml"}, caller=None)
        ctx.api.call("tickets.rebind", {"from": old, "to": new_id,
            "now": now.get("ts")}, caller=None)
    return ctx.api.call("projects.view", {"rec": rec}, caller=None)


def _as_handler(fn):
    """装配适配：纯函数只收 payload，路由协议仍是 fn(ctx, payload)。"""
    return lambda ctx, payload: fn(payload)
