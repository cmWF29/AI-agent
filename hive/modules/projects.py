"""项目模块 —— 多项目并行。

层级：项目(project) 内包含若干工单(ticket)，工单内包含若干角色(role)。
知识三层的 project 层就是以项目名为键，所以项目在这里是**一等公民**：
  * 建项目、列项目、看项目（含工单统计）；
  * 工单创建前会 ensure 项目存在，避免出现“孤儿工单”。

对外只暴露 API：projects.list / create / get / ensure / archive。
别的模块（tickets / knowledge）一律通过 ctx.api 调它，不 import 本文件。
"""
from __future__ import annotations

import os
import re
import shutil
import time

from ..kernel.api import ApiError, Module
from ..kernel.config import path_of
from ..kernel.store import Collection, inside, valid_id
from ..kernel.tools import Tool

MAX_NAME = 48


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _dir_size(path):
    total = 0
    if not os.path.isdir(path):
        return 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total


def _file_count(path):
    n = 0
    if not os.path.isdir(path):
        return 0
    for _dirpath, _dirnames, filenames in os.walk(path):
        n += len(filenames)
    return n


def _rmtree(path):
    """Windows 上 .git 文件可能短暂被占用；重试，避免“忽略错误”留下半棵树。"""
    if not os.path.isdir(path):
        return True
    for i in range(5):
        try:
            shutil.rmtree(path)
            return not os.path.exists(path)
        except OSError:
            # 清掉只读位后重试；不要把错误吞掉
            for dirpath, dirnames, filenames in os.walk(path):
                for name in dirnames + filenames:
                    try:
                        os.chmod(os.path.join(dirpath, name), 0o700)
                    except OSError:
                        pass
            time.sleep(0.2 * (i + 1))
    return not os.path.exists(path)


