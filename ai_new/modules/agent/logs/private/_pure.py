"""日志模块纯函数：清单条目成形、合并、剔除与归属分组。不碰盘、不取时间。

日志恒为系统自动落盘（source=system），不向 LLM 开放写口；类别固定 log。
"""
from __future__ import annotations


def _bad(code, message):
    return {"ok": False, "code": code, "error": message}


def entry(p):
    """清单条目成形：归属/类型/路径由外部传入，时间由 clock 给。"""
    return {
        "path": p.get("path") or "",
        "category": "log",
        "doc_kind": None,
        "source": p.get("source") or "system",
        "layer": p.get("layer") or "public",
        "project": p.get("project") or "",
        "ticket": p.get("ticket") or "",
        "kind": p.get("kind") or "",
        "name": p.get("name") or "",
        "created": p.get("now") or "",
        "updated": p.get("now") or "",
    }


def index_upsert(p):
    """旧清单 entries + 新条目 → 按 path 去重合并；已有条目保留 created，刷新 updated/name。"""
    incoming = p.get("entry") or {}
    rel = incoming.get("path") or ""
    out, seen = [], False
    for row in p.get("entries") or []:
        if not isinstance(row, dict):
            continue
        if row.get("path") == rel:
            merged = dict(row)
            merged["updated"] = incoming.get("updated") or merged.get("updated")
            merged["name"] = incoming.get("name") or merged.get("name")
            out.append(merged)
            seen = True
        else:
            out.append(row)
    if rel and not seen:
        out.append(dict(incoming))
    return {"entries": out}


def index_purge(p):
    """剔除归属前缀或指定路径下的条目；删项目/工单目录、回收会话后清清单用。"""
    prefix = p.get("prefix") or ""
    drop = set(p.get("paths") or [])
    keep = []
    for row in p.get("entries") or []:
        if not isinstance(row, dict):
            continue
        rel = row.get("path") or ""
        if rel in drop:
            continue
        if prefix and rel.startswith(prefix):
            continue
        keep.append(row)
    return {"entries": keep}


def group(p):
    """清单条目 → 公共/项目/工单三级归属树；纯分组，不读正文。

    entries: 清单条目列表；tickets: 工单档案（id/project/title）用于补项目归属。
    """
    entries = p.get("entries") or []
    tickets = p.get("tickets") or []
    tpl = p.get("tpl") or {}
    layer_label = {"public": tpl.get("label_public") or "",
                   "project": tpl.get("label_project") or "",
                   "ticket": tpl.get("label_ticket") or ""}
    ticket_project, ticket_title = {}, {}
    for t in tickets:
        if not t:
            continue
        tid = t.get("id") or ""
        if tid:
            ticket_project[tid.lower()] = t.get("project") or ""
            ticket_title[tid.lower()] = t.get("title") or ""

    public_items, project_groups, orphan = [], {}, {}
    counts = {"public": 0, "project": 0, "ticket": 0}
    items = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        layer = row.get("layer") or "public"
        pid = row.get("project") or ""
        tid = row.get("ticket") or ""
        item = {"type": "log", "layer": layer, "project": pid, "ticket": tid,
                "name": row.get("name") or "", "path": row.get("path") or "",
                "kind": row.get("kind") or "", "source": row.get("source") or "system"}
        items.append(item)
        if layer == "public":
            public_items.append(item)
            counts["public"] += 1
        elif layer == "ticket":
            key = tid.lower()
            pid = pid or ticket_project.get(key, "")
            item["project"] = pid
            counts["ticket"] += 1
            if pid:
                grp = project_groups.setdefault(pid, {"docs": [], "tickets": {}})
                grp["tickets"].setdefault(key, []).append(item)
            else:
                orphan.setdefault(key, []).append(item)
        else:
            counts["project"] += 1
            project_groups.setdefault(pid, {"docs": [], "tickets": {}})["docs"].append(item)

    tree = []
    if public_items:
        tree.append({"type": "public", "label": layer_label["public"],
                     "badge": layer_label["public"], "children": public_items})
    for pid in sorted(project_groups):
        grp = project_groups[pid]
        children = list(grp["docs"])
        for key in sorted(grp["tickets"]):
            children.append({"type": "ticket", "label": ticket_title.get(key, key),
                             "badge": layer_label["ticket"], "children": grp["tickets"][key]})
        tree.append({"type": "project", "label": pid, "badge": layer_label["project"],
                     "children": children})
    for key in sorted(orphan):
        tree.append({"type": "ticket", "label": key,
                     "badge": layer_label["ticket"], "children": orphan[key]})
    return {"items": items, "counts": counts, "tree": tree}
