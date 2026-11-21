"""项目模块的纯函数：输入数据，输出数据。不读盘、不取时间、不发请求。"""
from __future__ import annotations


def build(rec):
    """造一条项目档案：id/name/created 由调用方给（id 来自 store，created 来自 clock）。

    岗位/流程/技能/工具定义只存公共库一份；项目档案只持有启停覆盖层，缺省四类空清单=全启用。
    """
    return {
        "id": rec.get("id") or "default",
        "name": rec.get("name") or rec.get("id") or "default",
        "created": rec.get("created") or "",
        "archived": False,
        "idle": {},
        "overrides": {kind: [] for kind in _OVERRIDE_KINDS},
    }


def view(p):
    rec = p.get("rec") or p
    return {"id": rec.get("id"), "name": rec.get("name"),
            "archived": rec.get("archived", False),
            "created": rec.get("created")}


def present(p):
    """读档后定型：缺档案返 not_found 形状，否则返视图。分支在模块内部，需求不写 when。"""
    rec = p.get("rec")
    if rec is None:
        return missing({"id": p.get("id"), "tpl": p.get("tpl")})
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
    items, archived = [], []
    for pr in projs:
        if not pr or not pr.get("id"):
            continue
        rows = by.get(pr.get("id")) or []
        open_n = len([t for t in rows if t.get("status") != "closed"])
        pv = view({"rec": pr})
        row = {"project": pv, "tickets": rows,
               "counts": {"total": len(rows), "open": open_n,
                          "closed": len(rows) - open_n}}
        (archived if pv.get("archived") else items).append(row)
    return {"items": items, "archived": archived, "orphans": orphans}


def _ticket_view(rec):
    return {"id": rec.get("id"), "title": rec.get("title"), "goal": rec.get("goal"),
            "project": rec.get("project"), "kind": rec.get("kind"),
            "status": rec.get("status"), "pm": rec.get("pm"),
            "updated": rec.get("updated")}


def screen(p):
    """列表：rows 是档案记录列表，这里只挑要露出的字段；非档案文件（如 messages.yaml 文案模板）
    没有档案 id，一并滤除，不渲染成空壳卡片。"""
    rows = p.get("rows") or []
    items = [view({"rec": rec}) for rec in rows if rec and rec.get("id")]
    return {"items": items}


def guard_archive(p):
    """归档前置：项目里还有没结单的工单就不许归档。

    归档的定义是"冻结成只读快照"，冻结时还挂着在途工单，等于把别人正在做的事锁在门外。
    """
    rec = p.get("rec") or {}
    tpl = p.get("tpl") or {}
    if rec.get("archived") is True:
        return {"ok": False, "code": "already_archived", "status": 409,
                "error": tpl.get("already_archived") or ""}
    open_ids = [str(x) for x in (p.get("open_tickets") or []) if x]
    if open_ids:
        t = tpl.get("open_tickets") or ""
        return {"ok": False, "code": "open_tickets", "status": 409,
                "error": t.format(n=len(open_ids), ids=", ".join(open_ids)) if t else ""}
    return {"ok": True}


def guard_writable(p):
    """归档后只读：改名、启停、删除、建单、发消息一律拒绝。

    "归档"必须有明确后果，否则按钮上写归档、实际什么都没变。
    """
    rec = p.get("rec") or {}
    if rec.get("archived") is True:
        return {"ok": False, "code": "project_archived", "status": 409,
                "error": (p.get("tpl") or {}).get("project_archived") or ""}
    return {"ok": True}


def archive(p):
    rec = p.get("rec") or {}
    out = dict(rec)
    out["archived"] = True
    out["updated"] = p.get("now") or ""
    return out


def renamed(payload):
    """改名后的档案：换 id/name，created/archived 原样保留。"""
    rec = dict(payload.get("rec") or {})
    rec["id"] = payload.get("id") or rec.get("id")
    rec["name"] = payload.get("name") or rec.get("name") or rec.get("id")
    rec["updated"] = payload.get("now") or rec.get("updated") or ""
    return rec


def missing(payload):
    pid = payload.get("id") or ""
    tpl = payload.get("tpl") or ""
    return {"ok": False, "code": "not_found", "status": 404,
            "error": tpl.format(id=pid) if tpl else ""}


def conflict(payload):
    pid = payload.get("id") or ""
    tpl = payload.get("tpl") or ""
    return {"ok": False, "code": "exists", "status": 409,
            "error": tpl.format(id=pid) if tpl else ""}


def deleted(payload):
    return {"deleted": True, "id": payload.get("id") or ""}


def record_path(p):
    """项目档案落盘相对路径：模板由需求层配置表给出，纯函数只填参。"""
    paths = p.get("paths") or {}
    t = paths.get("record") or ""
    pid = p.get("id") or ""
    return {"path": t.format(id=pid) if t else pid}


# ---- 项目级启停覆盖层：定义正文只存公共库一份，项目只记禁用清单 ----

_OVERRIDE_KINDS = ("roles", "flows", "skills", "tools", "states")


def _clean_list(items):
    """清单逐项转字符串、去空白、去空项、保序去重；形状规整归项目模块。"""
    out = []
    for raw in items or []:
        item = str(raw or "").strip()
        if item and item not in out:
            out.append(item)
    return out


def override_parts(p):
    """项目档案 → 四类禁用 id/name 清单；档案或缺字段缺省空清单（全启用）。"""
    rec = p.get("rec") or {}
    ov = rec.get("overrides") or {}
    return {kind: _clean_list(ov.get(kind)) for kind in _OVERRIDE_KINDS}


def toggle_override(p):
    """按项目档案翻转某类条目启停：启用移出禁用清单，禁用加入；去重保序，不回写公共库。

    纯数据成形；校验分岔在模块内，需求树不写 when。出错返 ok=False 形状。
    """
    kind = p.get("kind") or ""
    rid = str(p.get("id") or "").strip()
    enabled = bool(p.get("enabled"))
    tpl = p.get("tpl") or {}
    if kind not in _OVERRIDE_KINDS:
        t = tpl.get("bad_kind") or ""
        return {"ok": False, "code": "bad_kind", "status": 400,
                "error": t.format(kind=kind) if t else ""}
    if not rid:
        t = tpl.get("missing_id") or ""
        return {"ok": False, "code": "missing_id", "status": 400,
                "error": t if t else ""}
    rec = dict(p.get("rec") or {})
    ov = dict(rec.get("overrides") or {})
    cur = _clean_list(ov.get(kind))
    if enabled:
        cur = [x for x in cur if x != rid]
    elif rid not in cur:
        cur.append(rid)
    ov[kind] = cur
    # 禁用工具要连带禁用岗位：工具没了，依赖它的岗位派活也跑不动，留着只会制造半死的岗。
    cascaded = []
    if kind == "tools" and not enabled:
        roles = _clean_list(ov.get("roles"))
        for role in _clean_list(p.get("cascade_roles")):
            if role not in roles:
                roles.append(role)
                cascaded.append(role)
        ov["roles"] = roles
    for k in _OVERRIDE_KINDS:
        ov.setdefault(k, [])
    rec["overrides"] = ov
    rec["updated"] = p.get("now") or ""
    return rec
