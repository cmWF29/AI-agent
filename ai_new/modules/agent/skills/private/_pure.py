"""技能纯函数：技能卡就是岗位库里的记录，这里只筛、挑、标。"""
from __future__ import annotations


def _recs(p):
    return {item["id"]: item for item in (p.get("items") or []) if item.get("id")}


def screen(p):
    items = []
    q = (p.get("query") or "").lower()
    for sid, rec in _recs(p).items():
        if q:
            blob = (sid + " " + str(rec.get("cn") or "") + " " + str(rec.get("doc") or "")).lower()
            if q not in blob:
                continue
        items.append({"id": sid, "cn": rec.get("cn"), "doc": rec.get("doc"),
                      "has_flow": bool(rec.get("flow"))})
    return {"items": items}


def getp(p):
    rec = _recs(p).get(p.get("id") or "")
    if not rec:
        return {"ok": False, "code": "not_found", "status": 404,
                "error": "技能不存在: %s" % (p.get("id") or "")}
    out = {"id": p.get("id")}
    out.update(rec)
    return out


def noflow(p):
    return {"ok": False, "code": "no_flow", "status": 400,
            "error": "技能没有可执行步骤: %s" % (p.get("id") or "")}
