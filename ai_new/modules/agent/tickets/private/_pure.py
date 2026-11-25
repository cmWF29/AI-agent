"""工单纯函数：记录成形、状态迁移、角色/子单挂接、消息模板填充。不读盘、不取时间。"""
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




def newid(p):
    return {"id": "T-%s-%04d" % ((p.get("today") or "00000000")[:10].replace("-", ""),
                                 int(p.get("n") or 1))}


def next_n(p):
    """当日已有序号最大值 + 1。工单号全局唯一，不能按项目各自计数。"""
    day = str(p.get("day") or "")
    best = 0
    for raw in p.get("ids") or []:
        parts = str(raw or "").split("-")
        if len(parts) < 3 or parts[1] != day:
            continue
        try:
            k = int(parts[2])
        except ValueError:
            continue
        if k > best:
            best = k
    return {"n": best + 1}


def build(p):
    now = p.get("now") or ""
    title = p.get("title") or p.get("default_title") or ""
    return {
        "id": p.get("id"), "title": title,
        "goal": p.get("goal") or "", "project": p.get("project") or "",
        "kind": p.get("kind") or "normal", "parent": p.get("parent") or "",
        "children": [], "status": "queued", "pm": p.get("pm") or "", "roles": [],
        "auto_retrospective": bool(p.get("auto_retrospective")),
        "created": now, "updated": now,
        "closed": "", "summary": "", "verdict": "",
        "history": [{"at": now, "event": "created", "text": title,
                     "to": p.get("id") or "", "to_kind": "ticket"}],
        "meta": p.get("meta") or {},
    }



def guard_open(p):
    """工单是活体才允许写：已结单只读。

    归档项目里的工单必然都已结单，所以这一条同时挡住了"归档后还能发消息"。
    """
    rec = p.get("rec") or {}
    tpl = p.get("tpl") or {}
    if rec.get("status") == "closed":
        return {"ok": False, "code": "ticket_closed", "status": 409,
                "error": tpl.get("ticket_closed") or ""}
    return {"ok": True}


def guard_create(p):
    """建单前置：归档项目不收新单；PM 被禁用就不能建单（工单默认要拉起 PM）。"""
    tpl = p.get("tpl") or {}
    if p.get("project_archived") is True:
        return {"ok": False, "code": "project_archived", "status": 409,
                "error": tpl.get("project_archived") or ""}
    if p.get("pm_disabled") is True:
        return {"ok": False, "code": "pm_disabled", "status": 409,
                "error": tpl.get("pm_disabled") or ""}
    return {"ok": True}


def _bad(code, status, message=""):
    return {"ok": False, "code": code, "status": status, "error": message}


def _tpl_text(p, key, **fmt):
    """错误文案从 messages.yaml 取；纯层不内置中文，避免业务文案漏进私有层。"""
    tpl = p.get("tpl")
    text = tpl.get(key) if isinstance(tpl, dict) else ""
    if not isinstance(text, str) or not text:
        return ""
    try:
        return text.format(**fmt)
    except (KeyError, IndexError, ValueError):
        return text


def _opt_text(p, key, max_len, tpl=None):
    """可选文本字段：缺省/None 合法；存在就必须是字符串且不超长。"""
    src = p if tpl is None else {"tpl": tpl}
    value = p.get(key)
    if value is None:
        return "", None
    if not isinstance(value, str):
        return None, _bad("bad_input", 400, _tpl_text(src, "bad_type", field=key))
    if len(value) > max_len:
        return None, _bad("bad_input", 400,
                          _tpl_text(src, "bad_too_long", field=key, max=max_len))
    return value, None


def validate_create(p):
    """建单入参类型/长度守卫：HTTP/YAML 里列表、对象、超长正文不能进工单档案。

    必填项目由 ``validate_project`` 判；这里只把可选字段的坏形状提前收口，
    不让它们落到 ``build`` 里变成列表/字典，最后把页面渲染打崩。
    """
    check = {"ok": True}
    project = p.get("project")
    if project is not None and not isinstance(project, str):
        return _bad("bad_project", 400, _tpl_text(p, "bad_project_type"))
    for key, cap in (("title", 200), ("goal", 4000), ("kind", 32),
                     ("parent", 64), ("task", 8000), ("default_title", 200)):
        _, err = _opt_text(p, key, cap)
        if err:
            return err
    # 空 kind 是表单的合法缺省（由 build 回落默认类型），这里只拦非字符串。
    meta = p.get("meta")
    if meta is not None and not isinstance(meta, dict):
        return _bad("bad_input", 400, _tpl_text(p, "bad_meta"))
    steps = p.get("pm_max_steps")
    if steps is not None and (isinstance(steps, bool) or not isinstance(steps, int)):
        return _bad("bad_input", 400, _tpl_text(p, "bad_steps"))
    retro = p.get("auto_retrospective")
    if retro is not None and not isinstance(retro, bool):
        return _bad("bad_input", 400, _tpl_text(p, "bad_bool", field="auto_retrospective"))
    return check


