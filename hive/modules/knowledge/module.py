"""知识沉淀模块 —— 三层，互不包含。

  public : 本机（机器）级知识，跨项目复用，例如秘书/PM 的角色守则
  project: 项目级知识，一个项目可含多个工单
  ticket : 工单级知识，只在这次工单的生命周期内有效

三层的目录彼此独立（分布式部署时各自可迁走），compose 只是“按需拼装”，
不是包含关系：调用方显式指定要读哪几层。
"""
from __future__ import annotations

import os
import shutil
import time

from ...kernel.api import ApiError, Module
from ...kernel.config import path_of
from ...kernel.store import ensure_dir, safe_id
from ...kernel.tools import Tool


class Knowledge(Module):
    name = "knowledge"

    def setup(self):
        self.root = path_of(self.cfg, "knowledge.root", "data/knowledge")
        self.layers = self.cfg["knowledge"].get("layers") or ["public", "project", "ticket"]
        self.max_inject = int(self.cfg["knowledge"].get("max_inject_chars", 20000))
        for layer in ("public", "projects", "tickets"):
            ensure_dir(os.path.join(self.root, layer))
        self._seed_defaults()
        self.log.info("knowledge.ready", root=self.root, layers=self.layers)

        self.api.route("GET", "/api/knowledge/overview")(self.overview)
        self.api.route("POST", "/api/knowledge/write")(self.write)
        self.api.route("GET", "/api/knowledge/read")(self.read)
        self.api.route("GET", "/api/knowledge/list", name="list")(self.list_docs)
        self.api.route("GET", "/api/knowledge/search")(self.search)
        self.api.route("POST", "/api/knowledge/compose")(self.compose)
        self.api.route("POST", "/api/knowledge/remove-project")(self.remove_project_api)

        self._register_tools()

    # ---------------- 目录解析 ----------------
    def remove_project_api(self, payload=None):
        """删除项目层知识；public 层永远不删。"""
        pid = (payload or {}).get("project") or ""
        if not pid:
            raise ApiError("project 必填", code="missing_scope")
        path = os.path.join(self.root, "projects", safe_id(pid))
        if not os.path.isdir(path):
            return {"removed": False, "project": pid, "path": path}
        import shutil
        shutil.rmtree(path)
        self.log.info("knowledge.project_removed", project=pid)
        return {"removed": True, "project": pid, "path": path}

    def layer_dir(self, layer, project=None, ticket=None):
        if layer == "public":
            return os.path.join(self.root, "public")
        if layer == "project":
            if not project:
                raise ApiError("project 层必须给 project 名", code="missing_scope")
            return os.path.join(self.root, "projects", safe_id(project))
        if layer == "ticket":
            if not ticket:
                raise ApiError("ticket 层必须给 ticket id", code="missing_scope")
            return os.path.join(self.root, "tickets", safe_id(ticket))
        raise ApiError("未知知识层: %s（可选 public/project/ticket）" % layer, code="bad_layer")

    def _doc_path(self, layer, name, project=None, ticket=None):
        if not name:
            raise ApiError("name 必填", code="missing_name")
        d = self.layer_dir(layer, project, ticket)
        ensure_dir(d)
        clean = safe_id(name).replace(".md", "")
        return os.path.join(d, clean + ".md")

    # ---------------- 默认知识 ----------------
    def _seed_defaults(self):
        """首次启动把仓库内 prompts/ 里的公共知识灌进 public 层（只灌一次）。"""
        target = os.path.join(self.root, "public")
        marker = os.path.join(target, ".seeded")
        if os.path.exists(marker):
            return
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")
        copied = []
        if os.path.isdir(src):
            for name in sorted(os.listdir(src)):
                if not name.endswith(".md"):
                    continue
                shutil.copyfile(os.path.join(src, name), os.path.join(target, name))
                copied.append(name)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        if copied:
            self.log.info("knowledge.seeded", files=copied)

    # ---------------- API ----------------
    def overview(self, payload):
        counts = {}
        for layer in self.layers:
            if layer == "public":
                counts[layer] = len(self._list_files(os.path.join(self.root, "public")))
            elif layer == "project":
                base = os.path.join(self.root, "projects")
                counts[layer] = {d: len(self._list_files(os.path.join(base, d))) for d in self._subdirs(base)}
            elif layer == "ticket":
                base = os.path.join(self.root, "tickets")
                counts[layer] = {d: len(self._list_files(os.path.join(base, d))) for d in self._subdirs(base)}
        return {"root": self.root, "layers": self.layers, "counts": counts}

    def write(self, payload):
        layer = payload.get("layer") or "public"
        path = self._doc_path(layer, payload.get("name"), payload.get("project"), payload.get("ticket"))
        content = payload.get("content") or ""
        mode = payload.get("mode") or "overwrite"
        if mode == "append" and os.path.exists(path):
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n\n" + content)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        self.emit("knowledge.written", {"layer": layer, "name": payload.get("name"), "path": path, "chars": len(content)})
        return {"path": path, "chars": len(content), "layer": layer}

    def read(self, payload):
        path = self._doc_path(payload.get("layer") or "public", payload.get("name"),
                              payload.get("project"), payload.get("ticket"))
        if not os.path.exists(path):
            raise ApiError("知识不存在: %s" % path, status=404, code="not_found")
        with open(path, "r", encoding="utf-8") as f:
            return {"path": path, "content": f.read()}

    def list_docs(self, payload):
        layer = payload.get("layer") or "public"
        base = self.layer_dir(layer, payload.get("project"), payload.get("ticket"))
        items = []
        for path in self._list_files(base):
            items.append({
                "name": os.path.relpath(path, base),
                "chars": os.path.getsize(path),
                "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(path))),
            })
        return {"layer": layer, "dir": base, "items": items}

    def search(self, payload):
        query = (payload.get("query") or "").strip()
        if not query:
            raise ApiError("query 必填", code="missing_query")
        layers = payload.get("layers") or self.layers
        limit = min(int(payload.get("limit") or 20), 100)
        hits = []
        for layer in layers:
            if layer == "public":
                dirs = [os.path.join(self.root, "public")]
            elif layer == "project":
                dirs = [self.layer_dir("project", payload.get("project"))] if payload.get("project") else \
                    [os.path.join(self.root, "projects", d) for d in self._subdirs(os.path.join(self.root, "projects"))]
            else:
                dirs = [self.layer_dir("ticket", None, payload.get("ticket"))] if payload.get("ticket") else \
                    [os.path.join(self.root, "tickets", d) for d in self._subdirs(os.path.join(self.root, "tickets"))]
            for d in dirs:
                for path in self._list_files(d):
                    for line_no, line in enumerate(self._read_lines(path), 1):
                        if query.lower() in line.lower():
                            hits.append({"layer": layer, "path": path, "line": line_no,
                                         "text": line.strip()[:300]})
                            if len(hits) >= limit:
                                return {"query": query, "hits": hits, "truncated": True}
        return {"query": query, "hits": hits, "truncated": False}

    def compose(self, payload):
        """把指定层/作用域的文档拼成一段提示词，供秘书、PM、角色注入。"""
        scopes = payload.get("scopes") or [{"layer": "public"}]
        budget = int(payload.get("max_chars") or self.max_inject)
        names = payload.get("names")          # 可选：只取这些文件名
        sections = []
        used = 0
        for scope in scopes:
            layer = scope.get("layer") or "public"
            base = self.layer_dir(layer, scope.get("project"), scope.get("ticket"))
            label = "%s:%s" % (layer, scope.get("project") or scope.get("ticket") or "machine")
            for path in self._list_files(base):
                rel = os.path.relpath(path, base)
                if names and rel not in names and os.path.basename(path) not in names:
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        text = f.read()
                except OSError:
                    continue
                block = "\n\n### [%s] %s\n%s" % (label, rel, text.strip())
                if used + len(block) > budget:
                    remain = max(0, budget - used)
                    if remain < 200:
                        break
                    block = block[:remain] + "\n...(已截断)"
                sections.append(block)
                used += len(block)
                if used >= budget:
                    break
            if used >= budget:
                break
        return {"text": "".join(sections), "chars": used, "scopes": scopes, "truncated": used >= budget}

    # ---------------- 工具 ----------------
    def _register_tools(self):
        tools = self.ctx.tools

        def write_tool(args, tctx):
            layer = args.get("layer") or "ticket"
            # 工具默认带上下文里的 project / ticket
            payload = {
                "layer": layer,
                "name": args.get("name"),
                "content": args.get("content") or "",
                "project": args.get("project") or tctx.session.get("project"),
                "ticket": args.get("ticket") or tctx.session.get("ticket"),
                "mode": args.get("mode") or "overwrite",
            }
            res = tctx.api("knowledge.write", **payload)
            return {"text": "已写入 %s（%d 字）" % (res["path"], res["chars"]), "meta": res}

        def read_tool(args, tctx):
            res = tctx.api(
                "knowledge.read",
                layer=args.get("layer") or "public",
                name=args.get("name"),
                project=args.get("project") or tctx.session.get("project"),
                ticket=args.get("ticket") or tctx.session.get("ticket"),
            )
            return res["content"]

        def list_tool(args, tctx):
            res = tctx.api(
                "knowledge.list",
                layer=args.get("layer") or "public",
                project=args.get("project") or tctx.session.get("project"),
                ticket=args.get("ticket") or tctx.session.get("ticket"),
            )
            lines = ["%s (%dB)" % (i["name"], i["chars"]) for i in res["items"]]
            return "目录: %s\n%s" % (res["dir"], "\n".join(lines) or "(空)")

        def search_tool(args, tctx):
            res = tctx.api("knowledge.search", query=args.get("query"), layers=args.get("layers"),
                           project=args.get("project") or tctx.session.get("project"),
                           ticket=args.get("ticket") or tctx.session.get("ticket"),
                           limit=args.get("limit") or 20)
            if not res["hits"]:
                return "没有命中"
            return "\n".join("%s:%d %s" % (h["path"], h["line"], h["text"]) for h in res["hits"])

        def compose_tool(args, tctx):
            scopes = args.get("scopes") or [
                {"layer": "public"},
                {"layer": "project", "project": tctx.session.get("project")},
                {"layer": "ticket", "ticket": tctx.session.get("ticket")},
            ]
            res = tctx.api("knowledge.compose", scopes=scopes, max_chars=args.get("max_chars"))
            return res["text"] or "(无可用知识)"

        tools.register(Tool(
            "knowledge_write", "把经验/结论沉淀到知识库（默认写入当前工单层）。",
            {"type": "object", "properties": {
                "name": {"type": "string", "description": "文件名，如 pm-playbook、arch-notes"},
                "content": {"type": "string", "description": "Markdown 正文"},
                "layer": {"type": "string", "enum": ["public", "project", "ticket"], "description": "默认 ticket"},
                "mode": {"type": "string", "enum": ["overwrite", "append"]},
            }, "required": ["name", "content"]},
            write_tool, origin=self.name))

        tools.register(Tool(
            "knowledge_read", "读取指定层的知识文档。",
            {"type": "object", "properties": {
                "name": {"type": "string"},
                "layer": {"type": "string", "enum": ["public", "project", "ticket"]},
            }, "required": ["name"]},
            read_tool, origin=self.name))

        tools.register(Tool(
            "knowledge_list", "列出某一层已有的知识文档。",
            {"type": "object", "properties": {
                "layer": {"type": "string", "enum": ["public", "project", "ticket"]},
            }},
            list_tool, origin=self.name))

        tools.register(Tool(
            "knowledge_search", "跨层检索知识（按行命中）。",
            {"type": "object", "properties": {
                "query": {"type": "string"},
                "layers": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer"},
            }, "required": ["query"]},
            search_tool, origin=self.name))

        tools.register(Tool(
            "knowledge_compose", "按需拼装多层知识成一段提示词。",
            {"type": "object", "properties": {
                "scopes": {"type": "array", "items": {"type": "object"}, "description": "[{layer, project?, ticket?}]"},
                "max_chars": {"type": "integer"},
            }},
            compose_tool, origin=self.name))

    # ---------------- 文件工具 ----------------
    @staticmethod
    def _list_files(base):
        out = []
        if not os.path.isdir(base):
            return out
        for dirpath, _, files in os.walk(base):
            for name in sorted(files):
                if name.endswith(".md"):
                    out.append(os.path.join(dirpath, name))
        return out

    @staticmethod
    def _subdirs(base):
        if not os.path.isdir(base):
            return []
        return [d for d in sorted(os.listdir(base)) if os.path.isdir(os.path.join(base, d))]

    @staticmethod
    def _read_lines(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().splitlines()
        except OSError:
            return []
