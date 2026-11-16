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
    ctx.api.register("tickets.rebind", _route_rebind, "项目改名后把工单改挂到新项目 id", module="tickets")
    return True


def _msg_tpl(ctx):
    """消息模板表：工单模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent/tickets", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


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
    day = str(now.get("iso") or "")[:10].replace("-", "")
    listed = ctx.api.call("store.glob", {
        "module": "agent/tickets", "pattern": "tickets/T-*/ticket.yaml"}, caller=None)
    ids = [str(i).split("/")[1] for i in (listed.get("items") or [])
           if str(i).count("/") == 2]
    n = payload.get("n") or _pure.next_n({"ids": ids, "day": day}).get("n")
    fresh = ctx.api.call("tickets.newid", {
        "today": now.get("iso"), "n": n}, caller=None)
    backend = (payload.get("backend")
               or (prow.get("value") or {}).get("default_backend") or "")
    rec = ctx.api.call("tickets.build", {
        "backend": backend,
        "id": fresh.get("id"), "title": payload.get("title"),
        "goal": payload.get("goal"), "project": payload.get("project"),
        "kind": payload.get("kind"), "parent": payload.get("parent"),
        "meta": payload.get("meta"),
        "auto_retrospective": payload.get("auto_retrospective"),
        "now": now.get("ts")}, caller=None)
    if ctx.api.call("store.exists", {
            "module": "agent/tickets",
            "path": _ticket_path(rec.get("id"))}, caller=None).get("exists"):
        return ctx.api.call("tickets.err", {
            "code": "ticket_id_conflict", "status": 409,
            "message": "工单号已存在：%s，拒绝覆盖" % (rec.get("id") or "")}, caller=None)
    if not skip_pm:
        intro = _pure.msg({
            "tpl": (_msg_tpl(ctx).get("pm_intro") or ""),
            "vars": {"ticket": fresh.get("id") or "", "title": rec.get("title") or "",
                     "goal": rec.get("goal") or ""}}).get("text") or ""
        pm = ctx.runtime.call("session-spawn", {
            "kind": "pm", "name": "PM-%s" % (fresh.get("id") or ""),
            "backend": backend,
            "ticket": fresh.get("id"),
            "max_steps": payload.get("pm_max_steps"),
            "task": payload.get("task"),
            "intro": intro})
        rec = ctx.api.call("tickets.bindpm", {
            "rec": rec,
            "session": (pm.get("id")) or "",
            "now": now.get("ts")}, caller=None)
    view = ctx.api.call("tickets.view", {"rec": rec}, caller=None)
    view["effects"] = [{"kind": "write", "module": "agent/tickets",
                        "path": "tickets/%s/ticket.yaml" % (rec.get("id") or ""), "value": rec}]
    return view


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
    view = ctx.api.call("tickets.view", {"rec": closed}, caller=None)
    effects = [{"kind": "write", "module": "agent/tickets",
                "path": _ticket_path(closed.get("id")), "value": closed}]
    if closed.get("parent"):
        effects.append({"kind": "demand", "id": "ticket-message",
                        "input": {"id": closed.get("parent"),
                                  "text": "子工单已结单： %s" % (closed.get("id") or ""),
                                  "target": "pm"}})
    view["effects"] = effects
    return view


def _route_split(ctx, payload):
    """拆单闭环：上限守卫 + 逐个建子单（每次建单都是一条独立编排）。"""
    row = ctx.api.call("store.read", {"module": "agent/tickets",
                                      "path": _ticket_path(payload.get("id"))}, caller=None)
    cur = row.get("value") or {}
    if len(cur.get("children") or []) >= 8 and payload.get("force") is False:
        return {"ok": False, "code": "too_many_children", "status": 409,
                "error": "子工单最多 8 个"}
    effects = []
    for child_spec in payload.get("children") or []:
        spec = child_spec or {}
        child = ctx.runtime.call("ticket-create", {
            "title": spec.get("title"), "goal": spec.get("goal"),
            "project": cur.get("project"), "kind": "sub",
            "parent": payload.get("id"), "auto_retrospective": False})
        now = ctx.api.call("clock.now", {}, caller=None)
        cur = ctx.api.call("tickets.bindchild", {
            "rec": cur, "child": (child.get("id")) or "",
            "now": now.get("ts")}, caller=None)
        effects.append({"kind": "write", "module": "agent/tickets",
                        "path": _ticket_path(cur.get("id")), "value": cur})
    view = ctx.api.call("tickets.view", {"rec": cur}, caller=None)
    view["effects"] = effects
    return view


def _route_rebind(ctx, payload):
    """引用改挂：遍历工单，把指向旧项目 id 的记录改写为新 id。"""
    rows = ctx.api.call("store.walk", {"module": "agent/tickets", "root": "tickets",
                                       "pattern": "*/ticket.yaml"}, caller=None)
    moved = []
    effects = []
    for rec in rows.get("rows") or []:
        rec = rec or {}
        if rec.get("project") != payload.get("from"):
            continue
        cur = dict(rec)
        cur["project"] = payload.get("to")
        cur["updated"] = payload.get("now") or cur.get("updated")
        effects.append({"kind": "write", "module": "agent/tickets",
                        "path": _ticket_path(cur.get("id")), "value": cur})
        moved.append(cur.get("id"))
    return {"from": payload.get("from"), "to": payload.get("to"),
            "tickets": moved, "effects": effects}


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
        ctx.runtime.call("ticket-create", {
            "title": "停滞审计: %s" % tid, "goal": "工单久未推进: %s" % tid,
            "kind": "stall-audit", "auto_retrospective": False})
    return ctx.api.call("ops.assemble", {"parts": {"scan": hot, "at": now.get("ts")}},
                        caller=None)

