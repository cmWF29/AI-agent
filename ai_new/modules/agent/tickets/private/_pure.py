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
    title = p.get("title") or "未命名需求"
    return {
        "id": p.get("id"), "title": title,
        "goal": p.get("goal") or "", "project": p.get("project") or "",
        "kind": p.get("kind") or "normal", "parent": p.get("parent") or "",
        "children": [], "status": "queued", "pm": p.get("pm") or "", "roles": [],
        "auto_retrospective": bool(p.get("auto_retrospective")),
        "created": now, "updated": now,
        "closed": "", "summary": "", "verdict": "",
        "history": [{"at": now, "event": "created", "text": title}],
        "backend": p.get("backend") or "",
        "meta": p.get("meta") or {},
    }



def validate_project(p):
    """工单必须绑定项目：纯空值守卫，项目是否存在由需求层读盘判断。"""
    project = (p.get("project") or "").strip()
    if not project:
        return {"ok": False, "code": "missing_project", "status": 400,
                "error": "工单必须绑定到某个项目"}
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
    return [_slim_msg(m) for m in (messages or []) if (m or {}).get("role") != "system"]


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

    merged = [dict(m, session=pm_sid, actor="pm") for m in pm_messages]

    reg_by_sid = {(r or {}).get("session"): r for r in ticket.get("roles") or []}
    live_by_sid = {(r or {}).get("id"): r for r in role_threads}
    archived_by_sid = {(r or {}).get("session"): r for r in (transcript.get("roles") or [])}

    members = [{"session": pm_sid, "role": "pm", "display": "PM",
                "status": status, "kind": "pm"}]
    roles_out = []
    seen = set()

    def add_role(sid, reg, live, archived):
        if not sid or sid in seen:
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
                        "status": rstatus, "kind": (live or {}).get("kind") or "role"})
        roles_out.append({"session": sid, "role": actor, "display": display,
                          "status": rstatus, "task": (reg or {}).get("task") or ""})
        msgs = (live or {}).get("messages") or (archived or {}).get("messages") or []
        for m in msgs:
            mm = dict(m)
            mm["session"] = sid
            mm["actor"] = actor
            merged.append(mm)

    for sid, live in live_by_sid.items():
        add_role(sid, reg_by_sid.get(sid), live, archived_by_sid.get(sid))
    for sid, reg in reg_by_sid.items():
        add_role(sid, reg, live_by_sid.get(sid), archived_by_sid.get(sid))

    return {
        "ticket": view({"rec": ticket}),
        "thread": {"id": pm_sid, "name": thread.get("name") or "", "status": status,
                   "backend": thread.get("backend") or "", "role": "pm",
                   "updated": thread.get("updated") or "", "meta": thread.get("meta") or {},
                   "messages": merged},
        "roles": roles_out,
        "members": members,
    }


def thread(p):
    """线程定型：工单档案缺失返 not_found，否则交 threadp 拼视图。分支在模块内部。"""
    ticket = p.get("ticket")
    if ticket is None:
        return err({"code": "not_found", "status": 404,
                    "message": "工单不存在: %s" % (p.get("id") or "")})
    return threadp(p)


def view(p):
    rec = p.get("rec") or {}
    base = {k: rec.get(k) for k in ("id", "title", "goal", "project", "kind", "parent",
                                    "status", "pm", "created", "updated", "closed",
                                    "summary", "verdict", "auto_retrospective", "backend")}
    base.update({"children": rec.get("children") or [], "roles": rec.get("roles") or [],
                 "history": rec.get("history") or []})
    return base


def present(p):
    """读档后定型：缺档案返 not_found，否则返视图。分支在模块内部。"""
    rec = p.get("rec")
    if rec is None:
        return err({"code": "not_found", "status": 404,
                    "message": "工单不存在: %s" % (p.get("id") or "")})
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
                                          "text": "%s: %s" % (p.get("role"), p.get("task") or "")})
    rec["updated"] = p.get("now") or ""
    return rec


def bindpm(p):
    rec = dict(p.get("rec") or {})
    rec["pm"] = p.get("session") or ""
    rec.setdefault("history", []).append({"at": p.get("now") or "", "event": "pm_start",
                                          "text": "PM 会话已拉起"})
    rec["updated"] = p.get("now") or ""
    return rec


def bindchild(p):
    rec = dict(p.get("rec") or {})
    rec.setdefault("children", []).append(p.get("child"))
    rec.setdefault("history", []).append({"at": p.get("now") or "", "event": "child_split",
                                          "text": "拆出子工单: %s" % (p.get("child") or "")})
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
    verdict_label = "验收通过" if verdict == "accepted" else "未通过关闭"
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
                 "pass": ("review_pass", "评审达标"),
                 "exhausted": ("exhausted", p.get("exhausted_text") or "")}
    hit = event_map.get(verdict)
    if not hit:
        return rec
    event, text = hit
    rec.setdefault("history", []).append({"at": p.get("now") or "", "event": event, "text": text})
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


def files_filter(p):
    items = p.get("items") or []
    pattern = p.get("pattern") or "**/*"
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
    limit = int(p.get("limit_seconds") or 3600)
    return {"stale": idle >= limit}


def record_path(p):
    """工单记录落盘相对路径：布局约定属工单模块，需求层不拼字符串。"""
    return {"path": "tickets/%s/ticket.yaml" % (p.get("id") or "")}
