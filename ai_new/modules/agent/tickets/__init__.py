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
        ("tickets.touch", _pure.touch),
        ("tickets.bindrole", _pure.bindrole),
        ("tickets.bindpm", _pure.bindpm),
        ("tickets.bindchild", _pure.bindchild),
        ("tickets.review_mark", _pure.review_mark),
        ("tickets.closefin", _pure.closefin),
        ("tickets.collect_session_ids", _pure.collect_session_ids),
        ("tickets.archive_transcript", _pure.archive_transcript),
        ("tickets.pick", _pure.pick),
        ("tickets.files_filter", _pure.files_filter),
        ("tickets.paths", _pure.paths),
        ("tickets.msg", _pure.msg),
        ("tickets.err", _pure.err),
        ("tickets.stale", _pure.stale),
    ]:
        ctx.api.register(name, _as_handler(fn), module="tickets")
    ctx.api.register("tickets.record_path", _route_record_path, module="tickets")
    ctx.api.register("tickets.close", _route_close, "结单：子单守卫→关闭→落盘→通知父单 PM", module="tickets")
    ctx.api.register("tickets.split", _route_split, "拆子单：守上限→逐个建单并挂链接", module="tickets")
    ctx.api.register("tickets.stall_scan", _route_stall_scan, "停滞扫描：遍历在途→判定→开审计单", module="tickets")
    ctx.api.register("tickets.create", _route_create, "建工单：校验项目→造记录→拉 PM→落盘", module="tickets")
    ctx.api.register("tickets.rebind", _route_rebind, "项目改名后把工单改挂到新项目 id", module="tickets")
    ctx.api.register("tickets.send", _route_send, "发消息：工单/项目守卫→解析目标→追加→派发", module="tickets")
    ctx.api.register("tickets.note_write", _route_note_write, "追加备注：守卫→追加→落盘", module="tickets")
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


def _cfg_paths(ctx):
    row = ctx.api.call("config.get", {"key": "tickets.paths"}, caller=None)
    return row.get("value") or {}


def _cfg_logs(ctx):
    row = ctx.api.call("config.get", {"key": "logs.paths"}, caller=None)
    return row.get("value") or {}


def _as_handler(fn):
    def handler(ctx, payload):
        payload = dict(payload or {})
        if "paths" not in payload:
            payload["paths"] = _cfg_paths(ctx)
        return fn(payload)
    return handler


_TICKET_PROJECT = {}   # 工单 id -> 项目；工单只增不换项目，进程内记住即可


def _lookup_project(ctx, tid):
    """按目录反查工单归属：唯一命中才算，多个项目下同时存在就拒绝猜。"""
    if not tid:
        return ""
    listed = ctx.api.call("store.glob", {
        "module": "agent/tickets",
        "pattern": "projects/*/tickets/%s/ticket.yaml" % tid}, caller=None)
    owners = [str(rel).split("/")[1] for rel in (listed.get("items") or [])]
    if len(owners) > 1:
        raise ctx.ApiError("工单 %s 同时挂在多个项目下（%s），拒绝按猜测定位"
                           % (tid, "、".join(sorted(owners))), code="ticket_ambiguous", status=409)
    if owners:
        _TICKET_PROJECT[tid] = owners[0]
        return owners[0]
    return ""


def _ticket_path(ctx, ticket_id, project=None):
    """工单文件路径：项目目录下的 tickets/<id>/ticket.yaml。

    工单必属项目，路径就带项目。只给 id 时按目录反查归属；反查不到就退到"无项目
    前缀"的位置——那里迁移后一定是空的，所以读不到别人的单，不会串档。
    """
    tid = str(ticket_id or "")
    pj = str(project or "").strip() or _TICKET_PROJECT.get(tid, "")
    if not pj:
        pj = _lookup_project(ctx, tid)
        if pj:
            _TICKET_PROJECT[tid] = pj
    return _pure.record_path({"paths": _cfg_paths(ctx), "id": tid, "project": pj}).get("path") or ""


def _route_record_path(ctx, payload):
    """需求层取路径：给了项目就用，没给就按目录反查（反查不到的路径必然读不到东西）。"""
    p = dict(payload or {})
    p.setdefault("paths", _cfg_paths(ctx))
    tid = str(p.get("id") or "")
    pj = str(p.get("project") or "").strip()
    if not pj:
        pj = _TICKET_PROJECT.get(tid) or _lookup_project(ctx, tid)
    return _pure.record_path({"paths": p.get("paths") or {},
                              "id": p.get("id"), "project": pj})