def validate_split(p):
    """拆单入参：children 必须是对象列表；上限必须是整数，字符串比较会 TypeError。"""
    children = p.get("children")
    if not isinstance(children, list):
        return _bad("bad_input", 400, _tpl_text(p, "bad_children_list"))
    for i, child in enumerate(children):
        if not isinstance(child, dict):
            return _bad("bad_input", 400, _tpl_text(p, "bad_child", index=i))
        for key, cap in (("title", 200), ("goal", 4000)):
            _, err = _opt_text(child, key, cap, tpl=p.get("tpl"))
            if err:
                return err
    limit = p.get("max_children")
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            return _bad("bad_input", 400, _tpl_text(p, "bad_max_children"))
    force = p.get("force")
    if force is not None and not isinstance(force, bool):
        return _bad("bad_input", 400, _tpl_text(p, "bad_bool", field="force"))
    return {"ok": True}


def validate_text(p):
    """消息/备注正文：必须是字符串；空串由调用方按业务语义拒绝。"""
    text = p.get("text")
    if not isinstance(text, str):
        return _bad("bad_input", 400, _tpl_text(p, "bad_text_type"))
    if len(text) > 20000:
        return _bad("bad_input", 400, _tpl_text(p, "bad_text_long"))
    return {"ok": True, "text": text}


def validate_rebind(p):
    """项目改名改挂：from/to 都必须是字符串，否则会把工单 project 写成列表/对象。"""
    for key in ("from", "to"):
        value = p.get(key)
        if not isinstance(value, str) or not value.strip():
            return _bad("bad_input", 400, _tpl_text(p, "bad_nonempty", field=key))
    if p.get("from") == p.get("to"):
        return _bad("bad_input", 400, _tpl_text(p, "bad_from_to_same"))
    return {"ok": True}


def validate_project(p):
    """工单必须绑定项目：纯空值守卫，项目是否存在由需求层读盘判断。

    项目 id 来自 HTTP/YAML，非字符串不能 ``strip()`` 打 500；类型错按 bad_project 拒绝。
    """
    project = p.get("project")
    if not isinstance(project, str):
        return {"ok": False, "code": "bad_project", "status": 400,
                "error": p.get("tpl") or ""}
    project = project.strip()
    if not project:
        return {"ok": False, "code": "missing_project", "status": 400,
                "error": p.get("tpl") or ""}
    return {"ok": True, "project": project}


def _slim_msg(m):
    """留档消息：去掉 system 人设大段，只保留往来对话与工具调用痕迹。"""
    if not isinstance(m, dict):
        return {"role": "system", "content": str(m)}
    out = {"role": m.get("role") or "", "content": m.get("content") or ""}
    if m.get("ts"):
        out["ts"] = m.get("ts")
    if m.get("tool_calls"):
        out["tool_calls"] = m.get("tool_calls")
    return out


def _slim_thread(messages):
    out = []
    for m in messages or []:
        if isinstance(m, dict) and m.get("role") == "system":
            continue
        out.append(_slim_msg(m))
    return out


def archive_transcript(p):
    """结单留档：把 PM/角色会话往来对话固化进工单记录，随后会话文件可被回收。

    纯计算不读盘；会话快照由路由读盘后传入。system 人设不进留档。
    """
    rec = dict(p.get("rec") or {})
    pm = p.get("pm") or {}
    pm_snap = {"session": pm.get("session") or "", "name": pm.get("name") or "",
               "messages": _slim_thread(pm.get("messages"))}
    role_snaps = []
    for r in p.get("roles") or []:
        r = r or {}
        role_snaps.append({"session": r.get("session") or "", "role": r.get("role") or "",
                           "display": r.get("display") or r.get("role") or "",
                           "messages": _slim_thread(r.get("messages"))})
    rec["transcript"] = {"pm": pm_snap, "roles": role_snaps}
    return rec


