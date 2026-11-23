"""定时器模块：项目→工单架构上的跨期调度。

职责：LLM/秘书按项目（或工单内岗位）作用域登记 once/cron 定时器；后台循环按
tick_interval_s 扫描，到期槽位幂等触发——notify 进项目秘书队列，spawn_ticket 建工单。
失败落 last_run 并保留槽位重试，不静默丢；所有越权读写写审计台账。

本模块不留副作用：新状态算成 write/append effect 交需求 runtime.apply 落地。
"""
from __future__ import annotations

import threading

from .private import _pure

_MODULE = "agent/timer"


def setup(ctx):
    pairs = [
        ("timer.create", _route_create),
        ("timer.list", _route_list),
        ("timer.index", _route_index),
        ("timer.update", _route_update),
        ("timer.pause", _route_pause),
        ("timer.resume", _route_resume),
        ("timer.toggle", _route_toggle),
        ("timer.delete", _route_delete),
        ("timer.tick", _route_tick),
        ("timer.history", _route_history),
    ]
    for name, fn in pairs:
        ctx.api.register(name, fn, _doc(name), module="timer")
    _register_tools(ctx)
    return True


def start(ctx):
    """上线入口：拉起后台扫描循环；启动即按 next_at 与 max_catchup 补触发漏跑槽位。"""
    cfg = _cfg(ctx)
    interval = int(cfg.get("tick_interval_s") or 30)

    def _loop():
        while True:
            try:
                res = ctx.api.call("timer.tick", {}, caller=None)
                effects = res.get("effects") or []
                if effects:
                    ctx.runtime.apply({"effect": effects})
            except Exception:  # noqa: BLE001 —— 扫描失败不得掀翻后台循环
                pass
            ctx.api.call("clock.sleep", {"seconds": interval}, caller=None)

    thread = threading.Thread(target=_loop, daemon=True, name="timer-tick")
    thread.start()
    return True


# ---------------------------------------------------------------- 配置与文案

def _cfg(ctx):
    row = ctx.api.call("config.get", {"key": "timer"}, caller=None)
    return row.get("value") or {}


