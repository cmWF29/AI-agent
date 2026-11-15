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


def view(rec):
    return {"id": rec.get("id"), "name": rec.get("name"),
            "archived": rec.get("archived", False),
            "created": rec.get("created"),
            "default_backend": rec.get("default_backend", "")}


def screen(p):
    """列表：rows 是档案记录列表，这里只挑要露出的字段。"""
    rows = p.get("rows") or []
    items = [view(rec) for rec in rows if rec]
    return {"items": items}


def archive(rec, now=""):
    out = dict(rec or {})
    out["archived"] = True
    out["updated"] = now
    return out


def missing(payload):
    return {"ok": False, "code": "not_found", "status": 404,
            "error": "项目不存在: %s" % (payload.get("id") or "")}


def conflict(payload):
    return {"ok": False, "code": "exists", "status": 409,
            "error": "项目已存在: %s" % (payload.get("id") or "")}


def deleted(payload):
    return {"deleted": True, "id": payload.get("id") or ""}
