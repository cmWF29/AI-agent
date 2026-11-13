"""工单模块 —— 秘书发作业，PM 编排（也能自己干小活），角色干活，PM 收官。

一个工单 = 一个临时 PM 会话 + 若干临时角色会话 + 一个 git 分支。
* 秘书只负责“发”：ticket_create。
* PM 负责“排”和“收”：role_spawn / role_task / role_wait，最后 ticket_close；
  简单活（看一眼、改一行、跑个命令）PM 自己用 shell/read/write 做（需求 3）。
* 角色完成后，按“流程插件”校验必交产物，缺件自动追补（需求 15）。
* 关闭工单：校验 → 归档交付件 → 合并 git 分支 → 通知角色沉淀知识 → 销毁临时会话（需求 10）。
* 结单后的工单群只读，想改就新开工单并引用旧工单号（需求 10、18）。

本模块不直接读别的模块的存储：一律走 sessions.* / projects.* / artifacts.* / library.* / gitflow.* 的 API。
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

ROLE_CN = {
    "pm": "项目经理", "architect": "架构师", "developer": "开发", "dev": "开发",
    "reviewer": "核验者", "tester": "测试", "qa": "测试", "ops": "运维",
    "writer": "撰写", "researcher": "调研", "designer": "设计", "process": "流程专家",
    "secretary": "秘书", "security": "安全", "dba": "数据库", "frontend": "前端",
    "backend": "后端", "docs": "文档",
}

ROLE_TOOLS = [
    "shell", "read_file", "write_file", "grep", "http_get",
    "knowledge_read", "knowledge_write", "knowledge_list", "knowledge_search",
    "memory_add", "memory_search", "session_result",
    "artifact_write", "artifact_list",
    "git_sync", "git_status",
    "library_get", "flow_check", "ticket_tag",
]

PM_TOOLS = [
    # 编排
    "agent_spawn", "agent_send", "agent_wait", "agent_list", "agent_status",
    "agent_interrupt", "agent_destroy", "agent_compact",
    "role_spawn", "role_task", "role_wait", "role_report",
    "ticket_list", "ticket_status", "ticket_close",
    # 自己动手（需求 3：PM 得先能“了解项目”，小活自己干）
    "shell", "read_file", "write_file", "grep",
    # 库与流程（需求 15/17）
    "library_list", "library_get", "flow_design", "flow_check",
    # 交付件与 git
    "artifact_write", "artifact_list", "artifact_stats",
    "git_status", "git_sync", "git_merge", "ticket_tag",
    "knowledge_read", "knowledge_write", "knowledge_list", "knowledge_search",
    "memory_add", "memory_search",
]

SUFFIX = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def role_display(role, index=0):
    base = ROLE_CN.get(role, role)
    if index <= 0:
        return base
    return base + SUFFIX[min(index - 1, len(SUFFIX) - 1)]


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
        self._resume_after_boot()

        self.api.route("POST", "/api/tickets/create", name="create")(self.create_api)
        self.api.route("GET", "/api/tickets/list", name="list")(self.list_api)
        self.api.route("GET", "/api/tickets/{ticket_id}", name="get")(self.get_api)
        self.api.route("GET", "/api/tickets/{ticket_id}/flow", name="flow")(self.flow_api)
        self.api.route("POST", "/api/tickets/{ticket_id}/close", name="close")(self.close_api)
        self.api.route("POST", "/api/tickets/{ticket_id}/note", name="note")(self.note_api)
        self.api.route("POST", "/api/tickets/{ticket_id}/roles", name="roles")(self.role_api)
        self.api.route("POST", "/api/tickets/{ticket_id}/message", name="message")(self.message_api)
        self.api.route("GET", "/api/tickets/{ticket_id}/files", name="files")(self.files_api)
        self.api.route("GET", "/api/tickets/{ticket_id}/file", name="file")(self.file_api)
        self.api.route("POST", "/api/tickets/{ticket_id}/sync", name="sync")(self.sync_api)
        self.api.route("POST", "/api/tickets/{ticket_id}/tags", name="tags")(self.tags_api)
        self.api.route("POST", "/api/tickets/{ticket_id}/delete", name="delete")(self.delete_api)
        self.api.route("POST", "/api/tickets/dispatch", name="dispatch")(self.dispatch_api)

        self._register_tools()
        self.bus.subscribe("session.result", self._on_session_result, name="tickets.result")

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

    def _stage(self, ticket, stage, detail=""):
        """生命周期节点：写给网页画流程图用（和群聊分开，需求 13）。"""
        entry = {"stage": stage, "ts": _now(), "detail": str(detail)[:300]}
        ticket.setdefault("stages", []).append(entry)
        self._history(ticket, stage, detail)
        return entry

    # ---------------- 创建 ----------------
    def create(self, title, goal, project=None, roles_hint=None, parent="", when="auto",
               force=False, tags=None):
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
            "repo": "",
            "parent": parent or "",
            "summary": "",
            "created": _now(),
            "updated": _now(),
            "history": [],
            "stages": [],
        }
        self._stage(ticket, "created", goal[:200])
        ticket["tags"] = list(tags or [])
        self._save(ticket)

        # 空闲/高峰：高峰时先排队，等便宜时段再真启动（用户可选“直接执行”覆盖）
        if not force and when not in ("now", "direct"):
            try:
                state = self.ctx.api("idle.judge")["idle"]
            except ApiError:
                state = {"peak": False}
            if state.get("peak"):
                ticket["status"] = "queued"
                ticket["queued"] = _now()
                self._stage(ticket, "queued", state.get("reason") or "高峰排队")
                self._save(ticket)
                try:
                    item = self.ctx.api("idle.enqueue", kind="ticket", payload={"ticket_id": tid},
                                       note=state.get("reason") or "")
                    ticket["queue_id"] = (item.get("item") or {}).get("id") or ""
                    self._save(ticket)
                except ApiError as exc:
                    self.log.warn("ticket.enqueue.failed", ticket=tid, error=exc.message)
                self.emit("ticket.queued", {"ticket": tid, "reason": state.get("reason")})
                self.log.info("ticket.queued", ticket=tid)
                return ticket

        return self._dispatch(ticket)

    def _dispatch(self, ticket):
        """真正启动一张工单：建分支 -> 拉 PM -> 投递作业。排队恢复也走这里。"""
        tid = ticket["id"]
        project = ticket["project"]
        self._stage(ticket, "starting", "开始执行")
        self._save(ticket)

        # 标签沉淀：角色/用户打过的标签进公共库+项目库（需求 4）
        try:
            for tag in ticket.get("tags") or []:
                self.ctx.api("library.tag_add", name=tag, project=project)
        except ApiError:
            pass
        # 工单级 git：一个工单一个分支一个工作树（需求 2）
        try:
            repo = self.ctx.api("gitflow.ticket_init", ticket=tid, project=project).get("repo") or {}
            if repo.get("tree"):
                ticket["repo"] = repo["tree"]
                # 工作目录就是工单分支的工作树：PM/角色写的 docs/ 直接进 git，
                # 结单归档时也是从这里复制 → 交付件天然带工单号与版本。
                ticket["workdir"] = repo["tree"]
                self._stage(ticket, "git_branch", "%s @ %s" % (repo.get("branch"), repo["tree"]))
                self._save(ticket)
        except ApiError as exc:
            self.log.warn("ticket.git.init_failed", ticket=tid, error=exc.message)

        self.emit("ticket.created", {"ticket": tid, "project": project, "title": ticket["title"],
                                     "parent": ticket["parent"]})
        self.log.info("ticket.created", ticket=tid, project=project, parent=ticket["parent"])

        pm_prompt = self._pm_prompt(ticket)
        pm = self.ctx.api(
            "sessions.spawn",
            kind="pm",
            workspace=ticket["workdir"],
            title="PM/" + ticket["title"][:30],
            display="项目经理",
            system_prompt=pm_prompt,
            project=project,
            ticket=tid,
            role="pm",
            tools=PM_TOOLS,
        )["session"]
        ticket["pm"] = pm["id"]
        ticket["status"] = "running"
        self._stage(ticket, "pm_spawned", pm["id"])
        self._save(ticket)

        self.ctx.api("sessions.send", session=pm["id"], text=self._pm_kickoff(ticket), max_steps=60)
        return ticket


    def _pm_prompt(self, ticket):
        parts = [self._compose([{"layer": "public"},
                                {"layer": "project", "project": ticket["project"]},
                                {"layer": "ticket", "ticket": ticket["id"]}])]
        parts.append(
            "\n\n## 你的身份：本工单的项目经理（PM）\n"
            "你负责把这个工单做完：拆解 -> 定角色 -> 分发 -> 收作业 -> 验收 -> 结单。\n"
            "\n### 权限（需求 3）\n"
            "你有 shell/read_file/write_file/grep，可以自己读代码、看目录、跑命令——**先了解项目再动手**。\n"
            "小活（看一眼现状、改一行配置、跑一条命令、写个短说明）你自己做，别为它拉角色；\n"
            "大活（写代码、长文档、独立核验、调研）才拉角色。不许编造结果，做了就贴命令/输出。\n"
            "\n### 派角色（需求 15）\n"
            "1. 先 library_list(kind=roles) 看公共角色库有什么；\n"
            "2. 需要的角色库里没有（比如架构师），先 flow_design(role, responsibility, must_outputs, ...) 把它固化成\n"
            "   角色卡+提示词+流程插件，再 role_spawn；\n"
            "3. 流程插件会在角色交作业后自动校验必交产物，缺件系统会替你催，你也可以 role_task 让它补。\n"
            "4. 一个角色一个会话，任务写清验收标准、产出路径、边界。\n"
            "\n### git（需求 2）\n"
            "工单有自己的分支工作树（见 kickoff 里的 repo 路径）。代码改动必须在工作树里做；\n"
            "收尾前 git_sync 提交并推送；合并冲突时先解决冲突、**重跑测试**，再 sync/merge。\n"
            "\n### 结单\n"
            "全部达标后调用 ticket_close(ticket, summary)；结单会自动归档交付件、合并分支、\n"
            "通知角色沉淀知识并销毁临时会话。卡住/需要用户拍板时，直接说清卡点。\n"
        )
        return "".join(parts)

    def _pm_kickoff(self, ticket):
        repo = ticket.get("repo") or "(未启用 git)"
        parent = ("\n前序工单：%s（这次是在它的基础上改）" % ticket["parent"]) if ticket.get("parent") else ""
        return (
            "工单 %s\n标题：%s\n目标：%s\n项目：%s\n工作目录：%s\n代码工作树：%s%s\n\n"
            "请开始：先给拆解与角色安排（简短），然后立即 role_spawn 分发；能自己干的小活直接干。"
            % (ticket["id"], ticket["title"], ticket["goal"], ticket["project"],
               ticket["workdir"], repo, parent)
        )

    def _role_prompt(self, ticket, role, task, display=""):
        repo = ticket.get("repo") or ""
        parts = [
            self._compose([
                {"layer": "public"},
                {"layer": "project", "project": ticket["project"]},
                {"layer": "ticket", "ticket": ticket["id"]},
            ]),
        ]
        try:
            card = self.ctx.api("library.get", kind="roles", id=role).get("item") or {}
        except ApiError:
            card = {}
        parts.append(
            "\n\n## 你的身份：工单 %s 中的 %s%s\n工单目标：%s\n你的作业：%s\n"
            % (ticket["id"], display or role, ("（%s）" % card.get("cn")) if card.get("cn") else "",
               ticket["goal"], task)
        )
        if card.get("prompt"):
            parts.append("\n### 角色卡（来自角色库）\n%s\n" % card["prompt"])
        if card.get("must_outputs"):
            parts.append("\n### 必交产物（流程插件会校验，缺了会被催）\n%s\n"
                         % "\n".join("- " + p for p in card["must_outputs"]))
        parts.append(
            "\n### 规则\n"
            "1. 交付文档/数据写到工作目录 %s；代码改动在 git 工作树 %s 里做（cd 过去改，改完 git_status 看一眼）。\n"
            "2. 结论必须可验证：给出命令/文件/证据，别只给形容。\n"
            "3. 完成后调用 session_result(summary) 上报，再用 knowledge_write 沉淀（ticket 层）。\n"
            "4. 遇到阻塞就明确写出来，不要编造完成。\n"
            % (ticket["workdir"], repo or "(未启用)")
        )
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
        same = len([r for r in ticket.get("roles") or [] if r.get("role") == role])
        display = role_display(role, same)
        # 角色共用工单工作目录：交付件直接落在 docs/ 下，归档后路径干净（带工单号前缀）
        ws = ensure_dir(ticket["workdir"])
        sess = self.ctx.api(
            "sessions.spawn",
            kind="role",
            title="%s/%s" % (display, ticket["id"]),
            display=display,
            system_prompt=self._role_prompt(ticket, role, task, display),
            project=ticket["project"],
            ticket=ticket["id"],
            role=role,
            tools=ROLE_TOOLS,
            workspace=ws,
            input_text=task,
        )["session"]
        entry = {"session": sess["id"], "role": role, "display": display, "task": task[:400],
                 "status": "running", "created": _now(), "workspace": ws, "flow_retry": 0}
        ticket["roles"].append(entry)
        ticket["status"] = "running"
        self._stage(ticket, "role_spawned", "%s %s" % (display, sess["id"]))
        self._save(ticket)
        self.emit("ticket.role.spawned", {"ticket": ticket["id"], "role": role,
                                          "display": display, "session": sess["id"]})
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
                "session": r["session"], "role": r["role"], "display": r.get("display") or role_display(r["role"]),
                "task": r["task"],
                "state": info.get("state") or ("destroyed" if r.get("status") == "destroyed" else "gone"),
                "status": info.get("status") or r.get("status") or "gone",
                "chars": info.get("chars", 0),
                "reply": (info.get("last_reply") or "")[:600],
                "flow_retry": r.get("flow_retry", 0),
            })
        return out

    def wait_roles(self, ticket_id, sessions=None, timeout=600):
        ticket = self._get(ticket_id)
        targets = [r["session"] for r in ticket.get("roles") or []]
        if sessions:
            targets = [s for s in targets if s in sessions]
        end = None if not timeout else time.time() + timeout
        results = {}
        for sid in targets:
            remain = 0 if end is None else max(1, int(end - time.time()))
            try:
                res = self.ctx.api("sessions.wait", session=sid, timeout=remain)
                results[sid] = res
            except ApiError as exc:
                results[sid] = {"status": "error", "error": exc.message}
            if end is not None and time.time() >= end:
                break
        return results

    # ---------------- 流程插件校验（需求 15） ----------------
    def _ticket_files(self, ticket, extra=None):
        paths = list(extra or [])
        base = ticket["workdir"]
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "repo")]
            for fn in filenames:
                paths.append(os.path.relpath(os.path.join(dirpath, fn), base).replace(os.sep, "/"))
        repo = ticket.get("repo")
        if repo and os.path.isdir(repo):
            for dirpath, dirnames, filenames in os.walk(repo):
                dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
                for fn in filenames:
                    paths.append(os.path.relpath(os.path.join(dirpath, fn), repo).replace(os.sep, "/"))
        return paths

    def _check_role_flow(self, ticket, role_entry):
        """返回 {'missing': [...], 'known': bool}"""
        try:
            res = self.ctx.api("library.check", flow=role_entry["role"],
                               files=self._ticket_files(ticket))
            return res
        except ApiError:
            return {"missing": [], "known": False}

    def _enforce_flows(self, ticket, only=None):
        """角色交作业后（或结单前）校验必交产物，缺了就让角色补（最多 max_retry 次）。"""
        fixed = []
        for r in ticket.get("roles") or []:
            if only and r["session"] != only:
                continue
            if r.get("status") == "destroyed":
                continue
            chk = self._check_role_flow(ticket, r)
            if not chk.get("known") or not chk.get("missing"):
                continue
            retry = int(r.get("flow_retry", 0))
            max_retry = int(chk.get("max_retry") or 2)
            if retry >= max_retry:
                self._history(ticket, "flow.check.gaveup",
                              "%s 缺 %s（已催 %d 次）" % (r.get("display"), chk["missing"], retry))
                continue
            r["flow_retry"] = retry + 1
            note = ("流程插件校验未通过：还缺 %d 项必交产物：%s。\n"
                    "请补齐后再调 session_result 上报（这是硬性检查，不是建议）。"
                    % (len(chk["missing"]), ", ".join(chk["missing"])))
            try:
                self.ctx.api("sessions.send", session=r["session"], text=note)
                fixed.append({"session": r["session"], "missing": chk["missing"]})
                self.emit("ticket.flow.missing", {"ticket": ticket["id"], "session": r["session"],
                                                  "missing": chk["missing"]})
            except ApiError:
                pass
        if fixed:
            self._save(ticket)
        return fixed

    def _on_session_result(self, ev):
        payload = ev.get("payload") or {}
        ticket_id = payload.get("ticket")
        if not ticket_id:
            return
        t = self.store.get(ticket_id)
        if not t:
            return

        def _run():
            try:
                self._enforce_flows(t, only=payload.get("session"))
            except Exception as exc:
                self.log.warn("ticket.flow.check.failed", ticket=ticket_id, error=repr(exc))
        threading.Thread(target=_run, name="flow-" + ticket_id[-6:], daemon=True).start()

    # ---------------- 关闭 ----------------
    def close(self, ticket_id, summary="", force=False, block=True):
        ticket = self._get(ticket_id)
        if ticket["status"] in ("closed", "closing"):
            return {"ticket": ticket, "already_closed": ticket["status"] == "closed"}
        ticket["status"] = "closing"
        ticket["summary"] = summary or ticket.get("summary") or ""
        self._stage(ticket, "closing", summary[:200])
        self._save(ticket)
        self.emit("ticket.closing", {"ticket": ticket_id, "roles": [r["session"] for r in ticket.get("roles") or []]})

        if block:
            self._do_close(ticket, summary, force)
        else:
            if ticket_id in self._closing:
                return {"ticket": ticket, "closing": True}
            self._closing.add(ticket_id)
            threading.Thread(target=self._do_close_bg, args=(ticket, summary, force),
                             name="close-" + ticket_id, daemon=True).start()
        return {"ticket": self._get(ticket_id), "closing": True}

    def _do_close_bg(self, ticket, summary, force):
        try:
            self._do_close(ticket, summary, force)
        finally:
            self._closing.discard(ticket["id"])

    def _do_close(self, ticket, summary, force):
        ticket_id = ticket["id"]
        project = ticket["project"]

        # 0) 流程插件兜底校验（还没补的，这里再催一次并等一会儿）
        if not force:
            self._enforce_flows(ticket)
            time.sleep(0.2)

        # 1) 工单分支：commit + rebase + push（需求 2）
        sync = {}
        if ticket.get("repo"):
            try:
                sync = self.ctx.api("gitflow.ticket_sync", ticket=ticket_id,
                                    message="ticket: %s" % (summary[:80] or "close"))["result"]
            except ApiError as exc:
                self.log.warn("ticket.close.git", ticket=ticket_id, error=exc.message)
            if sync.get("conflict"):
                ticket["status"] = "conflict"
                ticket["conflict_files"] = sync["conflict"]
                self._stage(ticket, "conflict", ",".join(sync["conflict"]))
                self._save(ticket)
                self.emit("ticket.conflict", {"ticket": ticket_id, "files": sync["conflict"]})
                if ticket.get("pm"):
                    try:
                        self.ctx.api("sessions.send", session=ticket["pm"], text=(
                            "（系统）工单 %s 推送时与 main 冲突：%s。\n"
                            "请：1) 在工作树里解决冲突；2) **重新审视改动并重跑测试**（结果要贴出来）；"
                            "3) 再 git_sync；4) 确认无误后重新 ticket_close。"
                            % (ticket_id, ", ".join(sync["conflict"]))))
                    except ApiError:
                        pass
                return ticket

        # 2) 合回 main（冲突同样回退到 conflict 状态）
        if ticket.get("repo") and sync.get("ok"):
            try:
                merge = self.ctx.api("gitflow.ticket_merge", ticket=ticket_id, project=project)["result"]
            except ApiError as exc:
                merge = {"ok": False, "error": exc.message}
            if merge.get("conflict") or not merge.get("ok"):
                ticket["status"] = "conflict"
                ticket["conflict_files"] = merge["conflict"]
                self._stage(ticket, "conflict", "merge: " + (",".join(merge.get("conflict") or [])
                                                              or merge.get("error") or "merge failed"))
                self._save(ticket)
                if ticket.get("pm"):
                    try:
                        self.ctx.api("sessions.send", session=ticket["pm"], text=(
                            "（系统）工单 %s 合并回 main 冲突/失败：%s。解决后重跑测试，再重新结单。"
                            % (ticket_id, ", ".join(merge.get("conflict") or []) or merge.get("error") or "merge failed")))
                    except ApiError:
                        pass
                return ticket
            self._stage(ticket, "merged", merge.get("head") or "")

        # 3) 三层交付件归档（需求 9）
        archive = {}
        try:
            archive = self.ctx.api("artifacts.archive", ticket=ticket_id, project=project,
                                   source=ticket["workdir"])["index"]
            files = archive.get("files") or []
            self._stage(ticket, "archived", "%d 个文件 / %s bytes" % (len(files), archive.get("bytes", 0)))
        except ApiError as exc:
            self.log.warn("ticket.close.archive", ticket=ticket_id, error=exc.message)

        # 4) 角色自己沉淀知识（然后销毁）
        archive_note = (
            "工单 %s 即将关闭。请立刻用 knowledge_write 把本次作业中值得沉淀的内容写入 ticket 层："
            "结论、关键文件路径、可复用步骤、踩过的坑。写完回一句 DONE 就结束，不要再做新工作。"
            % ticket_id
        )
        for r in list(ticket.get("roles") or []):
            sid = r["session"]
            try:
                self.ctx.api("sessions.send", session=sid, text=archive_note)
                self.ctx.api("sessions.wait", session=sid, timeout=5 if force else self.close_timeout)
            except ApiError as exc:
                self.log.warn("ticket.close.role", ticket=ticket_id, session=sid, error=exc.message)
                r["status"] = "gone"
            except Exception as exc:
                self.log.warn("ticket.close.role.unknown", ticket=ticket_id, session=sid, error=repr(exc))
        pm = ticket.get("pm")
        if pm:
            try:
                self.ctx.api("sessions.send", session=pm, text=archive_note)
                # PM 正在执行 ticket_close 这个工具本身，等它“回话”会自锁；
                # 给它一个很短的窗口把知识写完即可，然后直接销毁。
                self.ctx.api("sessions.wait", session=pm, timeout=5)
            except Exception as exc:
                self.log.warn("ticket.close.pm", ticket=ticket_id, error=repr(exc))

        # 4.5) 冻结聊天记录：会话马上要销毁，但群聊历史要能回看（需求 7 / 11）
        transcript = []
        for r in list(ticket.get("roles") or []):
            try:
                items = self.ctx.api("sessions.messages", session_id=r["session"], limit=80).get("items") or []
            except ApiError:
                items = []
            transcript.append({"session": r["session"], "display": r.get("display") or r.get("role"),
                               "kind": "role",
                               "items": [m for m in items if m.get("role") in ("user", "assistant")]})
        if pm:
            try:
                items = self.ctx.api("sessions.messages", session_id=pm, limit=80).get("items") or []
            except ApiError:
                items = []
            transcript.append({"session": pm, "display": "项目经理", "kind": "pm",
                               "items": [m for m in items if m.get("role") in ("user", "assistant")]})
        if transcript:
            ticket["transcript"] = transcript

        # 5) 销毁临时会话（需求 10：结单后 PM/角色不该还能聊）
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

        # 6) 工单级知识归档
        text = "# 工单 %s\n\n- 目标：%s\n- 项目：%s\n- 创建：%s\n- 关闭：%s%s\n\n## 结论\n%s\n\n## 角色与产出\n%s" % (
            ticket_id, ticket["goal"], project, ticket["created"], _now(),
            ("\n- 前序工单：%s" % ticket["parent"]) if ticket.get("parent") else "",
            summary or "(未填写)",
            "\n".join("- %s (%s): %s" % (r.get("display") or r["role"], r["session"], r["task"][:120])
                      for r in ticket.get("roles") or []),
        )
        try:
            self.ctx.api("knowledge.write", layer="ticket", ticket=ticket_id, name="00-summary",
                         content=text, project=project)
        except ApiError as exc:
            self.log.warn("ticket.close.knowledge", ticket=ticket_id, error=exc.message)

        ticket["status"] = "closed"
        ticket["closed"] = _now()
        ticket["summary"] = summary or ticket.get("summary") or ""
        ticket["archive"] = {"files": archive.get("bytes"), "root": "artifacts/projects/%s/tickets/%s" % (project, ticket_id)}
        ticket["readonly"] = True
        self._stage(ticket, "closed", "")
        self._save(ticket)
        self.emit("ticket.closed", {"ticket": ticket_id, "roles": len(ticket.get("roles") or [])})
        self.log.info("ticket.closed", ticket=ticket_id)
        return ticket

    def _resume_after_boot(self):
        """重启后把“跑到一半”的工单接回来：给它的 PM 发一条续跑指令（限 3 个，避免齐刷）。"""
        def _run():
            time.sleep(15)                     # 等 server / 各模块就绪
            resumed = 0
            try:
                rows = self.store.list()
            except Exception as exc:
                self.log.error("tickets.resume.scan_failed", error=repr(exc))
                return
            for t in rows:
                if resumed >= 8:
                    break
                if t.get("status") not in ("running", "closing", "conflict") or not t.get("pm"):
                    continue
                try:
                    st = self.ctx.api("sessions.get", session_id=t["pm"])["session"]
                except Exception:
                    continue
                if st.get("state") not in ("idle", "interrupted"):
                    continue           # 有别的活正在跑就别插队
                if t.get("status") == "closing":
                    # 结单中途被打断：退回 running，让 PM 重新收尾（不然永远卡在 closing）
                    t["status"] = "running"
                    self._save(t)
                try:
                    self.ctx.api("sessions.send", session=t["pm"], text=(
                        "（系统）服务重启，你这单被打断了。先用 role_list 看角色和产物是否齐全，"
                        "缺什么就重派，齐了就直接收尾（写总结并 ticket_close）。"
                    ))
                    resumed += 1
                    self.log.info("ticket.resumed", ticket=t["id"], pm=t["pm"])
                    self.emit("ticket.resumed", {"ticket": t["id"], "pm": t["pm"]})
                except Exception as exc:
                    self.log.error("ticket.resume.failed", ticket=t["id"], error=repr(exc))
        threading.Thread(target=_run, name="ticket-resume", daemon=True).start()

    # ---------------- API ----------------
    def create_api(self, payload):
        goal = (payload.get("goal") or "").strip()
        if not goal:
            raise ApiError("goal 必填", code="missing_goal")
        t = self.create(payload.get("title") or "", goal, payload.get("project"),
                        payload.get("roles_hint"), payload.get("parent") or "",
                        when=payload.get("when") or "auto", force=bool(payload.get("force")),
                        tags=payload.get("tags") or [])
        return {"ticket": self._public(t)}

    def dispatch_api(self, payload):
        t = self._get(payload["ticket_id"])
        if t.get("status") != "queued":
            return {"ticket": self._public(t), "note": "不是排队状态"}
        if t.get("queue_id"):
            try:
                self.ctx.api("idle.dequeue", queue_id=t["queue_id"])
            except ApiError:
                pass
        return {"ticket": self._public(self._dispatch(t))}

    def tags_api(self, payload):
        t = self._get(payload["ticket_id"])
        add = [x.strip() for x in (payload.get("add") or []) if x and x.strip()]
        remove = [x.strip() for x in (payload.get("remove") or []) if x and x.strip()]
        cur = list(t.get("tags") or [])
        for tag in add:
            tag = tag[:24]
            if tag not in cur:
                cur.append(tag)
        for tag in remove:
            cur = [x for x in cur if x != tag]
        t["tags"] = cur
        t["updated"] = _now()
        self._save(t)
        for tag in add:
            try:
                self.ctx.api("library.tag_add", name=tag, project=t["project"])
            except ApiError:
                pass
        self.emit("ticket.tags", {"ticket": t["id"], "tags": cur})
        return {"ticket": self._public(t)}

    def delete_api(self, payload):
        """删除已结单的工单（只删记录与工作树；知识/交付件保留，作为证据沉淀）。"""
        t = self._get(payload["ticket_id"])
        if t.get("status") != "closed":
            raise ApiError("只能删除已结单的工单", status=409, code="ticket_not_closed")
        import shutil
        try:
            self.ctx.api("sessions.destroy", session_id=t.get("pm") or "")
        except ApiError:
            pass
        tdir = os.path.join(self.root, t["id"])
        shutil.rmtree(tdir, ignore_errors=True)
        self.store.delete(t["id"])
        self.emit("ticket.deleted", {"ticket": t["id"], "project": t["project"]})
        self.log.info("ticket.deleted", ticket=t["id"])
        return {"deleted": t["id"], "kept": {"artifacts": "artifacts/projects/%s/tickets/%s" % (t["project"], t["id"]),
                                            "knowledge": "knowledge/tickets/%s" % t["id"]}}

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
        out["stages"] = t.get("stages", [])
        out["readonly"] = t.get("status") == "closed"
        return {"ticket": out}

    def flow_api(self, payload):
        """生命周期：需求 13 要“流程图”，这里给结构化节点，网页自己画。"""
        t = self._get(payload["ticket_id"])
        roles = self.role_status(t["id"])
        stages = t.get("stages") or []
        current = t["status"]
        nodes = []
        seen = {}
        for s in stages:
            seen[s["stage"]] = s
        order = [("created", "立项"), ("git_branch", "建分支"), ("pm_spawned", "派项目经理"),
                 ("role_spawned", "拉角色"), ("conflict", "冲突处理"), ("closing", "验收结单"),
                 ("archived", "归档交付件"), ("merged", "合并 main"), ("closed", "结单")]
        for key, label in order:
            nodes.append({"key": key, "label": label, "done": key in seen,
                          "ts": (seen.get(key) or {}).get("ts"),
                          "detail": (seen.get(key) or {}).get("detail")})
        branches = []
        for r in roles:
            branches.append({"id": r.get("session"), "label": r.get("display") or r.get("role") or "角色",
                             "state": r.get("state"), "task": r.get("task") or "",
                             "chars": r.get("chars") or 0, "started": r.get("started") or ""})
        # 并行编排：角色是同时被拉起的（需求 8），这里给前端画并行 lane 的结构
        exec_stage = {"key": "execute", "label": "并行执行", "branches": branches,
                      "parallel": len(branches) > 1}
        for n in nodes:
            if n["key"] == "role_spawned":
                n["parallel"] = branches
        return {"ticket": t["id"], "status": current, "nodes": nodes, "parallel_stage": exec_stage,
                "roles": roles, "stages": stages, "readonly": current == "closed"}

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

    def sync_api(self, payload):
        t = self._get(payload["ticket_id"])
        res = self.ctx.api("gitflow.ticket_sync", ticket=t["id"], message=payload.get("message") or "")
        if res.get("result", {}).get("ok"):
            self._stage(t, "synced", res["result"].get("head") or "")
            self._save(t)
        return res

    # ---------------- 群聊：对工单说话 ----------------
    def message_api(self, payload):
        """在工单“群聊”里发一句话：默认发给 PM，也可指定某个角色会话。

        结单后只读（需求 10）：不给聊，引导新开工单并引用旧单号。
        """
        t = self._get(payload["ticket_id"])
        text = (payload.get("text") or "").strip()
        if not text:
            raise ApiError("text 必填", code="missing_text")
        if t.get("status") == "closed":
            raise ApiError(
                "工单 %s 已结单，群聊只读。要改结果请新开工单并在目标里写“基于 %s”："
                "这样前后因果会沉淀到项目知识库。" % (t["id"], t["id"]),
                status=410, code="ticket_closed")
        target = payload.get("session") or t.get("pm")
        if not target:
            raise ApiError("该工单已经没有在跑的 PM（可能已结单），新需求请另开工单", code="no_pm")
        res = self.ctx.api("sessions.send", session=target, text=text)
        self._history(t, "user_message", text[:200])
        self.emit("ticket.message", {"ticket": t["id"], "session": target, "chars": len(text),
                                     "text": text[:500]})
        self._save(t)
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
        return {"ticket": t["id"], "root": base, "items": items, "total": total,
                "archive_root": "artifacts/projects/%s/tickets/%s" % (t["project"], t["id"])}

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
            "parent": t.get("parent") or "", "repo": t.get("repo") or "",
            "roles": [{"session": r["session"], "role": r["role"],
                       "display": r.get("display") or role_display(r["role"]),
                       "status": r.get("status"), "task": r["task"][:160]}
                      for r in t.get("roles") or []],
            "created": t["created"], "updated": t.get("updated"),
            "workdir": t.get("workdir"), "readonly": t.get("status") == "closed",
            "closed": t.get("closed") or "",
            "conflict_files": t.get("conflict_files") or [],
            "transcript": t.get("transcript") or [],
            "tags": t.get("tags") or [],
            "queued": t.get("queued") or "",
        }

    # ---------------- 工具 ----------------
    def _register_tools(self):
        tools = self.ctx.tools

        def tag_tool(args, tctx):
            tid = args.get("ticket") or tctx.session.get("ticket")
            if not tid:
                return "缺少 ticket 上下文"
            res = self.tags_api({"ticket_id": tid, "add": args.get("add") or [], "remove": args.get("remove") or []})
            return "标签已更新：%s" % ", ".join(res["ticket"].get("tags") or [])

        def create_tool(args, tctx):
            t = self.create(args.get("title") or "", args.get("goal") or "",
                            args.get("project") or tctx.session.get("project"),
                            parent=args.get("parent") or "",
                            when=args.get("when") or "auto", force=bool(args.get("force")),
                            tags=args.get("tags") or [])
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
                lines.append("- %s %s | %s | %s字" % (r["display"], r["session"], r["state"], r["chars"]))
            if t.get("summary"):
                lines.append("结论: %s" % t["summary"][:300])
            return "\n".join(lines)

        def close_tool(args, tctx):
            tid = args.get("ticket") or tctx.session.get("ticket")
            if not tid:
                return "缺少 ticket 参数"
            self.close(tid, args.get("summary") or "", force=bool(args.get("force")), block=False)
            return "工单 %s 进入关闭流程：校验必交产物 → 归档交付件 → 合并分支 → 通知角色沉淀并销毁会话。结束前你可以用 ticket_status 复核。" % tid

        def role_spawn_tool(args, tctx):
            tid = args.get("ticket") or tctx.session.get("ticket")
            if not tid:
                return "缺少 ticket 上下文"
            t = self._get(tid)
            entry = self.spawn_role(t, args.get("role") or "developer", args.get("task") or "",
                                    args.get("title") or "")
            return "已拉起角色 %s（会话 %s），任务已投递：%s" % (entry["display"], entry["session"], entry["task"][:80])

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
                out.append("### %s %s [%s]\n%s" % (r["display"], r["session"], r["state"], r["reply"] or "(无回复)"))
            return "\n".join(out)

        tools.register(Tool(
            "ticket_create", "把一件事开成工单：自动拉起临时 PM 去编排。"
            "任何需要动手/查证/出结论的需求都直接调用它，不要先问用户“要不要开工单”。"
            "改老工单的结果时，用 parent 传老工单号，把前因后果沉淀下来。",
            {"type": "object", "properties": {
                "title": {"type": "string"},
                "goal": {"type": "string", "description": "目标、验收标准、边界"},
                "project": {"type": "string"},
                "parent": {"type": "string", "description": "可选：前序工单号，如 T-20261113-57fd20"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "模块标签，如 frontend/backend/docs"},
                "when": {"type": "string", "description": "auto=按空闲时段排队；now=立即执行"},
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
            "ticket_tag", "给当前工单打/删模块标签（frontend/backend/comm/docs...）。标签会自动沉淀到公共库与项目库。",
            {"type": "object", "properties": {
                "ticket": {"type": "string"},
                "add": {"type": "array", "items": {"type": "string"}},
                "remove": {"type": "array", "items": {"type": "string"}},
            }},
            tag_tool, origin=self.name))

        tools.register(Tool(
            "ticket_close", "结单：校验必交产物→归档交付件→合并 git 分支→通知角色沉淀知识→销毁临时会话。",
            {"type": "object", "properties": {
                "ticket": {"type": "string"},
                "summary": {"type": "string", "description": "工单结论/验收结果"},
                "force": {"type": "boolean"},
            }},
            close_tool, origin=self.name))

        tools.register(Tool(
            "role_spawn", "为当前工单拉起一个角色会话并投递任务。角色名可自创（先在角色库查，没有就 flow_design）。",
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