def _state_brief(rec):
    """会话状态机快照：只带可视化要的字段（阶段链与活跃集合），不带工具清单等重字段。"""
    rec = rec or {}
    pre = rec.get("machine")
    if isinstance(pre, dict) and pre.get("states"):
        return {"flow": pre.get("flow") or {}, "stage": pre.get("stage") or "",
                "initial": pre.get("initial") or "", "active": pre.get("active") or [],
                "states": pre.get("states") or []}
    meta = rec.get("meta") or {}
    raw = rec.get("stages") or meta.get("stages") or []
    states = []
    for st in raw:
        if not isinstance(st, dict):
            continue
        states.append({"id": st.get("id") or "",
                       "cn": st.get("cn") or st.get("id") or "",
                       "desc": st.get("desc") or "",
                       "next": st.get("next") or [],
                       "terminal": bool(st.get("terminal"))})
    return {"flow": rec.get("flow") or meta.get("flow") or {},
            "stage": rec.get("stage") or meta.get("stage") or "",
            "initial": rec.get("initial") or (meta.get("machine") or {}).get("initial") or "",
            "active": rec.get("active") or meta.get("active") or [],
            "states": states}


def _todo_brief(rec):
    """会话待办摘要：模型自排计划的条数与进行项，视图一行看得到，不摊整表。"""
    items = (rec or {}).get("todos") or []
    done = len([x for x in items if (x or {}).get("status") == "done"])
    doing = [x for x in items if (x or {}).get("status") == "doing"]
    return {"total": len(items), "done": done,
            "current": ((doing[0] or {}).get("text") or "") if doing else ""}


def _wire_brief(w, seq):
    """网络报文只留"这一轮真发过什么"的壳：请求体与响应原文是几 KB 的重字段，
    塞进群聊流会把首屏撑到兆级；原文按需用 message-wire 回读，视图只带定位与摘要。"""
    if not isinstance(w, dict) or not w.get("url"):
        return None
    def _len(v):
        if v is None:
            return 0
        return len(v) if isinstance(v, str) else len(str(v))
    return {"url": w.get("url") or "", "method": w.get("method") or "POST",
            "model": w.get("model") or "", "status": w.get("status"),
            "stream": bool(w.get("stream")),
            "req_len": _len(w.get("request")), "res_len": _len(w.get("response")),
            "seq": seq}


def _stamp(msgs, sid, actor, base, display=None):
    """给合并进群聊的消息打发言者与时间：缺 at 的用会话起始时刻加序位偏移兜底。

    会话开局的原始需求 role 仍是 user（喂模型），但它不是 PM 说的话：
    首个 user 且此前没有 assistant 的，补 kind=note，展示侧归“系统 → 岗位”。
    """
    out = []
    start = float(base or 0)
    seen_assistant = False
    for i, m in enumerate(msgs):
        mm = dict(m, session=sid, actor=actor)
        if mm.get("role") == "user" and mm.get("kind") is None and not seen_assistant:
            mm["kind"] = "note"
        if mm.get("kind") == "note":
            mm["actor"] = "system"
            if not mm.get("to") and display:
                mm["to"] = display
        if mm.get("role") == "assistant":
            seen_assistant = True
        if not mm.get("at"):
            mm["at"] = start + i * 1e-4
        brief = _wire_brief(mm.get("wire"), i)
        if brief is None:
            mm.pop("wire", None)
        else:
            mm["wire"] = brief
        out.append(mm)
    return out


