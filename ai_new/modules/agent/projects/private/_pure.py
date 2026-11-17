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
        rows = by.get(pr.get("id")) or []
        open_n = len([t for t in rows if t.get("status") != "closed"])
        items.append({"project": view({"rec": pr}),
                      "tickets": rows,
                      "counts": {"total": len(rows), "open": open_n,
                                 "closed": len(rows) - open_n}})
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


def record_path(p):
    """项目档案落盘相对路径：布局约定属项目模块，需求层不拼字符串。"""
    return {"path": "%s.yaml" % (p.get("id") or "")}


# ---- 项目级库：新建项目从公共库全量快照一份副本，项目内定制不回写公共 ----

def _copy_dict(d):
    """字典值浅拷贝一层；记录是字典就复制，避免项目副本回引公共对象。"""
    out = {}
    for k, v in (d or {}).items():
        out[k] = dict(v) if isinstance(v, dict) else v
    return out


def snapshot_parts(p):
    """新建项目时把公共岗位/流程/技能/工具四份字典整体复制为项目副本。

    全量物理快照：项目从此独立演进；种子内置岗位由 seed 恒定提供，不复制。
    """
    return {"roles": _copy_dict(p.get("roles")),
            "flows": _copy_dict(p.get("flows")),
            "skills": _copy_dict(p.get("skills")),
            "tools": _copy_dict(p.get("tools"))}


def project_lib_path(p):
    """项目库副本相对 projects 模块根：projects/<pid>/<kind>.yaml；kind 传复数 roles/flows/skills/tools。"""
    pid = p.get("id") or ""
    kind = p.get("kind") or "roles"
    return {"path": "projects/%s/%s.yaml" % (pid, kind)}


def choose_dict(p):
    """项目副本存在且非空用项目，否则回退公共；缺省分支在模块内，需求树不写 when。"""
    proj = p.get("project")
    if isinstance(proj, dict) and proj.get("exists") and proj.get("value"):
        return {"value": proj.get("value")}
    pub = p.get("public")
    return {"value": (pub.get("value") if isinstance(pub, dict) else pub)}
