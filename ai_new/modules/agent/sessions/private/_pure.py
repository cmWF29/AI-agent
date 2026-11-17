"""会话纯函数：造记录、拼系统消息、露出字段、裁剪上下文。不读盘、不取时间。"""
from __future__ import annotations


def _seed(system, intro):
    """会话开局消息：system 人设在前；原始需求作为第一条 user 消息在后。

    PM 一句话没说时，会话里也必须看得见"用户到底要什么"，否则工单是个空壳。
    """
    msgs = [{"role": "system", "content": system}]
    if intro:
        msgs.append({"role": "user", "content": intro})
    return msgs


def build(p):
    prefix = p.get("prefix") or ""
    prompt = p.get("prompt") or ""
    injected = p.get("injected") or ""
    task = p.get("task") or ""
    intro = p.get("intro") or ""
    system = (prefix + "\n" + prompt + "\n" + injected).strip()
    if task:
        system = system + "\n\n## 任务\n" + task
    sid = "%s-%s" % (p.get("kind") or "role", p.get("seq") or 1)
    return {
        "id": sid, "kind": p.get("kind") or "role", "name": p.get("name") or sid,
        "ticket": p.get("ticket") or "", "role": p.get("role") or "",
        "project": p.get("project") or "",
        "scenario": p.get("kind") or "role", "backend": p.get("backend") or "",
        "status": "idle", "created": p.get("now") or "", "updated": p.get("now") or "",
        "max_steps": p.get("max_steps"),
        "meta": p.get("meta") or {},
        "messages": _seed(system, intro),
    }


def view(p):
    rec = p.get("rec") or {}
    return {"id": rec.get("id"), "kind": rec.get("kind"), "name": rec.get("name"),
            "ticket": rec.get("ticket"), "role": rec.get("role"),
            "project": rec.get("project"),
            "backend": rec.get("backend"), "status": rec.get("status"),
            "created": rec.get("created"), "updated": rec.get("updated"),
            "meta": rec.get("meta") or {},
            "messages": rec.get("messages") or []}


def present(p):
    """读档后定型：缺记录返 not_found，否则返视图。分支在模块内部。"""
    rec = p.get("rec")
    if rec is None:
        return missing({"id": p.get("id")})
    return view({"rec": rec})


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


def record_path(p):
    """会话记录落盘相对路径：布局约定属会话模块，需求层不拼字符串。"""
    return {"path": "sessions/%s.yaml" % (p.get("id") or "")}


def role_name(p):
    """角色会话名：岗位标识 - 工单 id，纯拼装。"""
    return {"name": "%s-%s" % (p.get("role") or "", p.get("id") or "")}
