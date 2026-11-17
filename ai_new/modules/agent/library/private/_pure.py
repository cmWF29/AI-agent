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


def _pm_record():
    """PM 是工单主会话编排者，不是可被派单实例化的岗位；在库内只作只读条目展示。

    提示词引用会话侧 prompts/pm.md；这里只给定位与职责骨架，不读盘、不取时间。
    """
    return {"id": "pm", "cn": "PM", "prompt_file": "prompts/pm.md",
            "must_outputs": [],
            "must_dos": ["受理工单需求并拆解执行计划", "按需派角色、返工缺口与组织验收",
                         "对照验收标准闭环结单"],
            "forbidden": ["不替代执行角色直接撰写交付件"],
            "tools": ["role_spawn", "role_task", "ticket_split", "ticket_close",
                      "ticket_read_doc", "ticket_note"],
            "backend": "", "builtin": True, "readonly": True, "system": True}


def _position(rec, flow):
    """岗位 = 系统提示词引用 + 红线/必做 + 工具清单 + 代码性流程规范 + 产出约束。"""
    return {"id": rec.get("id"), "cn": rec.get("cn"),
            "prompt_file": rec.get("prompt_file"),
            "must_outputs": rec.get("must_outputs") or [],
            "forbidden": rec.get("forbidden") or [],
            "must_dos": rec.get("must_dos") or [],
            "tools": rec.get("tools") or [],
            "backend": rec.get("backend") or "",
            "builtin": bool(rec.get("builtin")),
            "readonly": bool(rec.get("readonly")),
            "system": bool(rec.get("system")),
            "flow": {"id": (flow or {}).get("id") or rec.get("id"),
                     "checks": (flow or {}).get("checks") or []}}


def reviewp(p):
    """一轮收尾评审：缺口清单 + 已回催次数 → 三态判定（纯计算，不带时钟）。

    pass      没有缺口，本轮交付达标；
    repush    有缺口且未超上限：计数 +1，交回催缺口清单；
    exhausted 有缺口但重试已到上限：不再催，留卡点交上层裁决。
    重试上限是模块内部策略，不写进需求树。
    """
    missing = p.get("missing") or []
    retries = int(p.get("retries") or 0)
    limit = int(p.get("max_retries") or 2)
    text = "; ".join(_gap_text(g) for g in missing)
    if not missing:
        return {"verdict": "pass", "missing": [], "missing_text": "",
                "retries": retries, "repush": []}
    if retries < limit:
        return {"verdict": "repush", "missing": missing, "missing_text": text,
                "retries": retries + 1, "repush": missing}
    return {"verdict": "exhausted", "missing": missing, "missing_text": text,
            "retries": retries, "repush": []}


def _gap_text(gap):
    """单条缺口成形为可读文本；形状来自 checkp，缺字段不报错。"""
    if not isinstance(gap, dict):
        return str(gap)
    if gap.get("path"):
        return str(gap["path"])
    if gap.get("text"):
        return str(gap["text"])
    if gap.get("reason"):
        return str(gap["reason"])
    return str(gap.get("paths") or gap)


def prompt_blocks(p):
    """把岗位自然语言正文与结构化红线/必做拼成系统提示词附加段。

    正文来自数据文件；这里只做结构拼装，不写任何职责正文。
    """
    text = p.get("text") or ""
    must = p.get("must_dos") or []
    forbidden = p.get("forbidden") or []
    parts = [text] if text else []
    if must:
        parts.append("## 必须做到\n" + "\n".join("- %s" % m for m in must))
    if forbidden:
        parts.append("## 禁止事项\n" + "\n".join("- %s" % m for m in forbidden))
    return {"system": "\n\n".join(parts)}


def positionp(p):
    """单条岗位：岗位记录 + 关联流程规范合并成形。PM 为主会话只读条目，不在角色记录里。"""
    rec = p.get("rec") or {}
    if not rec:
        if (p.get("id") or "") == "pm":
            return _position(_pm_record(), p.get("flow") or {})
        return {"ok": False, "code": "not_found", "status": 404,
                "error": "岗位不存在: %s" % (p.get("id") or "")}
    return _position(rec, p.get("flow") or {})


def positionsp(p):
    """岗位列表：岗位记录按 id 关联各自流程规范；末尾附只读 PM 主会话条目。"""
    roles = _records({"seed": p.get("seed"), "user": p.get("user"), "kind": "roles"})
    flows = _records({"seed": p.get("seed"), "user": p.get("flows"), "kind": "flows"})
    items = [_position(rec, flows.get(rid) or {}) for rid, rec in roles.items()]
    items.append(_position(_pm_record(), {}))
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
