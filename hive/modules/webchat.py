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
        self.api.route("GET", "/api/web/events", name="events")(self.events)
        self.api.route("GET", "/api/trace/recent", name="trace_recent")(self.trace_recent)
        self.api.route("GET", "/api/trace/file", name="trace_file")(self.trace_file)

    # ---------------- 发送 ----------------
    def _target_of(self, group):
        """group -> (session_id, kind)。传 'T-xxx' 走工单；'sec-<p>' 走项目秘书；其余走全局秘书。"""
        g = (group or "").strip()
        if g.startswith("ticket:"):
            g = g.split(":", 1)[-1]
        if g.startswith("T-"):
            t = self.ctx.api("tickets.get", ticket_id=g)["ticket"]
            if t.get("status") == "closed":
                raise ApiError(
                    "工单 %s 已结单，群聊只读。要改结果请新开工单，并在目标里写“基于 %s”。" % (g, g),
                    status=410, code="ticket_closed")
            return t.get("pm") or "", "ticket"
        if g.startswith("sec-"):
            return g, "secretary"
        return self.secretary_id, "secretary"

    def send(self, payload):
        text = (payload.get("text") or "").strip()
        if not text:
            raise ApiError("text 不能为空", code="empty_text")
        group = (payload.get("group") or self.secretary_id).strip()
        job_id = "c-" + uuid.uuid4().hex[:10]
        job = {"id": job_id, "group": group, "text": text, "status": "running",
               "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "reply": "", "t0": time.time()}
        self.jobs[job_id] = job
        if len(self.jobs) > 80:
            for k in sorted(self.jobs, key=lambda k: self.jobs[k]["t0"])[:20]:
                self.jobs.pop(k, None)

        session, kind = self._target_of(group)
        if kind == "ticket":
            if not session:
                raise ApiError("该工单当前没有 PM（可能已结单）", status=410, code="ticket_closed")
            res = self.ctx.api("tickets.message", ticket_id=group.split(":", 1)[-1], text=text)
            job.update({"status": "done", "session": session, "injected": res.get("injected"),
                        "reply": "已投递"})
        else:
            if kind == "secretary":
                project = "" if session == self.secretary_id else session[4:]
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
        inst = self.cfg.get("instance") if isinstance(self.cfg.get("instance"), dict) else {}
        info = {"layer": "local", "id": inst.get("id") or "local-1",
                "title": inst.get("title") or "本地节点",
                "scheme": self.ctx.state["http"].scheme if self.ctx.state.get("http") else "http",
                "ticket_root": self.cfg["tickets"].get("root")}

        items = [{"id": self.secretary_id, "kind": "secretary", "title": "秘书", "display": "秘书",
                  "project": "", "layer": "local", "open": True}]
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
                          "roles": len(t.get("roles") or []), "updated": t.get("updated"),
                          "open": t["status"] != "closed", "created": t.get("created"),
                          "parent": t.get("parent") or ""})
        return {"items": items, "projects": projects, "secretary": self.secretary_id,
                "instance": info, "default_project": (projects[0]["id"] if projects else "")}

    # ---------------- 时间线 ----------------
    def timeline(self, payload):
        group = (payload.get("group") or self.secretary_id).strip()
        limit = max(10, min(int(payload.get("limit") or 120), 500))
        since = payload.get("since_ts")
        items = []
        if group.startswith("ticket:"):
            group = group.split(":", 1)[-1]
        if group.startswith("T-"):
            items = self._ticket_timeline(group, limit)
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
        return {"group": group, "items": items[-limit:], "cursor": cursor}

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
        # 结单后会话被销毁了：从归档里补历史，群聊仍可回看（但只读）
        per = max(15, limit // max(1, len(sessions) or 1))
        out = []
        for s in sessions:
            try:
                res = self.ctx.api("sessions.messages", session_id=s["id"], limit=per)
            except ApiError:
                continue
            speaker = s.get("display") or s.get("title") or s.get("role") or s["id"]
            for m in res.get("items", []):
                role = m.get("role")
                if role not in ("user", "assistant"):
                    continue
                text = (m.get("content") or "").strip()
                if not text:
                    continue
                if role == "user" and s.get("kind") == "pm":
                    # PM 会话里的 user 消息 = 系统/秘书派给 PM 的作业（需求 12：不混进群聊当“我”说）
                    out.append({"ts": self._ts(m.get("ts")), "type": "task",
                                "speaker": "秘书", "to": speaker, "role": "user",
                                "session": s["id"], "text": text})
                    continue
                if role == "user" and s.get("kind") == "role":
                    # 角色会话里的 user 消息 = PM 派给它的任务，显示成“项目经理 → 开发A”
                    out.append({"ts": self._ts(m.get("ts")), "type": "task",
                                "speaker": "项目经理", "to": speaker, "role": "user",
                                "session": s["id"], "text": text})
                    continue
                out.append({"ts": self._ts(m.get("ts")), "type": "chat",
                            "speaker": "我" if role == "user" else speaker,
                            "role": role, "session": s["id"], "text": text,
                            "tools": m.get("tool_names") or []})
        out.sort(key=lambda i: i.get("ts") or 0)
        return out

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
        group = (payload.get("group") or self.secretary_id).strip()
        limit = min(int(payload.get("limit") or 12), 40)
        sessions = []
        try:
            q = {"ticket": group.split(":", 1)[-1]} if group.startswith(("T-", "ticket:")) else None
            items = self.ctx.api("sessions.list", **q) if q else self.ctx.api("sessions.list")
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
