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
        ("tickets.touch", _pure.touch),
        ("tickets.bindrole", _pure.bindrole),
        ("tickets.bindpm", _pure.bindpm),
        ("tickets.bindchild", _pure.bindchild),
        ("tickets.review_mark", _pure.review_mark),
        ("tickets.closefin", _pure.closefin),
        ("tickets.collect_session_ids", _pure.collect_session_ids),
        ("tickets.archive_transcript", _pure.archive_transcript),
        ("tickets.pick", _pure.pick),
        ("tickets.resolve_target", _pure.resolve_target),
        ("tickets.files_filter", _pure.files_filter),
        ("tickets.paths", _pure.paths),
        ("tickets.record_path", _pure.record_path),
        ("tickets.msg", _pure.msg),
        ("tickets.err", _pure.err),
        ("tickets.stale", _pure.stale),
    ]:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="tickets")
    ctx.api.register("tickets.close", _route_close, "结单：子单守卫→关闭→落盘→通知父单 PM", module="tickets")
    ctx.api.register("tickets.split", _route_split, "拆子单：守上限→逐个建单并挂链接", module="tickets")
    ctx.api.register("tickets.stall_scan", _route_stall_scan, "停滞扫描：遍历在途→判定→开审计单", module="tickets")
    ctx.api.register("tickets.create", _route_create, "建工单：校验项目→造记录→拉 PM→落盘", module="tickets")
    ctx.api.register("tickets.rebind", _route_rebind, "项目改名后把工单改挂到新项目 id", module="tickets")
    _register_tools(ctx)
    return True


def _register_tools(ctx):
    """编排工具就是需求桥接：PM 握分单/派角色/结单，角色只读文档与记备注。

    kinds 按会话类型放行；岗位 tools 名单在 library 成形时再做第二道裁剪。
    """
    pm, role = ["pm"], ["role"]
    tools = [
        ("role_spawn", "拉一个角色会话并分派任务",
         [{"name": "role", "type": "string", "desc": "角色 id（developer/tester/...）", "required": True},
          {"name": "display", "type": "string", "desc": "显示名", "required": False},
          {"name": "task", "type": "string", "desc": "任务目标、输入路径、产出路径、验收标准", "required": True}],
         "ticket-role-spawn", pm),
        ("role_task", "给已有角色返工或补缺口",
         [{"name": "role", "type": "string", "desc": "角色 id 或会话 id", "required": True},
          {"name": "text", "type": "string", "desc": "缺口与验收标准，不重复整份任务书", "required": True}],
         "ticket-role-task", pm),
        ("ticket_split", "拆成多个可独立验收的子工单",
         [{"name": "children", "type": "list", "desc": "子任务清单（title/goal）", "required": True},
          {"name": "force", "type": "boolean", "desc": "超出上限是否强制", "required": False}],
         "ticket-split", pm),
        ("ticket_close", "对照验收标准结单",
         [{"name": "summary", "type": "string", "desc": "结单摘要", "required": False},
          {"name": "verdict", "type": "string", "desc": "accepted=验收通过；rejected=未通过关闭（只记录驳回结论并关单，不自动重开）", "required": False}],
         "ticket-close", pm),
        ("ticket_read_doc", "读本工单交付件或交接文档（只读）",
         [{"name": "path", "type": "string", "desc": "交付件相对路径", "required": True}],
         "ticket-file", pm + role),
        ("ticket_note", "给工单记一条备注（不改动交付件）",
         [{"name": "text", "type": "string", "desc": "备注内容", "required": True}],
         "ticket-note", pm + role),
        ("ticket_status", "查看本工单当前状态", [], "ticket-get", role),
    ]
    for name, desc, params, demand, kinds in tools:
        ctx.tools.register_demand(name, desc, params, demand=demand,
                                  module="tickets", kinds=kinds)


def _msg_tpl(ctx):
    """消息模板表：工单模块自己的 data，读不到就退化成空。"""
    row = ctx.api.call("store.read", {
        "module": "agent/tickets", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def _route_create(ctx, payload):
    """建单闭环：项目守卫、查档、造记录、拉 PM、落盘。分岔与派发都在能力内部。"""
    skip_pm = payload.get("kind") == "stall-audit"
    vproj = ctx.api.call("tickets.validate_project", {
        "project": payload.get("project"),
        "tpl": _msg_tpl(ctx).get("missing_project") or ""}, caller=None)
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
    baseline = _pure.next_n({"ids": ids, "day": day}).get("n") - 1
    n = payload.get("n") or ctx.api.call("store.next_seq", {
        "bucket": "ticket:" + day, "baseline": baseline}, caller=None).get("seq")
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
        "default_title": _msg_tpl(ctx).get("default_title") or "",
        "now": now.get("ts")}, caller=None)
    if ctx.api.call("store.exists", {
            "module": "agent/tickets",
            "path": _ticket_path(rec.get("id"))}, caller=None).get("exists"):
        return ctx.api.call("tickets.err", {
            "code": "ticket_id_conflict", "status": 409,
            "message": "工单号已存在：%s，拒绝覆盖" % (rec.get("id") or "")}, caller=None)
    pm_id = ""
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
        pm_id = pm.get("id") or ""
        rec = ctx.api.call("tickets.bindpm", {
            "rec": rec,
            "session": pm_id,
            "pm_text": _msg_tpl(ctx).get("pm_started") or "",
            "now": now.get("ts")}, caller=None)
    view = ctx.api.call("tickets.view", {"rec": rec}, caller=None)
    effects = [{"kind": "write", "module": "agent/tickets",
                "path": "tickets/%s/ticket.yaml" % (rec.get("id") or ""), "value": rec}]
    # 首轮开工随效果清单后台派发：会话在 spawn 内已落盘，这里只交一把钥匙；审计单无 PM 不派发。
    if pm_id:
        effects.append({"kind": "dispatch", "id": "session-run",
                        "key": pm_id, "input": {"id": pm_id}})
    view["effects"] = effects
    return view


