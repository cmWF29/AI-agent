"""会话模块：会话记录的纯计算与拼装。

本模块不留副作用：要写的东西算成 effects 交出去，由需求调 runtime.apply 落地；
要再驱动别的需求，也由需求自己编排。人设来源的分岔仍在这里（控制流下沉能力）。
"""
from __future__ import annotations

from .private import _pure, _run_pure


def setup(ctx):
    # 通知型：一轮收尾后的校验/回催/复盘不阻塞响应，写完再派发
    ctx.hooks.point("sessions.finished", ("id", "kind", "role", "ticket"), defer=True)
    pairs = [
        ("sessions.build", _pure.build),
        ("sessions.refresh_constraint_message", _pure.refresh_constraint_message),
        ("sessions.inject_assigned_message", _pure.inject_assigned_message),
        ("sessions.view", _pure.view),
        ("sessions.members", _pure.members),
        ("sessions.present", _pure.present),
        ("sessions.screen", _pure.screen),
        ("sessions.gone", _pure.gone),
        ("sessions.record_path", _pure.record_path),
        ("sessions.role_name", _pure.role_name),
        ("sessions.compact", _pure.compactp),
        ("sessions.appendmsg", _run_pure.appendmsg),
        ("sessions.mark", _run_pure.mark),
        ("sessions.finish", _run_pure.finish),
        ("sessions.machine_apply", _pure.machine_applyp),
        ("sessions.reply", _run_pure.reply),
        ("sessions.statsp", _run_pure.statsp),
        ("sessions.flow_plan", _run_pure.flow_plan),
        ("sessions.resume_plan", _run_pure.resume_plan),
        ("sessions.stuck_plan", _run_pure.stuck_plan),
        ("sessions.active_same_role", _run_pure.active_same_role),
        ("sessions.wire_at", _pure.wire_at),
    ]
    for name, fn in pairs:
        ctx.api.register(name, _as_handler(fn), module="sessions")
    ctx.api.register("sessions.spawn", _route_spawn,
                     "造会话：取人设与知识拼记录，写入算成效果交出去", module="sessions")
    ctx.api.register("sessions.emit_finished", _route_emit_finished,
                     "一轮收尾落盘后触发 finished 钩子，后续业务由需求编排", module="sessions")
    ctx.api.register("sessions.ensure", _route_ensure,
                     "幂等造全局岗位会话：按 role+purpose 复用，没有才 spawn", module="sessions")
    ctx.api.register("sessions.talk", _route_talk,
                     "全局岗位会话对话：追加 human 并后台派发 session-run", module="sessions")
    ctx.api.register("sessions.by_ticket", _route_by_ticket,
                     "按工单归集全部会话视图：PM 与角色会话同一群聊流", module="sessions")
    ctx.api.register("sessions.resume", _route_resume,
                     "启动续跑：遍历残留 running → 分类成形落盘/派发效果清单", module="sessions")
    ctx.api.register("sessions.scan_stuck", _route_scan_stuck,
                     "自愈扫描：僵死/停滞超阈值的 running 会话复位 idle，落盘效果交 apply",
                     module="sessions")
    return True


def start(ctx):
    """启动期只触发续跑需求；扫描、分类、落盘、派发都在需求编排里。失败不阻断启动。"""
    try:
        ctx.runtime.call("session-resume", {})
    except Exception:  # noqa: BLE001 —— 启动回收失败不得掀翻服务启动
        pass


def _route_resume(ctx, payload):
    """启动续跑闭环：遍历残留 running 会话 → 纯函数分类 → 成形落盘/派发效果清单。

    遍历读盘在能力内；写盘与后台派发交需求 runtime.apply。配置与文案由需求层读好传入。
    """
    listed = ctx.api.call("store.glob", {
        "module": "agent/logs",
        "pattern": _cfg_logs(ctx).get("session_glob") or ""}, caller=None)
    rows = []
    for rel in listed.get("items") or []:
        row = ctx.api.call("store.read", {
            "module": "agent/logs", "path": rel}, caller=None)
        if row.get("value"):
            rows.append({"path": rel, "rec": row["value"]})
    now = ctx.api.call("clock.now", {}, caller=None)
    enabled = payload.get("enabled")
    enabled = True if enabled is None else bool(enabled)
    max_n = int(payload.get("max") or 5)
    plan = ctx.api.call("sessions.resume_plan", {
        "rows": rows, "now": now.get("ts"), "enabled": enabled, "max": max_n,
        "resume_text": payload.get("resume_text"),
        "stale_text": payload.get("stale_text")}, caller=None)
    effects = [{"kind": "write", "module": "agent/logs",
                "path": i["path"], "value": i["rec"]}
               for i in (plan.get("resume") or []) + (plan.get("stale") or [])]
    for i in plan.get("resume") or []:
        sid = i.get("id")
        if sid:
            effects.append({"kind": "dispatch", "id": "session-run",
                            "key": sid, "input": {"id": sid}})
    return {"effects": effects,
            "resumed": [i.get("id") for i in plan.get("resume") or []],
            "stale": [i.get("id") for i in plan.get("stale") or []]}