def threadp(p):
    """工单群聊线程视图：工单档案 + PM/角色会话合并消息流 + 成员与角色实例清单。

    PM 与角色会话不分 tab，并入同一消息流；每条消息带 session/actor 标注发言者。
    会话被回收后，往来对话从工单留档 transcript 回填，结单后仍可回看。
    """
    ticket = p.get("ticket") or {}
    thread = p.get("thread") or {}
    role_threads = p.get("role_threads") or []
    transcript = ticket.get("transcript") or {}

    pm_sid = thread.get("id") or ticket.get("pm") or ""
    pm_messages = thread.get("messages") or []
    if not pm_messages:
        pm_messages = (transcript.get("pm") or {}).get("messages") or []
    status = thread.get("status") or ""
    if ticket.get("status") == "closed" and not status:
        status = "gone"

    # 消息时间轴：新消息自带 at；历史落盘没有时间戳的，用会话创建时刻 + 序位补齐，
    # 保证同一会话内单调递增，视图才能把工单历程事件按时间插进消息流而不是全堆在最前面。
    base = (thread.get("created") or thread.get("updated")
            or ticket.get("created") or ticket.get("updated"))
    merged = _stamp(pm_messages, pm_sid, "pm", base, "PM")

    reg_by_sid = {(r or {}).get("session"): r for r in ticket.get("roles") or []}
    live_by_sid = {(r or {}).get("id"): r for r in role_threads}
    archived_by_sid = {(r or {}).get("session"): r for r in (transcript.get("roles") or [])}

    members = [{"session": pm_sid, "role": "pm", "display": "PM",
                "status": status, "kind": "pm", "task": ticket.get("goal") or "",
                "machine": _state_brief(thread),
                "todos": _todo_brief(thread)}]
    roles_out = []
    seen = {pm_sid}

    def add_role(sid, reg, live, archived):
        if not sid or sid == pm_sid or sid in seen:
            return
        seen.add(sid)
        actor = (live or {}).get("role") or (reg or {}).get("role") or sid
        display = (reg or {}).get("display") or (live or {}).get("name") or actor
        if live:
            rstatus = live.get("status") or "idle"
        else:
            rstatus = "gone"
        if ticket.get("status") == "closed":
            rstatus = "gone"
        members.append({"session": sid, "role": actor, "display": display,
                        "status": rstatus, "kind": (live or {}).get("kind") or "role",
                        "task": (reg or {}).get("task") or "",
                        "machine": _state_brief(live or archived),
                        "todos": _todo_brief(live or archived)})
        roles_out.append({"session": sid, "role": actor, "display": display,
                          "status": rstatus, "task": (reg or {}).get("task") or ""})
        msgs = (live or {}).get("messages") or (archived or {}).get("messages") or []
        merged.extend(_stamp(msgs, sid, actor,
                             (live or archived or {}).get("created")
                             or base, display))

    for sid, live in live_by_sid.items():
        add_role(sid, reg_by_sid.get(sid), live, archived_by_sid.get(sid))
    for sid, reg in reg_by_sid.items():
        add_role(sid, reg, live_by_sid.get(sid), archived_by_sid.get(sid))

    # 只读门禁一处算：结单或所在项目归档，都落到同一个 locked，前端四个控件共用。
    closed = ticket.get("status") == "closed"
    archived = p.get("project_archived") is True
    locked = closed or archived
    reason = ""
    if archived:
        reason = (p.get("tpl_lock") or {}).get("archived") or ""
    elif closed:
        reason = (p.get("tpl_lock") or {}).get("closed") or ""

    return {
        "locked": locked,
        "lock_reason": reason,
        "ticket": view({"rec": ticket}),
        "thread": {"id": pm_sid, "name": thread.get("name") or "", "status": status,
                   "role": "pm",
                   "updated": thread.get("updated") or "", "meta": thread.get("meta") or {},
                   "todos": thread.get("todos") or [], "messages": merged},
        "roles": roles_out,
        "members": members,
    }


def thread(p):
    """线程定型：工单档案缺失返 not_found，否则交 threadp 拼视图。分支在模块内部。"""
    ticket = p.get("ticket")
    if ticket is None:
        tpl = p.get("tpl") or ""
        tid = p.get("id") or ""
        return err({"code": "not_found", "status": 404,
                    "message": tpl.format(id=tid) if tpl else ""})
    return threadp(p)


def view(p):
    rec = p.get("rec") or {}
    base = {k: rec.get(k) for k in ("id", "title", "goal", "project", "kind", "parent",
                                    "status", "pm", "created", "updated", "closed",
                                    "summary", "verdict", "auto_retrospective")}
    base.update({"children": rec.get("children") or [], "roles": rec.get("roles") or [],
                 "history": rec.get("history") or []})
    return base


def present(p):
    """读档后定型：缺档案返 not_found，否则返视图。分支在模块内部。"""
    rec = p.get("rec")
    if rec is None:
        tpl = p.get("tpl") or ""
        tid = p.get("id") or ""
        return err({"code": "not_found", "status": 404,
                    "message": tpl.format(id=tid) if tpl else ""})
    return view({"rec": rec})


