"""项目秘书模块：项目级自然语言路由与消息队列。

职责：用户零散表述先入项目秘书队列；秘书空闲后取整批一起理解、按后发优先合并冲突，
形成一份需求再经既有 tickets.create 建单分派；不一条消息建一张单。

本模块不留副作用：新队列状态算成 write effect 交需求 runtime.apply 落地；建单走
ticket-create 需求（项目守卫与 PM 拉起都在 tickets.create 能力内），不绕过。
"""
from __future__ import annotations

from .private import _pure


def setup(ctx):
    ctx.api.register("secretary.push", _route_push,
                     "消息入队：项目守卫→幂等入队→回队列视图与落盘效果", module="secretary")
    ctx.api.register("secretary.flush", _route_flush,
                     "批量处理：取整批→后发优先合并→一次建单→回填；失败回滚保留队列",
                     module="secretary")
    ctx.api.register("secretary.list", _route_list,
                     "队列与批次只读视图数据", module="secretary")
    ctx.api.register("secretary.discard", _route_discard,
                     "撤回一条消息：pending/processing -> discarded", module="secretary")
    ctx.api.register("secretary.status", _route_status,
                     "队列状态机：状态枚举与合法迁移", module="secretary")
    ctx.api.register("secretary.timers", _route_timers,
                     "本项目定时器只读列表：project  scope 隔离，转调 timer.list",
                     module="secretary")
    _register_timer_tools(ctx)
    return True


# ---------------------------------------------------------------- 定时器工具接线

def _session_caller(session):
    """会话上下文 → 权限调用方。工单内岗位走 ticket 作用域；秘书/PM 走 project 作用域。

    project/ticket 只取会话记录，模型参数不可改写作用域或跨项目指向。
    """
    s = session or {}
    ticket = s.get("ticket") or ""
    scope = "ticket" if ticket else "project"
    return {"scope": scope, "project": s.get("project") or "", "ticket": ticket,
            "session": s.get("id") or "", "role": s.get("role") or "",
            "kind": s.get("kind") or ""}


def _timer_tool(route):
    def fn(ctx, args, session=None):
        caller = _session_caller(session)
        payload = dict(args or {})
        payload["project"] = caller["project"]
        payload["caller"] = caller
        return ctx.api.call(route, payload, caller=None)
    return fn


def _register_timer_tools(ctx):
    # 直接读 ctx.tools（不用 getattr 字符串）：装配 DAG 静态扫描据此推导 tools 依赖边。
    tools = ctx.tools
    if tools is None:
        return
    tpl = _msg_tpl(ctx)
    specs = [
        ("timer_create", "timer.create", "tool_timer_create_desc", [
            {"name": "kind", "type": "string", "required": True,
             "desc": "once 一次性；cron 按周期重复"},
            {"name": "expr", "type": "string", "required": True,
             "desc": "cron 五段表达式；once 为触发时间"},
            {"name": "title", "type": "string", "required": True, "desc": "定时器标题"},
            {"name": "tz", "type": "string", "desc": "时区，如 Asia/Shanghai"},
            {"name": "action", "type": "string",
             "desc": "notify 进秘书队列；spawn_ticket 到点建工单"},
            {"name": "ticket", "type": "string", "desc": "关联工单（可选）"},
            {"name": "role", "type": "string", "desc": "目标岗位（可选）"},
        ]),
        ("timer_list", "timer.list", "tool_timer_list_desc", []),
        ("timer_pause", "timer.pause", "tool_timer_pause_desc", [
            {"name": "id", "type": "string", "required": True, "desc": "定时器 id"}]),
        ("timer_resume", "timer.resume", "tool_timer_resume_desc", [
            {"name": "id", "type": "string", "required": True, "desc": "定时器 id"}]),
        ("timer_delete", "timer.delete", "tool_timer_delete_desc", [
            {"name": "id", "type": "string", "required": True, "desc": "定时器 id"}]),
    ]
    for name, route, desc_key, params in specs:
        if tools.has(name):
            continue
        tools.register(name, tpl.get(desc_key) or "", params, _timer_tool(route),
                       module="secretary", kinds=["pm", "secretary"], builtin=True)


# ---------------------------------------------------------------- 配置与档案读取

def _msg_tpl(ctx):
    try:
        row = ctx.api.call("store.read", {
            "module": "agent/secretary", "path": "messages.yaml"}, caller=None)
        return row.get("value") or {}
    except Exception:  # noqa: BLE001 — 词表读不到不阻断结构化降级，退回空文案
        return {}


