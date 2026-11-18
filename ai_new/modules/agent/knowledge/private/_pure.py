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
    layer = p.get("layer") or "public"
    if layer == "public":
        return {"ok": True, "prefix": "public"}
    if layer == "project":
        pid = p.get("project") or ""
        if not pid:
            return _bad("missing_scope", "project 层必须给 project")
        return {"ok": True, "prefix": "projects/%s" % pid}
    if layer == "ticket":
        tid = p.get("ticket") or ""
        if not tid:
            return _bad("missing_scope", "ticket 层必须给 ticket id")
        return {"ok": True, "prefix": "tickets/%s" % tid}
    return _bad("bad_layer", "未知知识层: %s" % layer)


def doc(p):
    """前缀 + 已归一化的文档名 → 文档相对路径。"""
    name = p.get("name") or ""
    if not name:
        return _bad("missing_name", "name 必填")
    clean = name[:-3] if name.endswith(".md") else name
    return {"ok": True, "path": "%s/%s.md" % (p.get("prefix") or "public", clean)}


def view(p):
    return {"path": p.get("path"), "content": p.get("content") or "",
            "chars": len(p.get("content") or ""),
            "text": p.get("content") or ""}


def present(p):
    """取文后定型：空文本返 not_found，否则返视图。分支在模块内部。"""
    content = p.get("content") or ""
    if content == "":
        return missing({"name": p.get("name")})
    return view({"path": p.get("path"), "content": content})


def screen(p):
    """列表：rows 是相对路径列表，这里只挑文件名与长度。"""
    items = []
    for rel in p.get("rows") or []:
        size = (p.get("sizes") or {}).get(rel)
        items.append({"name": rel.rsplit("/", 1)[-1],
                      "chars": size if size is not None else 0,
                      "source": "user" if (p.get("layer") or "public") == "public" else None})
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
    counts = {"public": 0, "project": 0, "ticket": 0}
    layer_label = {"public": "公共", "project": "项目", "ticket": "工单"}
    ticket_project, ticket_title = {}, {}
    for t in p.get("tickets") or []:
        if not t:
            continue
        tid = t.get("id") or ""
        if tid:
            ticket_project[tid] = t.get("project") or ""
            ticket_title[tid] = t.get("title") or ""

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
            pid = ticket_project.get(tid, "")
            doc = _doc("ticket", pid, tid, name, rel)
            items.append(doc); counts["ticket"] += 1
            if pid:
                grp = project_groups.setdefault(pid, {"docs": [], "tickets": {}})
                grp["tickets"].setdefault(tid, []).append(doc)
            else:
                orphan_tickets.setdefault(tid, []).append(doc)

    tree = []
    if public_docs:
        tree.append({"type": "public", "label": "公共", "badge": "公共", "children": public_docs})
    for pid in sorted(project_groups):
        grp = project_groups[pid]
        children = list(grp["docs"])
        for tid in sorted(grp["tickets"]):
            children.append({"type": "ticket", "label": tid, "sub": ticket_title.get(tid, ""),
                             "badge": "工单", "children": grp["tickets"][tid]})
        tree.append({"type": "project", "label": pid, "badge": "项目", "children": children})
    for tid in sorted(orphan_tickets):
        tree.append({"type": "ticket", "label": tid, "sub": ticket_title.get(tid, ""),
                     "badge": "工单", "children": orphan_tickets[tid]})
    return {"items": items, "counts": counts, "tree": tree}


def search(p):
    """rows: [{path,text}]；按内容与路径匹配，截 400 字。"""
    q = (p.get("query") or "").lower()
    limit = int(p.get("limit") or 10)
    items = []
    for row in p.get("rows") or []:
        rel = row.get("path") or ""
        text = row.get("text") or ""
        if q in text.lower() or _glob(rel.lower(), "*" + q + "*"):
            items.append({"path": rel, "snippet": text[:400]})
        if len(items) >= limit:
            break
    return {"query": p.get("query") or "", "items": items}


def compose(p):
    """rows: [{path,text}]；按前缀顺序拼注入块，按字符上限截断。"""
    limit = int(p.get("max_chars") or 20000)
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
    return {"ok": False, "code": "not_found", "status": 404,
            "error": "知识不存在: %s" % (p.get("name") or "")}


def removed(p):
    return {"removed": bool(p.get("removed")), "project": p.get("project") or ""}


def project_dir(p):
    """项目知识目录相对路径：projects/<id>。"""
    return {"path": "projects/%s" % (p.get("project") or p.get("ticket") or "")}


def project_prefix(p):
    """项目层知识注入前缀：projects/<id>（与 compose 前缀约定一致）。"""
    return {"prefix": "projects/%s" % (p.get("ticket") or p.get("project") or "")}