def _ticket_path(ticket_id):
    return "tickets/%s/ticket.yaml" % (ticket_id or "")


def _session_snapshot(ctx, sid):
    """读会话留档快照；会话已不在则返 None。消息原文交纯函数裁剪。"""
    if not sid:
        return None
    row = ctx.api.call("store.read", {"module": "agent/sessions",
                                      "path": "sessions/%s.yaml" % sid}, caller=None)
    rec = row.get("value")
    if not rec:
        return None
    return {"session": sid, "name": rec.get("name") or "",
            "messages": rec.get("messages") or []}


def _route_close(ctx, payload):
    """结单闭环：守子单 → 关闭落盘 → 对话固化进工单 → 回收 PM/角色会话 → 通知父单。

    会话文件回收前先 stop 等收尾（同 purge 范式）；往来对话已固化进工单 transcript，
    删文件后仍可从工单回看。守卫、固化、回收都在能力内部。
    """
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
        "verdict": payload.get("verdict"), "now": now.get("ts"),
        "accepted_text": _msg_tpl(ctx).get("close_accepted") or "",
        "rejected_text": _msg_tpl(ctx).get("close_rejected") or ""}, caller=None)
    listed = ctx.api.call("store.glob", {
        "module": "agent/sessions", "pattern": "sessions/*.yaml"}, caller=None)
    session_rows, session_by_sid = [], {}
    for rel in listed.get("items") or []:
        row = ctx.api.call("store.read", {"module": "agent/sessions",
                                          "path": rel}, caller=None)
        rec_s = row.get("value")
        if rec_s:
            session_rows.append(rec_s)
            session_by_sid[rec_s.get("id") or ""] = rec_s
    sids = ctx.api.call("tickets.collect_session_ids", {
        "rec": closed, "rows": session_rows}, caller=None).get("sids") or []
    # 先停后台线程并等收尾，避免定稿落盘把已删会话又写回
    for sid in sids:
        ctx.runtime.stop(sid)
    pm_snap = _session_snapshot(ctx, closed.get("pm"))
    role_snaps = []
    known = {closed.get("pm")}
    for r in closed.get("roles") or []:
        snap = _session_snapshot(ctx, r.get("session"))
        if snap:
            snap["role"] = r.get("role") or ""
            snap["display"] = r.get("display") or r.get("role") or ""
            role_snaps.append(snap)
        known.add(r.get("session"))
    # 兜底归集：目录里挂在本工单、却没登记回 roles 的会话，往来对话一并留档再删
    for sid in sids:
        if sid in known:
            continue
        extra = session_by_sid.get(sid) or {}
        snap = _session_snapshot(ctx, sid)
        if snap:
            snap["role"] = extra.get("role") or ""
            snap["display"] = extra.get("display") or extra.get("role") or sid
            role_snaps.append(snap)
    archived = ctx.api.call("tickets.archive_transcript", {
        "rec": closed, "pm": pm_snap, "roles": role_snaps}, caller=None)
    view = ctx.api.call("tickets.view", {"rec": archived}, caller=None)
    effects = [{"kind": "write", "module": "agent/tickets",
                "path": _ticket_path(archived.get("id")), "value": archived}]
    for sid in sids:
        effects.append({"kind": "remove", "module": "agent/sessions",
                        "path": "sessions/%s.yaml" % sid})
    if archived.get("parent"):
        effects.append({"kind": "demand", "id": "ticket-message",
                        "input": {"id": archived.get("parent"),
                                  "text": "子工单已结单： %s" % (archived.get("id") or ""),
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
            "tpl": _msg_tpl(ctx).get("child_split") or "",
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
    """停滞扫描闭环：开关/阈值/上限/是否开单由需求层从配置传入；遍历判定归本能力。"""
    now = ctx.api.call("clock.now", {}, caller=None)
    if not bool(payload.get("enabled")):
        return ctx.api.call("ops.assemble", {"parts": {"scan": [], "at": now.get("ts")}},
                            caller=None)
    rows = ctx.api.call("store.walk", {"module": "agent/tickets", "root": "tickets",
                                       "pattern": "*/ticket.yaml"}, caller=None)
    limit_seconds = int(payload.get("idle_minutes")) * 60
    max_per_scan = int(payload.get("max_per_scan"))
    create_audit = bool(payload.get("create_audit"))
    hot = []
    for rec in rows.get("rows") or []:
        rec = rec or {}
        idle = ctx.api.call("clock.since", {"iso": rec.get("updated")}, caller=None)
        verdict = ctx.api.call("tickets.stale", {
            "rec": rec, "idle_seconds": idle.get("seconds"),
            "limit_seconds": limit_seconds}, caller=None)
        if verdict.get("stale") is True:
            hot.append(rec.get("id"))
    if create_audit:
        for tid in hot[:max_per_scan]:
            ctx.runtime.call("ticket-create", {
                "title": "停滞审计: %s" % tid, "goal": "工单久未推进: %s" % tid,
                "kind": "stall-audit", "auto_retrospective": False})
    return ctx.api.call("ops.assemble", {"parts": {"scan": hot, "at": now.get("ts")}},
                        caller=None)