def _slug(text, fallback="project"):
    """项目名规范化：允许中文，去掉空格和斜杠，长度受限。"""
    name = (text or "").strip()
    # 只保留字母/数字/下划线/中文/连字符；点号也去掉，避免 ".." 变成路径
    name = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name, flags=re.UNICODE)
    name = re.sub(r"-{2,}", "-", name).strip("-_")
    if not valid_id(name):
        name = fallback
    return name[:MAX_NAME]


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
        self.api.route("GET", "/api/projects/{project_id}/delete-preview", name="delete_preview")(self.delete_preview_api)
        self.api.route("POST", "/api/projects/ensure", name="ensure")(self.ensure_api)
        self.api.route("POST", "/api/projects/{project_id}/rename", name="rename")(self.rename_api)
        self.api.route("GET", "/api/projects/{project_id}/files", name="files")(self.files_api)
        self.api.route("GET", "/api/projects/{project_id}/file", name="file")(self.file_api)
        self.api.route("POST", "/api/projects/{project_id}/backend", name="backend")(self.backend_api)
        self.api.route("POST", "/api/projects/{project_id}/source", name="source_bind")(self.source_bind_api)
        self.api.route("GET", "/api/projects/{project_id}/source/files", name="source_files")(self.source_files_api)
        self.api.route("GET", "/api/projects/{project_id}/source/file", name="source_file")(self.source_file_api)

        self._register_tools()
        self.ensure(self.default, title="默认项目", silent=True)

    # ---------------- 存储 ----------------
    def ensure(self, name, title="", description="", silent=False, backend="", source_path=""):
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
            "backend": backend or "",
            "source_path": source_path or "",
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
            "backend": rec.get("backend") or "",
            "source_path": rec.get("source_path") or "",
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
        rec = self.ensure(name, title=payload.get("title") or "", description=payload.get("description") or "",
                          backend=payload.get("backend") or "", source_path=payload.get("source_path") or "")
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

    def backend_api(self, payload):
        rec = self._get(payload["project_id"])
        backend = (payload.get("backend") or "").strip()
        if backend not in ("", "api", "claude-code"):
            raise ApiError("未知 backend: %s" % backend, status=400, code="bad_backend")
        rec["backend"] = backend
        rec["updated"] = _now()
        self.store.put(rec["id"], rec)
        self.emit("project.backend", {"project": rec["id"], "backend": backend})
        return {"project": self._public(rec)}

    def source_bind_api(self, payload):
        import os
        rec = self._get(payload["project_id"])
        raw = (payload.get("path") or "").strip()
        if not raw:
            rec["source_path"] = ""
            rec["updated"] = _now()
            self.store.put(rec["id"], rec)
            return {"project": self._public(rec), "bound": False}
        path = os.path.realpath(raw)
        if not os.path.isdir(path):
            raise ApiError("目录不存在: %s" % raw, status=404, code="no_source")
        rec["source_path"] = path
        rec["updated"] = _now()
        self.store.put(rec["id"], rec)
        self.emit("project.source", {"project": rec["id"], "path": path})
        return {"project": self._public(rec), "bound": True}

    def _source_tree(self, project_id):
        return self._get(project_id).get("source_path") or ""

    def source_files_api(self, payload):
        import os
        base = self._source_tree(payload["project_id"])
        if not base:
            raise ApiError("项目还没有绑定源码目录", status=404, code="no_source")
        rel = (payload.get("path") or "").strip("/")
        target = os.path.realpath(os.path.join(base, rel))
        if not inside(base, target):
            raise ApiError("路径越界", status=400, code="bad_path")
        if not os.path.isdir(target):
            return {"root": base, "path": rel, "items": []}
        items = []
        for name in sorted(os.listdir(target)):
            if name in (".git", "__pycache__"):
                continue
            full = os.path.join(target, name)
            items.append({"name": name, "path": os.path.relpath(full, base).replace(os.sep, "/"),
                          "type": "dir" if os.path.isdir(full) else "file",
                          "size": os.path.getsize(full) if os.path.isfile(full) else 0})
        return {"root": base, "path": rel, "items": items}

    def source_file_api(self, payload):
        import base64, os
        base = self._source_tree(payload["project_id"])
        if not base:
            raise ApiError("项目还没有绑定源码目录", status=404, code="no_source")
        rel = (payload.get("path") or "").strip("/")
        target = os.path.realpath(os.path.join(base, rel))
        if not inside(base, target) or not os.path.isfile(target):
            raise ApiError("文件不存在", status=404, code="no_file")
        size = os.path.getsize(target)
        if size > 512 * 1024:
            raise ApiError("文件过大（>512KB）", status=413, code="too_big")
        raw = open(target, "rb").read()
        try:
            text, enc = raw.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            text, enc = base64.b64encode(raw).decode("ascii"), "base64"
        return {"path": rel, "text": text, "encoding": enc, "bytes": size}

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
        if not inside(base, target):
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
        if not inside(base, target) or not os.path.isfile(target):
            raise ApiError("文件不存在", status=404, code="no_file")
        if os.path.getsize(target) > 512 * 1024:
            raise ApiError("文件过大（>512KB），请用 git 查看", status=413, code="too_big")
        try:
            text = open(target, encoding="utf-8").read()
            enc = "utf-8"
        except UnicodeDecodeError:
            text, enc = "", "binary"
        return {"path": rel, "text": text, "encoding": enc, "bytes": os.path.getsize(target)}

    def _tickets_of(self, pid):
        try:
            return self.ctx.api("tickets.list", project=pid).get("items", [])
        except ApiError:
            return []

    def delete_preview_api(self, payload):
        """删除前预览：有多少工单/未结单、哪些数据会被清掉。"""
        rec = self._get(payload["project_id"])
        pid = rec["id"]
        tickets = self._tickets_of(pid)
        open_tickets = [t["id"] for t in tickets if t.get("status") != "closed"]
        art = os.path.join(path_of(self.cfg, "artifacts.root", "data/artifacts"), "projects", pid)
        know = os.path.join(path_of(self.cfg, "knowledge.root", "data/knowledge"), "projects", pid)
        main = os.path.join(self.root, pid)
        return {
            "project": self._public(rec),
            "tickets": len(tickets), "closed_tickets": len(tickets) - len(open_tickets),
            "open_tickets": open_tickets,
            "artifacts": {"path": art, "exists": os.path.isdir(art),
                          "bytes": _dir_size(art)},
            "knowledge": {"path": know, "exists": os.path.isdir(know),
                           "files": _file_count(know)},
            "main_tree": {"path": main, "exists": os.path.isdir(main)},
            "source_path": rec.get("source_path") or "",
        }

    def delete_api(self, payload):
        """项目生命周期：归档，或删除（删除可选级联清理）。

        * mode=archive：只打 archived 标记，不删除任何数据。
        * mode=delete：默认保持旧行为（只删项目记录 + 秘书会话，工单/交付件/知识/工作树保留）。
        * cascade 为对象：tickets / artifacts / knowledge / main_tree / source。
          - tickets=true 只删除已结单工单（调用 tickets.delete，按约定保留其交付件/知识）；
          - 未结单工单存在且 force!=true 时拒绝，避免删掉正在跑的工作。
          - source=true 只解绑源码路径，绝不删除外部源码目录。
        """
        if (payload.get("mode") or "delete") == "archive":
            return self.archive_api(payload)
        pid = _slug(payload["project_id"], self.default)
        rec = self.store.get(pid)
        if rec is None:
            raise ApiError("项目不存在: %s" % pid, status=404, code="no_project")
        cascade = payload.get("cascade") if isinstance(payload.get("cascade"), dict) else {}
        tickets = self._tickets_of(pid)
        open_tickets = [t["id"] for t in tickets if t.get("status") != "closed"]
        if open_tickets and not bool(payload.get("force")):
            raise ApiError("还有未结单工单，不能删除项目；先结单或显式 force",
                           status=409, code="open_tickets",
                           extra={"open_tickets": open_tickets})
        destroyed, deleted_tickets = [], []
        # 项目秘书由 sessions 订阅 project.delete.before 自行清理；
        # 这里只发同步事件，不同步调用 sessions.destroy，保持模块 API 单向依赖。
        self.bus.publish("project.delete.before", {"project": pid}, source=self.name, sync=True)
        destroyed.append("sec-" + pid)
        if cascade.get("tickets"):
            for t in tickets:
                if t.get("status") != "closed":
                    continue
                try:
                    self.ctx.api("tickets.delete", ticket_id=t["id"])
                    deleted_tickets.append(t["id"])
                except ApiError as exc:
                    self.log.warn("project.delete.ticket_failed", project=pid, ticket=t["id"], error=exc.message)
        if cascade.get("artifacts"):
            try:
                self.ctx.api("artifacts.remove_project", project=pid)
            except ApiError as exc:
                self.log.warn("project.delete.artifacts_failed", project=pid, error=exc.message)
        if cascade.get("knowledge"):
            try:
                self.ctx.api("knowledge.remove_project", project=pid)
            except ApiError as exc:
                self.log.warn("project.delete.knowledge_failed", project=pid, error=exc.message)
        if cascade.get("main_tree"):
            _rmtree(os.path.join(self.root, pid))
        if cascade.get("source"):
            rec["source_path"] = ""
        kept = {}
        if not cascade.get("tickets"):
            kept["tickets"] = "data/tickets/*"
        if not cascade.get("artifacts"):
            kept["artifacts"] = "data/artifacts/projects/%s" % pid
        if not cascade.get("knowledge"):
            kept["knowledge"] = "data/knowledge/projects/%s" % pid
        self.store.delete(pid)
        self.emit("project.deleted", {"project": pid, "destroyed": destroyed,
                                      "deleted_tickets": deleted_tickets, "cascade": cascade})
        self.log.info("project.deleted", project=pid, cascade=cascade)
        return {"deleted": pid, "destroyed_sessions": destroyed,
                "deleted_tickets": deleted_tickets, "kept": kept,
                "cascade": cascade}

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
