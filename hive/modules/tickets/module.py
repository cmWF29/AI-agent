"""工单模块 —— 秘书发作业，PM 只做结构/分单/验收，角色干活。

一个工单 = 一个临时 PM 会话 + 若干临时角色会话 + 一个 git 分支。
* 秘书只负责“发”：ticket_create；原始需求原样转，不拆不改。
* PM 负责“结构化 + 分单 + 验收”：先读知识库、写 docs/pm/plan.md，能用子工单就 ticket_split；
  角色/子工单完成后系统发**短通知**，PM 不 role_wait、不监工，最后 ticket_close。
* 角色完成后，按“流程插件”校验必交产物；交接细节写 docs/handoff/<role>.md，PM 按需读文档。
* 关闭工单：校验 → 归档交付件 → 合并 git 分支 → 通知角色沉淀知识 → 销毁临时会话。
* 结单后的工单群只读，想改就开工单并引用旧工单号。
* 自动回顾工单默认关闭（配置可开启）；停滞工单由 worker 定期扫描并拉运维审计单。

本模块不直接读别的模块的存储：一律走 sessions.* / projects.* / artifacts.* / library.* / gitflow.* 的 API。
"""
from __future__ import annotations

import os
import threading
import time
import uuid
import calendar

from ...kernel.api import ApiError, Module
from ...kernel.config import path_of
from ...kernel.store import Collection, ensure_dir
from ...kernel.tools import Tool

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
    "artifact_write", "artifact_read", "artifact_list",
    "git_sync", "git_status",
    "library_get", "library_update_prompt", "flow_check", "ticket_tag",
]

