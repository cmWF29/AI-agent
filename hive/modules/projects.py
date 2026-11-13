"""项目模块 —— 多项目并行。

层级：项目(project) 内包含若干工单(ticket)，工单内包含若干角色(role)。
知识三层的 project 层就是以项目名为键，所以项目在这里是**一等公民**：
  * 建项目、列项目、看项目（含工单统计）；
  * 工单创建前会 ensure 项目存在，避免出现“孤儿工单”。

对外只暴露 API：projects.list / create / get / ensure / archive。
别的模块（tickets / knowledge）一律通过 ctx.api 调它，不 import 本文件。
"""
from __future__ import annotations

import re
import time

from ..kernel.api import ApiError, Module
from ..kernel.config import path_of
from ..kernel.store import Collection
from ..kernel.tools import Tool

MAX_NAME = 48


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _slug(text, fallback="project"):
    """项目名规范化：允许中文，去掉空格和斜杠，长度受限。"""
    name = re.sub(r"[\s/\\]+", "-", (text or "").strip())
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return (name or fallback)[:MAX_NAME]


class Projects(Module):
    name = "projects"

    def setup(self):
        self.root = path_of(self.cfg, "projects.root", "data/projects")
        self.store = Collection(self.root)
        cfg = self.cfg.get("projects") if isinstance(self.cfg.get("projects"), dict) else {}
        self.default = _slug(cfg.get("default") or "default")
        self.log.info("projects.ready", root=self.root, default=self.default)

        self.api.route("GET", "/api/projects/list", name="list")(self.list_api)
        self.api.route("POST", "/api/projects/create", name="create")(self.create_api)
        self.api.route("GET", "/api/projects/{project_id}", name="get")(self.get_api)
        self.api.route("POST", "/api/projects/{project_id}/archive", name="archive")(self.archive_api)
        self.api.route("POST", "/api/projects/{project_id}/delete", name="delete")(self.delete_api)
        self.api.route("POST", "/api/projects/ensure", name="ensure")(self.ensure_api)
        self.api.route("POST", "/api/projects/{project_id}/rename", name="rename")(self.rename_api)
        self.api.route("GET", "/api/projects/{project_id}/files", name="files")(self.files_api)
        self.api.route("GET", "/api/projects/{project_id}/file", name="file")(self.file_api)

        self._register_tools()
        self.ensure(self.default, title="默认项目", silent=True)

    # ---------------- 存储 ----------------
    def ensure(self, name, title="", description="", silent=False):
        pid = _slug(name, self.default)
        rec = self.store.get(pid)
        if rec:
            return rec
        rec = {
            "id": pid,
            "title": title or pid,
            "description": description,
            "created": _now(),
            "updated": _now(),
            "archived": False,
        }
        self.store.put(pid, rec)
        if not silent:
            self.emit("project.created", {"project": pid, "title": rec["title"]})
            self.log.info("project.created", project=pid)
        # 每个项目一份 git 仓库（工单各自从它拉分支，收口合回 main）
        try:
            self.ctx.api("gitflow.project_init", project=pid)
        except ApiError as exc:
            self.log.warn("project.git.init_failed", project=pid, error=exc.message)
        return rec

    def _get(self, project_id):
        pid = _slug(project_id, self.default)
        rec = self.store.get(pid)
        if rec is None:
            raise ApiError("项目不存在: %s" % project_id, status=404, code="no_project")
        return rec

    def _public(self, rec):
        return {
            "id": rec["id"], "title": rec.get("title"), "description": rec.get("description"),
            "created": rec.get("created"), "updated": rec.get("updated"),
            "archived": bool(rec.get("archived")),
        }

    # ---------------- API ----------------
    def list_api(self, payload):
        include_archived = bool(payload.get("include_archived"))
        items = [self._public(r) for r in self.store.list()]
        if not include_archived:
            items = [i for i in items if not i["archived"]]
        items.sort(key=lambda i: (i["archived"], i["created"]))
        return {"items": items, "total": len(items), "default": self.default}

    def create_api(self, payload):
        name = payload.get("name") or payload.get("title") or ""
        if not name.strip():
            raise ApiError("name 必填", code="missing_name")
        rec = self.ensure(name, title=payload.get("title") or "", description=payload.get("description") or "")
        return {"project": self._public(rec)}

    def get_api(self, payload):
        rec = self._get(payload["project_id"])
        out = self._public(rec)
        try:
            tickets = self.ctx.api("tickets.list", project=rec["id"]).get("items", [])
        except ApiError:
            tickets = []
        out["tickets"] = [{"id": t["id"], "title": t["title"], "status": t["status"],
                           "tags": t.get("tags") or []} for t in tickets]
        out["ticket_count"] = len(tickets)
        out["open_tickets"] = len([t for t in tickets if t["status"] not in ("closed",)])
        out["secretary"] = "sec-" + rec["id"]
        out["artifacts_root"] = "artifacts/projects/" + rec["id"]
        return {"project": out}

    def rename_api(self, payload):
        rec = self._get(payload["project_id"])
        title = (payload.get("title") or "").strip()
        if not title:
            raise ApiError("title 必填", code="missing_title")
        rec["title"] = title[:64]
        rec["updated"] = _now()
        self.store.put(rec["id"], rec)
        self.emit("project.renamed", {"project": rec["id"], "title": rec["title"]})
        return {"project": self._public(rec)}

    def _main_tree(self, project_id):
        import os
        rec = self._get(project_id)
        return os.path.realpath(os.path.join(self.root, rec["id"], "main"))

    def files_api(self, payload):
        import os
        base = self._main_tree(payload["project_id"])
        rel = (payload.get("path") or "").strip("/")
        target = os.path.realpath(os.path.join(base, rel))
        if not target.startswith(base):
            raise ApiError("路径越界", status=400, code="bad_path")
        if not os.path.isdir(target):
            return {"root": base, "path": rel, "items": [], "note": "项目还没有 main 工作树"}
        items = []
        for name in sorted(os.listdir(target)):
            if name in (".git",):
                continue
            full = os.path.join(target, name)
            items.append({"name": name, "path": os.path.relpath(full, base),
                          "type": "dir" if os.path.isdir(full) else "file",
                          "size": os.path.getsize(full) if os.path.isfile(full) else 0})
        return {"root": base, "path": rel, "items": items}

    def file_api(self, payload):
        import os
        base = self._main_tree(payload["project_id"])
        rel = (payload.get("path") or "").strip("/")
        target = os.path.realpath(os.path.join(base, rel))
        if not target.startswith(base) or not os.path.isfile(target):
            raise ApiError("文件不存在", status=404, code="no_file")
        if os.path.getsize(target) > 512 * 1024:
            raise ApiError("文件过大（>512KB），请用 git 查看", status=413, code="too_big")
        try:
            text = open(target, encoding="utf-8").read()
            enc = "utf-8"
        except UnicodeDecodeError:
            text, enc = "", "binary"
        return {"path": rel, "text": text, "encoding": enc, "bytes": os.path.getsize(target)}

    def delete_api(self, payload):
        """删除项目（需求 8）。

        后处理只做一件必要的事：清掉这个项目的秘书会话（否则它会一直挂着一个已不存在的项目）。
        知识/交付件/工单记录都保留（知识已经运行时沉淀，删掉反而丢证据）。
        """
        pid = _slug(payload["project_id"], self.default)
        rec = self.store.get(pid)
        if rec is None:
            raise ApiError("项目不存在: %s" % pid, status=404, code="no_project")
        destroyed = []
        try:
            self.ctx.api("sessions.destroy", session_id="sec-" + pid)
            destroyed.append("sec-" + pid)
        except ApiError:
            pass
        self.store.delete(pid)
        self.emit("project.deleted", {"project": pid, "destroyed": destroyed})
        self.log.info("project.deleted", project=pid)
        return {"deleted": pid, "destroyed_sessions": destroyed,
                "kept": {"tickets": "data/tickets/*", "artifacts": "data/artifacts/projects/%s" % pid,
                         "knowledge": "data/knowledge/projects/%s" % pid}}

    def archive_api(self, payload):
        rec = self._get(payload["project_id"])
        rec["archived"] = bool(payload.get("archived", True))
        rec["updated"] = _now()
        self.store.put(rec["id"], rec)
        self.emit("project.archived", {"project": rec["id"], "archived": rec["archived"]})
        return {"project": self._public(rec)}

    def ensure_api(self, payload):
        rec = self.ensure(payload.get("name") or payload.get("project") or self.default,
                          title=payload.get("title") or "")
        return {"project": self._public(rec)}

    # ---------------- 工具 ----------------
    def _register_tools(self):
        tools = self.ctx.tools

        def list_tool(args, tctx):
            items = self.store.list()
            if not items:
                return "暂无项目"
            return "\n".join("%s | %s | %s" % (i["id"], i.get("title") or "-", "归档" if i.get("archived") else "在用")
                             for i in items)

        def create_tool(args, tctx):
            name = args.get("name") or args.get("title") or ""
            if not name:
                return "缺少 name"
            rec = self.ensure(name, title=args.get("title") or "")
            return "项目 %s 已就绪（%s）" % (rec["id"], rec.get("title") or "-")

        def status_tool(args, tctx):
            pid = args.get("project") or tctx.session.get("project") or self.default
            rec = self._get(pid)
            try:
                tickets = self.ctx.api("tickets.list", project=rec["id"]).get("items", [])
            except ApiError:
                tickets = []
            lines = ["%s (%s) 工单 %d 个" % (rec["id"], rec.get("title"), len(tickets))]
            for t in tickets:
                lines.append("- %s [%s] %s" % (t["id"], t["status"], t["title"]))
            return "\n".join(lines)

        tools.register(Tool("project_list", "列出所有项目。",
                            {"type": "object", "properties": {}}, list_tool, origin=self.name))
        tools.register(Tool("project_create", "新建项目（项目内可以开多个工单）。",
                            {"type": "object", "properties": {
                                "name": {"type": "string"}, "title": {"type": "string"}},
                             "required": ["name"]}, create_tool, origin=self.name))
        tools.register(Tool("project_status", "查看某项目下的工单。",
                            {"type": "object", "properties": {"project": {"type": "string"}}},
                            status_tool, origin=self.name))