def _route_scan_stuck(ctx, payload):
    """自愈扫描闭环：对照运行表活跃任务与停滞阈值，僵死/超阈值的 running 会话复位 idle。

    遍历读盘、时钟换算在能力内；复位写盘交需求 runtime.apply。只复位不重跑，
    续跑交启动 resume 或人工触发。
    """
    listed = ctx.api.call("store.glob", {
        "module": "agent/logs",
        "pattern": _cfg_logs(ctx).get("session_glob") or ""}, caller=None)
    rows = []
    for rel in listed.get("items") or []:
        row = ctx.api.call("store.read", {"module": "agent/logs", "path": rel}, caller=None)
        rec = row.get("value")
        if not rec:
            continue
        idle = ctx.api.call("clock.since", {"iso": rec.get("updated")}, caller=None)
        rows.append({"path": rel, "rec": rec, "idle_seconds": idle.get("seconds") or 0})
    now = ctx.api.call("clock.now", {}, caller=None)
    enabled = payload.get("enabled")
    enabled = True if enabled is None else bool(enabled)
    plan = ctx.api.call("sessions.stuck_plan", {
        "rows": rows, "active": list(ctx.runtime.active_keys()),
        "now": now.get("ts"), "enabled": enabled,
        "idle_seconds": int(payload.get("idle_minutes") or 0) * 60,
        "stale_text": payload.get("stale_text")}, caller=None)
    effects = [{"kind": "write", "module": "agent/logs",
                "path": i["path"], "value": i["rec"]} for i in plan.get("stuck") or []]
    return {"effects": effects,
            "stuck": [i.get("id") for i in plan.get("stuck") or []],
            "keep": plan.get("keep") or []}


def _route_ensure(ctx, payload):
    """全局岗位会话幂等入口：同 role + meta.purpose 已有记录就复用，否则走统一 spawn。

    配置岗位不挂项目/工单，不能靠 active_same_role 的在途窗口；purpose 是长期键。
    """
    role = payload.get("role") or ""
    purpose = (payload.get("meta") or {}).get("purpose") or ""
    if not role or not purpose:
        raise ctx.ApiError("全局岗位会话缺少 role 或 purpose", code="bad_request", status=400)
    listed = ctx.api.call("store.glob", {
        "module": "agent/logs", "pattern": _cfg_logs(ctx).get("session_glob") or ""},
        caller=None)
    for rel in listed.get("items") or []:
        row = ctx.api.call("store.read", {"module": "agent/logs", "path": rel}, caller=None)
        rec = row.get("value") or {}
        meta = rec.get("meta") or {}
        if (rec.get("role") == role and rec.get("kind") == (payload.get("kind") or "role")
                and meta.get("purpose") == purpose and rec.get("status") != "gone"):
            view = ctx.api.call("sessions.view", {"rec": rec}, caller=None)
            view["rec"] = rec
            view["reused"] = True
            view["effects"] = []
            return view
    return _route_spawn(ctx, payload)


def _route_talk(ctx, payload):
    """配置者对话：人给的文本追加为 human，落盘后立即派发统一会话驱动。"""
    sid = str(payload.get("id") or "").strip()
    text = str(payload.get("text") or "").strip()
    if not sid:
        raise ctx.ApiError("缺少会话 id", code="bad_request", status=400)
    if not text:
        raise ctx.ApiError("消息内容不能为空", code="bad_request", status=400)
    path = _record_path(_cfg_logs(ctx), sid)
    row = ctx.api.call("store.read", {"module": "agent/logs", "path": path}, caller=None)
    if not row.get("value"):
        raise ctx.ApiError("会话不存在：" + sid, code="not_found", status=404)
    ctx.demand_engine.run_callable("session-send", {"id": sid, "text": text})
    ctx.runtime.dispatch({"demand": "session-run", "key": sid, "input": {"id": sid}})
    return {"ok": True, "id": sid}


