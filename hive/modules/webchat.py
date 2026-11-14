"""网页桥 —— 群聊控制台的后端（v3）。

三个职责：
1) 群列表：本地层（本机节点）→ 全局秘书 → 各项目（含项目秘书）→ 各工单群；
2) 时间线：把会话里的“人话”聚合成群聊；**系统事件不混进群聊**（需求 12/13），
   事件走 /api/tickets/{id}/flow 与 /api/web/events；
3) 直播：/api/web/live 返回“谁正在说话（流式增量）+ 最近发生了什么”，
   网页据此显示打字机效果、判断死循环、点“打断”（需求 16）。

发送：POST /api/chat/send → 直接走 sessions.submit（不再套 CLI，避免固定超时）。
结单后的工单群只读，由 tickets.message 的 410 拒绝（需求 10）。

对外 API：
  POST /api/chat/send
  GET  /api/chat/job/{job_id}
  GET  /api/web/groups
  GET  /api/web/timeline?group=&limit=&since_ts=
  GET  /api/web/live?group=
  GET  /api/web/events?limit=
  GET  /api/trace/recent?session=&ticket=&kind=
  GET  /api/trace/file?session=
"""
from __future__ import annotations

import time
import uuid

from ..kernel.api import ApiError, Module


class WebChat(Module):
    name = "webchat"

    def setup(self):
        self.jobs = {}
        self.secretary_id = self.cfg["secretary"].get("session_id") or "secretary"
        self.log.info("webchat.ready", secretary=self.secretary_id)
        self.api.route("POST", "/api/chat/send", name="send")(self.send)
        self.api.route("GET", "/api/chat/job/{job_id}", name="job")(self.job)
        self.api.route("GET", "/api/web/groups", name="groups")(self.groups)
        self.api.route("GET", "/api/web/timeline", name="timeline")(self.timeline)
        self.api.route("GET", "/api/web/live", name="live")(self.live)
        self.api.route("GET", "/api/web/modules", name="modules")(self.modules_api)
        self.api.route("GET", "/api/web/events", name="events")(self.events)
        self.api.route("GET", "/api/trace/recent", name="trace_recent")(self.trace_recent)
        self.api.route("GET", "/api/trace/file", name="trace_file")(self.trace_file)

    def _default_secretary(self):
        try:
            projects = self.ctx.api("projects.list").get("items", [])
        except ApiError:
            projects = []
        return ("sec-" + projects[0]["id"]) if projects else ""

    # ---------------- 发送 ----------------
    def _target_of(self, group):
        """group -> (session_id, kind)。传 'T-xxx' 走工单；'sec-<p>' 走项目秘书；其余走全局秘书。"""
        g = (group or "").strip()
        if g.startswith("ticket:"):
            g = g.split(":", 1)[-1]
        if g.startswith("T-"):
            t = self.ctx.api("tickets.get", ticket_id=g)["ticket"]
            if t.get("status") in ("closed", "closing"):
                raise ApiError(
                    "工单 %s 已结单或正在结单，群聊只读。要改结果请新开工单，并在目标里写“基于 %s”。" % (g, g),
                    status=410, code="ticket_closed")
            return t.get("pm") or "", "ticket"
        if g.startswith("sec-"):
            return g, "secretary"
        if not g or g == self.secretary_id:
            g = self._default_secretary()
            if not g:
                raise ApiError("还没有项目；请先创建项目，全局秘书已移除", code="no_project")
            return g, "secretary"
        return g, "secretary"

    def send(self, payload):
        text = (payload.get("text") or "").strip()
        if not text:
            raise ApiError("text 不能为空", code="empty_text")
        group = (payload.get("group") or self._default_secretary()).strip()
        job_id = "c-" + uuid.uuid4().hex[:10]
        job = {"id": job_id, "group": group, "text": text, "status": "running",
               "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "reply": "", "t0": time.time()}
        self.jobs[job_id] = job
        if len(self.jobs) > 80:
            for k in sorted(self.jobs, key=lambda k: self.jobs[k]["t0"])[:20]:
                self.jobs.pop(k, None)

        session, kind = self._target_of(group)
        # 高峰排队：先判断，再决定“发”还是“囤”
        force = payload.get("force") in (True, 1, "1")
        if not force:
            try:
                idle = self.ctx.api("idle.judge")["idle"]
            except ApiError:
                idle = {"peak": False}
            if idle.get("peak"):
                project = session[4:] if session.startswith("sec-") else ""
                self.ctx.api("idle.enqueue", kind="message",
                             payload={"session": session, "text": text, "project": project},
                             note=idle.get("reason") or "", project=project)
                job.update({"status": "queued", "reply": "高峰排队中，空闲时自动发送", "idle": idle,
                            "session": session})
                job["ms"] = int((time.time() - job["t0"]) * 1000)
                self.emit("webchat.queued", {"group": group, "session": session})
                return {"job_id": job_id, "status": "queued", "group": group, "session": session,
                        "idle": idle}

        if kind == "ticket":
            if not session:
                raise ApiError("该工单当前没有 PM（可能已结单）", status=410, code="ticket_closed")
            res = self.ctx.api("tickets.message", ticket_id=group.split(":", 1)[-1], text=text)
            job.update({"status": "done", "session": session, "injected": res.get("injected"),
                        "reply": "已投递"})
        else:
            if kind == "secretary":
                project = session[4:] if session.startswith("sec-") else ""
                if not project:
                    raise ApiError("全局秘书已移除，请使用项目秘书", code="no_project")
                self.ctx.api("sessions.ensure", project=project)
            res = self.ctx.api("sessions.send", session=session, text=text)
            job.update({"status": "done", "session": session, "injected": res.get("injected"),
                        "job": res.get("job_id"), "reply": "已投递"})
        job["ms"] = int((time.time() - job["t0"]) * 1000)
        self.emit("webchat.send", {"job": job_id, "group": group, "session": session,
                                   "chars": len(text), "via": payload.get("via") or "api"})
        return {"job_id": job_id, "status": "done", "group": group, "session": session}

    def job(self, payload):
        job = self.jobs.get(payload["job_id"])
        if not job:
            raise ApiError("job 不存在: %s" % payload["job_id"], status=404, code="no_job")
        return {"job": {k: v for k, v in job.items() if k != "t0"}}

    # ---------------- 群列表 ----------------
    def groups(self, payload):
        # 全局秘书已移除：只保留项目秘书与工单群。
        items = []
        try:
            projects = self.ctx.api("projects.list").get("items", [])
        except ApiError:
            projects = []
        tickets = []
        try:
            tickets = self.ctx.api("tickets.list").get("items", [])
        except ApiError:
            tickets = []

        for p in projects:
            pid = p["id"]
            mine = [t for t in tickets if t["project"] == pid]
            try:
                sec = self.ctx.api("sessions.get", session_id="sec-" + pid)["session"]
                sec_state = sec.get("state") or sec.get("status")
                sec_msgs = sec.get("messages", 0)
            except ApiError:
                sec_state, sec_msgs = "lazy", 0
            items.append({"id": "sec-" + pid, "kind": "project_secretary", "title": "项目秘书·" + pid,
                          "display": "项目秘书·" + pid, "project": pid, "layer": "project",
                          "state": sec_state, "messages": sec_msgs, "open": True,
                          "tickets": len(mine), "open_tickets": len([t for t in mine if t["status"] != "closed"])})

        for t in tickets:
            items.append({"id": t["id"], "kind": "ticket", "title": t["title"], "display": t["title"],
                          "project": t["project"], "status": t["status"],
                          "state": t["status"], "pm": t.get("pm") or "",
                          "backend": t.get("backend") or "api",
                          "trace_enabled": bool(t.get("trace_enabled")),
                          "roles": len(t.get("roles") or []), "updated": t.get("updated"),
                          "open": t["status"] != "closed", "created": t.get("created"),
                          "parent": t.get("parent") or ""})
        return {"items": items, "projects": projects, "secretary": "",
                "default_project": (projects[0]["id"] if projects else ""),
                "default_group": self._default_secretary()}

    # ---------------- 时间线 ----------------
    def timeline(self, payload):
        group = (payload.get("group") or self._default_secretary()).strip()
        limit = max(10, min(int(payload.get("limit") or 120), 500))
        since = payload.get("since_ts")
        items = []
        trace_on = False
        if group.startswith("ticket:"):
            group = group.split(":", 1)[-1]
        if group.startswith("T-"):
            items = self._ticket_timeline(group, limit)
            try:
                trace_on = bool(self.ctx.api("tickets.get", ticket_id=group)["ticket"].get("trace_enabled"))
            except ApiError:
                trace_on = False
            # 生命周期/系统事件始终进群聊；模块报文只有 trace=true 才合并。
            items.extend(self._system_timeline(group, limit))
            if trace_on:
                items.extend(self._module_timeline(group, limit))
            items.sort(key=lambda i: i.get("ts") or 0)
        elif group.startswith("sec-"):
            items = self._session_timeline(group, limit, user_label="我", bot_label="项目秘书")
        else:
            items = self._session_timeline(self.secretary_id, limit, user_label="我", bot_label="秘书")
        if since not in (None, ""):
            try:
                cut = float(since)
                items = [i for i in items if (i.get("ts") or 0) > cut]
            except (TypeError, ValueError):
                pass
        cursor = max([float(i.get("ts") or 0) for i in items] or [0])
        return {"group": group, "items": items[-limit:], "cursor": cursor,
                "trace_enabled": trace_on,
                "trace_note": ("模块报文 trace 已开启" if trace_on
                               else "本工单未开启模块报文 trace；系统生命周期消息仍会显示")}

    def _system_timeline(self, ticket_id, limit):
        """把工单生命周期事件作为“系统”消息放进群聊。

    这些事件来自 ticket.history（创建/起分支/派 PM/拉角色/合并/归档/结单等），
    与模块报文 trace 开关无关。历史工单即使 trace=false，也不会丢掉“发生过什么”。
    """
        labels = {
            "created": "工单创建",
            "starting": "开始执行",
            "git_branch": "创建工单分支",
            "pm_spawned": "项目经理已拉起",
            "role_spawned": "角色已拉起",
            "closing": "进入结单流程",
            "merged": "合并回项目 main",
            "pushed": "推送工单分支",
            "archived": "交付件归档",
            "closed": "工单结单",
            "queued": "进入空闲队列",
            "dispatched": "队列开始执行",
            "flow_retry": "流程校验未通过，重试",
            "force_closed": "强制结单",
            "note": "系统备注",
        }
        try:
            t = self.ctx.api("tickets.get", ticket_id=ticket_id)["ticket"]
        except ApiError:
            return []
        out = []
        for h in (t.get("history") or [])[-max(10, min(limit, 60)):]:
            event = (h.get("event") or "").strip()
            detail = (h.get("detail") or "").strip()
            if not event:
                continue
            label = labels.get(event, "事件 " + event)
            out.append({
                "ts": self._ts(h.get("ts")), "type": "system", "role": "system",
                "speaker": "系统", "session": "system", "event": event,
                "text": "【%s】%s" % (label, detail or "—"),
            })
        return out


    def _session_timeline(self, session_id, limit, user_label="我", bot_label="秘书"):
        try:
            res = self.ctx.api("sessions.messages", session_id=session_id, limit=limit)
        except ApiError:
            return []
        out = []
        for m in res.get("items", []):
            role = m.get("role")
            if role not in ("user", "assistant"):
                continue                     # system / tool 不进群聊（需求 12）
            text = (m.get("content") or "").strip()
            if not text:
                continue
            out.append({
                "ts": self._ts(m.get("ts")), "type": "chat",
                "speaker": user_label if role == "user" else bot_label,
                "role": role, "session": session_id,
                "text": text, "tools": m.get("tool_names") or [],
            })
        return out

    def _ticket_timeline(self, ticket_id, limit):
        try:
            t = self.ctx.api("tickets.get", ticket_id=ticket_id)["ticket"]
        except ApiError:
            return []
        sessions = []
        try:
            sessions = self.ctx.api("sessions.list", ticket=ticket_id).get("items", [])
        except ApiError:
            pass
        out = []
        # 用户本人在工单群里说过的话：显示成“我”，不能伪装成秘书/PM 的派活
        user_texts = {m.get("text") for m in (t.get("user_messages") or []) if m.get("text")}
        # 会话还活着：直接读消息
        per = max(15, limit // max(1, len(sessions) or 1))
        for s in sessions:
            try:
                items = self.ctx.api("sessions.messages", session_id=s["id"], limit=per).get("items", [])
            except ApiError:
                continue
            out.extend(self._session_chat(s["id"], s.get("display") or s.get("title") or s.get("role") or s["id"],
                                          s.get("kind") or "", items, user_texts=user_texts))
        # 结单后会话已销毁：回放结单时冻结的 transcript（聊天记录不会随之消失）
        if not out:
            for ts in t.get("transcript") or []:
                out.extend(self._session_chat(ts.get("session") or "", ts.get("display") or "角色",
                                              ts.get("kind") or "", ts.get("items") or [],
                                              user_texts=user_texts))
        out.sort(key=lambda i: i.get("ts") or 0)
        refs = t.get("artifact_refs") or []
        # 每条角色的最后一条发言附上它在本次工单中写过的交付件（按会话+时间匹配）
        for sid in {x.get("session") for x in out if x.get("session")}:
            mine = [x for x in out if x.get("session") == sid and x.get("role") == "assistant"]
            if not mine:
                continue
            arts = [a for a in refs if a.get("session") == sid][-3:]
            if arts:
                mine[-1]["artifacts"] = arts
        return out

    def _session_chat(self, sid, speaker, kind, items, user_texts=None):
        """"把某个会话的消息渲染成群聊口径：PM 的入活显示为“秘书→项目经理”，
        角色的入活显示为“项目经理→角色”，用户本人发的话显示为“我”，系统消息不进群聊。"""
        out = []
        user_texts = user_texts or set()
        for m in items:
            role = m.get("role")
            if role not in ("user", "assistant"):
                continue
            text = (m.get("content") or "").strip()
            if not text:
                continue
            if role == "user" and text.startswith("（系统）"):
                continue                     # 系统注入的续跑/催补/冲突提示，群聊里不展示
            if role == "user" and text in user_texts:
                out.append({"ts": self._ts(m.get("ts")), "type": "chat",
                            "speaker": "我", "role": "user", "session": sid, "text": text})
                continue
            if role == "user" and kind == "pm":
                out.append({"ts": self._ts(m.get("ts")), "type": "task",
                            "speaker": "秘书", "to": speaker, "role": "user",
                            "session": sid, "text": text})
                continue
            if role == "user" and text.startswith("（系统）"):
                continue
            if role == "user" and kind == "role":
                out.append({"ts": self._ts(m.get("ts")), "type": "task",
                            "speaker": "项目经理", "to": speaker, "role": "user",
                            "session": sid, "text": text})
                continue
            out.append({"ts": self._ts(m.get("ts")), "type": "chat",
                        "speaker": "我" if role == "user" else speaker,
                        "role": role, "session": sid, "text": text,
                        "tools": m.get("tool_names") or []})
        return out

    # ---------------- 模块作为“角色”进群聊（需求 19） ----------------
    KINDS = {
        "llm.request": ("LLM", "请求"),
        "llm.response": ("LLM", "响应"),
        "llm.delta": ("LLM", "流式增量"),
        "llm.error": ("LLM", "错误"),
        "tool.call": ("工具", "调用"),
        "tool.result": ("工具", "返回"),
        "api.call": ("模块", "API 调用"),
        "bus.event": ("总线", "事件"),
        "agent.message": ("通信", "agent 消息"),
    }

    def _module_timeline(self, ticket_id, limit, before_ts=None, full=False):
        import json, os
        from ..kernel.config import path_of
        try:
            t = self.ctx.api("tickets.get", ticket_id=ticket_id)["ticket"]
        except ApiError:
            return []
        ids = []
        if t.get("pm"):
            ids.append(t["pm"])
        for r in t.get("roles") or []:
            if r.get("session"):
                ids.append(r["session"])
        for tr in t.get("transcript") or []:
            if tr.get("session"):
                ids.append(tr["session"])
        # 老工单可能没冻结 transcript：从 stages 里补 pm/role 会话，至少能看到执行报文
        for st in t.get("stages") or []:
            if st.get("stage") in ("pm_spawned", "role_spawned") and st.get("detail"):
                detail = str(st["detail"]).split("@")[0].strip()
                if detail.startswith(("pm-", "role-")):
                    ids.append(detail)
        ids = list(dict.fromkeys([i for i in ids if i]))
        root = path_of(self.cfg, "trace.root", "data/traces")
        out = []
        per = max(40 if full else 20, limit // max(1, len(ids)))
        for sid in ids:
            path = os.path.join(root, sid + ".jsonl")
            if not os.path.exists(path):
                continue
            try:
                lines = open(path, encoding="utf-8").read().splitlines()[-max(per, 200 if full else per):]
            except OSError:
                continue
            for line in lines:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                kind = ev.get("kind")
                if kind not in self.KINDS or kind == "llm.delta":
                    continue
                ev_ts = float(ev.get("t") or 0)
                if before_ts and ev_ts >= before_ts:
                    continue
                # 降噪：总线的 llm/tool/session.hook 广播与界面重复，只保留业务事件
                if kind == "bus.event":
                    topic = str((ev.get("data") or {}).get("topic") or "")
                    if topic.startswith(("llm.", "tool.", "session.hook")):
                        continue
                actor, action = self.KINDS[kind]
                data = ev.get("data") or {}
                out.append({"ts": float(ev.get("t") or 0), "type": "module", "role": "module",
                            "speaker": actor, "session": sid, "kind": kind,
                            "text": self._module_line(actor, action, kind, data),
                            "payload": data, "ticket": ticket_id})
        out.sort(key=lambda i: i.get("ts") or 0)
        # 群聊时间线默认只放最近 60 条，避免淹没角色发言；单独查看更早时按请求数量返回
        return out[-limit:] if full else out[-min(limit, 60):]

    def modules_api(self, payload):
        group = (payload.get("group") or "").strip()
        if group.startswith("ticket:"):
            group = group.split(":", 1)[-1]
        if not group.startswith("T-"):
            return {"items": []}
        limit = max(10, min(int(payload.get("limit") or 200), 300))
        try:
            before = float(payload.get("before_ts") or 0)
        except (TypeError, ValueError):
            before = 0
        items = self._module_timeline(group, limit, before_ts=before or None, full=True)
        return {"items": items, "oldest": (items[0].get("ts") if items else None)}

    def _module_line(self, actor, action, kind, data):
        if kind == "api.call":
            return "%s → %s（%sms）" % (data.get("caller") or data.get("from") or "?", data.get("route") or "",
                                         data.get("ms") or 0)
        if kind == "bus.event":
            return "广播 %s" % (data.get("topic") or data.get("event") or "")
        if kind == "tool.call":
            return "调用 %s" % (data.get("name") or data.get("tool") or "")
        if kind == "tool.result":
            return "返回 %s" % (str(data.get("text") or data.get("result") or "")[:80])
        if kind in ("llm.request", "llm.response"):
            return "%s 第 %s 步%s" % (action, data.get("step") or "", data.get("model") or "")
        if kind == "llm.delta":
            return "“%s”" % (str(data.get("text") or "")[:60])
        if kind == "agent.message":
            return "%s → %s：%s" % (data.get("from") or "?", data.get("to") or "?",
                                    str(data.get("text") or "")[:60])
        return action

    def _ts(self, v):
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v:
            try:
                return time.mktime(time.strptime(v, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
            except ValueError:
                return 0.0
        return 0.0

    # ---------------- 直播（流式 + 打断） ----------------
    def live(self, payload):
        group = (payload.get("group") or self._default_secretary()).strip()
        limit = min(int(payload.get("limit") or 12), 40)
        sessions = []
        try:
            if group.startswith(("T-", "ticket:")):
                q = {"ticket": group.split(":", 1)[-1]}
            elif group.startswith("sec-"):
                q = {"kind": "secretary", "project": group[4:]}
            else:
                q = {"kind": "secretary", "project": ""}
            items = self.ctx.api("sessions.list", **q)
            sessions = items.get("items", [])
        except ApiError:
            sessions = []
        running = []
        for s in sessions:
            part = s.get("partial") or {}
            if s.get("state") != "running" and not part.get("text"):
                continue
            running.append({"session": s["id"], "display": s.get("display") or s.get("title"),
                            "state": s.get("state"), "step": part.get("step"),
                            "partial": (part.get("text") or "")[-4000:],
                            "phase": part.get("state")})
        try:
            recent = list(self.bus.recent)[-limit:]
        except Exception:
            recent = []
        events = []
        for ev in recent:
            payload_ = ev.get("payload") or {}
            sid = payload_.get("session") or ""
            if group.startswith("T-") and payload_.get("ticket") != group and not sid:
                continue
            events.append({"t": ev.get("t"), "topic": ev.get("topic"),
                           "source": ev.get("source"), "session": sid,
                           "summary": self._ev_summary(ev.get("topic"), payload_)})
        return {"group": group, "running": running, "events": events,
                "cursor": time.time(), "state": self.ctx.api("sessions.state")}

    def events(self, payload):
        limit = min(int(payload.get("limit") or 60), 300)
        out = []
        for ev in list(self.bus.recent)[-limit:]:
            p = ev.get("payload") or {}
            out.append({"t": ev.get("t"), "topic": ev.get("topic"), "source": ev.get("source"),
                        "session": p.get("session") or "", "ticket": p.get("ticket") or "",
                        "summary": self._ev_summary(ev.get("topic"), p)})
        return {"items": out}

    def _ev_summary(self, topic, payload):
        t = topic or ""
        if t == "llm.delta":
            return "…%s" % (payload.get("text") or "")[-60:]
        if t == "tool.start":
            return "调用 %s %s" % (payload.get("tool"), (payload.get("args") or "")[:80])
        if t == "tool.result":
            return "%s 返回 %s 字（%s）" % (payload.get("tool"), payload.get("chars"), payload.get("mode"))
        if t in ("ticket.created", "ticket.closed", "ticket.role.spawned", "ticket.conflict"):
            return "%s %s" % (payload.get("ticket"), payload.get("role") or payload.get("display") or "")
        if t == "session.run.start":
            return "%s 开始运行" % payload.get("session")
        if t == "session.run.finish":
            return "%s 结束（%s）" % (payload.get("session"), payload.get("status"))
        if t == "gitflow.pushed":
            return "推送 %s @ %s" % (payload.get("branch"), payload.get("head"))
        return t

    # ---------------- 透明化（需求 19） ----------------
    def trace_recent(self, payload):
        trace = self.ctx.state.get("trace")
        if trace is None:
            return {"items": [], "stats": {}}
        kinds = payload.get("kind")
        kinds = kinds.split(",") if kinds else None
        session = payload.get("session") or ""
        if not session and payload.get("group", "").startswith("T-"):
            session = ""
        items = trace.recent(session=session, ticket=payload.get("ticket") or "",
                             kinds=kinds, limit=int(payload.get("limit") or 120))
        return {"items": items, "stats": trace.stats()}

    def trace_file(self, payload):
        trace = self.ctx.state.get("trace")
        if trace is None:
            return {"items": []}
        kinds = payload.get("kind")
        kinds = kinds.split(",") if kinds else None
        return {"items": trace.read_file(payload.get("session") or "", limit=int(payload.get("limit") or 400),
                                         kinds=kinds)}