PM_TOOLS = [
    # 编排（不包含 role_wait / role_report：角色交作业由系统通知，禁止监工）
    "agent_spawn", "agent_send", "agent_list", "agent_status",
    "agent_interrupt", "agent_destroy", "agent_compact",
    "role_spawn", "role_task",
    "ticket_create", "ticket_split", "ticket_list", "ticket_status", "ticket_verify", "ticket_close",
    "ticket_read_doc",
    # 库与流程（需求 15/17）
    "library_list", "library_get", "flow_design", "flow_check",
    "skill_sources", "skill_install", "skill_decompose",
    # 交付件与 git（PM 只看文档，不读源码）
    "artifact_read", "artifact_write", "artifact_list", "artifact_stats",
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
        self.stall_cfg = self.cfg["tickets"].get("stall_check") if isinstance(
            self.cfg["tickets"].get("stall_check"), dict) else {}
        self.log.info("tickets.ready", root=self.root)
        self._resume_after_boot()
        self._start_stall_worker()

        self.api.route("POST", "/api/tickets/create", name="create")(self.create_api)
        self.api.route("GET", "/api/tickets/list", name="list")(self.list_api)
        # 静态路径必须注册在 /{ticket_id} 之前，否则 “stalled” 会被当工单号
        self.api.route("GET", "/api/tickets/stalled", name="stalled")(self.stalled_api)
        self.api.route("POST", "/api/tickets/stalled/scan", name="stalled_scan")(self.stalled_scan_api)
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
        self.api.route("POST", "/api/tickets/{ticket_id}/verify", name="verify")(self.verify_api)
        self.api.route("POST", "/api/tickets/{ticket_id}/delete", name="delete")(self.delete_api)
        self.api.route("POST", "/api/tickets/dispatch", name="dispatch")(self.dispatch_api)

        # 队列派发由 idle 发事件、tickets 执行并回 ack；tickets 不再被 idle 同步调用。
        self.event("event.idle.ticket_dispatch", self._on_idle_ticket_dispatch,
                   name="tickets.idle_dispatch")

        self._register_tools()
        self.event("event.session.result.tickets", self._on_session_result, name="tickets.result")
        self.event("event.gitflow.conflict", self._on_git_conflict, name="tickets.git-conflict")
        self.event("event.artifacts.written", self._on_artifact_written, name="tickets.artifact")

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

    def _link_child(self, parent_id, child_id):
        parent = self.store.get(parent_id)
        if not parent:
            return
        kids = parent.setdefault("children", [])
        if child_id not in kids:
            kids.append(child_id)
            parent["updated"] = _now()
            self.store.put(parent_id, parent)
            self.emit("ticket.child.linked", {"parent": parent_id, "child": child_id})

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
               force=False, tags=None, backend="", trace_enabled=False, kind="normal",
               auto_retrospective=None):
        project = project or self.default_project
        project_backend = ""
        try:
            prep = self.ctx.rule("ticket.bind_project", name=project)["project"]
            project = prep["id"]
            project_backend = prep.get("backend") or ""
        except ApiError:
            project = project
        tid = "T-%s-%s" % (time.strftime("%Y%m%d"), uuid.uuid4().hex[:6])
        workdir = ensure_dir(os.path.join(self.root, tid, "workspace"))
        if auto_retrospective is None:
            cfg = self.cfg.get("tickets") if isinstance(self.cfg.get("tickets"), dict) else {}
            auto_retrospective = bool(cfg.get("auto_retrospective", False))
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
            "children": [],
            "backend": backend or project_backend,
            "kind": kind or "normal",
            "trace_enabled": bool(trace_enabled),
            "auto_retrospective": bool(auto_retrospective) and kind != "retrospective",
            "summary": "",
            "created": _now(),
            "updated": _now(),
            "history": [],
            "stages": [],
        }
        self._stage(ticket, "created", goal[:200])
        ticket["tags"] = list(tags or [])
        self._save(ticket)
        if parent:
            self._link_child(parent, tid)

        # 空闲/高峰：高峰时先排队，等便宜时段再真启动（用户可选“直接执行”覆盖）
        if not force and when not in ("now", "direct"):
            try:
                state = self.ctx.rule("ticket.judge_capacity")["idle"]
            except ApiError:
                state = {"peak": False}
            if state.get("peak"):
                ticket["status"] = "queued"
                ticket["queued"] = _now()
                self._stage(ticket, "queued", state.get("reason") or "高峰排队")
                self._save(ticket)
                try:
                    item = self.ctx.rule("ticket.queue", kind="ticket",
                                       payload={"ticket_id": tid, "project": project},
                                       note=state.get("reason") or "", project=project)
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
                self.ctx.rule("ticket.apply_tag", name=tag, project=project)
        except ApiError:
            pass
        # 工单级 git：一个工单一个分支一个工作树（需求 2）
        try:
            repo = self.ctx.rule("ticket.open_workspace", ticket=tid, project=project).get("repo") or {}
            if repo.get("tree"):
                ticket["repo"] = repo["tree"]
                ticket["base"] = repo.get("base") or ""
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
        pm = self.ctx.rule(
            "ticket.spawn_session",
            kind="pm",
            workspace=ticket["workdir"],
            title="PM/" + ticket["title"][:30],
            display="项目经理",
            system_prompt=pm_prompt,
            project=project,
            ticket=tid,
            role="pm",
            tools=PM_TOOLS,
            # PM 必须能调 role_spawn/ticket_close，始终走内核 API；
            # ticket.backend 只决定“被派出去的角色”用 API 还是已有 Agent。
            backend="api",
        )["session"]
        ticket["pm"] = pm["id"]
        ticket["status"] = "running"
        self._stage(ticket, "pm_spawned", pm["id"])
        self._save(ticket)

        # PM 步数由配置决定：tickets.pm_max_steps，默认 0 = 不限。
        # 0 必须显式传下去（react 里 0 表示不限），不能写成 `or None`，
        # 否则会退化成 cfg.react.max_steps（默认 20），PM 干到一半被截断。
        pm_max_steps = self.cfg.get("tickets", {}).get("pm_max_steps", 0)
        try:
            pm_max_steps = int(pm_max_steps)
        except (TypeError, ValueError):
            pm_max_steps = 0
        self.ctx.rule("ticket.send_instruction", session=pm["id"], text=self._pm_kickoff(ticket),
                      max_steps=pm_max_steps)
        return ticket


    def _pm_prompt(self, ticket):
        parts = [self._compose([{"layer": "public"},
                                {"layer": "project", "project": ticket["project"]},
                                {"layer": "ticket", "ticket": ticket["id"]}])]
        parts.append(
            "\n\n## 你的身份：本工单的 PM / 架构负责人\n"
            "你只做结构层：读知识、拆需求、定模块/规则、写计划、分单/派角色、验收、结单。\n"
            "你不写业务代码、不跑命令、不读源码；没有 shell/read_file/write_file/grep。\n"
            "\n### 1) 先读知识\n"
            "先看上面的 public/project/ticket 知识，再 `knowledge_search` 查项目地图与历史经验；\n"
            "需要代码事实就派 researcher/ops/architect 去查，让他们带回证据和路径，不要贴回整段代码。\n"
            "\n### 2) 结构化计划\n"
            "`artifact_write(layer=\"ticket\", path=\"docs/pm/plan.md\")` 写：目标/验收标准、影响模块、"
            "新增或变更的运行规则、边界、子任务（输入/产出路径/验收/依赖）、风险与回滚。\n"
            "计划是后续角色和子工单的共同输入，不要只放在聊天里。\n"
            "\n### 3) 分单与编排\n"
            "- 大需求先开“总需求负责”父工单；能独立验收的子任务用 `ticket_split` 建子工单（parent 自动指向本单）。\n"
            "- 不需要拆单才 `role_spawn`；任务只给目标、知识/文档路径、产出路径、验收标准、边界。\n"
            "- 不要把长上下文、整段代码或别人的完整回复塞给角色；他们自己读文档、按需查代码。\n"
            "- 返工用 `role_task`，只发缺口和验收标准。\n"
            "\n### 4) 通知式收作业（禁止监工）\n"
            "- `role_spawn` / `ticket_split` 后结束本轮；不要 role_wait、不要反复 role_report、不要盯会话。\n"
            "- 角色/子工单完成后系统发短通知（摘要 + 交接文档路径 + 知识文档名）；按需 `ticket_read_doc` / "
            "`artifact_read` / `knowledge_read`，不要让角色全文回传。\n"
            "- 全部有结论后逐条验收；齐了 `ticket_close(summary=...)`，不齐就补缺口。\n"
            "\n### 5) 留痕\n"
            "重要取舍写 `knowledge_write(name=\"pm-decisions\")`；开工后用 ticket_tag 标模块。\n"
        )
        if ticket.get("kind") == "retrospective":
            parts.append(
                "\n\n## 这是一个“提示词自迭代”回顾工单（历史遗留）\n"
                "自动回顾流程默认已关闭；若手工创建此单，只做最小判断，不要为了迭代而迭代：\n"
                "1. 先读旧工单知识与交付件，判断是否有角色缺输入、流程校验缺项、提示词导致返工；\n"
                "2. 没有明确改进点就 `ticket_close(summary='NO_RETROSPECTIVE: 原因')`；\n"
                "3. 有改进点才拉 process 角色，用 library_update_prompt/flow_design 落地最小改动，"
                "并写 docs/retrospective.md 记录前后差异。\n"
            )
        elif ticket.get("kind") == "stall-audit":
            parts.append(
                "\n\n## 这是一个停滞工单健康检查单（只读）\n"
                "你的目标不是改原工单，而是只读诊断：看 PM/角色会话状态、工单 stages/history、"
                "最近日志和资源；判断是等待通知、角色卡死、git/流程门禁、还是资源问题。\n"
                "只拉 ops/reviewer 做只读检查；不要改原工单、不启动 claude-code；"
                "结论写 docs/health-report.md，给出恢复/重派/关闭三种建议之一，然后结单。\n"
            )
        elif ticket.get("parent"):
            parts.append("\n\n## 前序/父工单\n本工单基于 %s；先读它的知识与交付件，不要重复造轮子。\n"
                         % ticket["parent"])
        return "".join(parts)

    def _pm_kickoff(self, ticket):
        repo = ticket.get("repo") or "(未启用 git)"
        parent = ("\n父工单：%s（先读父单知识与交付件，再决定拆分）" % ticket["parent"]) if ticket.get("parent") else ""
        return (
            "工单 %s\n标题：%s\n目标：%s\n项目：%s\n工作目录：%s\n代码工作树：%s%s\n\n"
            "请按 PM 职责开始：先读知识库，不要读源码；把需求结构化写进 docs/pm/plan.md，"
            "再判断是 ticket_split 子工单还是 role_spawn 角色。派完后结束本轮，等系统通知，不要监工。"
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
            card = self.ctx.rule("ticket.load_card", kind="roles", id=role).get("item") or {}
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
            "1. **先读上面的知识库**；知识没覆盖的代码事实，再按任务边界读对应代码，不要一上来全库扫描。\n"
            "2. 交付文档/数据写到工作目录 %s；代码改动在 git 工作树 %s 里做。\n"
            "3. 完整过程写 `docs/handoff/%s.md`（做了什么、证据/命令、风险、下一步）；"
            "`session_result(summary)` 只写 5 行以内，不把全文/整段代码回传。\n"
            "4. 可复用结论 `knowledge_write` 到 ticket 层；交付件 `artifact_write` 落盘。"
            "知识是总结，交付件是文件，不要混。\n"
            "5. 遇到阻塞就明确写出来，不要编造完成。\n"
            % (ticket["workdir"], repo or "(未启用)", (display or role).replace("/", "-"))
        )
        return "".join(parts)

    def _compose(self, scopes):
        try:
            return self.ctx.rule("ticket.load_context", scopes=scopes).get("text") or ""
        except ApiError:
            return ""

    # ---------------- 角色 ----------------
    def spawn_role(self, ticket, role, task, title="", backend=""):
        ticket = self._get(ticket["id"]) if isinstance(ticket, dict) else self._get(ticket)
        if len(ticket.get("roles") or []) >= self.max_roles:
            raise ApiError("角色数已达上限 %d" % self.max_roles, code="too_many_roles")
        role = (role or "developer").strip()[:40]
        same = len([r for r in ticket.get("roles") or [] if r.get("role") == role])
        display = role_display(role, same)
        # 角色共用工单工作目录：交付件直接落在 docs/ 下，归档后路径干净（带工单号前缀）
        ws = ensure_dir(ticket["workdir"])
        if not backend:
            backend = ticket.get("backend") or ""
        if not backend:
            try:
                flow = self.ctx.rule("ticket.load_card", kind="flows", id=role).get("item") or {}
                backend = flow.get("backend") or ""
            except ApiError:
                backend = ""
        sess = self.ctx.rule(
            "ticket.spawn_session",
            kind="role",
            title="%s/%s" % (display, ticket["id"]),
            display=display,
            system_prompt=self._role_prompt(ticket, role, task, display),
            project=ticket["project"],
            ticket=ticket["id"],
            role=role,
            tools=ROLE_TOOLS,
            workspace=ws,
            backend=backend,
            input_text=task,
        )["session"]
        entry = {"session": sess["id"], "role": role, "display": display, "task": task[:400],
                 "status": "running", "created": _now(), "workspace": ws, "flow_retry": 0,
                 "backend": backend or "api"}
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
            for item in self.ctx.rule("ticket.list_sessions").get("items", []):
                live[item["id"]] = item
        except ApiError:
            pass
        out = []
        for r in ticket.get("roles") or []:
            info = live.get(r["session"]) or {}
            out.append({
                "session": r["session"], "role": r["role"], "display": r.get("display") or role_display(r["role"]),
                "backend": r.get("backend") or "api", "task": r["task"],
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
                res = self.ctx.rule("ticket.wait_session", session=sid, timeout=remain)
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
            res = self.ctx.rule("ticket.check_outputs", flow=role_entry["role"],
                               files=self._ticket_files(ticket), root=ticket["workdir"])
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
            note = ("（系统）流程插件校验未通过：还缺 %d 项必交产物：%s。\n"
                    "请补齐后再调 session_result 上报（这是硬性检查，不是建议）。"
                    % (len(chk["missing"]), ", ".join(chk["missing"])))
            try:
                self.ctx.rule("ticket.send_instruction", session=r["session"], text=note)
                fixed.append({"session": r["session"], "missing": chk["missing"]})
                self.emit("ticket.flow.missing", {"ticket": ticket["id"], "session": r["session"],
                                                  "missing": chk["missing"]})
            except ApiError:
                pass
        if fixed:
            self._save(ticket)
        return fixed

    def _on_artifact_written(self, ev):
        payload = ev.get("payload") or {}
        tid = payload.get("ticket")
        if not tid:
            return
        t = self.store.get(tid)
        if not t:
            return
        ref = {"session": payload.get("session") or "", "path": payload.get("path") or "",
               "layer": payload.get("layer") or "ticket", "ts": payload.get("ts") or time.time()}
        if ref["path"]:
            t.setdefault("artifact_refs", []).append(ref)
            t["artifact_refs"] = t["artifact_refs"][-80:]
            self._save(t)

    def _on_git_conflict(self, ev):
        """PM 过程中自己 sync 冲突，也要登记复验；不能只有结单 merge 冲突才算。"""
        payload = ev.get("payload") or {}
        tid = payload.get("ticket")
        if not tid:
            return
        t = self.store.get(tid)
        if not t or t.get("status") in ("closed", "closing"):
            return
        files = payload.get("files") or []
        self._require_reverify(t, "git sync 冲突：" + ", ".join(files) if files else "git sync 冲突")

    def _flow_missing(self, ticket):
        out = []
        for r in ticket.get("roles") or []:
            chk = self._check_role_flow(ticket, r)
            if chk.get("known") and chk.get("missing"):
                out.append({"session": r.get("session"), "display": r.get("display") or r.get("role"),
                            "missing": chk["missing"]})
        return out

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
                fixed = self._enforce_flows(t, only=payload.get("session"))
                # 流程已通过才通知 PM；缺件时由流程插件继续催补，避免 PM 收到半成品
                role_missing = []
                for r in t.get("roles") or []:
                    if r.get("session") != payload.get("session"):
                        continue
                    chk = self._check_role_flow(t, r)
                    if chk.get("known") and chk.get("missing"):
                        role_missing = chk["missing"]
                if not fixed and not role_missing:
                    self._notify_role_result(t, payload)
            except Exception as exc:
                self.log.warn("ticket.flow.check.failed", ticket=ticket_id, error=repr(exc))
        threading.Thread(target=_run, name="flow-" + ticket_id[-6:], daemon=True).start()

    def _notify_role_result(self, ticket, payload):
        """把角色结果压缩成一条短通知，不把全文/上下文塞进 PM。"""
        if ticket.get("status") in ("closed", "closing") or not ticket.get("pm"):
            return
        sid = payload.get("session") or ""
        entry = None
        for r in ticket.get("roles") or []:
            if r.get("session") == sid:
                entry = r
                break
        if not entry:
            return
        summary = (payload.get("summary") or "").strip()
        if not summary or entry.get("result_summary") == summary:
            return
        entry["result_summary"] = summary[:500]
        entry["result_at"] = _now()
        entry["status"] = "done"
        # 交接文档按角色显示名定路径；角色卡要求写 docs/handoff/<display>.md
        display = (entry.get("display") or entry.get("role") or "role").replace("/", "-")
        handoff = "docs/handoff/%s.md" % display
        if not os.path.isfile(os.path.join(ticket.get("workdir") or "", handoff)):
            handoff = "docs/handoff/（角色未按约定落盘，请读交付件）"
        note = (
            "（系统通知）角色 %s 已交作业。\n"
            "摘要：%s\n"
            "交接文档：%s\n"
            "知识：knowledge/tickets/%s\n"
            "请按需读文档/知识，不要要求角色把全文或整段代码回传；需要返工只发缺口和验收标准。"
            % (entry.get("display") or entry.get("role"), summary[:500], handoff, ticket["id"])
        )
        try:
            self.ctx.rule("ticket.send_instruction", session=ticket["pm"], text=note, max_steps=0)
            entry["result_notified"] = True
            self._history(ticket, "role.result.notified", "%s %s" % (entry.get("display"), sid))
            self._save(ticket)
            self.emit("ticket.role.result", {"ticket": ticket["id"], "session": sid,
                                             "display": entry.get("display"), "summary": summary[:300],
                                             "handoff": handoff})
        except ApiError as exc:
            self.log.warn("ticket.role.notify.failed", ticket=ticket["id"], error=exc.message)

    def _require_reverify(self, ticket, reason):
        ticket["reverify"] = {"required": True, "passed": False, "since": _now(),
                              "reason": str(reason)[:300]}
        self._stage(ticket, "verification_required", reason)
        self._save(ticket)

    # ---------------- 关闭 ----------------
    def close(self, ticket_id, summary="", force=False, block=True):
        ticket = self._get(ticket_id)
        if ticket["status"] in ("closed", "closing"):
            return {"ticket": ticket, "already_closed": ticket["status"] == "closed"}
        rv = ticket.get("reverify") or {}
        if rv.get("required") and not rv.get("passed") and not force:
            raise ApiError(
                "工单 %s 发生过 git 冲突，必须先重新审视改动、重跑测试并调用 ticket_verify 记录证据，再结单。"
                % ticket_id, status=409, code="reverify_required")
        if not force:
            # 结单门禁：架构静态扫描必须通过（模块唯一出口/DAG/网页状态机/流程 DAG）
            from ...archscan import gate as arch_gate
            ok, errs, _warns = arch_gate()
            if not ok:
                self.emit("ticket.arch.blocked", {"ticket": ticket_id, "errors": errs[:5]})
                raise ApiError(
                    "工单 %s 的架构静态门禁未通过，不能结单：%s"
                    % (ticket_id, "；".join(errs[:5]), ),
                    status=409, code="arch_gate_failed")
            # 结单前硬门禁：缺必交产物就不允许进入 closing（不是催一句就放过）
            self._enforce_flows(ticket)
            missing = self._flow_missing(ticket)
            if missing:
                self.emit("ticket.flow.blocked", {"ticket": ticket_id, "missing": missing})
                raise ApiError(
                    "工单 %s 还有角色缺必交产物，已发消息催补：%s。补齐后再结单。"
                    % (ticket_id, "；".join("%s 缺 %s" % (m["display"], ", ".join(m["missing"]))
                                            for m in missing)),
                    status=409, code="flow_incomplete")
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

        # 0) 流程插件兜底校验：再查一次；仍缺就退回 working，不销毁会话
        if not force:
            self._enforce_flows(ticket)
            missing = self._flow_missing(ticket)
            if missing:
                ticket["status"] = "working"
                stage = self._stage(ticket, "flow_incomplete",
                                    "；".join("%s 缺 %s" % (m["display"], ", ".join(m["missing"])) for m in missing))
                ticket["status"] = "working"
                self._save(ticket)
                self.emit("ticket.flow.blocked", {"ticket": ticket_id, "missing": missing})
                if ticket.get("pm"):
                    try:
                        self.ctx.rule("ticket.send_instruction", session=ticket["pm"], text=(
                            "（系统）结单被拦下：%s。请让对应角色补齐必交产物，再调用 ticket_close。"
                            % stage["detail"]))
                    except ApiError:
                        pass
                return ticket

        # 1) 工单分支：commit + rebase + push（需求 2）
        sync = {}
        if ticket.get("repo"):
            try:
                sync = self.ctx.rule("ticket.sync_workspace", ticket=ticket_id,
                                    message="ticket: %s" % (summary[:80] or "close"))["result"]
            except ApiError as exc:
                self.log.warn("ticket.close.git", ticket=ticket_id, error=exc.message)
            if sync.get("conflict"):
                ticket["status"] = "conflict"
                ticket["conflict_files"] = sync["conflict"]
                self._require_reverify(ticket, "push 冲突：" + ",".join(sync["conflict"]))
                self._stage(ticket, "conflict", ",".join(sync["conflict"]))
                self._save(ticket)
                self.emit("ticket.conflict", {"ticket": ticket_id, "files": sync["conflict"]})
                if ticket.get("pm"):
                    try:
                        self.ctx.rule("ticket.send_instruction", session=ticket["pm"], text=(
                            "（系统）工单 %s 推送时与 main 冲突：%s。\n"
                            "请：1) 在工作树里解决冲突；2) **重新审视改动并重跑测试**（结果要贴出来）；"
                            "3) 再 git_sync；4) 调用 ticket_verify(summary=..., commands=..., result=...) 记录验证；5) 再 ticket_close。"
                            % (ticket_id, ", ".join(sync["conflict"]))))
                    except ApiError:
                        pass
                return ticket
            if sync.get("enabled") is not False and not sync.get("ok"):
                # fetch / commit / push 失败不是冲突，也不能继续归档结单
                ticket["status"] = "conflict"
                err = sync.get("error") or "git sync 失败"
                self._stage(ticket, "conflict", "sync: " + err[:300])
                self._save(ticket)
                self.emit("ticket.conflict", {"ticket": ticket_id, "error": err})
                if ticket.get("pm"):
                    try:
                        self.ctx.rule("ticket.send_instruction", session=ticket["pm"], text=(
                            "（系统）工单 %s 同步失败：%s。请排查后重试 ticket_close。" % (ticket_id, err)))
                    except ApiError:
                        pass
                return ticket

        # 2) 合回 main（冲突同样回退到 conflict 状态）
        if ticket.get("repo") and sync.get("ok"):
            try:
                merge = self.ctx.rule("ticket.merge_workspace", ticket=ticket_id, project=project)["result"]
            except ApiError as exc:
                merge = {"ok": False, "error": exc.message}
            if merge.get("conflict") or not merge.get("ok"):
                ticket["status"] = "conflict"
                ticket["conflict_files"] = merge["conflict"]
                self._require_reverify(ticket, "merge 失败：" + (",".join(merge.get("conflict") or [])
                                                               or merge.get("error") or "merge failed"))
                self._stage(ticket, "conflict", "merge: " + (",".join(merge.get("conflict") or [])
                                                              or merge.get("error") or "merge failed"))
                self._save(ticket)
                if ticket.get("pm"):
                    try:
                        self.ctx.rule("ticket.send_instruction", session=ticket["pm"], text=(
                            "（系统）工单 %s 合并回 main 冲突/失败：%s。解决后重跑测试，再重新结单。"
                            % (ticket_id, ", ".join(merge.get("conflict") or []) or merge.get("error") or "merge failed")))
                    except ApiError:
                        pass
                return ticket
            self._stage(ticket, "merged", merge.get("head") or "")

        # 3) 三层交付件归档（需求 9）
        archive = {}
        try:
            changed = []
            try:
                changed = self.ctx.rule("ticket.list_changes", ticket=ticket_id,
                                       base=ticket.get("base") or "")["files"]
            except ApiError:
                changed = []
            archive = self.ctx.rule("ticket.archive_outputs", ticket=ticket_id, project=project,
                                   source=ticket["workdir"],
                                   paths=changed if (ticket.get("base") and changed) else None)["index"]
            files = archive.get("files") or []
            self._stage(ticket, "archived", "%d 个文件 / %s bytes" % (len(files), archive.get("bytes", 0)))
            # 把归档文件挂到 PM 的最后一条消息上，保证“消息级交付件”不是空壳。
            for f in files[:30]:
                rel = f.get("path") if isinstance(f, dict) else ""
                if not rel:
                    continue
                ticket.setdefault("artifact_refs", []).append({
                    "session": ticket.get("pm") or "", "path": rel,
                    "layer": "ticket", "ts": time.time()})
            ticket["artifact_refs"] = (ticket.get("artifact_refs") or [])[-80:]
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
                self.ctx.rule("ticket.send_instruction", session=sid, text=archive_note)
                self.ctx.rule("ticket.wait_session", session=sid, timeout=5 if force else self.close_timeout)
            except ApiError as exc:
                self.log.warn("ticket.close.role", ticket=ticket_id, session=sid, error=exc.message)
                r["status"] = "gone"
            except Exception as exc:
                self.log.warn("ticket.close.role.unknown", ticket=ticket_id, session=sid, error=repr(exc))
        pm = ticket.get("pm")
        if pm:
            try:
                self.ctx.rule("ticket.send_instruction", session=pm, text=archive_note)
                # PM 正在执行 ticket_close 这个工具本身，等它“回话”会自锁；
                # 给它一个很短的窗口把知识写完即可，然后直接销毁。
                self.ctx.rule("ticket.wait_session", session=pm, timeout=5)
            except Exception as exc:
                self.log.warn("ticket.close.pm", ticket=ticket_id, error=repr(exc))

        # 4.5) 冻结聊天记录：会话马上要销毁，但群聊历史要能回看（需求 7 / 11）
        transcript = []
        for r in list(ticket.get("roles") or []):
            try:
                items = self.ctx.rule("ticket.session_messages", session_id=r["session"], limit=80).get("items") or []
            except ApiError:
                items = []
            transcript.append({"session": r["session"], "display": r.get("display") or r.get("role"),
                               "kind": "role",
                               "items": [m for m in items if m.get("role") in ("user", "assistant")]})
        if pm:
            try:
                items = self.ctx.rule("ticket.session_messages", session_id=pm, limit=80).get("items") or []
            except ApiError:
                items = []
            transcript.append({"session": pm, "display": "项目经理", "kind": "pm",
                               "items": [m for m in items if m.get("role") in ("user", "assistant")]})
        if transcript:
            ticket["transcript"] = transcript

        # 5) 销毁临时会话（需求 10：结单后 PM/角色不该还能聊）
        for r in list(ticket.get("roles") or []):
            try:
                self.ctx.rule("ticket.release_session", session_id=r["session"])
            except ApiError:
                pass
            r["status"] = "destroyed"
        if pm:
            try:
                self.ctx.rule("ticket.release_session", session_id=pm)
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
            self.ctx.rule("ticket.write_learning", layer="ticket", ticket=ticket_id, name="00-summary",
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
        self._notify_parent(ticket)
        self._maybe_spawn_retrospective(ticket)

    def _notify_parent(self, ticket):
        """子工单结单后，通知父工单 PM 一条短结果；父 PM 不轮询子单。"""
        parent_id = ticket.get("parent")
        if not parent_id:
            return
        parent = self.store.get(parent_id)
        if not parent or parent.get("status") in ("closed", "closing") or not parent.get("pm"):
            return
        text = (
            "（系统通知）子工单 %s 已结单。\n标题：%s\n结论：%s\n"
            "交付件：artifacts/projects/%s/tickets/%s\n知识：knowledge/tickets/%s\n"
            "请判断本子任务是否满足父工单验收；父工单可继续分单/派角色，全部齐了再结单。"
            % (ticket["id"], ticket.get("title") or "", (ticket.get("summary") or "(无)")[:500],
               ticket.get("project") or "", ticket["id"], ticket["id"])
        )
        try:
            self.ctx.rule("ticket.send_instruction", session=parent["pm"], text=text, max_steps=0)
            self._history(parent, "child.closed", ticket["id"])
            parent.setdefault("child_results", []).append({
                "ticket": ticket["id"], "summary": (ticket.get("summary") or "")[:500],
                "at": _now()})
            self._save(parent)
            self.emit("ticket.child.closed", {"parent": parent_id, "child": ticket["id"]})
        except ApiError as exc:
            self.log.warn("ticket.parent.notify.failed", ticket=ticket["id"], parent=parent_id, error=exc.message)

    def _maybe_spawn_retrospective(self, ticket):
        """结单后由项目秘书拉起回顾工单；新 PM 自己判断要不要改提示词。"""
        if not ticket.get("auto_retrospective") or ticket.get("kind") == "retrospective":
            return
        cfg = self.cfg.get("tickets") if isinstance(self.cfg.get("tickets"), dict) else {}
        if not bool(cfg.get("auto_retrospective", False)):
            return
        old = ticket["id"]
        project = ticket["project"]
        goal = (
            "回顾工单 %s 的协作过程，判断是否需要迭代角色/流程提示词。\n"
            "旧工单目标：%s\n旧工单结论：%s\n"
            "旧交付件：artifacts/projects/%s/tickets/%s\n"
            "要求：先读旧工单知识（ticket 层）和交付件；没有明确改进点就写 NO_RETROSPECTIVE 结单；"
            "有改进点则拉起临时流程专家（role=process），用 library_update_prompt/flow_design 落地最小改动，"
            "并在 docs/retrospective.md 记录前因后果。"
            % (old, ticket.get("goal") or "", ticket.get("summary") or "(无)", project, old))
        def _run():
            time.sleep(1.0)
            try:
                t = self.create(
                    title="回顾迭代：" + (ticket.get("title") or old)[:40],
                    goal=goal, project=project, parent=old,
                    when="now", force=True, backend=ticket.get("backend") or "",
                    kind="retrospective", auto_retrospective=False)
                self.emit("ticket.retrospective.created", {"ticket": t["id"], "parent": old})
                self.log.info("ticket.retrospective.created", ticket=t["id"], parent=old)
            except Exception as exc:
                self.log.warn("ticket.retrospective.failed", parent=old, error=repr(exc))
        threading.Thread(target=_run, name="retro-" + old[-6:], daemon=True).start()
        return ticket

    # ---------------- 停滞工单健康检查 ----------------
    def _start_stall_worker(self):
        cfg = self.stall_cfg or {}
        if not bool(cfg.get("enabled", True)):
            self.log.info("tickets.stall.disabled")
            return
        interval = max(30, int(cfg.get("interval_sec", 300)))

        def _loop():
            time.sleep(min(20, interval))
            while True:
                try:
                    self.scan_stalled()
                except Exception as exc:
                    self.log.warn("tickets.stall.scan.failed", error=repr(exc))
                time.sleep(interval)

        threading.Thread(target=_loop, name="ticket-stall", daemon=True).start()
        self.log.info("tickets.stall.worker", interval=interval,
                      idle_minutes=cfg.get("idle_minutes", 45))

    @staticmethod
    def _ts_epoch(ts):
        if not ts:
            return 0
        try:
            return calendar.timegm(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError):
            return 0

    def _ticket_last_activity(self, t):
        ts = [self._ts_epoch(t.get("updated")), self._ts_epoch(t.get("created"))]
        for s in t.get("stages") or []:
            ts.append(self._ts_epoch(s.get("ts")))
        for r in t.get("roles") or []:
            ts.append(self._ts_epoch(r.get("result_at")))
        return max(ts) if ts else 0

    def _ticket_live_sessions(self, t):
        """返回 (pm_state, running_roles, pm_present)。只读会话状态，不改任何东西。"""
        pm_state, pm_present = "gone", False
        running = 0
        pm = t.get("pm")
        if pm:
            try:
                st = self.ctx.rule("ticket.session_status", session_id=pm).get("session") or {}
                pm_state = st.get("state") or "gone"
                pm_present = pm_state not in ("gone", "destroyed", "error")
            except ApiError:
                pm_state, pm_present = "gone", False
        for r in t.get("roles") or []:
            try:
                st = self.ctx.rule("ticket.session_status", session_id=r.get("session") or "").get("session") or {}
                if st.get("state") == "running":
                    running += 1
            except ApiError:
                pass
        return pm_state, running, pm_present

    def _open_audit(self, t):
        for cid in t.get("children") or []:
            c = self.store.get(cid)
            if c and c.get("kind") == "stall-audit" and c.get("status") != "closed":
                return cid
        return ""

    def scan_stalled(self, create_audit=None, limit=None):
        """扫描“有 PM 但长时间没动静”的工单；默认拉一张只读运维审计单。

        - PM 正在跑 -> 正常，不算停滞；
        - 有角色正在跑 -> 正常（可能任务长），不算停滞；
        - PM idle/destroyed 且最近活动超过 idle_minutes -> 停滞；
        - 同一工单已有未结的 stall-audit -> 不重复拉单。
        """
        cfg = self.stall_cfg or {}
        if create_audit is None:
            create_audit = bool(cfg.get("create_audit", True))
        idle_minutes = int(cfg.get("idle_minutes", 45))
        max_per_scan = int(limit or cfg.get("max_per_scan", 2))
        cutoff = time.time() - idle_minutes * 60
        found, created = [], []
        for t in self.store.list():
            if t.get("status") in ("closed", "queued"):
                continue
            if t.get("kind") in ("stall-audit", "retrospective"):
                continue
            if len(t.get("roles") or []) == 0 and t.get("status") == "planning" and not t.get("pm"):
                continue
            pm_state, running, pm_present = self._ticket_live_sessions(t)
            if pm_state == "running" or running:
                continue
            last = self._ticket_last_activity(t)
            if last and last >= cutoff:
                continue
            reason = "PM %s，%.0f 分钟无活动" % (pm_state, (time.time() - last) / 60 if last else -1)
            existing = self._open_audit(t)
            item = {"ticket": t["id"], "title": t.get("title") or "", "status": t.get("status"),
                    "project": t.get("project") or "", "pm": t.get("pm") or "",
                    "pm_state": pm_state, "last_activity": t.get("updated") or "",
                    "reason": reason, "audit": existing}
            found.append(item)
            if t.get("stall_audit"):
                item["audit"] = t["stall_audit"] if not existing else existing
                continue
            if existing:
                item["audit"] = existing
                continue
            if not create_audit or len(created) >= max_per_scan:
                continue
            goal = (
                "健康检查：工单 %s 已停滞。\n"
                "原工单：%s [%s]，项目 %s，PM %s（%s），最后活动 %s。\n"
                "已知：%s。\n"
                "你是只读审计单：只拉 ops/reviewer 检查 PM/角色会话、stages/history、日志、资源与 git 状态；"
                "不要修改原工单、不要启动 claude-code。判断卡点，写 docs/health-report.md，"
                "给出“恢复（发续跑指令）/重派角色/建议关闭”三种建议之一，然后结单。"
                % (t["id"], t.get("title") or "", t.get("status"), t.get("project") or "",
                   t.get("pm") or "-", pm_state, t.get("updated") or "", reason)
            )
            try:
                audit = self.create(
                    title="停滞审计：" + (t.get("title") or t["id"])[:40],
                    goal=goal, project=t.get("project"), parent=t["id"],
                    when="now", force=True, backend="api", kind="stall-audit",
                    auto_retrospective=False, roles_hint=["ops"])
                t = self.store.get(t["id"]) or t
                t["stall_audit"] = audit["id"]
                self._history(t, "stall.audit.created", audit["id"])
                self._save(t)
                item["audit"] = audit["id"]
                created.append(audit["id"])
                self.emit("ticket.stall.audit.created", {"ticket": t["id"], "audit": audit["id"]})
                self.log.info("ticket.stall.audit.created", ticket=t["id"], audit=audit["id"])
            except Exception as exc:
                self.log.warn("ticket.stall.audit.failed", ticket=t["id"], error=repr(exc))
        return {"items": found, "created": created, "checked_at": _now(),
                "idle_minutes": idle_minutes}

    def stalled_api(self, payload=None):
        return self.scan_stalled(create_audit=False)

    def stalled_scan_api(self, payload=None):
        return self.scan_stalled(create_audit=True)

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
                    st = self.ctx.rule("ticket.session_status", session_id=t["pm"])["session"]
                except Exception:
                    continue
                if st.get("state") not in ("idle", "interrupted"):
                    continue           # 有别的活正在跑就别插队
                if t.get("status") == "closing":
                    # 结单中途被打断：退回 running，让 PM 重新收尾（不然永远卡在 closing）
                    t["status"] = "running"
                    self._save(t)
                try:
                    self.ctx.rule("ticket.send_instruction", session=t["pm"], text=(
                        "（系统）服务重启，你这单被打断了。先用 ticket_status 看角色和产物是否齐全，"
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
        ar = payload.get("auto_retrospective", None)
        if isinstance(ar, str):
            ar = ar.lower() in ("1", "true", "yes", "on")
        t = self.create(payload.get("title") or "", goal, payload.get("project"),
                        payload.get("roles_hint"), payload.get("parent") or "",
                        when=payload.get("when") or "auto", force=bool(payload.get("force")),
                        tags=payload.get("tags") or [], backend=payload.get("backend") or "",
                        trace_enabled=bool(payload.get("trace") or payload.get("trace_enabled")),
                        kind=payload.get("kind") or "normal",
                        auto_retrospective=ar)
        return {"ticket": self._public(t)}

    def _on_idle_ticket_dispatch(self, ev):
        p = ev.get("payload") or {}
        qid, tid = p.get("queue_id"), p.get("ticket_id")
        ok, error = False, ""
        try:
            ticket = self._get(tid)
            if ticket.get("status") == "queued":
                self._dispatch(ticket)
            ok = True
        except Exception as exc:
            error = getattr(exc, "message", None) or repr(exc)
            self.log.warn("ticket.idle_dispatch.failed", ticket=tid, error=error)
        self.emit("idle.dispatch.ack", {"queue_id": qid, "ticket": tid, "ok": ok, "error": error})

    def dispatch_api(self, payload):
        t = self._get(payload["ticket_id"])
        if t.get("status") != "queued":
            return {"ticket": self._public(t), "note": "不是排队状态"}
        if t.get("queue_id"):
            try:
                self.ctx.rule("ticket.dequeue", queue_id=t["queue_id"])
            except ApiError:
                pass
        return {"ticket": self._public(self._dispatch(t))}

    def verify_api(self, payload):
        """冲突后的强制复验：记录“改了什么、跑了什么、结果如何”，通过后才允许结单。"""
        t = self._get(payload["ticket_id"])
        summary = (payload.get("summary") or "").strip()
        commands = (payload.get("commands") or "").strip()
        result = (payload.get("result") or "").strip()
        if not (summary and commands and result):
            raise ApiError("summary / commands / result 都必须填写", code="missing_verification")
        rv = dict(t.get("reverify") or {})
        rv.update({"required": True, "passed": True, "verified_at": _now(),
                   "summary": summary[:300], "commands": commands[:500], "result": result[:500]})
        t["reverify"] = rv
        self._stage(t, "verified", summary[:200])
        self._save(t)
        self.emit("ticket.verified", {"ticket": t["id"], "summary": summary[:200]})
        return {"ticket": self._public(t), "verification": {k: rv.get(k) for k in
                                                           ("summary", "commands", "result", "verified_at")}}

    def tags_api(self, payload):
        t = self._get(payload["ticket_id"])
        if t.get("status") in ("closed", "closing") and (payload.get("add") or payload.get("remove")):
            raise ApiError("工单已结单/正在结单，标签只读", status=410, code="ticket_closed")
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
                self.ctx.rule("ticket.apply_tag", name=tag, project=t["project"])
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
            self.ctx.rule("ticket.release_session", session_id=t.get("pm") or "")
        except ApiError:
            pass
        try:
            self.ctx.rule("ticket.remove_workspace", ticket=t["id"], project=t["project"])
        except ApiError as exc:
            self.log.warn("ticket.delete.git", ticket=t["id"], error=exc.message)
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
        out["readonly"] = t.get("status") in ("closed", "closing")
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
                 ("role_spawned", "拉角色"), ("conflict", "冲突处理"),
                 ("verification_required", "复验要求"), ("verified", "复验通过"),
                 ("closing", "验收结单"), ("merged", "合并 main"),
                 ("archived", "归档交付件"), ("closed", "结单")]
        optional = {"conflict", "verification_required", "verified"}
        for key, label in order:
            # 没发生过的冲突/复验节点不画在正常流程线上；发生过才显示
            if key in optional and key not in seen:
                continue
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
                "roles": roles, "stages": stages, "readonly": current in ("closed", "closing")}

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
                                payload.get("task") or t["goal"], payload.get("title") or "",
                                backend=payload.get("backend") or "")
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
        res = self.ctx.rule("ticket.sync_workspace", ticket=t["id"], message=payload.get("message") or "")
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
        if t.get("status") in ("closed", "closing"):
            raise ApiError(
                "工单 %s 已结单或正在结单，群聊只读。要改结果请新开工单并在目标里写“基于 %s”："
                "这样前后因果会沉淀到项目知识库。" % (t["id"], t["id"]),
                status=410, code="ticket_closed")
        target = payload.get("session") or t.get("pm")
        if not target:
            raise ApiError("该工单已经没有在跑的 PM（可能已结单），新需求请另开工单", code="no_pm")
        res = self.ctx.rule("ticket.send_instruction", session=target, text=text,
                            max_steps=0 if target == t.get("pm") else None)
        # 记录“这是用户本人在群里说的”，网页据此把发言人显示成“我”，而不是“秘书/PM”
        t.setdefault("user_messages", []).append({"ts": time.time(), "session": target, "text": text})
        t["user_messages"] = t["user_messages"][-30:]
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
            "children": t.get("children") or [],
            "stall_audit": t.get("stall_audit") or "",
            "backend": t.get("backend") or "api", "kind": t.get("kind") or "normal",
            "trace_enabled": bool(t.get("trace_enabled")),
            "auto_retrospective": bool(t.get("auto_retrospective")),
            "artifact_refs": t.get("artifact_refs") or [],
            "roles": [{"session": r["session"], "role": r["role"],
                       "display": r.get("display") or role_display(r["role"]),
                       "backend": r.get("backend") or "api",
                       "status": r.get("status"), "task": r["task"][:160]}
                      for r in t.get("roles") or []],
            "created": t["created"], "updated": t.get("updated"),
            "workdir": t.get("workdir"), "readonly": t.get("status") == "closed",
            "closed": t.get("closed") or "",
            "conflict_files": t.get("conflict_files") or [],
            "reverify": t.get("reverify") or {},
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
                            tags=args.get("tags") or [],
                            backend=args.get("backend") or "",
                            trace_enabled=bool(args.get("trace_enabled")),
                            kind=args.get("kind") or "normal",
                            auto_retrospective=args.get("auto_retrospective"))
            return "工单已创建：%s（PM 会话 %s 已开工）。后续你可以用 ticket_status 查看进度。" % (t["id"], t["pm"])

        def split_tool(args, tctx):
            tid = args.get("ticket") or tctx.session.get("ticket")
            if not tid:
                return "缺少 ticket 上下文"
            parent = self._get(tid)
            items = args.get("items") or []
            if not items:
                return "没有子任务；请传 items=[{title, goal, roles_hint, tags}]"
            made = []
            for item in items[:8]:
                goal = (item.get("goal") or "").strip()
                if not goal:
                    continue
                try:
                    child = self.create(
                        title=item.get("title") or ("子任务：" + goal[:36]),
                        goal=goal, project=item.get("project") or parent["project"],
                        roles_hint=item.get("roles_hint") or parent.get("roles_hint") or [],
                        parent=tid, when=item.get("when") or "now", force=True,
                        tags=item.get("tags") or parent.get("tags") or [],
                        backend=item.get("backend") or parent.get("backend") or "api",
                        trace_enabled=bool(item.get("trace_enabled", parent.get("trace_enabled"))),
                        kind="sub", auto_retrospective=False)
                    made.append(child["id"])
                except Exception as exc:
                    made.append("FAILED:" + getattr(exc, "message", repr(exc)))
            return "子工单已创建（父单 %s）：%s。子单结单会自动通知你，不要轮询。" % (
                tid, ", ".join(made) if made else "无")

        def read_doc_tool(args, tctx):
            tid = args.get("ticket") or tctx.session.get("ticket")
            if not tid:
                return "缺少 ticket 上下文"
            path = (args.get("path") or "").strip().lstrip("/")
            ext = os.path.splitext(path)[1].lower()
            if ext not in (".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".log"):
                return "PM 只读文档；源码/二进制请让角色用 read_file 并交文档摘要。"
            res = self.file_api({"ticket_id": tid, "path": path, "max_bytes": args.get("max_bytes") or 262144})
            if res.get("encoding") != "utf-8":
                return "（二进制/非 UTF-8 文档，%d bytes）" % (res.get("size") or 0)
            text = res.get("text") or ""
            return text[:8000] + ("\n...(已截断)" if len(text) > 8000 else "")

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
                                    args.get("title") or "",
                                    backend=args.get("backend") or "")
            return "已拉起角色 %s（会话 %s），任务已投递：%s" % (entry["display"], entry["session"], entry["task"][:80])

        def role_task_tool(args, tctx):
            sid = args.get("session")
            if not sid:
                return "缺少 session"
            res = self.ctx.rule("ticket.send_instruction", session=sid, text=args.get("text") or "")
            # 返工后允许新的结果通知；不要因为上一次已通知就不再叫 PM。
            tid = tctx.session.get("ticket")
            if tid:
                t = self.store.get(tid)
                if t:
                    for r in t.get("roles") or []:
                        if r.get("session") == sid:
                            r["result_notified"] = False
                            r["result_summary"] = ""
                            r["status"] = "running"
                            self._save(t)
                            break
            if args.get("wait"):
                w = self.ctx.rule("ticket.wait_session", session=sid, timeout=int(args.get("timeout") or 300))
                return "角色 %s 回复：\n%s" % (sid, (w.get("reply") or w.get("status"))[:2000])
            return "已投递（injected=%s）。返工结果会由系统短通知你，不要轮询。" % res.get("injected")

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
            "ticket_create", "开一张工单：自动拉起临时 PM 去编排。秘书把原始需求原样转进来；"
            "PM 也可以用它建子工单（parent 指向本单）。",
            {"type": "object", "properties": {
                "title": {"type": "string"},
                "goal": {"type": "string", "description": "目标、验收标准、边界"},
                "project": {"type": "string"},
                "parent": {"type": "string", "description": "可选：前序/父工单号"},
                "kind": {"type": "string", "enum": ["normal", "sub", "stall-audit", "retrospective"],
                         "description": "默认 normal；子单用 sub；健康审计用 stall-audit"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "模块标签，如 frontend/backend/docs"},
                "when": {"type": "string", "description": "auto=按空闲时段排队；now=立即执行"},
                "backend": {"type": "string", "enum": ["", "api", "claude-code"],
                            "description": "空=项目默认；claude-code=交给已有 Agent CLI"},
                "trace_enabled": {"type": "boolean", "description": "是否把模块报文并入群聊；默认关闭"},
                "auto_retrospective": {"type": "boolean", "description": "结单后是否自动起回顾工单；默认 false（迭代流程已拔掉）"},
            }, "required": ["goal"]},
            create_tool, origin=self.name))

        tools.register(Tool(
            "ticket_split", "PM 分单：把一个父需求拆成若干子工单（parent 自动指向当前工单）。"
            "子单独立跑、结单后自动短通知父 PM；不要用 role_wait 监工。",
            {"type": "object", "properties": {
                "ticket": {"type": "string", "description": "父工单号；默认当前工单"},
                "items": {"type": "array", "items": {"type": "object"}, "description":
                          "[{title, goal, roles_hint?, tags?, backend?}]，最多 8 个"},
            }, "required": ["items"]},
            split_tool, origin=self.name))

        tools.register(Tool(
            "ticket_read_doc", "PM 读工单工作树里的文档（只允许 .md/.txt/.json/.csv/.yaml/.log），"
            "用于看角色交接文档、计划、健康报告；不能读源码。",
            {"type": "object", "properties": {
                "ticket": {"type": "string"},
                "path": {"type": "string"},
                "max_bytes": {"type": "integer"},
            }, "required": ["path"]},
            read_doc_tool, origin=self.name))

        tools.register(Tool(
            "ticket_list", "列出所有工单及状态。",
            {"type": "object", "properties": {}},
            list_tool, origin=self.name))

        tools.register(Tool(
            "ticket_status", "查看某个工单的 PM/角色/进度。",
            {"type": "object", "properties": {"ticket": {"type": "string"}}},
            status_tool, origin=self.name))

        def verify_tool(args, tctx):
            try:
                tid = args.get("ticket") or tctx.session.get("ticket") or ""
                r = self.verify_api({"ticket_id": tid,
                                     "summary": args.get("summary") or "",
                                     "commands": args.get("commands") or "",
                                     "result": args.get("result") or ""})
                return "复验已登记：%s" % (r.get("verification") or {})
            except ApiError as exc:
                return "复验登记失败：%s" % exc.message

        tools.register(Tool(
            "ticket_verify", "冲突后强制复验：登记重新审视的结论、重跑的命令与结果；不登记不能结单。",
            {"type": "object", "properties": {
                "ticket": {"type": "string"},
                "summary": {"type": "string", "description": "改了什么、为什么这样解决冲突"},
                "commands": {"type": "string", "description": "实际重跑的命令"},
                "result": {"type": "string", "description": "真实输出/通过情况"},
            }, "required": ["summary", "commands", "result"]},
            verify_tool, origin=self.name))

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
                "backend": {"type": "string", "enum": ["api", "claude-code"],
                            "description": "可选：用哪个 agent 循环；不填走流程插件/全局默认"},
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
