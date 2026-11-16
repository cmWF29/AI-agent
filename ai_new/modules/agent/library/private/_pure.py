"""岗位库纯函数：种子与用户记录的合并、查询、成形。不读盘、不取时间。"""
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




def _records(p):
    seed = p.get("seed") or {}
    user = p.get("user") or {}
    kind = p.get("kind") or "roles"
    out = dict(user)
    for rec in seed.get(kind) or []:
        rid = rec.get("id")
        if rid and rid not in out:
            out[rid] = dict(rec, builtin=True)
    return out


def _position(rec, flow):
    """岗位 = 相对性系统提示词引用 + 代码性流程规范 + 产出约束。"""
    return {"id": rec.get("id"), "cn": rec.get("cn"),
            "prompt_file": rec.get("prompt_file"),
            "must_outputs": rec.get("must_outputs") or [],
            "backend": rec.get("backend") or "",
            "builtin": bool(rec.get("builtin")),
            "flow": {"id": (flow or {}).get("id") or rec.get("id"),
                     "checks": (flow or {}).get("checks") or []}}


def positionp(p):
    """单条岗位：岗位记录 + 关联流程规范合并成形。"""
    rec = p.get("rec") or {}
    if not rec:
        return {"ok": False, "code": "not_found", "status": 404,
                "error": "岗位不存在: %s" % (p.get("id") or "")}
    return _position(rec, p.get("flow") or {})


def positionsp(p):
    """岗位列表：岗位记录按 id 关联各自流程规范。"""
    roles = _records({"seed": p.get("seed"), "user": p.get("user"), "kind": "roles"})
    flows = _records({"seed": p.get("seed"), "user": p.get("flows"), "kind": "flows"})
    items = [_position(rec, flows.get(rid) or {}) for rid, rec in roles.items()]
    return {"items": items}


def listp(p):
    kind = p.get("kind") or "roles"
    return {"kind": kind, "items": [dict(r) for r in _records(p).values()]}


def getp(p):
    kind = p.get("kind") or "roles"
    rid = p.get("id") or ""
    rec = _records(p).get(rid)
    if not rec:
        return {"ok": False, "code": "not_found", "status": 404,
                "error": "%s 不存在: %s" % (kind, rid)}
    return {"kind": kind, "item": rec}


def designp(p):
    """用户记录合并字段；内置角色不许改提示词。"""
    kind = p.get("kind") or "roles"
    rid = p.get("id") or ""
    fields = p.get("fields") or {}
    if not rid:
        return {"ok": False, "code": "missing_id", "error": "id 必填"}
    rec = dict(p.get("record") or {})
    if rec.get("builtin") and kind == "roles" and fields.get("prompt"):
        return {"ok": False, "code": "builtin_protected", "status": 403,
                "error": "内置角色提示词受保护"}
    rec.update(fields)
    rec.setdefault("id", rid)
    rec.setdefault("builtin", False)
    rec["updated"] = p.get("now") or ""
    return rec


def summaryp(p):
    seed = p.get("seed") or {}
    user = p.get("user") or {}
    counts, names = {}, {}
    for kind in ("roles", "flows", "skills"):
        recs = _records({"seed": seed, "user": user.get(kind) or {}, "kind": kind})
        counts[kind] = len(recs)
        names[kind] = sorted(recs)
    return {"counts": counts, "roles": names["roles"],
            "flows": names["flows"], "skills": names["skills"]}


def promptp(p):
    role = p.get("role") or ""
    rec = p.get("rec") or {}
    ref = rec.get("prompt_file")
    if not ref:
        return {"ok": False, "code": "no_prompt_file", "error": "角色没有 prompt_file: %s" % role}
    return {"role": role, "prompt": p.get("text") or "", "ref": ref}


def checkp(p):
    """files: [路径]；contents: {路径: 文本}；checks 来自流程记录。"""
    rec = p.get("rec") or {}
    checks = rec.get("checks") or []
    files = p.get("files") or []
    contents = p.get("contents") or {}
    missing = []
    for c in checks:
        kind = c.get("kind")
        if kind == "glob":
            paths = c.get("paths") or []
            match = c.get("match") or "all"
            if match == "any":
                if not any(any(_glob(f, pat) for pat in paths) for f in files):
                    missing.append({"kind": kind, "paths": paths, "match": match,
                                    "reason": "任一命中即可，均未命中"})
            else:
                for pat in paths:
                    if not any(_glob(f, pat) for f in files):
                        missing.append({"kind": kind, "path": pat, "match": match})
        elif kind == "contains":
            text = c.get("text")
            if not any(text and text in (contents.get(f) or "") for f in files):
                missing.append({"kind": kind, "text": text, "reason": "无文件包含该文本"})
    return {"flow": p.get("flow") or "", "missing": missing, "checked": len(checks)}
