"""会话模块：会话记录的纯计算与拼装。

本模块不留副作用：要写的东西算成 effects 交出去，由需求调 runtime.apply 落地；
要再驱动别的需求，也由需求自己编排。人设来源的分岔仍在这里（控制流下沉能力）。
"""
from __future__ import annotations

from .private import _pure, _run_pure


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
    ]
    for name, fn in pairs:
        ctx.api.register(name, lambda payload, fn=fn: fn(payload), module="sessions")
    ctx.api.register("sessions.spawn", _route_spawn,
                     "造会话：取人设与知识拼记录，写入算成效果交出去", module="sessions")
    return True


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
    nid = ctx.api.call("store.id", {"value": payload.get("name")}, caller=None)
    tid = ctx.api.call("store.id", {"value": payload.get("ticket")}, caller=None)
    role_prompt = payload.get("role_prompt") or None
    if role_prompt is None:
        row = ctx.api.call("store.read_text", {
            "module": "agent/sessions", "path": "prompts/%s.md" % kind}, caller=None)
        role_prompt = row.get("value") or ""
    listed = ctx.api.call("store.glob", {
        "module": "agent/sessions", "pattern": "sessions/*.yaml"}, caller=None)
    seq = payload.get("seq") or _seq_of(kind, listed.get("items"))
    now = ctx.api.call("clock.now", {}, caller=None)
    rec = ctx.api.call("sessions.build", {
        "kind": kind, "seq": seq,
        "name": nid.get("id"), "ticket": payload.get("ticket"),
        "role": payload.get("role"), "backend": payload.get("backend"),
        "max_steps": payload.get("max_steps"), "meta": payload.get("meta"),
        "prompt": role_prompt,
        "injected": payload.get("injected") or "",
        "prefix": "", "task": payload.get("task"), "intro": payload.get("intro"),
        "now": now.get("ts")}, caller=None)
    view = ctx.api.call("sessions.view", {"rec": rec}, caller=None)
    view["rec"] = rec
    view["effects"] = [{
        "kind": "write", "module": "agent/sessions",
        "path": "sessions/%s.yaml" % (rec.get("id") or ""), "value": rec}]
    return view
