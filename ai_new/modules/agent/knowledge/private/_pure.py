"""知识模块的纯函数：输入数据，输出形状。不读盘、不取时间、不调服务。"""
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




def _bad(code, message):
    return {"ok": False, "code": code, "error": message}


def scope(p):
    """layer + 已归一化的 project/ticket id → 相对前缀。"""
    tpl = p.get("tpl") or {}
    paths = p.get("paths") or {}
    layer = p.get("layer") or "public"
    if layer == "public":
        return {"ok": True, "prefix": paths.get("public") or ""}
    if layer == "project":
        pid = p.get("project") or ""
        if not pid:
            t = tpl.get("missing_scope_project") or ""
            return _bad("missing_scope", t)
        t = paths.get("project") or ""
        return {"ok": True, "prefix": t.format(project=pid) if t else ""}
    if layer == "ticket":
        tid = p.get("ticket") or ""
        if not tid:
            t = tpl.get("missing_scope_ticket") or ""
            return _bad("missing_scope", t)
        t = paths.get("ticket") or ""
        return {"ok": True, "prefix": t.format(ticket=tid) if t else ""}
    t = tpl.get("bad_layer") or ""
    return _bad("bad_layer", t.format(layer=layer) if t else "")


def doc(p):
    """前缀 + 已归一化的文档名 → 文档相对路径。"""
    tpl = p.get("tpl") or {}
    paths = p.get("paths") or {}
    name = p.get("name") or ""
    if not name:
        t = tpl.get("missing_name") or ""
        return _bad("missing_name", t)
    clean = name[:-3] if name.endswith(".md") else name
    t = paths.get("doc") or ""
    return {"ok": True, "path": t.format(prefix=p.get("prefix") or "", name=clean) if t else ""}


def view(p):
    return {"path": p.get("path"), "content": p.get("content") or "",
            "chars": len(p.get("content") or ""),
            "text": p.get("content") or ""}


def present(p):
    """取文后定型：空文本返 not_found，否则返视图。分支在模块内部。"""
    content = p.get("content") or ""
    if content == "":
        return missing({"name": p.get("name"), "tpl": p.get("tpl")})
    return view({"path": p.get("path"), "content": content})


def screen(p):
    """列表：rows 是相对路径列表，这里只挑文件名与长度。"""
    items = []
    for rel in p.get("rows") or []:
        size = (p.get("sizes") or {}).get(rel)
        items.append({"name": rel.rsplit("/", 1)[-1],
                      "chars": size if size is not None else 0,
                      "source": "llm"})
    return {"layer": p.get("layer") or "public", "items": items}


def overview(p):
    counts = {"public": 0, "project": {}, "ticket": {}}
    for row in p.get("rows") or []:
        rel = row.get("path") if isinstance(row, dict) else row
        parts = rel.split("/")
        if parts[0] == "public" and len(parts) == 2:
            counts["public"] += 1
        elif parts[0] in ("projects", "tickets") and len(parts) == 3:
            key = "project" if parts[0] == "projects" else "ticket"
            counts[key][parts[1]] = counts[key].get(parts[1], 0) + 1
    return {"counts": counts}


