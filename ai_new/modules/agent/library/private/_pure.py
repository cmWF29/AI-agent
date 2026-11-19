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
    seed_recs = seed.get(kind) or []
    system_ids = {r.get("id") for r in seed_recs if r.get("system")}
    out = {rid: dict(rec) for rid, rec in user.items()}
    for rec in seed_recs:
        rid = rec.get("id")
        if not rid:
            continue
        if rid in out and rid not in system_ids:
            continue  # 非系统内置允许用户库覆盖；系统内置恒定以种子为准
        out[rid] = dict(rec, builtin=True)
    return out


def _check_desc(c, tpl):
    """单条流程检查规则翻成可读中文；形状来自 flows 记录，缺字段不报错。"""
    tpl = tpl or {}
    kind = c.get("kind")
    paths = c.get("paths") or []
    joined = "、".join(paths)
    minb = c.get("min_bytes")
    if kind == "contains":
        head = (tpl.get("check_contains") or "").format(text=c.get("text") or "")
    else:
        match = c.get("match") or "all"
        if match == "any":
            head = (tpl.get("check_any") or "").format(paths=joined)
        else:
            head = (tpl.get("check_all") or "").format(paths=joined)
    if minb:
        head += (tpl.get("check_min_bytes") or "").format(minb=minb)
    return head


def _position(rec, flow, prompt_text="", tpl=None):
    """岗位 = 系统提示词引用 + 红线/必做 + 工具清单 + 代码性流程规范 + 产出约束。

    正文取提示词文件内容；提示词归属模块由记录 prompt_module 标注。
    """
    tpl = tpl or {}
    flow = flow or {}
    checks = [dict(c, desc=_check_desc(c, tpl)) for c in (flow.get("checks") or [])]
    return {"id": rec.get("id"), "cn": rec.get("cn"),
            "prompt_file": rec.get("prompt_file"),
            "prompt_module": rec.get("prompt_module") or "agent/library",
            "prompt": prompt_text or "",
            "must_outputs": rec.get("must_outputs") or [],
            "forbidden": rec.get("forbidden") or [],
            "must_dos": rec.get("must_dos") or [],
            "tools": rec.get("tools") or [],
            "stages": rec.get("stages") or [],
            "skill": rec.get("skill") or "",
            "builtin": bool(rec.get("builtin")),
            "readonly": bool(rec.get("readonly")),
            "system": bool(rec.get("system")),
            "flow": {"id": (flow or {}).get("id") or rec.get("id"),
                     "checks": checks}}


def reviewp(p):
    """一轮收尾评审：缺口清单 + 已回催次数 → 三态判定（纯计算，不带时钟）。

    pass      没有缺口，本轮交付达标；
    repush    有缺口且未超上限：计数 +1，交回催缺口清单；
    exhausted 有缺口但重试已到上限：不再催，留卡点交上层裁决。
    重试上限由需求层从配置传入，纯函数不持有策略默认值。
    """
    missing = p.get("missing") or []
    retries = int(p.get("retries") or 0)
    limit = int(p.get("max_retries"))
    text = "; ".join(_gap_text(g) for g in missing)
    if not missing:
        return {"verdict": "pass", "missing": [], "missing_text": "",
                "retries": retries, "repush": []}
    if retries < limit:
        return {"verdict": "repush", "missing": missing, "missing_text": text,
                "retries": retries + 1, "repush": missing}
    return {"verdict": "exhausted", "missing": missing, "missing_text": text,
            "retries": retries, "repush": []}


def stage_contractp(p):
    """岗位阶段契约定形：列表 → 索引、初始阶段与终态集合。无 stages 直通。"""
    stages = [s for s in (p.get("stages") or []) if isinstance(s, dict) and s.get("id")]
    by = {s.get("id"): s for s in stages}
    initial = stages[0].get("id") if stages else ""
    terminals = [s.get("id") for s in stages if s.get("terminal")]
    return {"stages": stages, "by_id": by, "initial": initial, "terminals": terminals}


