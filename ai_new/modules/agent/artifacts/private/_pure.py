"""交付件纯函数：分层前缀、越界防护、读取成形。不碰盘。"""
from __future__ import annotations


def base(p):
    layer = p.get("layer") or "ticket"
    if layer == "public":
        return {"ok": True, "base": "public"}
    if layer == "project":
        pid = p.get("project") or ""
        if not pid:
            return {"ok": False, "code": "missing_scope", "error": "project 层必须给 project"}
        return {"ok": True, "base": "projects/%s" % pid}
    if layer == "ticket":
        tid = p.get("ticket") or ""
        if not tid:
            return {"ok": False, "code": "missing_scope", "error": "ticket 层必须给 ticket"}
        return {"ok": True, "base": "projects/%s/tickets/%s" % (p.get("project") or "_", tid)}
    return {"ok": False, "code": "bad_layer", "error": "未知交付件层: %s" % layer}


def rel(p):
    base_dir = p.get("base") or ""
    path = str(p.get("path") or "").replace("\\", "/").lstrip("/")
    if not path or "\x00" in path:
        return {"ok": False, "code": "bad_path", "error": "path 非法"}
    if ".." in path.split("/"):
        return {"ok": False, "code": "path_escape", "error": "路径越界", "status": 403}
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
    limit = int(p.get("max_bytes") or 262144)
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


def missing(p):
    return {"ok": False, "code": "no_file", "status": 404,
            "error": "文件不存在: %s" % (p.get("path") or "")}