def _route_by_ticket(ctx, payload):
    """按工单归集会话视图：有工单档案就只读已知的 PM/角色会话，不再扫全库日志。"""
    raw = payload.get("ticket")
    ticket = raw if isinstance(raw, dict) else {}
    tid = str(ticket.get("id") or ("" if ticket else raw) or "")
    known = []
    if ticket:
        known.append(ticket.get("pm"))
        known.extend((r or {}).get("session") or (r or {}).get("id")
                     for r in ticket.get("roles") or [])
        known = [str(x) for x in known if x]
    items, seen = [], set()
    if known:
        tpl = _cfg_logs(ctx).get("session") or "s/{id}.yaml"
        for sid in known:
            if sid in seen:
                continue
            seen.add(sid)
            row = ctx.api.call("store.read", {"module": "agent/logs",
                                              "path": tpl.format(id=sid)}, caller=None)
            rec = row.get("value")
            if not rec or (tid and rec.get("ticket") != tid):
                continue
            items.append(ctx.api.call("sessions.view", {"rec": rec}, caller=None))
        return {"items": items}
    listed = ctx.api.call("store.glob", {
        "module": "agent/logs",
        "pattern": _cfg_logs(ctx).get("session_glob") or ""}, caller=None)
    for rel in listed.get("items") or []:
        row = ctx.api.call("store.read", {"module": "agent/logs",
                                          "path": rel}, caller=None)
        rec = row.get("value")
        if not rec or rec.get("ticket") != tid:
            continue
        items.append(ctx.api.call("sessions.view", {"rec": rec}, caller=None))
    return {"items": items}


def _route_emit_finished(ctx, payload):
    rec = payload.get("rec") or {}
    if getattr(ctx, "hooks", None) is not None:
        ctx.hooks.emit("sessions.finished", {
            "id": rec.get("id"), "kind": rec.get("kind"),
            "role": rec.get("role"), "ticket": rec.get("ticket")})
    return {"ok": True}


def _seq_of(kind, items):
    """同一 kind 的会话序号：拿已有最大值 + 1，绝不复用已有会话 id。"""
    best = 0
    for rel in items or []:
        name = str(rel).rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if not name.startswith((kind or "role") + "-"):
            continue
        tail = name[len(kind) + 1:]
        if tail.isdigit():
            best = max(best, int(tail))
    return best + 1


def _role_guard(ctx, payload):
    """项目覆盖层禁用岗位就不许再拉这条线：岗位启停必须与派单联动，否则禁用只是展示。

    内置只读/系统岗位恒定受保护，项目禁用标记对它们无效。
    """
    role = payload.get("role") or ""
    project = payload.get("project") or ""
    if not role or not project or (payload.get("kind") or "role") != "role":
        return ""
    # 项目档案由编排层读好传进来（sessions 不越权去碰 projects 目录），这里只做裁决。
    ov = payload.get("project_overrides") or {}
    if role not in set(ov.get("roles") or []):
        return ""
    # 内置系统/只读岗位恒定受保护：岗位属性由编排层从契约里取出传进来，模块不读库。
    if payload.get("role_system") or payload.get("role_readonly"):
        return ""
    tpl = _msg_tpl(ctx).get("role_disabled") or ""
    return tpl.format(role=role, project=project) if tpl else ""


def _route_spawn(ctx, payload):
    """造会话：幂等键只做互斥闸（同工单同岗同类型在并发时只放一个进去），
    重复/重放交给下面 `_spawn` 自带的在途复用判定，不在这里丢弃工作。"""
    sig = "|".join([str(payload.get("ticket") or ""), str(payload.get("role") or ""),
                    str(payload.get("kind") or "role")])
    key = str(ctx.api.call("codec.digest", {"text": sig}, caller=None).get("hex") or "")[:40]
    claim = ctx.api.call("store.claim", {
        "module": "agent/sessions", "bucket": "spawn", "key": key,
        "route": "sessions.spawn", "scope": str(payload.get("ticket") or ""),
        "lease_seconds": 300}, caller=None)
    if not claim.get("claimed") and claim.get("status") == "abandoned":
        raise ctx.ApiError("会话创建已中止，需人工处置", code="idem_abandoned", status=409)
    rec = _spawn(ctx, payload)
    if claim.get("claimed"):
        ctx.api.call("store.settle", {
            "module": "agent/sessions", "bucket": "spawn", "key": key,
            "status": "done", "result_digest": str(rec.get("id") or "")}, caller=None)
    return rec