def _project_state(ctx, project):
    """项目档案里的两件事实：是否归档、哪些岗位被项目禁用。

    写在工单侧是因为这里的每个写入口都要用；不做缓存，一次点击一次读盘就够。
    """
    name = str(project or "").strip()
    if not name:
        return {"archived": False, "roles": [], "exists": False}
    paths = _cfg_paths(ctx)
    pr = paths.get("project_record") or ""
    row = ctx.api.call("store.read", {
        "module": "agent/projects",
        "path": pr.format(project=name) if pr else name}, caller=None)
    rec = row.get("value") or {}
    ov = (rec.get("overrides") or {}) if isinstance(rec, dict) else {}
    return {"archived": rec.get("archived") is True,
            "roles": [str(x) for x in (ov.get("roles") or [])],
            "exists": row.get("value") is not None}


def _err(ctx, code, status, message):
    return ctx.api.call("tickets.err", {
        "code": code, "status": status, "message": message}, caller=None)


def _route_send(ctx, payload):
    """发消息闭环：工单守卫（结单只读）→ 项目守卫（归档只读）→ 解析目标 → 追加 → 派发。

    守卫必须放在写之前：前端把按钮灰掉是提示，这里才是真正拦得住的地方。
    """
    shape = _pure.validate_text(dict(payload, tpl=_msg_tpl(ctx)))
    if shape.get("ok") is False:
        return _err(ctx, shape.get("code"), shape.get("status"), shape.get("error"))
    text = shape.get("text") or ""
    if not text.strip():
        return _err(ctx, "empty_text", 400, "")
    tid = payload.get("id") or ""
    tpl = _msg_tpl(ctx)
    row = ctx.api.call("store.read", {"module": "agent/tickets",
                                      "path": _ticket_path(ctx, tid)}, caller=None)
    rec = row.get("value")
    if rec is None:
        return _err(ctx, "not_found", 404, tpl.get("missing") or "")
    guard = _pure.guard_open({"rec": rec, "tpl": tpl})
    if guard.get("ok") is False:
        return _err(ctx, guard.get("code"), guard.get("status"), guard.get("error"))
    proj = _project_state(ctx, rec.get("project"))
    if proj.get("archived"):
        return _err(ctx, "project_archived", 409, tpl.get("project_archived") or "")
    tgt = _pure.resolve_target({"rec": rec, "target": payload.get("target") or "pm"})
    sid = tgt.get("session") or ""
    if not sid:
        return _err(ctx, "no_session", 409, tpl.get("pm_started") or "")
    ctx.demand_engine.run_callable("session-send", {
        "id": sid, "text": text})
    ctx.runtime.dispatch({"demand": "session-run", "key": sid, "input": {"id": sid}})
    return ctx.api.call("tickets.view", {"rec": rec}, caller=None)


def _route_note_write(ctx, payload):
    """追加备注：同一套守卫，追加后立即落盘并回视图。"""
    tid = payload.get("id") or ""
    tpl = _msg_tpl(ctx)
    row = ctx.api.call("store.read", {"module": "agent/tickets",
                                      "path": _ticket_path(ctx, tid)}, caller=None)
    rec = row.get("value")
    if rec is None:
        return _err(ctx, "not_found", 404, tpl.get("missing") or "")
    guard = _pure.guard_open({"rec": rec, "tpl": tpl})
    if guard.get("ok") is False:
        return _err(ctx, guard.get("code"), guard.get("status"), guard.get("error"))
    if _project_state(ctx, rec.get("project")).get("archived"):
        return _err(ctx, "project_archived", 409, tpl.get("project_archived") or "")
    shape = _pure.validate_text(dict(payload, tpl=_msg_tpl(ctx)))
    if shape.get("ok") is False:
        return _err(ctx, shape.get("code"), shape.get("status"), shape.get("error"))
    text = (shape.get("text") or "").strip()
    if not text:
        return _err(ctx, "empty_text", 400, "")
    now = ctx.api.call("clock.now", {}, caller=None)
    rec2 = _pure.note({"rec": rec, "text": text, "now": now.get("ts")})
    # 写盘不在能力里做：能力只声明 effect，由需求层统一落盘（架构闸会盯这一条）
    view = ctx.api.call("tickets.view", {"rec": rec2}, caller=None)
    view["effects"] = [{"kind": "write", "module": "agent/tickets",
                        "path": _ticket_path(ctx, rec2.get("id"), rec2.get("project")),
                        "value": rec2}]
    return view


