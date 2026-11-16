"""工单模块：工单记录的纯计算。生命周期编排在 ticket-* 需求里。"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    for name, fn in [
        ("tickets.newid", _pure.newid),
        ("tickets.build", _pure.build),
        ("tickets.validate_project", _pure.validate_project),
        ("tickets.thread", _pure.thread),
        ("tickets.present", _pure.present),
        ("tickets.view", _pure.view),
        ("tickets.screen", _pure.screen),
        ("tickets.roles", _pure.roles),
        ("tickets.note", _pure.note),
        ("tickets.bindrole", _pure.bindrole),
        ("tickets.bindpm", _pure.bindpm),
        ("tickets.bindchild", _pure.bindchild),
        ("tickets.closefin", _pure.closefin),
        ("tickets.pick", _pure.pick),
        ("tickets.resolve_target", _pure.resolve_target),
        ("tickets.files_filter", _pure.files_filter),
        ("tickets.err", _pure.err),
        ("tickets.stale", _pure.stale),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="tickets")
    ctx.api.register("tickets.create", _route_create, "建工单：校验项目→造记录→拉 PM→落盘", module="tickets")
    return True


def _route_create(ctx, payload):
    """建单闭环：项目守卫、查档、造记录、拉 PM、落盘。分岔与派发都在能力内部。"""
    skip_pm = payload.get("kind") == "stall-audit"
    vproj = ctx.api.call("tickets.validate_project", {
        "project": payload.get("project")}, caller=None)
    if vproj.get("ok") is False:
        return ctx.api.call("tickets.err", {
            "code": "missing_project", "status": 400,
            "message": vproj.get("error")}, caller=None)
    prow = ctx.api.call("store.read", {
        "module": "agent/projects",
        "path": "%s.yaml" % (payload.get("project") or "")}, caller=None)
    if prow.get("value") is None:
        return ctx.api.call("projects.missing", {"id": payload.get("project")}, caller=None)
    now = ctx.api.call("clock.now", {}, caller=None)
    fresh = ctx.api.call("tickets.newid", {
        "today": now.get("iso"), "n": payload.get("n")}, caller=None)
    rec = ctx.api.call("tickets.build", {
        "id": fresh.get("id"), "title": payload.get("title"),
        "goal": payload.get("goal"), "project": payload.get("project"),
        "kind": payload.get("kind"), "parent": payload.get("parent"),
        "meta": payload.get("meta"),
        "auto_retrospective": payload.get("auto_retrospective"),
        "now": now.get("ts")}, caller=None)
    if not skip_pm:
        pm = ctx.api.call("demand_engine.run", {
            "id": "session-spawn",
            "input": {"kind": "pm", "name": "PM-%s" % (fresh.get("id") or ""),
                      "ticket": fresh.get("id"),
                      "max_steps": payload.get("pm_max_steps"),
                      "task": payload.get("task")}}, caller=None)
        rec = ctx.api.call("tickets.bindpm", {
            "rec": rec,
            "session": ((pm.get("result") or {}).get("id")) or "",
            "now": now.get("ts")}, caller=None)
    ctx.api.call("store.write", {
        "module": "agent/tickets",
        "path": "tickets/%s/ticket.yaml" % (rec.get("id") or ""),
        "value": rec}, caller=None)
    return ctx.api.call("tickets.view", {"rec": rec}, caller=None)