def _spawn(ctx, payload):
    """造会话：人设两路来源（岗位提示词 / 内置提示词文件）在这里选，知识注入由需求给。

    幂等收口：同工单同岗已有在途会话（queued/running/stalled）时复用已有会话，
    不重复建档、不落盘新记录；重复触发/编排重试不会并出第二条同岗线。
    """
    kind = payload.get("kind") or "role"
    tpl = _msg_tpl(ctx)
    guard = _role_guard(ctx, payload)
    if guard:
        raise ctx.ApiError(guard, code="role_disabled", status=403)
    logs_paths = _cfg_logs(ctx)
    prompt_paths = _cfg_prompt(ctx)
    listed = ctx.api.call("store.glob", {
        "module": "agent/logs",
        "pattern": logs_paths.get("session_glob") or ""}, caller=None)
    records = []
    for rel in listed.get("items") or []:
        row = ctx.api.call("store.read", {"module": "agent/logs",
                                          "path": rel}, caller=None)
        if row.get("value"):
            records.append(row["value"])
    dups = ctx.api.call("sessions.active_same_role", {
        "ticket": payload.get("ticket"), "role": payload.get("role"),
        "records": records}, caller=None).get("items") or []
    if dups:
        rec = dups[0]
        view = ctx.api.call("sessions.view", {"rec": rec}, caller=None)
        view["rec"] = rec
        view["reused"] = True
        view["duplicate"] = True
        view["effects"] = []
        return view
    nid = ctx.api.call("store.id", {"value": payload.get("name")}, caller=None)
    tid = ctx.api.call("store.id", {"value": payload.get("ticket")}, caller=None)
    role_prompt = payload.get("role_prompt") or None
    if not role_prompt:
        pt = prompt_paths.get("prompt") or ""
        row = ctx.api.call("store.read_text", {
            "module": "agent/sessions",
            "path": pt.format(kind=kind) if pt else kind}, caller=None)
        role_prompt = row.get("value") or ""
    baseline = _seq_of(kind, listed.get("items")) - 1
    seq = payload.get("seq") or ctx.api.call("store.next_seq", {
        "bucket": "session:" + kind, "baseline": baseline}, caller=None).get("seq")
    now = ctx.api.call("clock.now", {}, caller=None)
    meta = dict(payload.get("meta") or {})
    if payload.get("tools"):
        meta["tools"] = payload.get("tools")
    if payload.get("machine"):
        meta["machine"] = payload.get("machine")
    if payload.get("flow"):
        meta["flow"] = payload.get("flow")
    if payload.get("active"):
        meta["active"] = payload.get("active")
    if payload.get("stages"):
        meta["stages"] = payload.get("stages")
    if payload.get("stage"):
        meta["stage"] = payload.get("stage")
    rec = ctx.api.call("sessions.build", {
        "kind": kind, "seq": seq,
        "name": nid.get("id"), "ticket": payload.get("ticket"),
        "role": payload.get("role"), "project": payload.get("project"),
        "max_steps": payload.get("max_steps"), "meta": meta,
        "prompt": role_prompt,
        "constraint": payload.get("constraint"),
        "injected": payload.get("injected") or "",
        "prefix": tpl.get("common_prompt") or "", "task": payload.get("task"), "intro": payload.get("intro"),
        "now": now.get("ts")}, caller=None)
    view = ctx.api.call("sessions.view", {"rec": rec}, caller=None)
    view["rec"] = rec
    rel_path = _record_path(logs_paths, rec.get("id") or "")
    body_effect = {"kind": "write", "module": "agent/logs",
                   "path": rel_path, "value": rec}
    log_rec = ctx.api.call("logs.record", {
        "path": rel_path, "kind": "session",
        "layer": "ticket" if rec.get("ticket") else "public",
        "project": rec.get("project") or "", "ticket": rec.get("ticket") or "",
        "name": rec.get("id") or ""}, caller=None)
    view["effects"] = [body_effect] + (log_rec.get("effects") or [])
    return view


def _as_handler(fn):
    def handler(ctx, payload):
        payload = dict(payload or {})
        if "tpl" not in payload:
            payload["tpl"] = _msg_tpl(ctx)
        if "paths" not in payload:
            payload["paths"] = _cfg_logs(ctx)
        return fn(payload)
    return handler


def _msg_tpl(ctx):
    row = ctx.api.call("store.read", {
        "module": "agent/sessions", "path": "messages.yaml"}, caller=None)
    return row.get("value") or {}


def _cfg_logs(ctx):
    row = ctx.api.call("config.get", {"key": "logs.paths"}, caller=None)
    return row.get("value") or {}


def _cfg_prompt(ctx):
    row = ctx.api.call("config.get", {"key": "sessions.paths"}, caller=None)
    return row.get("value") or {}


def _record_path(paths, sid):
    t = (paths or {}).get("session") or ""
    return t.format(id=sid) if t else sid
