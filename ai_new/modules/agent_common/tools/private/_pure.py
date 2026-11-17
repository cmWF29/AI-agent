"""工具库纯函数：记录合并、依赖就绪判定、清单成形。不读盘、不探测、不执行。

探测快照（哪些命令/包/凭证在位）由闭环能力从 host/config 取来交入；
这里只给定快照做判定与文本成形，不自己碰主机与环境。
"""
from __future__ import annotations


_DEP_KINDS = (("cli", "命令"), ("pip", "Python 包"),
              ("env", "环境变量"), ("config", "配置项"),
              ("resources", "资源文件"))


def merge(p):
    """内置注册表清单 ∪ 外部登记记录（data/tools.yaml）；内置优先，外部不覆盖同名。

    disabled 为已禁用 Skill 标识集合：归属这些 Skill 的外部工具不进合并清单。
    """
    builtin = p.get("builtin") or []
    external = p.get("external") or {}
    disabled = set(p.get("disabled") or [])
    seen = {t.get("name") for t in builtin if t.get("name")}
    items = [dict(t) for t in builtin]
    for name, rec in (external or {}).items():
        if not name or name in seen:
            continue
        row = dict(rec or {})
        row.setdefault("name", name)
        row.setdefault("builtin", False)
        if row.get("skill") and row["skill"] in disabled:
            continue
        items.append(row)
    items.sort(key=lambda x: x.get("name") or "")
    return {"items": items}


def pickp(p):
    """合并清单按岗位名单交集裁剪；名单为空按会话类型放行。成形归模块，注册表与外部候选由路由给齐。"""
    items = p.get("items") or []
    allow = p.get("tools") or []
    kind = p.get("kind")
    if allow:
        wanted = set(allow)
        base = [t for t in items if t.get("name") in wanted]
    else:
        base = [t for t in items
                if not t.get("kinds") or (kind and kind in (t.get("kinds") or []))]
    return {"items": [{"name": t.get("name"), "desc": t.get("desc"),
                       "params": t.get("params"), "module": t.get("module")}
                      for t in base]}


def scope(items, kind):
    """按来源裁剪清单：builtin=代码内置工具库，external=外部登记/拆解来的工具，all=全量。

    内置与外部工具的划分在此成形；视图只按组取数，不在前端做判断。
    """
    items = items or []
    if kind == "builtin":
        return [t for t in items if t.get("builtin")]
    if kind == "external":
        return [t for t in items if not t.get("builtin")]
    return list(items)


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


def install_plan(p):
    """合并后工具清单 + 在位快照 → 安装计划：pip 包可自动装，cli/env/config 需人工处理。

    只算计划不执行；resources 不在在线探测范围，也不进计划。
    """
    snap = p.get("snapshot") or {}
    pip, manual = [], {"cli": [], "env": [], "config": []}
    seen = set()
    for t in p.get("tools") or []:
        deps = t.get("deps") or {}
        for m in _missing_for(deps, snap):
            kind, name = m.get("kind"), str(m.get("name") or "")
            if not name:
                continue
            if kind == "pip":
                if name not in seen:
                    seen.add(name)
                    pip.append(name)
            elif kind in manual:
                entry = {"tool": t.get("name") or "", "name": name}
                if entry not in manual[kind]:
                    manual[kind].append(entry)
    return {"pip": pip, "manual": manual,
            "ready": not pip and not any(manual[k] for k in manual)}


def external_pending(p):
    """外部工具执行占位：后端未接入前回显登记与依赖提示；不碰主机、不执行。"""
    rec = p.get("rec") or {}
    name = p.get("tool") or ""
    return {"ok": False, "code": "external_pending", "tool": name,
            "desc": rec.get("desc") or "", "args": p.get("args") or {},
            "deps": _deps_text(rec.get("deps") or {}),
            "message": "外部工具「%s」后端尚未接入，参数与依赖已登记；接入后在此执行。" % (name or "?")}


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
            "skill": t.get("skill") or "",
            "source": "内置" if t.get("builtin") else "拆解",
        })
    return {"items": rows}
