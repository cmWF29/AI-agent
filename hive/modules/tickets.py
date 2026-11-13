"""工单模块 —— 秘书发作业，PM 编排，角色干活，PM 收官。

一个工单 = 一个临时 PM 会话 + 若干临时角色会话。
* 秘书只负责“发”：ticket_create。
* PM 负责“排”和“收”：role_spawn / role_task / role_wait，最后 ticket_close。
* 关闭工单时本模块发消息给每个角色，让它们自己沉淀知识再被销毁。

本模块不直接读别的模块的存储：角色状态一律走 sessions.* 的 API。
"""
from __future__ import annotations

import os
import threading
import time
import uuid

from ..kernel.api import ApiError, Module
from ..kernel.config import path_of
from ..kernel.store import Collection, ensure_dir
from ..kernel.tools import Tool

ROLE_TOOLS = [
    "shell", "read_file", "write_file", "grep", "http_get",
    "knowledge_read", "knowledge_write", "knowledge_list", "knowledge_search",
    "memory_add", "memory_search", "session_result",
]

PM_TOOLS = [
    "agent_spawn", "agent_send", "agent_wait", "agent_list", "agent_status",
    "agent_interrupt", "agent_destroy", "agent_compact",
    "role_spawn", "role_task", "role_wait", "role_report",
    "ticket_list", "ticket_status", "ticket_close",
    "knowledge_read", "knowledge_write", "knowledge_list", "knowledge_search",
    "memory_add", "memory_search",
]


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Tickets(Module):
    name = "tickets"

    def setup(self):
        self.root = path_of(self.cfg, "tickets.root", "data/tickets")
        self.store = Collection(self.root)
        self.close_timeout = int(self.cfg["tickets"].get("close_reply_timeout", 120))
        self.max_roles = int(self.cfg["tickets"].get("max_roles", 8))
        self.default_project = self.cfg["tickets"].get("default_project") or "default"
        self._closing = set()
        self.log.info("tickets.ready", root=self.root)

        self.api.route("POST", "/api/tickets/create", name="create")(self.create_api)
        self.api.route("GET", "/api/tickets/list", name="list")(self.list_api)
        self.api.route("GET", "/api/tickets/{ticket_id}", name="get")(self.get_api)
        self.api.route("POST", "/api/tickets/{ticket_id}/close", name="close")(self.close_api)
        self.api.route("POST", "/api/tickets/{ticket_id}/note", name="note")(self.note_api)
        self.api.route("POST", "/api/tickets/{ticket_id}/roles", name="roles")(self.role_api)
        self.api.route("POST", "/api/tickets/{ticket_id}/message", name="message")(self.message_api)
        self.api.route("GET", "/api/tickets/{ticket_id}/files", name="files")(self.files_api)
        self.api.route("GET", "/api/tickets/{ticket_id}/file", name="file")(self.file_api)

        self._register_tools()

    # ---------------- 工单存储 ----------------
    def _get(self, ticket_id):
        t = self.store.get(ticket_id)
        if not t:
            raise ApiError("工单不存在: %s" % ticket_id, status=404, code="no_ticket")
        return t

    def _save(self, ticket):
        ticket["updated"] = _now()
        self.store.put(ticket["id"], ticket)
        return ticket

    def _history(self, ticket, event, detail=""):
        ticket.setdefault("history", []).append({"ts": _now(), "event": event, "detail": str(detail)[:500]})

    # ---------------- 创建 ----------------
    def create(self, title, goal, project=None, roles_hint=None):
        project = project or self.default_project
        try:
            project = self.ctx.api("projects.ensure", name=project)["project"]["id"]
        except ApiError:
            project = project
        tid = "T-%s-%s" % (time.strftime("%Y%m%d"), uuid.uuid4().hex[:6])
        workdir = ensure_dir(os.path.join(self.root, tid, "workspace"))
        ticket = {
            "id": tid,
            "title": title or goal[:60],
            "goal": goal,
            "project": project,
            "status": "planning",
            "roles_hint": roles_hint or [],
            "roles": [],
            "pm": "",
            "workdir": workdir,
            "summary": "",
            "created": _now(),
            "updated": _now(),
            "history": [],
        }
        self._history(ticket, "created", goal[:200])
        self._save(ticket)
        self.emit("ticket.created", {"ticket": tid, "project": project, "title": ticket["title"]})
        self.log.info("ticket.created", ticket=tid, project=project)

        pm_prompt = self._pm_prompt(ticket)
        pm = self.ctx.api(
            "sessions.spawn",
            kind="pm",
            title="PM/" + ticket["title"][:30],
            system_prompt=pm_prompt,
            project=project,
            ticket=tid,
            role="pm",
            tools=PM_TOOLS,
        )["session"]
        ticket["pm"] = pm["id"]
        ticket["status"] = "running"
        self._history(ticket, "pm_spawned", pm["id"])
        self._save(ticket)

        self.ctx.api("sessions.send", session=pm["id"], text=self._pm_kickoff(ticket), max_steps=40)
        return ticket

    def _pm_prompt(self, ticket):
        parts = [self._compose([{"layer": "public"},
                                {"layer": "project", "project": ticket["project"]},
                                {"layer": "ticket", "ticket": ticket["id"]}])]
        parts.append(
            "\n\n## 你的身份：本工单的 PM\n"
            "你负责把这个工单做完：拆解 -> 定角色 -> 分发 -> 收作业 -> 结单。\n"
            "铁律：\n"
            "1. 不要自己动手写业务代码/长文档，那是角色的活；你只编排和验收。\n"
            "2. 角色按需自建：role_spawn(role, task)，角色名可自创（architect/developer/reviewer/researcher/ops…）。\n"
            "3. 一个角色一个会话，任务要写清楚验收标准、产出路径、边界。\n"
            "4. 收作业用 role_wait / role_report，不要靠猜。\n"
            "5. 全部达标后调用 ticket_close(ticket, summary) 结单；结单会自动通知角色沉淀知识并销毁它们。\n"
            "6. 卡住/需要用户拍板时，直接说清楚卡点，不要假装完成。\n"
        )
        return "".join(parts)

    def _pm_kickoff(self, ticket):
        return (
            "工单 %s\n标题：%s\n目标：%s\n项目：%s\n工作目录：%s\n\n"
            "请开始：先给出拆解与角色安排（简短），然后立即 role_spawn 分发任务。"
            % (ticket["id"], ticket["title"], ticket["goal"], ticket["project"], ticket["workdir"])
        )

    def _role_prompt(self, ticket, role, task):
        parts = [
            self._compose([
                {"layer": "public"},
                {"layer": "project", "project": ticket["project"]},
                {"layer": "ticket", "ticket": ticket["id"]},
            ]),
            "\n\n## 你的身份：工单 %s 中的 %s\n工单目标：%s\n你的作业：%s\n"
            "要求：\n"
            "1. 在工作目录 %s 内产出，路径写清楚；需要动仓库代码时先看清现状再改。\n"
            "2. 结论必须可验证：给出命令/文件/证据，别只给形容。\n"
            "3. 完成后调用 session_result(summary) 上报，然后再用 knowledge_write 沉淀经验（ticket 层）。\n"
            "4. 遇到阻塞就明确写出来，不要编造完成。\n"
            % (ticket["id"], role, ticket["goal"], task, ticket["workdir"]),
        ]
        return "".join(parts)

    def _compose(self, scopes):
        try:
            return self.ctx.api("knowledge.compose", scopes=scopes).get("text") or ""
        except ApiError:
            return ""

    # ---------------- 角色 ----------------
    def spawn_role(self, ticket, role, task, title=""):
        ticket = self._get(ticket["id"]) if isinstance(ticket, dict) else self._get(ticket)
        if len(ticket.get("roles") or []) >= self.max_roles:
            raise ApiError("角色数已达上限 %d" % self.max_roles, code="too_many_roles")
        role = (role or "developer").strip()[:40]
        ws = ensure_dir(os.path.join(self.root, ticket["id"], "workspace", "%s-%d" % (role, len(ticket["roles"]) + 1)))
        sess = self.ctx.api(
            "sessions.spawn",
            kind="role",
            title=title or ("%s/%s" % (role, ticket["id"])),
            system_prompt=self._role_prompt(ticket, role, task),
            project=ticket["project"],
            ticket=ticket["id"],
            role=role,
            tools=ROLE_TOOLS,
            workspace=ws,
            input_text=task,
        )["session"]
        entry = {"session": sess["id"], "role": role, "task": task[:400], "status": "running",
                 "created": _now(), "workspace": ws}
        ticket["roles"].append(entry)
        ticket["status"] = "running"
        self._history(ticket, "role_spawned", "%s %s" % (role, sess["id"]))
        self._save(ticket)
        self.emit("ticket.role.spawned", {"ticket": ticket["id"], "role": role, "session": sess["id"]})
        return entry

    def role_status(self, ticket_id):
        ticket = self._get(ticket_id)
        live = {}
        try:
            for item in self.ctx.api("sessions.list").get("items", []):
                live[item["id"]] = item
        except ApiError:
            pass
        out = []
        for r in ticket.get("roles") or []:
            info = live.get(r["session"]) or {}
            out.append({
                "session": r["session"], "role": r["role"], "task": r["task"],
                "state": info.get("state") or "gone",
                "status": info.get("status") or "gone",
                "chars": info.get("chars", 0),
                "reply": (info.get("last_reply") or "")[:600],
            })
        return out

    def wait_roles(self, ticket_id, sessions=None, timeout=600):
        ticket = self._get(ticket_id)
        targets = [r["session"] for r in ticket.get("roles") or []]
        if sessions:
            targets = [s for s in targets if s in sessions]
        end = time.time() + timeout
        results = {}
        for sid in targets:
            remain = max(1, int(end - time.time()))
            try:
                res = self.ctx.api("sessions.wait", session=sid, timeout=remain)
                results[sid] = res
            except ApiError as exc:
                results[sid] = {"status": "error", "error": exc.message}
            if time.time() >= end:
                break
        return results

    # ---------------- 关闭 ----------------
    def close(self, ticket_id, summary="", force=False, block=True):
        ticket = self._get(ticket_id)
        if ticket["status"] == "closed":
            return {"ticket": ticket, "already_closed": True}
        ticket["status"] = "closing"
        ticket["summary"] = summary or ticket.get("summary") or ""
        self._history(ticket, "closing", summary[:200])
        self._save(ticket)
        self.emit("ticket.closing", {"ticket": ticket_id, "roles": [r["session"] for r in ticket.get("roles") or []]})

        if block:
            self._do_close(ticket, summary, force)
        else:
            if ticket_id in self._closing:
                return {"ticket": ticket, "closing": True}
            self._closing.add(ticket_id)
            threading.Thread(target=self._do_close_bg, args=(ticket, summary, force), name="close-" + ticket_id,
                             daemon=True).start()
        return {"ticket": self._get(ticket_id), "closing": True}

    def _do_close_bg(self, ticket, summary, force):
        try:
            self._do_close(ticket, summary, force)
        finally:
            self._closing.discard(ticket["id"])

    def _do_close(self, ticket, summary, force):
        ticket_id = ticket["id"]
        archive_note = (
            "工单 %s 即将关闭。请立刻用 knowledge_write 把本次作业中值得沉淀的内容写入 ticket 层："
            "结论、关键文件路径、可复用步骤、踩过的坑。写完回一句 DONE 就结束，不要再做新工作。"
            % ticket_id
        )
        # 1) 角色自己沉淀
        for r in list(ticket.get("roles") or []):
            sid = r["session"]
            try:
                self.ctx.api("sessions.send", session=sid, text=archive_note)
                self.ctx.api("sessions.wait", session=sid, timeout=self.close_timeout if not force else 5)
            except ApiError as exc:
                self.log.warn("ticket.close.role", ticket=ticket_id, session=sid, error=exc.message)
                r["status"] = "gone"
            except Exception as exc:
                self.log.warn("ticket.close.role.unknown", ticket=ticket_id, session=sid, error=repr(exc))
        # 2) PM 自己沉淀
        pm = ticket.get("pm")
        if pm:
            try:
                self.ctx.api("sessions.send", session=pm, text=archive_note)
                self.ctx.api("sessions.wait", session=pm, timeout=self.close_timeout if not force else 5)
            except Exception as exc:
                self.log.warn("ticket.close.pm", ticket=ticket_id, error=repr(exc))
        # 3) 销毁临时会话
        for r in list(ticket.get("roles") or []):
            try:
                self.ctx.api("sessions.destroy", session_id=r["session"])
            except ApiError:
                pass
            r["status"] = "destroyed"
        if pm:
            try:
                self.ctx.api("sessions.destroy", session_id=pm)
            except ApiError:
                pass
            ticket["pm"] = ""

        # 4) 工单级知识归档：写一份 summary
        text = "# 工单 %s\n\n- 目标：%s\n- 项目：%s\n- 创建：%s\n- 关闭：%s\n\n## 结论\n%s\n\n## 角色与产出\n%s" % (
            ticket_id, ticket["goal"], ticket["project"], ticket["created"], _now(),
            summary or "(未填写)",
            "\n".join("- %s (%s): %s" % (r["role"], r["session"], r["task"][:120]) for r in ticket.get("roles") or []),
        )
        try:
            self.ctx.api("knowledge.write", layer="ticket", ticket=ticket_id, name="00-summary",
                         content=text, project=ticket["project"])
        except ApiError as exc:
            self.log.warn("ticket.close.knowledge", ticket=ticket_id, error=exc.message)

        ticket["status"] = "closed"
        ticket["closed"] = _now()
        ticket["summary"] = summary or ticket.get("summary") or ""
        self._history(ticket, "closed", "")
        self._save(ticket)
        self.emit("ticket.closed", {"ticket": ticket_id, "roles": len(ticket.get("roles") or [])})
        self.log.info("ticket.closed", ticket=ticket_id)
        return ticket

    # ---------------- API ----------------
    def create_api(self, payload):
        goal = (payload.get("goal") or "").strip()
        if not goal:
            raise ApiError("goal 必填", code="missing_goal")
        t = self.create(payload.get("title") or "", goal, payload.get("project"), payload.get("roles_hint"))
        return {"ticket": self._public(t)}

    def list_api(self, payload):
        items = [self._public(t) for t in self.store.list()]
        if payload.get("project"):
            items = [i for i in items if i["project"] == payload["project"]]
        if payload.get("status"):
            want = str(payload["status"]).split(",")
            items = [i for i in items if i["status"] in want]
        items.sort(key=lambda t: t["created"], reverse=True)
        open_items = [i for i in items if i["status"] != "closed"]
        return {"items": items, "total": len(items), "open": len(open_items)}

    def get_api(self, payload):
        t = self._get(payload["ticket_id"])
        out = self._public(t)
        out["roles"] = self.role_status(t["id"])
        out["history"] = t.get("history", [])[-30:]
        return {"ticket": out}

    def close_api(self, payload):
        t = self.close(
            payload["ticket_id"],
            payload.get("summary") or "",
            force=bool(payload.get("force")),
            block=payload.get("block", True) in (True, "true", "1", 1),
        )
        if isinstance(t.get("ticket"), dict):
            t["ticket"] = self._public(t["ticket"])
        return t

    def role_api(self, payload):
        t = self._get(payload["ticket_id"])
        entry = self.spawn_role(t, payload.get("role") or "developer",
                                payload.get("task") or t["goal"], payload.get("title") or "")
        return {"role": entry}

    def note_api(self, payload):
        t = self._get(payload["ticket_id"])
        text = payload.get("text") or ""
        if text:
            self._history(t, "note", text)
            self._save(t)
        return {"ticket": self._public(t)}

    # ---------------- 群聊：对工单说话 ----------------
    def message_api(self, payload):
        """在工单“群聊”里发一句话：默认发给 PM，也可指定某个角色会话。"""
        t = self._get(payload["ticket_id"])
        text = (payload.get("text") or "").strip()
        if not text:
            raise ApiError("text 必填", code="missing_text")
        target = payload.get("session") or t.get("pm")
        if not target:
            raise ApiError("该工单已经没有在跑的 PM（可能已结单），新需求请另开工单", code="no_pm")
        res = self.ctx.api("sessions.send", session=target, text=text)
        self._history(t, "user_message", text[:200])
        self._save(t)
        self.emit("ticket.message", {"ticket": t["id"], "session": target, "chars": len(text)})
        return {"ticket": t["id"], "session": target, "injected": res.get("injected"), "job": res.get("job_id")}

    # ---------------- 交付件 ----------------
    def _safe_path(self, t, rel):
        base = os.path.realpath(t["workdir"])
        p = os.path.realpath(os.path.join(base, rel or ""))
        if p != base and not p.startswith(base + os.sep):
            raise ApiError("非法路径（越界）", status=400, code="bad_path")
        return p

    def files_api(self, payload):
        """列出工单工作目录里的交付件（全部是相对路径，网页直接可点）。"""
        t = self._get(payload["ticket_id"])
        base = os.path.realpath(t["workdir"])
        limit = int(payload.get("limit") or 200)
        items = []
        total = 0
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                total += 1
                if len(items) < limit:
                    items.append({
                        "path": os.path.relpath(p, base).replace(os.sep, "/"),
                        "size": st.st_size,
                        "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
                    })
        items.sort(key=lambda i: (i["path"].count("/"), i["path"]))
        return {"ticket": t["id"], "root": base, "items": items, "total": total}

    def file_api(self, payload):
        """读一个交付件：文本给 text，二进制给 base64（图片可直接在网页里显示）。"""
        import base64
        t = self._get(payload["ticket_id"])
        rel = (payload.get("path") or "").strip().lstrip("/")
        if not rel:
            raise ApiError("path 必填", code="missing_path")
        p = self._safe_path(t, rel)
        if not os.path.isfile(p):
            raise ApiError("文件不存在: %s" % rel, status=404, code="no_file")
        size = os.path.getsize(p)
        limit = int(payload.get("max_bytes") or 262144)
        with open(p, "rb") as f:
            raw = f.read(min(size, limit))
        enc = "utf-8"
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = base64.b64encode(raw).decode("ascii")
            enc = "base64"
        return {"ticket": t["id"], "path": rel, "size": size, "truncated": size > limit,
                "encoding": enc, "text": text}

    def _public(self, t):
        return {
            "id": t["id"], "title": t["title"], "goal": t["goal"], "project": t["project"],
            "status": t["status"], "pm": t.get("pm"), "summary": t.get("summary"),
            "roles": [{"session": r["session"], "role": r["role"], "status": r.get("status"), "task": r["task"][:160]}
                      for r in t.get("roles") or []],
            "created": t["created"], "updated": t.get("updated"),
            "workdir": t.get("workdir"),
        }

    # ---------------- 工具 ----------------
    def _register_tools(self):
        tools = self.ctx.tools

        def create_tool(args, tctx):
            t = self.create(args.get("title") or "", args.get("goal") or "",
                            args.get("project") or tctx.session.get("project"))
            return "工单已创建：%s（PM 会话 %s 已开工）。后续你可以用 ticket_status 查看进度。" % (t["id"], t["pm"])

        def list_tool(args, tctx):
            items = self.store.list()
            if not items:
                return "暂无工单"
            items.sort(key=lambda t: t["created"], reverse=True)
            return "\n".join("%s | %s | %s | PM=%s" % (t["id"], t["status"], t["title"][:40], t.get("pm") or "-")
                             for t in items[:20])

        def status_tool(args, tctx):
            t = self._get(args.get("ticket"))
            rows = self.role_status(t["id"])
            lines = ["%s [%s] %s" % (t["id"], t["status"], t["title"]), "目标: %s" % t["goal"][:200]]
            lines.append("PM: %s" % (t.get("pm") or "-"))
            for r in rows:
                lines.append("- %s %s | %s | %s字" % (r["role"], r["session"], r["state"], r["chars"]))
            if t.get("summary"):
                lines.append("结论: %s" % t["summary"][:300])
            return "\n".join(lines)

        def close_tool(args, tctx):
            tid = args.get("ticket") or tctx.session.get("ticket")
            if not tid:
                return "缺少 ticket 参数"
            self.close(tid, args.get("summary") or "", force=bool(args.get("force")), block=False)
            return "工单 %s 进入关闭流程：会通知各角色沉淀知识，然后销毁临时会话。结束前你可以用 ticket_status 复核。" % tid

        def role_spawn_tool(args, tctx):
            tid = args.get("ticket") or tctx.session.get("ticket")
            if not tid:
                return "缺少 ticket 上下文"
            t = self._get(tid)
            entry = self.spawn_role(t, args.get("role") or "developer", args.get("task") or "",
                                    args.get("title") or "")
            return "已拉起角色 %s（会话 %s），任务已投递：%s" % (entry["role"], entry["session"], entry["task"][:80])

        def role_task_tool(args, tctx):
            sid = args.get("session")
            if not sid:
                return "缺少 session"
            res = self.ctx.api("sessions.send", session=sid, text=args.get("text") or "")
            if args.get("wait"):
                w = self.ctx.api("sessions.wait", session=sid, timeout=int(args.get("timeout") or 300))
                return "角色 %s 回复：\n%s" % (sid, (w.get("reply") or w.get("status"))[:2000])
            return "已投递（injected=%s）" % res.get("injected")

        def role_wait_tool(args, tctx):
            tid = args.get("ticket") or tctx.session.get("ticket")
            results = self.wait_roles(tid, timeout=int(args.get("timeout") or 600))
            return "\n".join("%s -> %s (%s字)" % (k, v.get("status"), len(v.get("reply") or "")) for k, v in results.items()) or "没有角色"

        def role_report_tool(args, tctx):
            tid = args.get("ticket") or tctx.session.get("ticket")
            rows = self.role_status(tid)
            if not rows:
                return "还没有角色"
            out = []
            for r in rows:
                out.append("### %s %s [%s]\n%s" % (r["role"], r["session"], r["state"], r["reply"] or "(无回复)"))
            return "\n".join(out)

        tools.register(Tool(
            "ticket_create", "把一件事开成工单：自动拉起临时 PM 去编排。"
            "任何需要动手/查证/出结论的需求都直接调用它，不要先问用户“要不要开工单”。",
            {"type": "object", "properties": {
                "title": {"type": "string"},
                "goal": {"type": "string", "description": "目标、验收标准、边界"},
                "project": {"type": "string"},
            }, "required": ["goal"]},
            create_tool, origin=self.name))

        tools.register(Tool(
            "ticket_list", "列出所有工单及状态。",
            {"type": "object", "properties": {}},
            list_tool, origin=self.name))

        tools.register(Tool(
            "ticket_status", "查看某个工单的 PM/角色/进度。",
            {"type": "object", "properties": {"ticket": {"type": "string"}}},
            status_tool, origin=self.name))

        tools.register(Tool(
            "ticket_close", "结单：通知角色沉淀知识、销毁临时会话、写工单总结。",
            {"type": "object", "properties": {
                "ticket": {"type": "string"},
                "summary": {"type": "string", "description": "工单结论/验收结果"},
                "force": {"type": "boolean"},
            }},
            close_tool, origin=self.name))

        tools.register(Tool(
            "role_spawn", "为当前工单拉起一个角色会话并投递任务。",
            {"type": "object", "properties": {
                "role": {"type": "string"},
                "task": {"type": "string", "description": "任务：目标、产出路径、验收标准"},
                "title": {"type": "string"},
                "ticket": {"type": "string"},
            }, "required": ["role", "task"]},
            role_spawn_tool, origin=self.name))

        tools.register(Tool(
            "role_task", "给已有角色追加任务（可选等待回复）。",
            {"type": "object", "properties": {
                "session": {"type": "string"},
                "text": {"type": "string"},
                "wait": {"type": "boolean"},
                "timeout": {"type": "integer"},
            }, "required": ["session", "text"]},
            role_task_tool, origin=self.name))

        tools.register(Tool(
            "role_wait", "等待本工单的角色都跑完。",
            {"type": "object", "properties": {"ticket": {"type": "string"}, "timeout": {"type": "integer"}}},
            role_wait_tool, origin=self.name))

        tools.register(Tool(
            "role_report", "收取本工单所有角色的结果。",
            {"type": "object", "properties": {"ticket": {"type": "string"}}},
            role_report_tool, origin=self.name))