def stage_transitionp(p):
    """校验自报阶段与跳转边。prev 缺省视为开局；nxt 为空表示本轮未上报阶段，直通保留 prev。

    ok            合法（含原地停留、开局进初始阶段）；
    unknown_stage 自报阶段不在契约内；
    illegal_start 开局未进初始阶段；
    illegal_edge  相对上一阶段的跳转不在 next 表内。
    """
    contract = p.get("contract") or {}
    by = contract.get("by_id") or {}
    nxt = str(p.get("nxt") or "").strip()
    prev = str(p.get("prev") or "").strip()
    if not nxt:
        return {"ok": True, "code": "unset", "stage": prev}
    if nxt not in by:
        return {"ok": False, "code": "unknown_stage", "stage": prev}
    if not prev:
        if nxt == contract.get("initial"):
            return {"ok": True, "code": "ok", "stage": nxt}
        return {"ok": False, "code": "illegal_start", "stage": prev}
    if prev == nxt:
        return {"ok": True, "code": "ok", "stage": nxt}
    allowed = (by.get(prev) or {}).get("next") or []
    if nxt in allowed:
        return {"ok": True, "code": "ok", "stage": nxt}
    return {"ok": False, "code": "illegal_edge", "stage": prev}


def stage_toolsp(p):
    """按阶段裁剪工具清单：阶段 tools 与全集取交集；阶段未列 tools 回退全集。"""
    contract = p.get("contract") or {}
    by = contract.get("by_id") or {}
    stage = str(p.get("stage") or contract.get("initial") or "")
    items = p.get("items") or []
    allow = (by.get(stage) or {}).get("tools") or []
    if not allow:
        return {"items": list(items)}
    wanted = set(allow)
    kept = []
    for t in items:
        name = t.get("name") if isinstance(t, dict) else t
        if name in wanted:
            kept.append(t)
    return {"items": kept}


def stage_blockp(p):
    """把当前阶段契约拼成注入 system 的文本段；标题与措辞来自模板，阶段内容来自数据。"""
    tpl = p.get("tpl") or {}
    contract = p.get("contract") or {}
    by = contract.get("by_id") or {}
    stage = str(p.get("stage") or contract.get("initial") or "")
    rec = by.get(stage) or {}
    if not rec:
        return {"system": ""}
    lines = []
    head = tpl.get("heading_stage") or ""
    if head:
        lines.append(head)
    cur = (tpl.get("stage_current") or "").format(cn=rec.get("cn") or stage, id=stage)
    if cur:
        lines.append(cur)
    desc = rec.get("desc") or ""
    if desc:
        lines.append((tpl.get("stage_desc") or "").format(desc=desc))
    nxt = rec.get("next") or []
    if nxt:
        nxt_cn = [by.get(x, {}).get("cn") or x for x in nxt]
        lines.append((tpl.get("stage_next") or "").format(next="、".join(nxt_cn)))
    elif rec.get("terminal"):
        lines.append(tpl.get("stage_terminal") or "")
    return {"system": "\n".join(lines)}


def stage_gapsp(p):
    """把阶段约束并入产物缺口：非终态阶段、非法跳转各成一条缺口；无契约直通。"""
    tpl = p.get("tpl") or {}
    contract = p.get("contract") or {}
    by = contract.get("by_id") or {}
    stage = str(p.get("stage") or contract.get("initial") or "")
    alerts = p.get("stage_alert") or {}
    missing = list(p.get("base") or [])
    if by:
        rec = by.get(stage)
        if rec and not rec.get("terminal"):
            txt = (tpl.get("stage_not_terminal") or "").format(
                cn=rec.get("cn") or stage, id=stage)
            missing.append({"kind": "stage", "text": txt})
    if alerts and alerts.get("code"):
        txt = (tpl.get("stage_alert") or "").format(code=alerts.get("code") or "")
        missing.append({"kind": "stage", "text": txt})
    return {"missing": missing}


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
    tpl = p.get("tpl") or {}
    text = p.get("text") or ""
    must = p.get("must_dos") or []
    forbidden = p.get("forbidden") or []
    stage_text = p.get("stage") or ""
    parts = [text] if text else []
    if must:
        head = tpl.get("heading_must") or ""
        parts.append(head + "\n" + "\n".join("- %s" % m for m in must) if head
                     else "\n".join("- %s" % m for m in must))
    if forbidden:
        head = tpl.get("heading_forbidden") or ""
        parts.append(head + "\n" + "\n".join("- %s" % m for m in forbidden) if head
                     else "\n".join("- %s" % m for m in forbidden))
    if stage_text:
        parts.append(stage_text)
    return {"system": "\n\n".join(parts)}


