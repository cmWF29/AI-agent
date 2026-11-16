"""会话模块：会话记录与运行的纯计算。读写、驱动、等待都在 session-* 需求里。"""
from __future__ import annotations

import threading

from .private import _pure, _run_pure

# 本进程内的运行登记表：sid -> 正在跑的线程。打断靠"置位 + 等它自己退"。
_RUNS = {}
_CANCEL = {}          # sid -> 打断时间戳；同一进程内可见，跨线程传递最快
_RUN_LOCK = threading.Lock()


def setup(ctx):
    pairs = [
        ("sessions.build", _pure.build),
        ("sessions.view", _pure.view),
        ("sessions.present", _pure.present),
        ("sessions.screen", _pure.screen),
        ("sessions.gone", _pure.gone),
        ("sessions.compact", _pure.compactp),
        ("sessions.appendmsg", _run_pure.appendmsg),
        ("sessions.mark", _run_pure.mark),
        ("sessions.finish", _run_pure.finish),
        ("sessions.reply", _run_pure.reply),
        ("sessions.statsp", _run_pure.statsp),
        ("sessions.cancelled", _pure_cancelled),
    ]
    for name, fn in pairs:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="sessions")
    ctx.api.register("sessions.spawn", _route_spawn, "造会话：人设+知识→拼系统消息→落盘→回执", module="sessions")
    ctx.api.register("sessions.dispatch", _route_dispatch,
                     "驱动会话：上一轮若在跑则先置打断，等它退出后再跑新一轮", module="sessions")
    return True


def _sess_path(sid):
    return "sessions/%s.yaml" % sid


def _now(ctx):
    return ctx.api.call("clock.now", {}, caller=None).get("ts")


def _pure_cancelled(p):
    """本轮是否已被打断：since 之后有人置过位就是。"""
    sid = p.get("id") or ""
    since = p.get("since") or 0
    return {"cancelled": (_CANCEL.get(sid) or 0) > since}


def _mark_cancel(ctx, sid):
    """置打断位：由会话主人（PM）的循环自己看到并干净退出。"""
    _CANCEL[sid] = _now(ctx)


def _route_dispatch(ctx, payload):
    """用户发来消息后驱动会话跑一轮。

    已在跑就置打断位，等它收尾（已产出的东西会落盘），再用新消息开新一轮；
    等待与重跑都放在后台线程里，HTTP 立刻返回，前端靠轮询看状态。
    """
    sid = payload.get("id") or ""
    if not sid:
        return {"ok": False, "code": "no_session"}
    with _RUN_LOCK:
        prev = _RUNS.get(sid)
    interrupted = bool(prev and prev.is_alive())

    slot = {}

    def work():
        if prev and prev.is_alive():
            _mark_cancel(ctx, sid)
            prev.join()
        with _RUN_LOCK:
            if _RUNS.get(sid) is not slot.get("t"):
                return  # 后面又有人接管了，这一棒作废，避免并发跑两轮
        ctx.api.call("demand_engine.run", {
            "id": "session-run", "input": {"id": sid}}, caller=None)

    t = threading.Thread(target=work, name="sess-%s" % sid, daemon=True)
    slot["t"] = t
    with _RUN_LOCK:
        _RUNS[sid] = t
    t.start()
    return {"ok": True, "id": sid, "status": "running", "interrupted": interrupted}


def _next_seq(ctx, kind):
    """同一 kind 的会话序号自增：拿当日已有最大值 + 1，绝不复用已有会话 id。"""
    listed = ctx.api.call("store.glob", {
        "module": "agent/sessions", "pattern": "sessions/*.yaml"}, caller=None)
    best = 0
    for rel in listed.get("items") or []:
        name = str(rel).rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if not name.startswith((kind or "role") + "-"):
            continue
        tail = name[len(kind) + 1:]
        if tail.isdigit():
            best = max(best, int(tail))
    return best + 1


def _route_spawn(ctx, payload):
    """造会话闭环：取人设与知识、拼消息、落盘。人设来源的分岔在能力内部。"""
    nid = ctx.api.call("store.id", {"value": payload.get("name")}, caller=None)
    tid = ctx.api.call("store.id", {"value": payload.get("ticket")}, caller=None)
    if payload.get("kind") == "role":
        scn = ctx.api.call("demand_engine.run", {
            "id": "library-role-prompt", "input": {"role": payload.get("role")}}, caller=None)
        prompt_text = ((scn.get("result") or {}).get("prompt")) or ""
    else:
        scn = ctx.api.call("store.read_text", {
            "module": "agent/sessions",
            "path": "prompts/%s.md" % (payload.get("kind") or "")}, caller=None)
        prompt_text = scn.get("value") or ""
    prefixes = ["public/", "projects/%s/" % (tid.get("id") or "")]
    know = ctx.api.call("demand_engine.run", {
        "id": "knowledge-compose", "input": {"prefixes": prefixes}}, caller=None)
    now = ctx.api.call("clock.now", {}, caller=None)
    kind = payload.get("kind") or "role"
    seq = payload.get("seq") or _next_seq(ctx, kind)
    rec = ctx.api.call("sessions.build", {
        "kind": kind, "seq": seq,
        "name": nid.get("id"), "ticket": payload.get("ticket"),
        "role": payload.get("role"), "backend": payload.get("backend"),
        "max_steps": payload.get("max_steps"), "meta": payload.get("meta"),
        "prompt": prompt_text,
        "injected": ((know.get("result") or {}).get("text")) or "",
        "prefix": "", "task": payload.get("task"), "intro": payload.get("intro"),
        "now": now.get("ts")}, caller=None)
    ctx.api.call("store.write", {
        "module": "agent/sessions",
        "path": "sessions/%s.yaml" % (rec.get("id") or ""),
        "value": rec}, caller=None)
    return ctx.api.call("sessions.view", {"rec": rec}, caller=None)