def _route_create(ctx, payload):
    """建单：幂等键 = 项目 + 标题 + 目标。重放直接回原单，不建第二张。

    键里没有时间戳，也没有随机数，所以"同一件事重投/崩溃重放"算出来的键必然相同；
    想真的再建一张，改标题或目标即可（那本来就是另一件事）。
    """
    shape = _pure.validate_create(dict(payload, tpl=_msg_tpl(ctx)))
    if shape.get("ok") is False:
        return _err(ctx, shape.get("code"), shape.get("status"), shape.get("error"))
    sig = "\n".join([str(payload.get("project") or ""), str(payload.get("title") or ""),
                      str(payload.get("goal") or "")])
    key = str(ctx.api.call("codec.digest", {"text": sig}, caller=None).get("hex") or "")[:40]
    claim = ctx.api.call("store.claim", {
        "module": "agent/tickets", "bucket": "create", "key": key,
        "route": "tickets.create", "scope": str(payload.get("project") or ""),
        "lease_seconds": 600}, caller=None)
    if not claim.get("claimed"):
        status = claim.get("status") or ""
        if status == "done":
            view = _reuse_created(ctx, claim.get("result_digest") or "")
            if view:
                return view
            raise ctx.ApiError("原单已不在，需人工核对", code="idem_ghost", status=409)
        if status == "abandoned":
            raise ctx.ApiError("建单已中止，需人工处置", code="idem_abandoned", status=409)
        raise ctx.ApiError("同一建单请求正在进行", code="idem_in_flight", status=409)
    try:
        view = _create(ctx, payload)
    except Exception as exc:
        ctx.api.call("store.settle", {
            "module": "agent/tickets", "bucket": "create", "key": key,
            "status": "failed", "error_code": type(exc).__name__}, caller=None)
        raise
    ok = not (isinstance(view, dict) and view.get("ok") is False)
    tid = str((view or {}).get("id") or (view or {}).get("ticket") or "")
    ctx.api.call("store.settle", {
        "module": "agent/tickets", "bucket": "create", "key": key,
        "status": "done" if (ok and tid) else "failed",
        "result_digest": tid if (ok and tid) else "",
        "error_code": "" if (ok and tid) else str((view or {}).get("code") or "unresolved")},
        caller=None)
    return view


def _reuse_created(ctx, ticket_id):
    """重放：按票据 id 读回原单并出视图，不再落盘、不再派发。"""
    if not ticket_id:
        return None
    row = ctx.api.call("store.read", {
        "module": "agent/tickets", "path": _ticket_path(ctx, ticket_id)}, caller=None)
    rec = row.get("value")
    if not rec:
        return None
    view = ctx.api.call("tickets.view", {"rec": rec}, caller=None)
    view["reused"] = True
    view["effects"] = []
    return view