def _cfg_secretary_paths(ctx):
    row = ctx.api.call("config.get", {"key": "secretary.paths"}, caller=None)
    return row.get("value") or {}


def _cfg_project_paths(ctx):
    row = ctx.api.call("config.get", {"key": "projects.paths"}, caller=None)
    return row.get("value") or {}


def _path_for(ctx, project):
    tpl = _cfg_secretary_paths(ctx).get("record") or "projects/{project}/queue.yaml"
    return tpl.format(project=project)


def _project_state(ctx, project):
    name = str(project or "").strip()
    if not name:
        return {"archived": False, "exists": False, "roles": []}
    paths = _cfg_project_paths(ctx)
    tpl = paths.get("project_record") or paths.get("record") or ""
    rel = tpl.format(project=name, id=name) if tpl else name
    row = ctx.api.call("store.read", {
        "module": "agent/projects", "path": rel}, caller=None)
    raw = row.get("value")
    rec = raw if isinstance(raw, dict) else {}
    ov = (rec.get("overrides") or {})
    return {"archived": rec.get("archived") is True,
            "exists": raw is not None,
            "roles": [str(x) for x in (ov.get("roles") or [])]}


# ---------------------------------------------------------------- 状态读写

def _read_state(ctx, project):
    row = ctx.api.call("store.read", {
        "module": "agent/secretary", "path": _path_for(ctx, project)}, caller=None)
    rec = row.get("value")
    if not isinstance(rec, dict):
        rec = _pure.empty_state(project)
    rec.setdefault("project", project)
    rec.setdefault("messages", [])
    rec.setdefault("batches", [])
    return rec


def _write_effect(ctx, project, state):
    return {"kind": "write", "module": "agent/secretary",
            "path": _path_for(ctx, project), "value": state}


def _err(code, status, message):
    return {"ok": False, "code": code, "status": status, "error": message}


def _guard_project(ctx, project, tpl):
    if not project:
        return _err("missing_project", 400, tpl.get("missing_project") or "")
    proj = _project_state(ctx, project)
    if not proj["exists"]:
        return _err("missing_project", 404, tpl.get("missing_project") or "")
    if proj["archived"]:
        return _err("project_archived", 409, tpl.get("project_archived") or "")
    return None


# ---------------------------------------------------------------- 路由

def _route_push(ctx, payload):
    tpl = _msg_tpl(ctx)
    project = str(payload.get("project") or "").strip()
    guard = _guard_project(ctx, project, tpl)
    if guard is not None:
        return guard
    state = _read_state(ctx, project)
    now = ctx.api.call("clock.now", {}, caller=None)
    msg_id = str(payload.get("msg_id") or "").strip()
    if not msg_id:
        seq = ctx.api.call("store.next_seq", {
            "bucket": "secretary-msg:" + project, "baseline": 0}, caller=None).get("seq")
        msg_id = "m-%04d" % int(seq or 1)
    res = _pure.enqueue({
        "state": state,
        "msg_id": msg_id,
        "text": payload.get("text"),
        "fields": payload.get("fields"),
        "source": payload.get("source"),
        "timer_id": payload.get("timer_id"),
        "slot": payload.get("slot"),
        "at": now.get("ts"),
    })
    if not res["ok"]:
        tip = tpl.get("msg_id_missing") if res["code"] == "msg_id_missing" else tpl.get("empty_text")
        return _err(res["code"], 400, tip or "")
    view = _pure.queue_view({"state": state})
    return {"ok": True, "created": res["created"], "entry": res["entry"],
            "counts": view["counts"], "effects": [_write_effect(ctx, project, state)]}


def _assemble_goal(brief_b, tpl):
    lines = []
    if brief_b.get("background"):
        lines.append(brief_b["background"])
    if brief_b.get("goal"):
        lines.append(brief_b["goal"])
    if brief_b.get("acceptance"):
        lines.append(brief_b["acceptance"])
    if brief_b.get("constraints"):
        lines.append(brief_b["constraints"])
    if brief_b.get("priority"):
        lines.append(brief_b["priority"])
    return "\n".join(x for x in lines if x) or tpl.get("fallback_goal") or ""


