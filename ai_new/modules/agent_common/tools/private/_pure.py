"""工具库纯函数：记录合并、依赖就绪判定、清单成形。不读盘、不探测、不执行。

探测快照（哪些命令/包/凭证在位）由闭环能力从 host/config 取来交入；
这里只给定快照做判定与文本成形，不自己碰主机与环境。
"""
from __future__ import annotations


_DEP_KINDS = (("cli", "命令"), ("pip", "Python 包"),
              ("env", "环境变量"), ("config", "配置项"),
              ("resources", "资源文件"))


def merge(p):
    """内置注册表清单 ∪ 外部登记记录（data/tools.yaml）；内置优先，外部不覆盖同名。"""
    builtin = p.get("builtin") or []
    external = p.get("external") or {}
    seen = {t.get("name") for t in builtin if t.get("name")}
    items = [dict(t) for t in builtin]
    for name, rec in (external or {}).items():
        if not name or name in seen:
            continue
        row = dict(rec or {})
        row.setdefault("name", name)
        row.setdefault("builtin", False)
        items.append(row)
    items.sort(key=lambda x: x.get("name") or "")
    return {"items": items}


def _missing_for(deps, snapshot):
    """按依赖分类对照快照，列出缺项；resources 不在在线探测范围，只登记不判。"""
    deps = deps or {}
    snap = snapshot or {}
    missing = []
    for kind, _label in _DEP_KINDS:
        names = deps.get(kind) or []
        if kind == "resources":
            continue
        present = snap.get(kind) or {}
        for name in names:
            name = str(name or "")
            if not name:
                continue
            ok = present.get(name)
            if kind in ("env", "config"):
                ok = bool(ok)
            if not ok:
                missing.append({"kind": kind, "name": name})
    return missing


def probe(p):
    """单条工具依赖 → 就绪状态；缺什么记清楚，不在这里装东西。"""
    deps = p.get("deps") or {}
    missing = _missing_for(deps, p.get("snapshot"))
    return {"status": "ok" if not missing else "missing", "missing": missing}


def _deps_text(deps):
    deps = deps or {}
    parts = []
    for kind, label in _DEP_KINDS:
        names = [str(x) for x in (deps.get(kind) or []) if str(x or "")]
        if names:
            parts.append("%s: %s" % (label, "、".join(names)))
    return "；".join(parts) if parts else "无"


def _missing_text(missing):
    if not missing:
        return ""
    labels = dict(_DEP_KINDS)
    return "、".join("%s:%s" % (labels.get(m.get("kind"), m.get("kind")), m.get("name"))
                     for m in missing)


def listing(p):
    """合并后工具清单翻成只读清单行：参数、可见类型、依赖、就绪状态都成形为文本。"""
    rows = []
    for t in p.get("tools") or []:
        params = t.get("params") or []
        param_text = "; ".join(
            "%s: %s%s" % (x.get("name") or "", x.get("type") or "string",
                          "*" if x.get("required") else "")
            for x in params)
        kinds = t.get("kinds") or []
        kinds_text = "全部" if not kinds else "、".join(str(k) for k in kinds)
        deps = t.get("deps") or {}
        status = probe({"deps": deps, "snapshot": p.get("snapshot")})
        rows.append({
            "name": t.get("name") or "",
            "desc": t.get("desc") or "",
            "module": t.get("module") or "",
            "params": param_text,
            "kinds": kinds_text,
            "deps": _deps_text(deps),
            "status": status["status"],
            "status_text": "就绪" if status["status"] == "ok" else "缺依赖",
            "missing": _missing_text(status["missing"]),
            "builtin": bool(t.get("builtin")),
        })
    return {"items": rows}
