"""工单纯函数：记录成形、状态迁移、角色/子单挂接、消息模板填充。不读盘、不取时间。"""
from __future__ import annotations

def _glob_one(text, pattern):
    """`*` `?` 通配，纯字符比较，不借标准库。"""
    if not pattern:
        return text == ""
    head, rest = pattern[0], pattern[1:]
    if head == "*":
        if not rest:
            return True
        for i in range(len(text) + 1):
            if _glob_one(text[i:], rest):
                return True
        return False
    if head == "?":
        return bool(text) and _glob_one(text[1:], rest)
    return bool(text) and text[0] == head and _glob_one(text[1:], rest)


def _glob(path, pattern):
    parts = [p for p in pattern.split("/") if p not in ("", ".")]
    segs = [s for s in path.split("/") if s not in ("", ".")]
    return _glob_path(segs, parts)


def _glob_path(segs, parts):
    if not parts:
        return not segs
    head, rest = parts[0], parts[1:]
    if head == "**":
        for i in range(len(segs) + 1):
            if _glob_path(segs[i:], rest):
                return True
        return False
    return bool(segs) and _glob_one(segs[0], head) and _glob_path(segs[1:], rest)




def newid(p):
    return {"id": "T-%s-%04d" % ((p.get("today") or "00000000")[:10].replace("-", ""),
                                 int(p.get("n") or 1))}


def build(p):
    return {
        "id": p.get("id"), "title": p.get("title") or "未命名需求",
        "goal": p.get("goal") or "", "project": p.get("project") or "",
        "kind": p.get("kind") or "normal", "parent": p.get("parent") or "",
        "children": [], "status": "queued", "pm": p.get("pm") or "", "roles": [],
        "auto_retrospective": bool(p.get("auto_retrospective")),
        "created": p.get("now") or "", "updated": p.get("now") or "",
        "closed": "", "summary": "", "verdict": "", "history": [],
        "meta": p.get("meta") or {},
    }


def validate_project(p):
    """工单必须绑定项目：纯空值守卫，项目是否存在由需求层读盘判断。"""
    project = (p.get("project") or "").strip()
    if not project:
        return {"ok": False, "code": "missing_project", "status": 400,
                "error": "工单必须绑定到某个项目"}
    return {"ok": True, "project": project}


def threadp(p):
    """工单主会话（1:1）线程视图：工单档案 + 主会话消息流 + 角色实例清单。"""
    ticket = p.get("ticket") or {}
    thread = p.get("thread") or {}
    return {
        "ticket": view({"rec": ticket}),
        "thread": {"id": thread.get("id") or "", "name": thread.get("name") or "",
                   "status": thread.get("status") or "",
                   "messages": thread.get("messages") or []},
        "roles": ticket.get("roles") or [],
    }


def thread(p):
    """线程定型：工单档案缺失返 not_found，否则交 threadp 拼视图。分支在模块内部。"""
    ticket = p.get("ticket")
    if ticket is None:
        return err({"code": "not_found", "status": 404,
                    "message": "工单不存在: %s" % (p.get("id") or "")})
    return threadp(p)


def view(p):
    rec = p.get("rec") or {}
    base = {k: rec.get(k) for k in ("id", "title", "goal", "project", "kind", "parent",
                                    "status", "pm", "created", "updated", "closed",
                                    "summary", "verdict", "auto_retrospective")}
    base.update({"children": rec.get("children") or [], "roles": rec.get("roles") or [],
                 "history": rec.get("history") or []})
    return base


def present(p):
    """读档后定型：缺档案返 not_found，否则返视图。分支在模块内部。"""
    rec = p.get("rec")
    if rec is None:
        return err({"code": "not_found", "status": 404,
                    "message": "工单不存在: %s" % (p.get("id") or "")})
    return view({"rec": rec})


def screen(p):
    items = []
    for rec in p.get("rows") or []:
        if not rec:
            continue
        if p.get("status") and rec.get("status") != p.get("status"):
            continue
        if p.get("project") and rec.get("project") != p.get("project"):
            continue
        items.append(view({"rec": rec}))
    return {"items": items}


def roles(p):
    return {"items": (p.get("rec") or {}).get("roles") or []}


def note(p):
    rec = dict(p.get("rec") or {})
    rec.setdefault("history", []).append({"at": p.get("now") or "", "event": "note",
                                          "text": p.get("text") or ""})
    rec["updated"] = p.get("now") or ""
    return rec


def bindrole(p):
    rec = dict(p.get("rec") or {})
    rec.setdefault("roles", []).append({"session": p.get("session"), "role": p.get("role"),
                                        "display": p.get("display") or p.get("role"),
                                        "task": p.get("task") or "", "status": "spawned"})
    rec.setdefault("history", []).append({"at": p.get("now") or "", "event": "role_spawn",
                                          "text": "%s: %s" % (p.get("role"), p.get("task") or "")})
    rec["updated"] = p.get("now") or ""
    return rec


def bindpm(p):
    rec = dict(p.get("rec") or {})
    rec["pm"] = p.get("session") or ""
    rec["updated"] = p.get("now") or ""
    return rec


def bindchild(p):
    rec = dict(p.get("rec") or {})
    rec.setdefault("children", []).append(p.get("child"))
    rec["updated"] = p.get("now") or ""
    return rec


def closefin(p):
    rec = dict(p.get("rec") or {})
    rec["status"] = "closed"
    rec["summary"] = p.get("summary") or ""
    rec["verdict"] = p.get("verdict") or "accepted"
    rec["closed"] = p.get("now") or ""
    rec["updated"] = p.get("now") or ""
    rec.setdefault("history", []).append({"at": p.get("now") or "", "event": "closed",
                                          "text": p.get("summary") or ""})
    return rec


def branch(p):
    """子单是否都结了：给需求当守卫。"""
    open_children = [c for c in p.get("children") or [] if c and c.get("status") != "closed"]
    return {"open": open_children, "all_closed": not open_children}


def pick(p):
    """按角色名/显示名/会话 id 找目标会话。"""
    for r in (p.get("rec") or {}).get("roles") or []:
        if p.get("target") in (r.get("role"), r.get("display"), r.get("session")):
            return {"session": r.get("session"), "role": r.get("role")}
    return {"session": "", "role": ""}


def resolve_target(p):
    """归一消息目标：pm 走工单主会话，其余交 pick 找角色会话。分支在模块内部。"""
    rec = p.get("rec") or {}
    if p.get("target") == "pm":
        return {"session": rec.get("pm") or "", "role": "pm"}
    return pick(p)


def files_filter(p):
    items = p.get("items") or []
    pattern = p.get("pattern") or "**/*"
    if pattern != "**/*":
        items = [it for it in items if _glob(it.get("path") or "", pattern)]
    return {"ticket": p.get("ticket"), "items": items}


def err(p):
    return {"ok": False, "code": p.get("code") or "error",
            "status": p.get("status") or 400, "error": p.get("message") or ""}


def msg(p):
    """消息模板：模板文本与变量都由需求取来，这里只做填充。"""
    tpl = p.get("tpl") or p.get("fallback") or ""
    try:
        return {"text": tpl.format(**(p.get("vars") or {}))}
    except KeyError:
        return {"text": tpl}


def stale(p):
    """超过阈值没动、且还开着 —— 判定是纯比较，时间由 clock 给。"""
    rec = p.get("rec") or {}
    if rec.get("status") == "closed":
        return {"stale": False}
    idle = int(p.get("idle_seconds") or 0)
    limit = int(p.get("limit_seconds") or 3600)
    return {"stale": idle >= limit}