def index(p):
    """整树路径 + 工单记录 → 扁平 items 与「公共/项目/工单/文档」归属树。

    rows: [{path}]；tickets: 工单档案记录列表（带 id/project/title）。纯分组，不读正文。
    取数归需求，归组形状归模块；前端只按 tree 递归渲染。
    """
    items = []
    # 计数分口径：project/ticket 是"知识层级"，project_groups/placed/orphan 是"工单归属"
    counts = {"public": 0, "project": 0, "ticket": 0,
              "project_groups": 0, "placed": 0, "orphan": 0}
    tpl = p.get("tpl") or {}
    layer_label = {"public": tpl.get("label_public") or "",
                   "project": tpl.get("label_project") or "",
                   "ticket": tpl.get("label_ticket") or "",
                   "orphan": tpl.get("label_orphan") or ""}
    ticket_project, ticket_title, ticket_raw = {}, {}, {}
    for t in p.get("tickets") or []:
        if not t:
            continue
        tid = t.get("id") or ""
        if tid:
            key = tid.lower()
            ticket_project[key] = t.get("project") or ""
            ticket_title[key] = t.get("title") or ""
            ticket_raw[key] = tid

    public_docs = []
    project_groups = {}   # pid -> {"docs": [], "tickets": {tid: [doc]}}
    orphan_tickets = {}   # tid -> [doc]（工单档案缺失项目归属）

    def _doc(layer, pid, tid, name, rel):
        return {"type": "doc", "layer": layer, "layer_label": layer_label[layer],
                "project": pid, "ticket": tid, "name": name, "path": rel}

    for row in p.get("rows") or []:
        rel = row.get("path") if isinstance(row, dict) else str(row or "")
        parts = [s for s in rel.split("/") if s]
        name = parts[-1][:-3] if parts and parts[-1].endswith(".md") else (parts[-1] if parts else "")
        if parts[0] == "public" and len(parts) == 2:
            doc = _doc("public", "", "", name, rel)
            items.append(doc); counts["public"] += 1
            public_docs.append(doc)
        elif parts[0] == "projects" and len(parts) == 3:
            pid = parts[1]
            doc = _doc("project", pid, "", name, rel)
            items.append(doc); counts["project"] += 1
            project_groups.setdefault(pid, {"docs": [], "tickets": {}})["docs"].append(doc)
        elif parts[0] == "tickets" and len(parts) == 3:
            tid = parts[1]
            key = tid.lower()
            pid = ticket_project.get(key, "")
            doc = _doc("ticket", pid, tid, name, rel)
            items.append(doc); counts["ticket"] += 1
            if pid:
                grp = project_groups.setdefault(pid, {"docs": [], "tickets": {}})
                grp["tickets"].setdefault(key, []).append(doc)
            else:
                orphan_tickets.setdefault(key, []).append(doc)

    counts["project_groups"] = len(project_groups)
    counts["placed"] = sum(len(grp["tickets"]) for grp in project_groups.values())
    counts["orphan"] = len(orphan_tickets)

    tree = []
    # 公共层恒在：它是知识库的第一级，没文档也要露出来，否则用户不知道还有这一层
    tree.append({"type": "public", "label": layer_label["public"],
                 "badge": layer_label["public"], "children": public_docs})
    for pid in sorted(project_groups):
        grp = project_groups[pid]
        children = list(grp["docs"])
        for key in sorted(grp["tickets"]):
            children.append({"type": "ticket", "label": ticket_raw.get(key, key),
                             "sub": ticket_title.get(key, ""),
                             "badge": layer_label["ticket"], "children": grp["tickets"][key]})
        tree.append({"type": "project", "label": pid, "badge": layer_label["project"],
                     "children": children})
    # 项目归属缺失的工单（档案里查不到 project）：不冒充项目层，也不平铺裸挂在顶层，
    # 归成一个「工单 / 未归工单」分组——层级名仍是工单，组名说清为什么它不挂在项目下
    if orphan_tickets:
        kids = []
        for key in sorted(orphan_tickets):
            kids.append({"type": "ticket", "label": ticket_raw.get(key, key),
                         "sub": ticket_title.get(key, ""),
                         "badge": layer_label["ticket"], "children": orphan_tickets[key]})
        tree.append({"type": "orphan", "label": layer_label["orphan"],
                     "badge": layer_label["ticket"], "children": kids})
    return {"items": items, "counts": counts, "tree": tree}


def search(p):
    """rows: [{path,text}]；按内容与路径匹配，截 400 字。"""
    q = (p.get("query") or "").lower()
    limit = int(p.get("limit"))
    snippet = int(p.get("snippet_chars"))
    items = []
    for row in p.get("rows") or []:
        rel = row.get("path") or ""
        text = row.get("text") or ""
        if q in text.lower() or _glob(rel.lower(), "*" + q + "*"):
            items.append({"path": rel, "snippet": text[:snippet]})
        if len(items) >= limit:
            break
    return {"query": p.get("query") or "", "items": items}


def compose(p):
    """rows: [{path,text}]；按前缀顺序拼注入块，按字符上限截断。"""
    limit = int(p.get("max_chars"))
    prefixes = p.get("prefixes") or ["public/"]
    parts = []
    total = 0
    for prefix in prefixes:
        for row in p.get("rows") or []:
            rel = row.get("path") or ""
            if not rel.startswith(prefix):
                continue
            name = rel.rsplit("/", 1)[-1]
            block = "## %s\n%s" % (name, row.get("text") or "")
            if total + len(block) > limit:
                block = block[:max(0, limit - total)]
            parts.append(block)
            total += len(block)
            if total >= limit:
                break
        if total >= limit:
            break
    return {"text": "\n\n".join(parts), "chars": total, "truncated": total >= limit}


def missing(p):
    name = p.get("name") or ""
    tpl = p.get("tpl") or ""
    return {"ok": False, "code": "not_found", "status": 404,
            "error": tpl.format(name=name) if tpl else ""}


def removed(p):
    return {"removed": bool(p.get("removed")), "project": p.get("project") or ""}


def project_dir(p):
    """项目知识目录相对路径。"""
    paths = p.get("paths") or {}
    t = paths.get("project_dir") or ""
    ident = p.get("project") or p.get("ticket") or ""
    return {"path": t.format(id=ident) if t else ""}


def project_prefix(p):
    """项目层知识注入前缀（与 compose 前缀约定一致）。"""
    paths = p.get("paths") or {}
    t = paths.get("project_dir") or ""
    ident = p.get("ticket") or p.get("project") or ""
    return {"prefix": t.format(id=ident) if t else ""}

def entry(p):
    """清单条目成形：知识恒 category=knowledge、doc_kind=None、source=llm。

    归属/路径由外部传入，时间由 clock 给；纯函数不内置业务默认来源。
    """
    return {
        "path": p.get("path") or "",
        "category": "knowledge",
        "doc_kind": None,
        "source": p.get("source") or "llm",
        "layer": p.get("layer") or "public",
        "project": p.get("project") or "",
        "ticket": p.get("ticket") or "",
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
    """剔除归属前缀下的条目；删项目/工单目录后清清单用。"""
    prefix = p.get("prefix") or ""
    keep = []
    for row in p.get("entries") or []:
        if not isinstance(row, dict):
            continue
        rel = row.get("path") or ""
        if prefix and rel.startswith(prefix):
            continue
        keep.append(row)
    return {"entries": keep}