def _msg(ctx):
    row = ctx.api.call("store.read", {"module": _MODULE, "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def _doc(name):
    return {
        "timer.create": "建定时器：作用域守卫→配额→幂等去重→推算下次触发",
        "timer.list": "定时器列表：先按作用域过滤再返回",
        "timer.index": "定时器聚合：统计条数 + 列表行",
        "timer.update": "改定时器：标题/表达式/时区/动作/工单/岗位，改完重排下次触发",
        "timer.pause": "暂停定时器：active → paused",
        "timer.resume": "恢复定时器：paused → active 并重排下次触发",
        "timer.toggle": "暂停/恢复翻转：按当前状态落 pause 或 resume",
        "timer.delete": "删除定时器：记录与执行审计一并清除",
        "timer.tick": "扫描到期槽位：幂等触发，失败保留重试",
        "timer.history": "某定时器最近执行结果与审计条目",
    }.get(name, "")


# ---------------------------------------------------------------- 存储读写

def _record_path(project, tid):
    return "projects/%s/timers.yaml" % project


def _runs_path(project, tid):
    return "projects/%s/runs/%s.jsonl" % (project, tid)


def _load_records(ctx, project=None):
    listed = ctx.api.call("store.glob", {"module": _MODULE,
                                         "pattern": "projects/*/timers.yaml"}, caller=None)
    records = []
    for rel in listed.get("items") or []:
        row = ctx.api.call("store.read", {"module": _MODULE, "path": rel}, caller=None)
        items = (row.get("value") or {}).get("items") or []
        for rec in items:
            if project and rec.get("project") != project:
                continue
            records.append(rec)
    return records


def _find(ctx, tid):
    for rec in _load_records(ctx):
        if rec.get("id") == tid:
            return rec
    return None


def _write_effect(project, records):
    return {"kind": "write", "module": _MODULE,
            "path": _record_path(project, records[0].get("id") if records else ""),
            "value": {"items": records}}


def _json_line(ctx, entry):
    out = ctx.api.call("codec.json_encode", {"value": entry}, caller=None)
    return (out.get("text") or "") + "\n"


def _audit_effect(ctx, entry):
    return {"kind": "append_text", "module": _MODULE, "path": "audit.jsonl",
            "text": _json_line(ctx, entry)}


def _audit(ctx, caller, action, rec, decision, reason):
    now = ctx.api.call("clock.now", {}, caller=None).get("ts")
    entry = {
        "at": now,
        "caller_scope": caller.get("scope"),
        "caller_session": caller.get("session"),
        "role": caller.get("role"),
        "action": action,
        "target_id": (rec or {}).get("id") or "",
        "target_project": (rec or {}).get("project") or caller.get("project"),
        "target_ticket": (rec or {}).get("ticket") or caller.get("ticket"),
        "decision": decision,
        "reason": reason or "",
    }
    return [_audit_effect(ctx, entry)]


def _err(code, status, message):
    return {"ok": False, "code": code, "status": status, "error": message}


# ---------------------------------------------------------------- 路由

def _route_create(ctx, payload):
    payload = dict(payload or {})
    caller = _pure.normalize_caller(payload)
    tpl = _msg(ctx)
    cfg = _cfg(ctx)

    # 作用域守卫：global 可跨项目；project/ticket 只能落自己名下
    if caller["scope"] != "global":
        if caller["project"] != str(payload.get("project") or ""):
            effects = _audit(ctx, caller, "create", None, "deny", "cross_project")
            return {**_err("forbidden_scope", 403, tpl.get("forbidden_scope") or ""),
                    "effects": effects}
        if caller["scope"] == "ticket" and caller["ticket"] != str(payload.get("ticket") or ""):
            effects = _audit(ctx, caller, "create", None, "deny", "cross_ticket")
            return {**_err("forbidden_scope", 403, tpl.get("forbidden_scope") or ""),
                    "effects": effects}

    all_records = _load_records(ctx)
    records = [r for r in all_records if r.get("project") == payload.get("project")]
    quota = _pure.quota_check(records, cfg)
    if quota["ok"] is False:
        effects = _audit(ctx, caller, "create", None, "deny", quota["code"])
        return {**_err(quota["code"], 409, tpl.get("quota_exceeded") or ""), "effects": effects}

    signature = _pure.idem_signature(payload)
    for rec in records:
        if rec.get("signature") == signature:
            effects = _audit(ctx, caller, "create", rec, "allow", "deduped")
            view = _pure.view_row(rec)
            return {"ok": True, "id": rec.get("id"), "next_at": rec.get("next_at"),
                    "tz": rec.get("tz"), "status": rec.get("status"),
                    "deduped": True, "view": view, "effects": effects}

    now = ctx.api.call("clock.now", {}, caller=None).get("ts")
    schedule = ctx.clock.schedule_next({
        "kind": payload.get("kind"), "expr": payload.get("expr"),
        "tz": payload.get("tz"), "after": now,
        "min_interval_s": cfg.get("min_interval_s")})
    spec = _pure.validate_spec(payload, schedule)
    if spec["ok"] is False:
        effects = _audit(ctx, caller, "create", None, "deny", spec["code"])
        return {**_err(spec["code"], 400, tpl.get(spec["code"]) or ""), "effects": effects}

    seq = ctx.api.call("store.next_seq", {
        "bucket": "timer", "baseline": _baseline(all_records)},
        caller=None).get("seq")
    tid = "tm-%04d" % int(seq or 1)
    rec = {
        "id": tid,
        "project": payload.get("project"),
        "ticket": payload.get("ticket") or "",
        "title": payload.get("title"),
        "kind": payload.get("kind"),
        "expr": payload.get("expr"),
        "tz": payload.get("tz") or cfg.get("default_tz") or "Asia/Shanghai",
        "action": payload.get("action"),
        "role": payload.get("role") or "",
        "payload": payload.get("payload") or {},
        "creator_session": caller["session"],
        "created_by": caller["role"],
        "creator": payload.get("creator") or caller["role"],
        "source_session": payload.get("source_session") or caller["session"],
        "status": "active",
        "next_at": spec.get("next_at"),
        "last_run": None,
        "attempts": 0,
        "fired": [],
        "signature": signature,
        "created": now,
        "updated": now,
    }
    records.append(rec)
    effects = [_write_effect(rec["project"], records)]
    effects += _audit(ctx, caller, "create", rec, "allow", "create")
    return {"ok": True, "id": tid, "next_at": rec["next_at"], "tz": rec["tz"],
            "status": rec["status"], "deduped": False,
            "view": _pure.view_row(rec), "effects": effects}


def _baseline(records):
    best = 0
    for rec in records or []:
        name = str(rec.get("id") or "")
        if name.startswith("tm-"):
            tail = name[3:]
            if tail.isdigit():
                best = max(best, int(tail))
    return best


def _route_list(ctx, payload):
    payload = dict(payload or {})
    caller = _pure.normalize_caller(payload)
    records = _pure.filter_scope(_load_records(ctx, payload.get("project")), caller)
    if payload.get("id"):
        records = [r for r in records if r.get("id") == payload["id"]]
    rows = _pure.view_rows(records)
    return {"project": payload.get("project") or "", "total": len(rows), "items": rows}


def _route_index(ctx, payload):
    payload = dict(payload or {})
    caller = _pure.normalize_caller(payload)
    records = _pure.filter_scope(_load_records(ctx, payload.get("project")), caller)
    rows = _pure.view_rows(records)
    now = ctx.api.call("clock.now", {}, caller=None).get("ts")
    return {"total": len(rows), "rows": rows, "counts": _pure.index_stats(rows, now)}


def _authorize_load(ctx, payload, action):
    caller = _pure.normalize_caller(payload)
    rec = _find(ctx, payload.get("id"))
    if rec is None:
        return caller, None, _err("not_found", 404, _msg(ctx).get("missing") or "")
    verdict = _pure.authorize(caller, rec, action)
    if verdict["ok"] is False:
        effects = _audit(ctx, caller, action, rec, "deny", verdict["reason"])
        return caller, rec, {**_err(verdict["code"], 403, _msg(ctx).get("forbidden_scope") or ""),
                             "effects": effects}
    return caller, rec, None


def _route_update(ctx, payload):
    payload = dict(payload or {})
    caller, rec, denied = _authorize_load(ctx, payload, "update")
    if denied:
        return denied
    cfg = _cfg(ctx)
    now = ctx.api.call("clock.now", {}, caller=None).get("ts")
    edits = ("title", "expr", "tz", "action", "ticket", "role")
    for key in edits:
        if payload.get(key) is not None:
            rec[key] = payload[key]
    schedule = ctx.clock.schedule_next({
        "kind": rec.get("kind"), "expr": rec.get("expr"), "tz": rec.get("tz"),
        "after": now, "min_interval_s": cfg.get("min_interval_s")})
    spec = _pure.validate_spec(rec, schedule)
    if spec["ok"] is False:
        effects = _audit(ctx, caller, "update", rec, "deny", spec["code"])
        return {**_err(spec["code"], 400, _msg(ctx).get(spec["code"]) or ""), "effects": effects}
    rec["next_at"] = spec.get("next_at")
    rec["updated"] = now
    records = _load_records(ctx, rec["project"])
    records = [r for r in records if r.get("id") != rec["id"]] + [rec]
    effects = [_write_effect(rec["project"], records)]
    effects += _audit(ctx, caller, "update", rec, "allow", "update")
    return {"ok": True, "id": rec["id"], "next_at": rec["next_at"],
            "status": rec["status"], "effects": effects}


def _route_pause(ctx, payload):
    caller, rec, denied = _authorize_load(ctx, payload, "pause")
    if denied:
        return denied
    now = ctx.api.call("clock.now", {}, caller=None).get("ts")
    rec["status"] = "paused"
    rec["updated"] = now
    records = _load_records(ctx, rec["project"])
    records = [r for r in records if r.get("id") != rec["id"]] + [rec]
    effects = [_write_effect(rec["project"], records)]
    effects += _audit(ctx, caller, "pause", rec, "allow", "pause")
    return {"ok": True, "id": rec["id"], "status": rec["status"], "effects": effects}


def _route_resume(ctx, payload):
    caller, rec, denied = _authorize_load(ctx, payload, "resume")
    if denied:
        return denied
    cfg = _cfg(ctx)
    now = ctx.api.call("clock.now", {}, caller=None).get("ts")
    schedule = ctx.clock.schedule_next({
        "kind": rec.get("kind"), "expr": rec.get("expr"), "tz": rec.get("tz"),
        "after": now, "min_interval_s": cfg.get("min_interval_s")})
    if schedule.get("ok"):
        rec["next_at"] = schedule.get("ts")
    rec["status"] = "active"
    rec["updated"] = now
    records = _load_records(ctx, rec["project"])
    records = [r for r in records if r.get("id") != rec["id"]] + [rec]
    effects = [_write_effect(rec["project"], records)]
    effects += _audit(ctx, caller, "resume", rec, "allow", "resume")
    return {"ok": True, "id": rec["id"], "status": rec["status"], "effects": effects}


def _route_toggle(ctx, payload):
    action = str(payload.get("action") or "")
    if action == "pause":
        return _route_pause(ctx, payload)
    if action == "resume":
        return _route_resume(ctx, payload)
    return _err("bad_action", 400, _msg(ctx).get("bad_action") or "")


def _route_delete(ctx, payload):
    caller, rec, denied = _authorize_load(ctx, payload, "delete")
    if denied:
        return denied
    effects = [
        {"kind": "remove", "module": _MODULE, "path": _record_path(rec["project"], rec["id"])},
        {"kind": "remove_dir", "module": _MODULE,
         "path": "projects/%s/runs/%s" % (rec["project"], rec["id"])},
    ]
    effects += _audit(ctx, caller, "delete", rec, "allow", "delete")
    return {"ok": True, "id": rec["id"], "status": "deleted", "effects": effects}


def _route_tick(ctx, payload):
    payload = dict(payload or {})
    cfg = _cfg(ctx)
    max_catchup = int(cfg.get("max_catchup") or 5)
    now = payload.get("now") or ctx.api.call("clock.now", {}, caller=None).get("ts")
    records = [r for r in _load_records(ctx) if r.get("status") == "active"]
    fired, skipped = [], []
    effects = []

    for rec in records:
        last = rec.get("last_run") or {}
        after = last.get("at") or rec.get("created") or 0
        due = ctx.clock.due_slots({
            "kind": rec.get("kind"), "expr": rec.get("expr"), "tz": rec.get("tz"),
            "after": after, "now": now, "limit": max_catchup})
        if not due.get("ok"):
            skipped.append({"id": rec.get("id"), "slot": None, "reason": due.get("code")})
            continue
        pending = _pure.due_select(rec, due.get("slots"), rec.get("fired"), max_catchup)
        if not pending:
            continue
        for slot in pending:
            outcome, ok, detail = _trigger(ctx, rec, slot)
            rec["attempts"] = int(rec.get("attempts") or 0) + 1
            rec["last_run"] = {"at": now, "ok": ok, "detail": detail,
                               "attempt": rec["attempts"]}
            entry = _pure.run_record(rec, slot, ok, detail, rec["attempts"], now,
                                     rec.get("action"))
            effects.append({"kind": "append_text", "module": _MODULE,
                            "path": _runs_path(rec["project"], rec["id"]),
                            "text": _json_line(ctx, entry)})
            if ok:
                rec["fired"].append(slot)
                if rec.get("kind") == "once":
                    rec["status"] = "done"
                else:
                    nxt = ctx.clock.schedule_next({
                        "kind": rec.get("kind"), "expr": rec.get("expr"),
                        "tz": rec.get("tz"), "after": now,
                        "min_interval_s": cfg.get("min_interval_s")})
                    if nxt.get("ok"):
                        rec["next_at"] = nxt.get("ts")
                fired.append({"id": rec["id"], "slot": slot, "outcome": outcome})
            else:
                skipped.append({"id": rec["id"], "slot": slot, "reason": detail})
        records_all = _load_records(ctx, rec["project"])
        records_all = [r for r in records_all if r.get("id") != rec["id"]] + [rec]
        effects.append(_write_effect(rec["project"], records_all))

    return {"fired": fired, "skipped": skipped, "effects": effects}


def _trigger(ctx, rec, slot):
    """到期触发：notify 进秘书队列；spawn_ticket 建工单。返回 (outcome, ok, detail)。"""
    tpl = _msg(ctx)
    msg_id = "timer:%s:%s" % (rec["id"], slot)
    try:
        if rec.get("action") == "notify":
            res = ctx.api.call("secretary.push", {
                "project": rec["project"], "msg_id": msg_id,
                "text": (rec.get("payload") or {}).get("text") or rec.get("title"),
                "fields": {"source": "timer", "timer_id": rec["id"], "slot": slot,
                           "title": rec.get("title")},
                "source": "timer", "timer_id": rec["id"], "slot": slot}, caller=None)
            ok = bool(res.get("ok", True))
            return "notify_pushed", ok, "" if ok else tpl.get("trigger_failed") or "notify 入队失败"
        meta = {"source": "timer", "timer_id": rec["id"], "slot": slot}
        res = ctx.api.call("tickets.create", {
            "title": rec.get("title"),
            "goal": (rec.get("payload") or {}).get("goal") or rec.get("title"),
            "project": rec["project"], "role": rec.get("role"), "meta": meta}, caller=None)
        ok = bool(res.get("ok", True))
        tid = (res or {}).get("id") or ""
        return "ticket_created", ok, tid if ok else (tpl.get("trigger_failed") or "建工单失败")
    except Exception as exc:  # noqa: BLE001 —— 触发失败落 last_run 保留重试，不吞掉
        return "failed", False, str(exc)


def _route_history(ctx, payload):
    payload = dict(payload or {})
    caller, rec, denied = _authorize_load(ctx, payload, "history")
    if denied:
        return denied
    limit = int(payload.get("limit") or 20)
    row = ctx.api.call("store.read_text", {"module": _MODULE,
                                           "path": _runs_path(rec["project"], rec["id"])},
                       caller=None)
    history = []
    for line in str(row.get("value") or "").splitlines():
        if not line.strip():
            continue
        dec = ctx.api.call("codec.json_decode", {"text": line}, caller=None)
        if dec.get("ok"):
            history.append(dec["value"])
    history = history[-limit:]
    return {"id": rec["id"], "project": rec["project"],
            "last_run": rec.get("last_run"), "history": history}


# ---------------------------------------------------------------- 工具接线

def _register_tools(ctx):
    tools = getattr(ctx, "tools", None)
    if tools is None:
        return
    tpl = _msg(ctx)
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
        tools.register(name, tpl.get(desc_key) or "", params,
                       _tool_fn(route), module="timer", kinds=["pm", "secretary"],
                       builtin=True)


def _tool_fn(route):
    def fn(ctx, args, session=None):
        caller = _session_caller(session)
        payload = dict(args or {})
        payload["project"] = caller["project"]
        payload["caller"] = caller
        return ctx.api.call(route, payload, caller=None)
    return fn


def _session_caller(session):
    """会话上下文 → 权限调用方；作用域与项目/工单取会话记录，模型参数不可改写。"""
    s = session or {}
    ticket = s.get("ticket") or ""
    scope = "ticket" if ticket else "project"
    return {"scope": scope, "project": s.get("project") or "", "ticket": ticket,
            "session": s.get("id") or "", "role": s.get("role") or "",
            "kind": s.get("kind") or ""}