def positionp(p):
    """单条岗位：岗位记录 + 关联流程规范合并成形。"""
    rec = p.get("rec") or {}
    prompt_text = p.get("prompt_text") or ""
    tpl = p.get("tpl") or {}
    if not rec:
        pid = p.get("id") or ""
        t = tpl.get("position_missing") or ""
        return {"ok": False, "code": "not_found", "status": 404,
                "error": t.format(id=pid) if t else ""}
    return _position(rec, p.get("flow") or {}, prompt_text, tpl)


def _disabled_skill_ids(skills):
    """状态为 disabled 的 Skill 标识集合；归属这些 Skill 的岗位/工具/流程不进运行名单。"""
    return {sid for sid, rec in (skills or {}).items()
            if isinstance(rec, dict) and rec.get("status") == "disabled"}


def positionsp(p):
    """岗位列表：岗位记录按 id 关联各自流程规范；禁用 Skill 的岗位摘除。

    disabled_roles 为项目级禁用岗位 id 集合：公共库记录仍展示并打 disabled 标记，供项目重新启用；
    system/readonly 内置条目恒定受保护，不被项目禁用标记摘除。
    """
    roles = _records({"seed": p.get("seed"), "user": p.get("user"), "kind": "roles"})
    flows = _records({"seed": p.get("seed"), "user": p.get("flows"), "kind": "flows"})
    disabled = _disabled_skill_ids(p.get("skills"))
    disabled_roles = set(p.get("disabled_roles") or [])
    tpl = p.get("tpl") or {}
    items = []
    for rid, rec in roles.items():
        sk = rec.get("skill")
        if sk and sk in disabled:
            continue
        row = _position(rec, flows.get(rid) or {}, "", tpl)
        locked = bool(rec.get("system") or rec.get("readonly"))
        row["disabled"] = (rid in disabled_roles) and not locked
        if row["disabled"]:
            row["disabled_text"] = tpl.get("label_disabled_project") or ""
        else:
            row["disabled_text"] = tpl.get("label_enabled") or ""
        row["locked"] = locked
        items.append(row)
    return {"items": items}


def listp(p):
    kind = p.get("kind") or "roles"
    return {"kind": kind, "items": [dict(r) for r in _records(p).values()]}


def getp(p):
    kind = p.get("kind") or "roles"
    rid = p.get("id") or ""
    rec = _records(p).get(rid)
    if not rec:
        tpl = (p.get("tpl") or {}).get("kind_missing") or ""
        return {"ok": False, "code": "not_found", "status": 404,
                "error": tpl.format(kind=kind, id=rid) if tpl else ""}
    return {"kind": kind, "item": rec}


def designp(p):
    """用户记录合并字段；内置角色不许改提示词。"""
    kind = p.get("kind") or "roles"
    rid = p.get("id") or ""
    fields = p.get("fields") or {}
    tpl = p.get("tpl") or {}
    if not rid:
        return {"ok": False, "code": "missing_id", "error": tpl.get("id_required") or ""}
    rec = dict(p.get("record") or {})
    if rec.get("builtin") and kind == "roles" and fields.get("prompt"):
        return {"ok": False, "code": "builtin_protected", "status": 403,
                "error": tpl.get("builtin_role_protected") or ""}
    rec.update(fields)
    rec.setdefault("id", rid)
    rec.setdefault("builtin", False)
    rec["updated"] = p.get("now") or ""
    return rec


