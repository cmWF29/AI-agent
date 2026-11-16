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
    ctx.api.register("tickets.close", _route_close, "结单：子单守卫→关闭→落盘→通知父单 PM", module="tickets")
    ctx.api.register("tickets.split", _route_split, "拆子单：守上限→逐个建单并挂链接", module="tickets")
    ctx.api.register("tickets.stall_scan", _route_stall_scan, "停滞扫描：遍历在途→判定→开审计单", module="tickets")
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


def _ticket_path(ticket_id):
    return "tickets/%s/ticket.yaml" % (ticket_id or "")


def _route_close(ctx, payload):
    """结单闭环：先守子单，再关闭落盘，最后按需通知父单。守卫与通知都在能力内部。"""
    row = ctx.api.call("store.read", {"module": "agent/tickets",
                                      "path": _ticket_path(payload.get("id"))}, caller=None)
    rec = row.get("value") or {}
    for cid in rec.get("children") or []:
        child = ctx.api.call("store.read", {"module": "agent/tickets",
                                            "path": _ticket_path(cid)}, caller=None)
        cv = child.get("value")
        if cv is not None and cv.get("status") != "closed":
            return {"ok": False, "code": "children_open", "status": 409,
                    "error": "子工单尚未结单: %s" % cid}
    now = ctx.api.call("clock.now", {}, caller=None)
    closed = ctx.api.call("tickets.closefin", {
        "rec": rec, "summary": payload.get("summary"),
        "verdict": payload.get("verdict"), "now": now.get("ts")}, caller=None)
    ctx.api.call("store.write", {"module": "agent/tickets",
                                 "path": _ticket_path(closed.get("id")), "value": closed},
                 caller=None)
    if closed.get("parent"):
        ctx.api.call("demand_engine.run", {
            "id": "ticket-message",
            "input": {"id": closed.get("parent"),
                      "text": "子工单已结单： %s" % (closed.get("id") or ""),
                      "target": "pm"}}, caller=None)
    return ctx.api.call("tickets.view", {"rec": closed}, caller=None)


def _route_split(ctx, payload):
    """拆单闭环：上限守卫 + 逐个建子单（每次建单都是一条独立编排）。"""
    row = ctx.api.call("store.read", {"module": "agent/tickets",
                                      "path": _ticket_path(payload.get("id"))}, caller=None)
    cur = row.get("value") or {}
    if len(cur.get("children") or []) >= 8 and payload.get("force") is False:
        return {"ok": False, "code": "too_many_children", "status": 409,
                "error": "子工单最多 8 个"}
    for child_spec in payload.get("children") or []:
        spec = child_spec or {}
        child = ctx.api.call("demand_engine.run", {
            "id": "ticket-create",
            "input": {"title": spec.get("title"), "goal": spec.get("goal"),
                      "project": cur.get("project"), "kind": "sub",
                      "parent": payload.get("id"), "auto_retrospective": False}},
            caller=None)
        now = ctx.api.call("clock.now", {}, caller=None)
        cur = ctx.api.call("tickets.bindchild", {
            "rec": cur, "child": ((child.get("result") or {}).get("id")) or "",
            "now": now.get("ts")}, caller=None)
        ctx.api.call("store.write", {"module": "agent/tickets",
                                     "path": _ticket_path(cur.get("id")), "value": cur},
                     caller=None)
    return ctx.api.call("tickets.view", {"rec": cur}, caller=None)


def _route_stall_scan(ctx, payload):
    """停滞扫描闭环：遍历在途工单、逐条判定、按命中开审计单。"""
    now = ctx.api.call("clock.now", {}, caller=None)
    rows = ctx.api.call("store.walk", {"module": "agent/tickets", "root": "tickets",
                                       "pattern": "*/ticket.yaml"}, caller=None)
    hot = []
    for rec in rows.get("rows") or []:
        rec = rec or {}
        idle = ctx.api.call("clock.since", {"iso": rec.get("updated")}, caller=None)
        verdict = ctx.api.call("tickets.stale", {
            "rec": rec, "idle_seconds": idle.get("seconds"),
            "limit_seconds": payload.get("limit_seconds")}, caller=None)
        if verdict.get("stale") is True:
            hot.append(rec.get("id"))
    for tid in hot:
        ctx.api.call("demand_engine.run", {
            "id": "ticket-create",
            "input": {"title": "停滞审计: %s" % tid, "goal": "工单久未推进: %s" % tid,
                      "kind": "stall-audit", "auto_retrospective": False}},
            caller=None)
    return ctx.api.call("ops.assemble", {"parts": {"scan": hot, "at": now.get("ts")}},
                        caller=None)

