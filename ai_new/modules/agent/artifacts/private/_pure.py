"""交付件纯函数：分层前缀、越界防护、读取成形。不碰盘。"""
from __future__ import annotations


def _bad(code, message):
    return {"ok": False, "code": code, "error": message}


def base(p):
    layer = p.get("layer") or "ticket"
    paths = p.get("paths") or {}
    tpl = p.get("tpl") or {}
    if layer == "public":
        return {"ok": True, "base": paths.get("public") or ""}
    if layer == "project":
        pid = p.get("project") or ""
        if not pid:
            return _bad("missing_scope", tpl.get("missing_scope_project") or "")
        t = paths.get("project") or ""
        return {"ok": True, "base": t.format(project=pid) if t else ""}
    if layer == "ticket":
        tid = p.get("ticket") or ""
        if not tid:
            return _bad("missing_scope", tpl.get("missing_scope_ticket") or "")
        t = paths.get("ticket") or ""
        return {"ok": True, "base": t.format(project=p.get("project") or "_", ticket=tid) if t else ""}
    t = tpl.get("bad_layer") or ""
    return _bad("bad_layer", t.format(layer=layer) if t else "")


def rel(p):
    base_dir = p.get("base") or ""
    path = str(p.get("path") or "").replace("\\", "/").lstrip("/")
    tpl = p.get("tpl") or {}
    if not path or "\x00" in path:
        return _bad("bad_path", tpl.get("bad_path") or "")
    if ".." in path.split("/"):
        return {"ok": False, "code": "path_escape", "error": tpl.get("path_escape") or "", "status": 403}
    return {"ok": True, "path": ("%s/%s" % (base_dir, path)) if base_dir else path}


def written(p):
    return {"path": p.get("path"), "size": int(p.get("size") or 0), "layer": p.get("layer")}


def viewed(p):
    return {"path": p.get("path"), "size": int(p.get("size") or 0),
            "truncated": bool(p.get("truncated")),
            "encoding": p.get("encoding") or "utf8",
            "text": p.get("text") or ""}


def decode(p):
    """hex → utf8；不行就退 base64（由 codec 在需求里先转）。"""
    hx = p.get("hex") or ""
    limit = int(p.get("max_bytes"))
    truncated = int(p.get("size") or 0) > limit
    raw = bytes.fromhex(hx)[:limit]
    try:
        return {"text": raw.decode("utf-8"), "encoding": "utf8", "truncated": truncated}
    except UnicodeDecodeError:
                return {"text": base64.b64encode(raw).decode("ascii"), "encoding": "binary", "needs_encode": True,
                "truncated": truncated}


def screen(p):
    items = []
    for row in p.get("rows") or []:
        if isinstance(row, dict):
            items.append({"path": row.get("path"), "size": len(row.get("text") or "")})
        else:
            items.append({"path": row[0], "size": int(row[1] or 0)})
    return {"layer": p.get("layer") or "ticket", "items": items}


def statsp(p):
    rows = p.get("rows") or []
    return {"files": len(rows), "bytes": sum(int(r.get("size") or 0) for r in rows),
            "chars": sum(len(r.get("text") or "") for r in rows)}

def classify(p):
    """校验文档类型与来源枚举；缺省 doc_kind=artifact、source=llm。

    合法集合由配置 taxonomy 给出，纯函数不内置业务枚举。
    """
    tpl = p.get("tpl") or {}
    doc_kinds = p.get("doc_kinds") or []
    sources = p.get("sources") or []
    doc_kind = p.get("doc_kind") or "artifact"
    source = p.get("source") or "llm"
    if doc_kinds and doc_kind not in doc_kinds:
        return _bad("bad_doc_kind", tpl.get("bad_doc_kind", "").format(kind=doc_kind))
    if sources and source not in sources:
        return _bad("bad_source", tpl.get("bad_source", "").format(source=source))
    return {"ok": True, "doc_kind": doc_kind, "source": source}


def entry(p):
    """清单条目成形：文档恒 category=document。"""
    return {
        "path": p.get("path") or "",
        "category": "document",
        "doc_kind": p.get("doc_kind") or None,
        "source": p.get("source") or "llm",
        "layer": p.get("layer") or "ticket",
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