def _create(ctx, payload):
    """建单闭环：项目守卫、查档、造记录、拉 PM、落盘。分岔与派发都在能力内部。"""
    skip_pm = payload.get("kind") == "stall-audit"
    paths = _cfg_paths(ctx)
    vproj = ctx.api.call("tickets.validate_project", {
        "project": payload.get("project"),
        "tpl": _msg_tpl(ctx).get("missing_project") or ""}, caller=None)
    if vproj.get("ok") is False:
        return ctx.api.call("tickets.err", {
            "code": "missing_project", "status": 400,
            "message": vproj.get("error")}, caller=None)
    pr = paths.get("project_record") or ""
    pname = payload.get("project") or ""
    prow = ctx.api.call("store.read", {
        "module": "agent/projects",
        "path": pr.format(project=pname) if pr else pname}, caller=None)
    if prow.get("value") is None:
        return ctx.api.call("projects.missing", {"id": payload.get("project")}, caller=None)
    prec = prow.get("value") or {}
    proles = [str(x) for x in ((prec.get("overrides") or {}).get("roles") or [])]
    cguard = _pure.guard_create({
        "project_archived": prec.get("archived") is True,
        "pm_disabled": "pm" in proles,
        "tpl": _msg_tpl(ctx)})
    if cguard.get("ok") is False:
        return ctx.api.call("tickets.err", {
            "code": cguard.get("code"), "status": cguard.get("status"),
            "message": cguard.get("error")}, caller=None)
    now = ctx.api.call("clock.now", {}, caller=None)
    day = str(now.get("iso") or "")[:10].replace("-", "")
    listed = ctx.api.call("store.glob", {
        "module": "agent/tickets", "pattern": paths.get("glob") or ""}, caller=None)
    ids = [str(i).split("/")[3] for i in (listed.get("items") or [])
           if str(i).count("/") == 4]
    baseline = _pure.next_n({"ids": ids, "day": day}).get("n") - 1
    n = payload.get("n") or ctx.api.call("store.next_seq", {
        "bucket": "ticket:" + day, "baseline": baseline}, caller=None).get("seq")
    fresh = ctx.api.call("tickets.newid", {
        "today": now.get("iso"), "n": n}, caller=None)
    rec = ctx.api.call("tickets.build", {
        "id": fresh.get("id"), "title": payload.get("title"),
        "goal": payload.get("goal"), "project": payload.get("project"),
        "kind": payload.get("kind"), "parent": payload.get("parent"),
        "meta": payload.get("meta"),
        "auto_retrospective": payload.get("auto_retrospective"),
        "default_title": _msg_tpl(ctx).get("default_title") or "",
        "now": now.get("ts")}, caller=None)
    if ctx.api.call("store.exists", {
            "module": "agent/tickets",
            "path": _ticket_path(ctx, rec.get("id"), payload.get("project"))}, caller=None).get("exists"):
        tpl_conflict = _msg_tpl(ctx).get("ticket_conflict") or ""
        tid = rec.get("id") or ""
        return ctx.api.call("tickets.err", {
            "code": "ticket_id_conflict", "status": 409,
            "message": tpl_conflict.format(id=tid) if tpl_conflict else ""}, caller=None)
    pm_id = ""
    if not skip_pm:
        intro = _pure.msg({
            "tpl": (_msg_tpl(ctx).get("pm_intro") or ""),
            "vars": {"ticket": fresh.get("id") or "", "title": rec.get("title") or "",
                     "goal": rec.get("goal") or ""}}).get("text") or ""
        pm = ctx.runtime.call("session-spawn", {
            "kind": "pm", "role": "pm",
            "name": "PM-%s" % (fresh.get("id") or ""),
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
    _TICKET_PROJECT[str(rec.get("id") or "")] = str(rec.get("project") or "")
    effects = [{"kind": "write", "module": "agent/tickets",
                "path": _ticket_path(ctx, rec.get("id"), rec.get("project")), "value": rec}]
    # 首轮开工随效果清单后台派发：会话在 spawn 内已落盘，这里只交一把钥匙；审计单无 PM 不派发。
    if pm_id:
        effects.append({"kind": "dispatch", "id": "session-run",
                        "key": pm_id, "input": {"id": pm_id}})
    view["effects"] = effects
    return view


def _session_snapshot(ctx, sid):
    """读会话留档快照；会话已不在则返 None。消息原文交纯函数裁剪。"""
    if not sid:
        return None
    st = _cfg_logs(ctx).get("session") or ""
    row = ctx.api.call("store.read", {"module": "agent/logs",
        "path": st.format(id=sid) if st else sid}, caller=None)
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
    paths = _cfg_paths(ctx)
    row = ctx.api.call("store.read", {"module": "agent/tickets",
                                      "path": _ticket_path(ctx, payload.get("id"))}, caller=None)
    rec = row.get("value") or {}
    if not rec:
        return _err(ctx, "not_found", 404, _msg_tpl(ctx).get("missing") or "")
    if _project_state(ctx, rec.get("project")).get("archived"):
        return _err(ctx, "project_archived", 409,
                    _msg_tpl(ctx).get("project_archived") or "")
    tpl_child_open = _msg_tpl(ctx).get("child_open") or ""
    children = []
    for cid in rec.get("children") or []:
        child = ctx.api.call("store.read", {"module": "agent/tickets",
                                            "path": _ticket_path(ctx, cid)}, caller=None)
        if child.get("value") is not None:
            children.append(child.get("value"))
    guard = _pure.branch({"children": children})
    if not guard["all_closed"]:
        open_child = guard["open"][0]
        msg_open = tpl_child_open.format(id=open_child.get("id") or "") if tpl_child_open else ""
        return {"ok": False, "code": "children_open", "status": 409, "error": msg_open}
    now = ctx.api.call("clock.now", {}, caller=None)
    closed = ctx.api.call("tickets.closefin", {
        "rec": rec, "summary": payload.get("summary"),
        "verdict": payload.get("verdict"), "now": now.get("ts"),
        "accepted_text": _msg_tpl(ctx).get("close_accepted") or "",
        "rejected_text": _msg_tpl(ctx).get("close_rejected") or ""}, caller=None)
    listed = ctx.api.call("store.glob", {
        "module": "agent/logs", "pattern": _cfg_logs(ctx).get("session_glob") or ""}, caller=None)
    session_rows, session_by_sid = [], {}
    for rel in listed.get("items") or []:
        row = ctx.api.call("store.read", {"module": "agent/logs",
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
                "path": _ticket_path(ctx, archived.get("id"), archived.get("project")), "value": archived}]
    st = _cfg_logs(ctx).get("session") or ""
    removed_paths = [st.format(id=sid) if st else sid for sid in sids]
    for rel in removed_paths:
        effects.append({"kind": "remove", "module": "agent/logs", "path": rel})
    purge = ctx.api.call("logs.purge", {"paths": removed_paths}, caller=None)
    effects += purge.get("effects") or []
    if archived.get("parent"):
        tpl_closed = _msg_tpl(ctx).get("child_closed") or ""
        aid = archived.get("id") or ""
        effects.append({"kind": "demand", "id": "ticket-message",
                        "input": {"id": archived.get("parent"),
                                  "text": tpl_closed.format(id=aid) if tpl_closed else "",
                                  "target": "pm"}})
    view["effects"] = effects
    return view


def _route_split(ctx, payload):
    """拆单闭环：上限守卫 + 逐个建子单（每次建单都是一条独立编排）。"""
    shape = _pure.validate_split(dict(payload, tpl=_msg_tpl(ctx)))
    if shape.get("ok") is False:
        return _err(ctx, shape.get("code"), shape.get("status"), shape.get("error"))
    row = ctx.api.call("store.read", {"module": "agent/tickets",
                                      "path": _ticket_path(ctx, payload.get("id"))}, caller=None)
    cur = row.get("value") or {}
    max_children = payload.get("max_children")
    if max_children is not None and len(cur.get("children") or []) >= max_children \
            and payload.get("force") is not True:
        tpl_max = _msg_tpl(ctx).get("too_many_children") or ""
        return {"ok": False, "code": "too_many_children", "status": 409,
                "error": tpl_max.format(max=max_children) if tpl_max else ""}
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
                        "path": _ticket_path(ctx, cur.get("id"), cur.get("project")), "value": cur})
    view = ctx.api.call("tickets.view", {"rec": cur}, caller=None)
    view["effects"] = effects
    return view


