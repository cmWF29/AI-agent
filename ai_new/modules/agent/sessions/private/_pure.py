"""会话纯函数：造记录、拼系统消息、露出字段、裁剪上下文。不读盘、不取时间。"""
from __future__ import annotations


def _seed(system, intro, constraint=None):
    """会话开局消息：system 人设在前；流程约束独立成结构化消息；原始需求作为首条 user 在后。

    PM 一句话没说时，会话里也必须看得见"用户到底要什么"，否则工单是个空壳。
    """
    msgs = [{"role": "system", "content": system}]
    if constraint:
        msgs.append({"role": "system", "kind": "flow-context",
                     "constraint": constraint,
                     "content": constraint.get("content") or ""})
    if intro:
        msgs.append({"role": "user", "content": intro})
    return msgs


def refresh_constraint_message(p):
    """用最新流程约束块替换独立的 flow-context 消息；人设 system 与其余消息保留不动。

    约束块的结构化字段（constraint）与渲染文本（content）一并刷新；纯数据成形。
    """
    msgs = list(p.get("messages") or [])
    constraint = p.get("constraint") or {}
    if not constraint:
        return {"messages": msgs}
    content = constraint.get("content") or ""
    for i, m in enumerate(msgs):
        if m.get("kind") == "flow-context":
            msgs[i] = dict(m, constraint=constraint, content=content)
            break
    return {"messages": msgs}


def refresh_stage_message(p):
    """用最新阶段段替换首条 system 里的旧阶段段；其余人设/红线原文保留。

    阶段段标题取新阶段段首行（与 stage_block 输出一致）；纯函数不持有文案默认值。
    """
    msgs = list(p.get("messages") or [])
    stage = p.get("stage") or ""
    head = stage.split("\n", 1)[0].strip() if stage else ""
    for i, m in enumerate(msgs):
        if m.get("role") != "system":
            continue
        text = m.get("content") or ""
        if head and head in text:
            before = text.split(head, 1)[0].rstrip()
            text = (before + "\n\n" + stage).strip() if stage else before
        elif stage:
            text = (text.rstrip() + "\n\n" + stage).strip()
        msgs[i] = dict(m, content=text)
        break
    return {"messages": msgs}


def inject_assigned_message(p):
    """把工单已分派角色清单并入首条 system；已有同标题段先剥离再重写，避免重复注入。

    清单与标题由编排层传入，纯函数不持有岗位名与文案默认值。
    """
    msgs = list(p.get("messages") or [])
    heading = p.get("heading") or ""
    names = []
    for r in p.get("roles") or []:
        rn = r.get("role") if isinstance(r, dict) else r
        if rn and rn not in names:
            names.append(rn)
    if not heading or not names:
        return {"messages": msgs}
    block = heading + "\n" + "\n".join("- %s" % n for n in names)
    for i, m in enumerate(msgs):
        if m.get("role") != "system":
            continue
        cur = m.get("content") or ""
        if heading in cur:
            before = cur.split(heading, 1)[0].rstrip()
            cur = (before + "\n\n" + block).strip()
        else:
            cur = (cur.rstrip() + "\n\n" + block).strip()
        msgs[i] = dict(m, content=cur)
        break
    return {"messages": msgs}


def build(p):
    prefix = p.get("prefix") or ""
    prompt = p.get("prompt") or ""
    injected = p.get("injected") or ""
    task = p.get("task") or ""
    intro = p.get("intro") or ""
    tpl = p.get("tpl") or {}
    system = (prefix + "\n" + prompt + "\n" + injected).strip()
    if task:
        heading = tpl.get("task_heading") or ""
        system = system + ("\n\n" + heading + "\n" if heading else "\n\n") + task
    sid = "%s-%s" % (p.get("kind") or "role", p.get("seq") or 1)
    return {
        "id": sid, "kind": p.get("kind") or "role", "name": p.get("name") or sid,
        "ticket": p.get("ticket") or "", "role": p.get("role") or "",
        "project": p.get("project") or "",
        "scenario": p.get("kind") or "role",
        "status": "idle", "created": p.get("now") or "", "updated": p.get("now") or "",
        "max_steps": p.get("max_steps"),
        "meta": p.get("meta") or {},
        "summary": "",
        "messages": _seed(system, intro, p.get("constraint")),
    }