def summaryp(p):
    seed = p.get("seed") or {}
    user = p.get("user") or {}
    counts, names = {}, {}
    for kind in ("roles", "flows"):
        recs = _records({"seed": seed, "user": user.get(kind) or {}, "kind": kind})
        counts[kind] = len(recs)
        names[kind] = sorted(recs)
    return {"counts": counts, "roles": names["roles"], "flows": names["flows"]}


def promptp(p):
    role = p.get("role") or ""
    rec = p.get("rec") or {}
    ref = rec.get("prompt_file")
    if not ref:
        tpl = p.get("tpl") or {}
        t = tpl.get("no_prompt_file") or ""
        return {"ok": False, "code": "no_prompt_file",
                "error": t.format(role=role) if t else ""}
    return {"role": role, "prompt": p.get("text") or "", "ref": ref}


def checkp(p):
    """files: [路径]；contents: {路径: 文本}；checks 来自流程记录。"""
    tpl = p.get("tpl") or {}
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
                                    "reason": tpl.get("missing_any") or ""})
            else:
                for pat in paths:
                    if not any(_glob(f, pat) for f in files):
                        missing.append({"kind": kind, "path": pat, "match": match})
        elif kind == "contains":
            text = c.get("text")
            if not any(text and text in (contents.get(f) or "") for f in files):
                missing.append({"kind": kind, "text": text, "reason": tpl.get("missing_contains") or ""})
    return {"flow": p.get("flow") or "", "missing": missing, "checked": len(checks)}


def kind_file(p):
    """岗位库分库用户记录文件：模板由需求层配置表给出，纯函数只填参。"""
    paths = p.get("paths") or {}
    t = paths.get("record") or ""
    kind = p.get("kind") or ""
    return {"path": t.format(kind=kind) if t else kind}


def prompt_path(p):
    """提示词文件定位：返回所属模块与相对路径；模板由需求层配置表给出，纯函数只填参。

    提示词归属模块由记录 prompt_module 标注（缺省 agent/library）；sessions 侧记录的
    prompt_file 已是相对会话数据根的完整路径，不再套 library 的 prompts 模板。
    """
    paths = p.get("paths") or {}
    rec = p.get("rec") or {}
    module = rec.get("prompt_module") or "agent/library"
    file = p.get("file") or rec.get("prompt_file") or ""
    if module == "agent/sessions":
        return {"module": module, "path": file}
    t = paths.get("prompt") or ""
    return {"module": module, "path": t.format(file=file) if t else file}


def save_record(p):
    """把合并后的记录并回用户记录字典（按 id 映射）；写盘值归岗位库模块。"""
    user = dict(p.get("user") or {})
    rec = p.get("rec") or {}
    rid = rec.get("id")
    if rid:
        user[rid] = dict(rec)
    return {"value": user}


# ---- Skill 单元：聚合岗位/流程/工具，支持禁用与级联卸载 ----

def disabled_p(p):
    """Skill 登记字典 → 已禁用标识清单；供工具/岗位清单按归属摘除。判断归岗位库模块。"""
    return {"ids": sorted(_disabled_skill_ids(p.get("skills")))}