def _route_flush(ctx, payload):
    tpl = _msg_tpl(ctx)
    project = str(payload.get("project") or "").strip()
    guard = _guard_project(ctx, project, tpl)
    if guard is not None:
        return guard
    state = _read_state(ctx, project)
    now = ctx.api.call("clock.now", {}, caller=None)
    seq = ctx.api.call("store.next_seq", {
        "bucket": "secretary-batch:" + project, "baseline": 0}, caller=None).get("seq")
    batch_id = "B-%04d" % int(seq or 1)
    claimed = _pure.claim_batch({
        "state": state, "batch_id": batch_id, "claimed_at": now.get("ts"),
        "roles_hint": payload.get("roles_hint")})
    if claimed["empty"]:
        return {"ok": True, "empty": True, "batch": {"batch_id": batch_id, "msg_ids": []},
                "effects": []}
    batch = claimed["batch"]
    entries = [m for m in state["messages"] if m.get("batch_id") == batch_id]
    merged = _pure.merge({"entries": entries})
    brief = _pure.to_brief({"merged": merged, "entries": entries})
    brief_b = brief["brief"]

    sig = project + "|" + batch_id
    key = str(ctx.api.call("codec.digest", {"text": sig}, caller=None).get("hex") or "")[:40]
    claim = ctx.api.call("store.claim", {
        "module": "agent/secretary", "bucket": "flush", "key": key,
        "route": "secretary.flush", "scope": project, "lease_seconds": 600}, caller=None)
    if not claim.get("claimed"):
        status = claim.get("status") or ""
        if status == "done":
            return {"ok": True, "reused": True, "batch": batch,
                    "ticket": claim.get("result_digest") or "", "effects": []}
        if status == "abandoned":
            return _err("idem_abandoned", 409, tpl.get("invalid_state") or "")
        return _err("idem_in_flight", 409, tpl.get("invalid_state") or "")

    title = str(brief_b.get("goal") or tpl.get("fallback_title") or "").strip()
    goal_text = _assemble_goal(brief_b, tpl)
    meta = {"secretary": {
        "batch_id": batch_id,
        "msg_ids": brief["msg_ids"],
        "brief": brief_b,
        "sources": brief["sources"],
    }}
    resp = {}
    try:
        resp = ctx.demand_engine.run_callable("ticket-create", {
            "title": title, "goal": goal_text, "project": project,
            "meta": meta, "auto_retrospective": False}) or {}
    except Exception as exc:  # 路由层异常：失败保留队列，回滚 pending、写 last_error
        _pure.mark_failed({"state": state, "batch_id": batch_id, "error": str(exc)})
        ctx.api.call("store.settle", {
            "module": "agent/secretary", "bucket": "flush", "key": key,
            "status": "failed", "error_code": type(exc).__name__}, caller=None)
        return {"ok": False, "code": "flush_failed", "error": str(exc),
                "batch": batch, "effects": [_write_effect(ctx, project, state)]}
    if not resp.get("ok"):
        failed = resp.get("failed") or {}
        err = failed.get("error") or failed.get("code") or "ticket-create failed"
        _pure.mark_failed({"state": state, "batch_id": batch_id, "error": str(err)})
        ctx.api.call("store.settle", {
            "module": "agent/secretary", "bucket": "flush", "key": key,
            "status": "failed", "error_code": str(failed.get("code") or "create_failed")},
            caller=None)
        return {"ok": False, "code": "flush_failed", "error": str(err),
                "batch": batch, "effects": [_write_effect(ctx, project, state)]}

    ticket = resp.get("result") or {}
    tid = str(ticket.get("id") or ticket.get("ticket") or "")
    if not tid:
        # 建单回包缺工单号：按失败回滚保留队列，不把"没建上单"记成已合并。
        _pure.mark_failed({"state": state, "batch_id": batch_id,
                           "error": "ticket-create 未返回工单 id"})
        ctx.api.call("store.settle", {
            "module": "agent/secretary", "bucket": "flush", "key": key,
            "status": "failed", "error_code": "missing_ticket_id"}, caller=None)
        return {"ok": False, "code": "flush_failed", "error": "建单回包缺工单号",
                "batch": batch, "effects": [_write_effect(ctx, project, state)]}
    _pure.mark_merged({"state": state, "batch_id": batch_id,
                       "ticket": tid, "merged_at": now.get("ts")})
    # claim_batch 必落批次记录，这里直接挂结构化 brief
    batch_rec = next(b for b in state["batches"] if b.get("batch_id") == batch_id)
    batch_rec["brief"] = brief_b
    batch_rec["sources"] = brief["sources"]
    ctx.api.call("store.settle", {
        "module": "agent/secretary", "bucket": "flush", "key": key,
        "status": "done", "result_digest": tid,
        "error_code": ""}, caller=None)
    view = _pure.queue_view({"state": state})
    return {"ok": True, "batch": batch, "ticket": tid,
            "counts": view["counts"], "effects": [_write_effect(ctx, project, state)]}