def screen(p):
    items = []
    for rec in p.get("rows") or []:
        if not rec:
            continue
        if p.get("status") and rec.get("status") != p.get("status"):
            continue
        if p.get("project") and rec.get("project") != p.get("project"):
            continue
        items.append(view({"rec": rec}))
    return {"items": items}


def roles(p):
    return {"items": (p.get("rec") or {}).get("roles") or []}


def touch(p):
    """会话活动后刷新工单 updated：不改状态、不记 history，只更新最后活动时间。"""
    rec = dict(p.get("rec") or {})
    rec["updated"] = p.get("now") or ""
    return rec


def note(p):
    rec = dict(p.get("rec") or {})
    text = (p.get("text") or "").strip()
    if not text:
        return rec  # 空备注不落盘：少一条记录，好过多一条脏记录
    rec.setdefault("history", []).append({"at": p.get("now") or "", "event": "note",
                                          "text": text})
    rec["updated"] = p.get("now") or ""
    return rec


def bindrole(p):
    rec = dict(p.get("rec") or {})
    rec.setdefault("roles", []).append({"session": p.get("session"), "role": p.get("role"),
                                        "display": p.get("display") or p.get("role"),
                                        "task": p.get("task") or "", "status": "spawned"})
    rec.setdefault("history", []).append({"at": p.get("now") or "", "event": "role_spawn",
                                          "text": "%s: %s" % (p.get("role"), p.get("task") or ""),
                                          "to": p.get("display") or p.get("role") or "",
                                          "to_kind": "role"})
    rec["updated"] = p.get("now") or ""
    return rec


def bindpm(p):
    rec = dict(p.get("rec") or {})
    rec["pm"] = p.get("session") or ""
    rec.setdefault("history", []).append({"at": p.get("now") or "", "event": "pm_start",
                                          "text": p.get("pm_text") or "",
                                          "to": p.get("session") or "PM", "to_kind": "pm"})
    rec["updated"] = p.get("now") or ""
    return rec


def bindchild(p):
    rec = dict(p.get("rec") or {})
    rec.setdefault("children", []).append(p.get("child"))
    tpl = p.get("tpl") or ""
    child = p.get("child") or ""
    rec.setdefault("history", []).append({"at": p.get("now") or "", "event": "child_split",
                                          "text": tpl.format(child=child) if tpl else "",
                                          "to": child, "to_kind": "ticket"})
    rec["updated"] = p.get("now") or ""
    return rec


def collect_session_ids(p):
    """结单回收名单：工单登记的 PM/角色会话 ∪ 会话目录里挂在本工单上的全部记录。

    登记名单可能漏挂异常退出的角色会话，再按会话记录的 ticket 字段兜底匹配，
    确保本工单会话不残留。纯计算不读盘；会话记录由闭环读盘后传入。
    """
    rec = p.get("rec") or {}
    tid = str(rec.get("id") or "")
    ids = []

    def add(sid):
        sid = str(sid or "").strip()
        if sid and sid not in ids:
            ids.append(sid)

    add(rec.get("pm"))
    for r in rec.get("roles") or []:
        add((r or {}).get("session"))
    for row in p.get("rows") or []:
        row = row or {}
        if str(row.get("ticket") or "") == tid:
            add(row.get("id"))
    return {"sids": ids}


def closefin(p):
    rec = dict(p.get("rec") or {})
    verdict = p.get("verdict") or "accepted"
    rec["status"] = "closed"
    rec["summary"] = p.get("summary") or ""
    rec["verdict"] = verdict
    rec["closed"] = p.get("now") or ""
    rec["updated"] = p.get("now") or ""
    verdict_label = (p.get("accepted_text") or "") if verdict == "accepted" else (p.get("rejected_text") or "")
    summary = p.get("summary") or ""
    text = "%s%s" % (verdict_label, ("：" + summary) if summary else "")
    rec.setdefault("history", []).append({"at": p.get("now") or "", "event": "closed",
                                          "text": text})
    return rec