def skills_listp(p):
    """Skill 登记字典 → 清单行：关联岗位中文名、流程在库与否、工具名清单与状态。

    disabled 为项目级禁用 Skill 标识集合：记录仍展示并打 disabled_project 标记，供项目重新启用。
    合并与摘要成形归岗位库模块；各库记录由需求读盘后交入。
    """
    skills = p.get("skills") or {}
    roles = p.get("roles") or {}
    flows = p.get("flows") or {}
    disabled_project = set(p.get("disabled") or [])
    tpl = p.get("tpl") or {}
    items = []
    for sid, rec in skills.items():
        if not isinstance(rec, dict):
            continue
        role_id = rec.get("role") or ""
        flow_id = rec.get("flow") or ""
        tool_names = rec.get("tools") or []
        role_rec = roles.get(role_id) or {}
        disabled = rec.get("status") == "disabled"
        items.append({
            "id": sid,
            "cn": rec.get("cn") or sid,
            "doc": rec.get("doc") or "",
            "source": rec.get("source") or "",
            "version": rec.get("version") or "",
            "status": rec.get("status") or "enabled",
            "status_text": (tpl.get("label_disabled") or "") if disabled else (tpl.get("label_enabled") or ""),
            "disabled_project": sid in disabled_project,
            "disabled_text": (tpl.get("label_disabled_project") or "") if sid in disabled_project else "",
            "role": role_id,
            "role_cn": role_rec.get("cn") or "",
            "flow": flow_id,
            "has_flow": bool(flow_id and flow_id in flows),
            "flow_text": (tpl.get("label_has_flow") or "") if (flow_id and flow_id in flows) else (tpl.get("label_no_flow") or ""),
            "tools": "、".join(tool_names),
            "tool_names": tool_names,
            "builtin": bool(rec.get("builtin")),
            "created": rec.get("created") or "",
            "updated": rec.get("updated") or "",
        })
    items.sort(key=lambda x: x.get("created") or "", reverse=True)
    return {"items": items}


def skill_statusp(p):
    """翻转 Skill 启用状态；内置 Skill 受保护不改。记录合并归岗位库模块。"""
    sid = (p.get("id") or "").strip()
    rec = dict(p.get("record") or {})
    tpl = p.get("tpl") or {}
    if not sid:
        return {"ok": False, "code": "missing_id", "error": tpl.get("id_required") or ""}
    if rec.get("builtin"):
        return {"ok": False, "code": "builtin_protected", "status": 403,
                "error": tpl.get("builtin_skill_protected") or ""}
    rec["id"] = sid
    rec["status"] = p.get("status") or rec.get("status") or "enabled"
    rec["updated"] = p.get("now") or ""
    return rec


def skill_uninstallp(p):
    """级联卸载：从 Skill 登记及其岗位/流程/工具字典中一并摘除；内置受保护。

    只裁剪字典不写盘；写盘编排归需求。工具按登记名单与 skill 归属双保险清理。
    """
    sid = (p.get("id") or "").strip()
    skills = dict(p.get("skills") or {})
    tpl = p.get("tpl") or {}
    if not sid:
        return {"ok": False, "code": "missing_id", "error": tpl.get("id_required") or ""}
    rec = skills.get(sid)
    if not isinstance(rec, dict):
        tpl_missing = tpl.get("skill_missing") or ""
        return {"ok": False, "code": "not_found", "status": 404,
                "error": tpl_missing.format(id=sid) if tpl_missing else ""}
    if rec.get("builtin"):
        return {"ok": False, "code": "builtin_protected", "status": 403,
                "error": tpl.get("builtin_skill_uninstall_protected") or ""}
    roles = dict(p.get("roles") or {})
    flows = dict(p.get("flows") or {})
    tools = dict(p.get("tools") or {})
    role_id = rec.get("role") or ""
    flow_id = rec.get("flow") or ""
    tool_names = list(rec.get("tools") or [])
    if role_id and role_id in roles:
        del roles[role_id]
    if flow_id and flow_id in flows:
        del flows[flow_id]
    for tn in tool_names:
        if tn in tools:
            del tools[tn]
    for tn, t in list(tools.items()):
        if isinstance(t, dict) and t.get("skill") == sid:
            del tools[tn]
    del skills[sid]
    return {"skills": skills, "roles": roles, "flows": flows, "tools": tools,
            "removed": {"role": role_id, "flow": flow_id, "tools": tool_names}}