def _route_list(ctx, payload):
    project = str(payload.get("project") or "").strip()
    if not project:
        return _err("missing_project", 400, _msg_tpl(ctx).get("missing_project") or "")
    try:
        state = _read_state(ctx, project)
        view = _pure.queue_view({"state": state})
    except Exception as exc:  # noqa: BLE001 — 读档/成形异常不裸抛，结构化降级
        return {"ok": False, "code": "state_unavailable",
                "error": str(exc) or type(exc).__name__,
                "counts": {"pending": 0, "processing": 0, "merged": 0, "discarded": 0},
                "rows": [], "batches": [], "messages": [], "members": []}
    tpl = _msg_tpl(ctx)
    msgs = []
    for ev in view.pop("events", []):
        if ev.get("kind") == "message":
            text = ev.get("text") or ""
            msgs.append({"role": "user", "actor": "user", "kind": "human",
                         "text": text, "content": text, "at": ev.get("at"),
                         "msg_id": ev.get("msg_id"), "status": ev.get("status")})
            continue
        if ev.get("error"):
            text = str(tpl.get("chat_merge_failed") or "").format(error=ev.get("error") or "")
            role = "system"
        else:
            text = str(tpl.get("chat_merged") or "").format(n=ev.get("count") or 0)
            if ev.get("ticket"):
                text += str(tpl.get("chat_ticket") or "").format(ticket=ev.get("ticket") or "")
            if ev.get("goal"):
                text += str(tpl.get("chat_goal") or "").format(goal=ev.get("goal") or "")
            role = "secretary"
        msgs.append({"role": role, "actor": role, "kind": "assistant",
                     "text": text, "content": text, "at": ev.get("at"),
                     "batch_id": ev.get("batch_id")})
    view["messages"] = msgs
    view["members"] = [
        {"role": "user", "display": tpl.get("member_me") or "", "status": "active"},
        {"role": "secretary", "display": tpl.get("member_secretary") or "", "status": "active"},
    ]
    return {"ok": True, **view}


def _route_timers(ctx, payload):
    """本项目定时器只读代理：project 作用域隔离，转调 timer.list；越权/未就位不静默。"""
    tpl = _msg_tpl(ctx)
    project = str(payload.get("project") or "").strip()
    if not project:
        return _err("missing_project", 400, tpl.get("missing_project") or "")
    caller = {"scope": "project", "project": project, "ticket": "",
              "session": payload.get("session") or "", "role": "", "kind": "secretary"}
    try:
        res = ctx.api.call("timer.list",
                           {"project": project, "caller": caller}, caller=None) or {}
    except Exception as exc:  # timer 能力未就位或越权：回可见错误，列表不冒充有数据
        code = getattr(exc, "code", "") or "timer_unavailable"
        return {"ok": False, "items": [], "code": code, "error": str(exc)}
    return {"ok": True, "project": project, "items": res.get("items") or []}


def _route_discard(ctx, payload):
    tpl = _msg_tpl(ctx)
    project = str(payload.get("project") or "").strip()
    guard = _guard_project(ctx, project, tpl)
    if guard is not None:
        return guard
    state = _read_state(ctx, project)
    res = _pure.discard({"state": state, "msg_id": payload.get("msg_id")})
    if not res["ok"]:
        if res["code"] == "not_found":
            tip = tpl.get("not_found", "").format(id=payload.get("msg_id") or "")
        else:
            tip = tpl.get("invalid_state")
        return _err(res["code"], 409, tip or "")
    view = _pure.queue_view({"state": state})
    return {"ok": True, "entry": res["entry"], "counts": view["counts"],
            "effects": [_write_effect(ctx, project, state)]}


def _route_status(ctx, payload):
    tpl = _msg_tpl(ctx)
    project = str(payload.get("project") or "").strip()
    if not project:
        return _err("missing_project", 400, tpl.get("missing_project") or "")
    try:
        state = _read_state(ctx, project)
        return _pure.status_machine({"state": state, "msg_id": payload.get("msg_id")})
    except Exception as exc:  # noqa: BLE001 — 读档/成形异常不裸抛，结构化降级回包
        return {"ok": False, "code": "state_unavailable",
                "error": str(exc) or type(exc).__name__}
