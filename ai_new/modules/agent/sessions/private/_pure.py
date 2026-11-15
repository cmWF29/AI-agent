"""会话纯函数：造记录、拼系统消息、露出字段、裁剪上下文。不读盘、不取时间。"""
from __future__ import annotations


def build(p):
    prefix = p.get("prefix") or ""
    prompt = p.get("prompt") or ""
    injected = p.get("injected") or ""
    task = p.get("task") or ""
    system = (prefix + "\n" + prompt + "\n" + injected).strip()
    if task:
        system = system + "\n\n## 任务\n" + task
    sid = "%s-%s" % (p.get("kind") or "role", p.get("seq") or 1)
    return {
        "id": sid, "kind": p.get("kind") or "role", "name": p.get("name") or sid,
        "ticket": p.get("ticket") or "", "role": p.get("role") or "",
        "scenario": p.get("kind") or "role", "backend": p.get("backend") or "",
        "status": "idle", "created": p.get("now") or "", "updated": p.get("now") or "",
        "max_steps": p.get("max_steps"),
        "meta": p.get("meta") or {},
        "messages": [{"role": "system", "content": system}],
    }


def view(p):
    rec = p.get("rec") or {}
    return {"id": rec.get("id"), "kind": rec.get("kind"), "name": rec.get("name"),
            "ticket": rec.get("ticket"), "role": rec.get("role"),
            "backend": rec.get("backend"), "status": rec.get("status"),
            "created": rec.get("created"), "updated": rec.get("updated"),
            "messages": rec.get("messages") or []}


def screen(p):
    items = []
    status = p.get("status")
    for rec in p.get("rows") or []:
        if not rec:
            continue
        if status and rec.get("status") != status:
            continue
        items.append(view({"rec": rec}))
    return {"items": items}


def gone(p):
    rec = dict(p.get("rec") or {})
    rec["status"] = "gone"
    rec["updated"] = p.get("now") or ""
    return rec


def compactp(p):
    rec = dict(p.get("rec") or {})
    keep = max(1, int(p.get("keep") or 10))
    msgs = rec.get("messages") or []
    system = [m for m in msgs if m.get("role") == "system"]
    rest = [m for m in msgs if m.get("role") != "system"]
    rec["messages"] = system + rest[-keep:]
    rec["updated"] = p.get("now") or ""
    return rec


def missing(p):
    return {"ok": False, "code": "not_found", "status": 404,
            "error": "会话不存在: %s" % (p.get("id") or "")}