def _machine_brief(rec):
    """流程状态机快照：阶段链与活跃集合，形状与 tickets 的 machine 一致，不带重字段。"""
    rec = rec or {}
    out = []
    for st in (rec.get("stages") or []):
        if not isinstance(st, dict):
            continue
        out.append({"id": st.get("id") or "", "cn": st.get("cn") or st.get("id") or "",
                    "desc": st.get("desc") or "", "next": st.get("next") or [],
                    "terminal": bool(st.get("terminal"))})
    return {"flow": rec.get("flow") or {}, "stage": rec.get("stage") or "",
            "initial": rec.get("initial") or "", "active": rec.get("active") or [],
            "states": out}


def view(p):
    rec = p.get("rec") or {}
    return {"id": rec.get("id"), "kind": rec.get("kind"), "name": rec.get("name"),
            "ticket": rec.get("ticket"), "role": rec.get("role"),
            "project": rec.get("project"),
            "status": rec.get("status"),
            "created": rec.get("created"), "updated": rec.get("updated"),
            "summary": rec.get("summary") or "",
            "meta": rec.get("meta") or {},
            "machine": rec.get("machine") if isinstance(rec.get("machine"), dict)
            else _machine_brief(rec),
            "todos": rec.get("todos") or [],
            "messages": rec.get("messages") or []}


def present(p):
    """读档后定型：缺记录返 not_found，否则返视图。分支在模块内部。"""
    rec = p.get("rec")
    if rec is None:
        return missing({"id": p.get("id"), "tpl": p.get("tpl")})
    return view({"rec": rec})


def screen(p):
    items = []
    status = p.get("status")
    for rec in p.get("rows") or []:
        if not rec:
            continue
        if status and rec.get("status") != status:
            continue
        items.append(view({"rec": rec}))
    return {"items": items}


def gone(p):
    rec = dict(p.get("rec") or {})
    rec["status"] = "gone"
    rec["updated"] = p.get("now") or ""
    return rec


def compactp(p):
    rec = dict(p.get("rec") or {})
    keep = max(1, int(p.get("keep")))
    msgs = rec.get("messages") or []
    system = [m for m in msgs if m.get("role") == "system"]
    rest = [m for m in msgs if m.get("role") != "system"]
    rec["messages"] = system + rest[-keep:]
    rec["updated"] = p.get("now") or ""
    return rec


def machine_applyp(p):
    """把并入后的状态机契约写回会话快照；活跃态不在新契约内则回收，空则回退初始。纯数据成形。"""
    rec = dict(p.get("rec") or {})
    contract = p.get("contract") or {}
    meta = dict(rec.get("meta") or {})
    meta["machine"] = contract
    by = contract.get("by_id") or {}
    active = [a for a in (meta.get("active") or []) if a in by]
    if not active:
        initial = contract.get("initial") or ""
        active = [initial] if initial else []
    meta["active"] = active
    rec["meta"] = meta
    return rec


def missing(p):
    tpl = p.get("tpl") or ""
    sid = p.get("id") or ""
    return {"ok": False, "code": "not_found", "status": 404,
            "error": tpl.format(id=sid) if tpl else ""}


def record_path(p):
    """会话记录落盘相对路径：模板由需求层配置表给出，纯函数只填参。"""
    paths = p.get("paths") or {}
    t = paths.get("session") or ""
    sid = p.get("id") or ""
    return {"path": t.format(id=sid) if t else sid}


def role_name(p):
    """角色会话名：岗位标识 - 工单 id，纯拼装。"""
    return {"name": "%s-%s" % (p.get("role") or "", p.get("id") or "")}
