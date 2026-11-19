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
        ("sessions.view", _pure.view),
        ("sessions.present", _pure.present),
        ("sessions.screen", _pure.screen),
        ("sessions.gone", _pure.gone),
        ("sessions.record_path", _pure.record_path),
        ("sessions.role_name", _pure.role_name),
        ("sessions.compact", _pure.compactp),
        ("sessions.appendmsg", _run_pure.appendmsg),
        ("sessions.mark", _run_pure.mark),
        ("sessions.finish", _run_pure.finish),
        ("sessions.reply", _run_pure.reply),
        ("sessions.statsp", _run_pure.statsp),
        ("sessions.flow_plan", _run_pure.flow_plan),
        ("sessions.resume_plan", _run_pure.resume_plan),
    ]
    for name, fn in pairs:
        ctx.api.register(name, _as_handler(fn), module="sessions")
    ctx.api.register("sessions.spawn", _route_spawn,
                     "造会话：取人设与知识拼记录，写入算成效果交出去", module="sessions")
    ctx.api.register("sessions.emit_finished", _route_emit_finished,
                     "一轮收尾落盘后触发 finished 钩子，后续业务由需求编排", module="sessions")
    ctx.api.register("sessions.by_ticket", _route_by_ticket,
                     "按工单归集全部会话视图：PM 与角色会话同一群聊流", module="sessions")
    ctx.api.register("sessions.resume", _route_resume,
                     "启动续跑：遍历残留 running → 分类成形落盘/派发效果清单", module="sessions")
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
            "resumed": [i["id"] for i in plan.get("resume") or []],
            "stale": [i["id"] for i in plan.get("stale") or []]}


def _route_by_ticket(ctx, payload):
    """按工单 id 归集本工单全部会话视图；遍历与读盘在闭环内，成形交 sessions.view。"""
    tid = payload.get("ticket") or ""
    listed = ctx.api.call("store.glob", {
        "module": "agent/logs",
        "pattern": _cfg_logs(ctx).get("session_glob") or ""}, caller=None)
    items = []
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


def _route_spawn(ctx, payload):
    """造会话：人设两路来源（岗位提示词 / 内置提示词文件）在这里选，知识注入由需求给。"""
    kind = payload.get("kind") or "role"
    tpl = _msg_tpl(ctx)
    logs_paths = _cfg_logs(ctx)
    prompt_paths = _cfg_prompt(ctx)
    nid = ctx.api.call("store.id", {"value": payload.get("name")}, caller=None)
    tid = ctx.api.call("store.id", {"value": payload.get("ticket")}, caller=None)
    role_prompt = payload.get("role_prompt") or None
    if not role_prompt:
        pt = prompt_paths.get("prompt") or ""
        row = ctx.api.call("store.read_text", {
            "module": "agent/sessions",
            "path": pt.format(kind=kind) if pt else kind}, caller=None)
        role_prompt = row.get("value") or ""
    listed = ctx.api.call("store.glob", {
        "module": "agent/logs",
        "pattern": logs_paths.get("session_glob") or ""}, caller=None)
    baseline = _seq_of(kind, listed.get("items")) - 1
    seq = payload.get("seq") or ctx.api.call("store.next_seq", {
        "bucket": "session:" + kind, "baseline": baseline}, caller=None).get("seq")
    now = ctx.api.call("clock.now", {}, caller=None)
    meta = dict(payload.get("meta") or {})
    if payload.get("tools"):
        meta["tools"] = payload.get("tools")
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