def review_mark(p):
    """收尾评审落历程：repush 回催缺口 / pass 达标 / exhausted 卡点；waiting 不落事件。

    纯计算，不读盘；事件节点随工单写盘一起落。verdict 三态由 library.review 判定，
    各态说明文案由调用方传入，选哪条由本函数按 verdict 决定。
    """
    rec = dict(p.get("rec") or {})
    verdict = p.get("verdict") or ""
    event_map = {"repush": ("repush", p.get("repush_text") or ""),
                 "pass": ("review_pass", p.get("pass_text") or ""),
                 "exhausted": ("exhausted", p.get("exhausted_text") or "")}
    hit = event_map.get(verdict)
    if not hit:
        return rec
    event, text = hit
    # 回催是发给具体岗位会话的，不是发给工单、更不是广播给全体；
    # 只有调用方显式带了接收岗位才改，旧调用/旧数据仍按工单归属，避免影响历史语义。
    to, to_kind = rec.get("id") or "", "ticket"
    if verdict == "repush" and p.get("to"):
        to, to_kind = str(p.get("to") or ""), str(p.get("to_kind") or "role")
    rec.setdefault("history", []).append({"at": p.get("now") or "", "event": event, "text": text,
                                          "to": to, "to_kind": to_kind})
    rec["updated"] = p.get("now") or ""
    return rec


def branch(p):
    """子单是否都结了：给需求当守卫。"""
    open_children = [c for c in p.get("children") or [] if c and c.get("status") != "closed"]
    return {"open": open_children, "all_closed": not open_children}


def pick(p):
    """按角色名/显示名/会话 id 找目标会话。"""
    for r in (p.get("rec") or {}).get("roles") or []:
        if p.get("target") in (r.get("role"), r.get("display"), r.get("session")):
            return {"session": r.get("session"), "role": r.get("role")}
    return {"session": "", "role": ""}


def resolve_target(p):
    """归一消息目标：pm 走工单主会话，其余交 pick 找角色会话。分支在模块内部。"""
    rec = p.get("rec") or {}
    if p.get("target") == "pm":
        return {"session": rec.get("pm") or "", "role": "pm"}
    return pick(p)


def _rel_to_ticket(path, ticket):
    """交付件清单基准归到工单目录：artifacts 落的是 projects/<p>/tickets/<t>/<rel>，
    流程 checks 写的是工单内相对 glob（docs/pm/plan.md），不剥前缀永远匹配不上。
    纯字符串比较（工单号大小写不一致也算同一单）。"""
    marker = "/tickets/%s/" % str(ticket or "")
    low = path.lower()
    idx = low.find(marker.lower())
    if idx >= 0 and ticket:
        return path[idx + len(marker):]
    return path


def files_filter(p):
    if not p.get("ticket"):
        # 无工单号（对话型会话）不能把清单基准退化成全库：空单号当作"无交付件"。
        return {"ticket": p.get("ticket") or "", "items": []}
    items = p.get("items") or []
    pattern = p.get("pattern") or "**/*"
    items = [dict(it, path=_rel_to_ticket(it.get("path") or "", p.get("ticket")))
             for it in items]
    if pattern != "**/*":
        items = [it for it in items if _glob(it.get("path") or "", pattern)]
    return {"ticket": p.get("ticket"), "items": items}


def paths(p):
    """交付件条目清单 → 路径字符串清单，交流程校验。"""
    return {"paths": [it.get("path") for it in (p.get("items") or []) if it.get("path")]}


def err(p):
    return {"ok": False, "code": p.get("code") or "error",
            "status": p.get("status") or 400, "error": p.get("message") or ""}


def msg(p):
    """消息模板：模板文本与变量都由需求取来，这里只做填充。"""
    tpl = p.get("tpl") or p.get("fallback") or ""
    try:
        return {"text": tpl.format(**(p.get("vars") or {}))}
    except KeyError:
        return {"text": tpl}


def stale(p):
    """超过阈值没动、且还开着 —— 判定是纯比较，时间由 clock 给。"""
    rec = p.get("rec") or {}
    if rec.get("status") == "closed":
        return {"stale": False}
    idle = int(p.get("idle_seconds") or 0)
    limit = int(p.get("limit_seconds"))
    return {"stale": idle >= limit}


def record_path(p):
    """工单记录落盘相对路径：模板由需求层配置表给出，纯函数只填参。

    模板带 `{project}` 时工单落在所属项目目录里；调用方没给项目就退到不带项目
    前缀的位置——那里迁移后一定是空的，所以读不到别人的单，也不会串档。
    """
    paths = p.get("paths") or {}
    t = paths.get("record") or ""
    tid = p.get("id") or ""
    if not t:
        return {"path": tid}
    pj = str(p.get("project") or "").strip()
    if "{project}" in t and not pj:
        return {"path": t.replace("projects/{project}/", "").format(id=tid)}
    return {"path": t.format(project=pj, id=tid)}
