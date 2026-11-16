"""项目模块的纯函数：输入数据，输出数据。不读盘、不取时间、不发请求。"""
from __future__ import annotations


def build(rec):
    """造一条项目档案：id/name/created 由调用方给（id 来自 store，created 来自 clock）。"""
    return {
        "id": rec.get("id") or "default",
        "name": rec.get("name") or rec.get("id") or "default",
        "created": rec.get("created") or "",
        "archived": False,
        "default_backend": rec.get("default_backend") or "",
        "idle": {},
    }


def view(p):
    rec = p.get("rec") or p
    return {"id": rec.get("id"), "name": rec.get("name"),
            "archived": rec.get("archived", False),
            "created": rec.get("created"),
            "default_backend": rec.get("default_backend", "")}


def present(p):
    """读档后定型：缺档案返 not_found 形状，否则返视图。分支在模块内部，需求不写 when。"""
    rec = p.get("rec")
    if rec is None:
        return missing({"id": p.get("id")})
    return view({"rec": rec})


def tree(p):
    """项目 → 工单两级归组：项目行与工单行都由需求取来，这里只分组成形。"""
    projs = p.get("projects") or []
    tickets = p.get("tickets") or []
    by, orphans = {}, []
    for t in tickets:
        if not t:
            continue
        proj = t.get("project") or ""
        item = _ticket_view(t)
        if proj:
            by.setdefault(proj, []).append(item)
        else:
            orphans.append(item)
    items = []
    for pr in projs:
        if not pr:
            continue
        items.append({"project": view({"rec": pr}),
                      "tickets": by.get(pr.get("id")) or []})
    return {"items": items, "orphans": orphans}


def _ticket_view(rec):
    return {"id": rec.get("id"), "title": rec.get("title"), "goal": rec.get("goal"),
            "project": rec.get("project"), "kind": rec.get("kind"),
            "status": rec.get("status"), "pm": rec.get("pm"),
            "updated": rec.get("updated")}


def screen(p):
    """列表：rows 是档案记录列表，这里只挑要露出的字段。"""
    rows = p.get("rows") or []
    items = [view({"rec": rec}) for rec in rows if rec]
    return {"items": items}


def archive(p):
    rec = p.get("rec") or {}
    out = dict(rec)
    out["archived"] = True
    out["updated"] = p.get("now") or ""
    return out


def renamed(payload):
    """改名后的档案：换 id/name（与 default_backend），created/archived 原样保留。"""
    rec = dict(payload.get("rec") or {})
    rec["id"] = payload.get("id") or rec.get("id")
    rec["name"] = payload.get("name") or rec.get("name") or rec.get("id")
    if payload.get("default_backend") not in (None, ""):
        rec["default_backend"] = payload.get("default_backend")
    rec["updated"] = payload.get("now") or rec.get("updated") or ""
    return rec


def missing(payload):
    return {"ok": False, "code": "not_found", "status": 404,
            "error": "项目不存在: %s" % (payload.get("id") or "")}


def conflict(payload):
    return {"ok": False, "code": "exists", "status": 409,
            "error": "项目已存在: %s" % (payload.get("id") or "")}


def deleted(payload):
    return {"deleted": True, "id": payload.get("id") or ""}
