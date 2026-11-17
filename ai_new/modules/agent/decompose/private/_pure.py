"""技能拆解纯函数：提示词成形、草稿解析与工具核对、草稿记录成形。

不读盘、不取时间、不调模型；模型返回的对象已由闭环解码后交进来。
"""
from __future__ import annotations


def _names(tools):
    return [t.get("name") for t in (tools or []) if t.get("name")]


def promptize(p):
    """把系统提示词、自然语言描述与可用工具名单拼成对话消息；成形规则归拆解模块。

    系统提示词是 data 文件，由需求读入后传入；纯函数不持提示词正文。
    """
    text = (p.get("text") or "").strip()
    system = (p.get("system") or "").strip()
    avail = "、".join(_names(p.get("tools")))
    user = "可用工具名单：%s\n\n待拆解技能描述：%s" % (avail, text)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    return {"messages": messages}


def parse(p):
    """模型返回对象 → 结构化草稿；工具名与注册表白名单核对，名单外的剔除并记 dropped。

    缺字段给空兜底，不报错；核对规则归拆解模块。
    """
    obj = p.get("draft") or {}
    whitelist = _names(p.get("tools"))
    avail = set(whitelist)
    skill = obj.get("skill") or {}
    role = obj.get("role") or {}
    flow = obj.get("flow") or {}
    kept, dropped = [], []
    for name in role.get("tools") or []:
        (kept if name in avail else dropped).append(name)
    draft = {
        "skill": {"id": skill.get("id") or "", "cn": skill.get("cn") or "",
                  "doc": skill.get("doc") or ""},
        "role": {"cn": role.get("cn") or "",
                 "must_dos": list(role.get("must_dos") or []),
                 "forbidden": list(role.get("forbidden") or []),
                 "tools": kept},
        "flow": {"checks": list(flow.get("checks") or []),
                 "nodes": list(flow.get("nodes") or []),
                 "edges": list(flow.get("edges") or [])},
    }
    return {"draft": draft, "dropped": dropped, "tools": whitelist}


def draft_record(p):
    """草稿成形：补状态、来源、时间；id 来自模型给的技能英文标识，缺了不收。"""
    draft = p.get("draft") or {}
    skill = draft.get("skill") or {}
    rid = (skill.get("id") or "").strip()
    if not rid:
        return {"ok": False, "code": "missing_id", "status": 400,
                "error": "拆解结果缺少技能 id（英文标识）"}
    rec = dict(draft)
    rec["id"] = rid
    rec["status"] = "draft"
    rec["source"] = p.get("source") or ""
    rec["created"] = p.get("now") or ""
    rec["builtin"] = False
    return {"rec": rec}


def save_draft(p):
    """并回草稿字典（按 id 映射）；写盘值归拆解模块。"""
    user = dict(p.get("user") or {})
    rec = p.get("rec") or {}
    rid = rec.get("id")
    if rid:
        user[rid] = dict(rec)
    return {"value": user}


def draft_file(p):
    """草稿分库用户记录文件：drafts.yaml。布局约定归拆解模块。"""
    return {"path": "drafts.yaml"}


def draft_get(p):
    """按 id 取一条草稿；查不到返回 not_found 形状。"""
    rec = (p.get("user") or {}).get(p.get("id") or "")
    if not rec:
        return {"ok": False, "code": "not_found", "status": 404,
                "error": "草稿不存在: %s" % (p.get("id") or "")}
    return {"item": rec}


def accept_parts(p):
    """草稿 → 岗位库三库记录形状（角色/流程/技能卡）。字段映射归拆解模块，不写盘。"""
    rec = p.get("rec") or {}
    skill = rec.get("skill") or {}
    role = rec.get("role") or {}
    flow = rec.get("flow") or {}
    rid = skill.get("id") or rec.get("id") or ""
    role_record = {"id": rid, "cn": role.get("cn") or skill.get("cn") or "",
                   "must_dos": role.get("must_dos") or [],
                   "forbidden": role.get("forbidden") or [],
                   "tools": role.get("tools") or [],
                   "prompt_file": "", "backend": "", "builtin": False}
    flow_record = {"id": rid, "role": rid}
    if flow.get("checks"):
        flow_record["checks"] = flow.get("checks")
    if flow.get("nodes"):
        flow_record["kind"] = "process"
        flow_record["nodes"] = flow.get("nodes")
        flow_record["edges"] = flow.get("edges")
    skill_record = {"id": rid, "cn": skill.get("cn") or "",
                    "doc": skill.get("doc") or "", "builtin": False}
    return {"role": role_record, "flow": flow_record, "skill": skill_record}