def _route_rebind(ctx, payload):
    """引用改挂：遍历工单，把指向旧项目 id 的记录改写为新 id。"""
    shape = _pure.validate_rebind(dict(payload, tpl=_msg_tpl(ctx)))
    if shape.get("ok") is False:
        return _err(ctx, shape.get("code"), shape.get("status"), shape.get("error"))
    paths = _cfg_paths(ctx)
    rows = ctx.api.call("store.walk", {"module": "agent/tickets", "root": paths.get("root") or "",
                                       "pattern": paths.get("walk_glob") or ""}, caller=None)
    moved = []
    effects = []
    for rec in rows.get("rows") or []:
        rec = rec or {}
        if rec.get("project") != payload.get("from"):
            continue
        cur = dict(rec)
        cur["project"] = payload.get("to")
        cur["updated"] = payload.get("now") or cur.get("updated")
        _TICKET_PROJECT[str(cur.get("id") or "")] = str(cur.get("project") or "")
        effects.append({"kind": "write", "module": "agent/tickets",
                        "path": _ticket_path(ctx, cur.get("id"), cur.get("project")), "value": cur})
        moved.append(cur.get("id"))
    return {"from": payload.get("from"), "to": payload.get("to"),
            "tickets": moved, "effects": effects}


def _route_stall_scan(ctx, payload):
    """停滞扫描闭环：开关/阈值/上限/是否开单由需求层从配置传入；遍历判定归本能力。"""
    now = ctx.api.call("clock.now", {}, caller=None)
    if not bool(payload.get("enabled")):
        return ctx.api.call("ops.assemble", {"parts": {"scan": [], "at": now.get("ts")}},
                            caller=None)
    paths = _cfg_paths(ctx)
    rows = ctx.api.call("store.walk", {"module": "agent/tickets", "root": paths.get("root") or "",
                                       "pattern": paths.get("walk_glob") or ""}, caller=None)
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
        tpl_title = _msg_tpl(ctx).get("audit_title") or ""
        tpl_goal = _msg_tpl(ctx).get("audit_goal") or ""
        for tid in hot[:max_per_scan]:
            # 审计单后台派发：扫描线程不占线等嵌套需求收口，避免执行器线程被回投 loop 阻塞。
            ctx.runtime.dispatch({
                "demand": "ticket-create",
                "key": "audit-" + str(tid),
                "input": {
                    "title": tpl_title.format(id=tid) if tpl_title else "",
                    "goal": tpl_goal.format(id=tid) if tpl_goal else "",
                    "kind": "stall-audit", "auto_retrospective": False}})
    return ctx.api.call("ops.assemble", {"parts": {"scan": hot, "at": now.get("ts")}},
                        caller=None)

