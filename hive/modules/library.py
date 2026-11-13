"""角色库 / 流程库 / 技能库（需求 15、17）。

为什么要有这三本库：
  * 角色库：一个角色“是什么人、用什么提示词、交什么产物”，存成文件而不是靠上下文记忆；
  * 流程库 = 可插拔的“流程插件”：一条条可执行的检查（必交产物、校验规则），
    角色交作业后由 agent 自动跑一遍，缺什么就发消息让它补——不依赖模型自觉；
  * 技能库：可复用的操作手册（怎么写架构文档、怎么跑测试），按需注入角色提示词。

对外 API：
  GET  /api/library/list?kind=roles|flows|skills
  GET  /api/library/item?kind=&id=
  POST /api/library/upsert
  POST /api/library/check       用一个流程插件校验交付件（缺件清单）
  POST /api/library/design      流程专家：把“我要一个架构师”拆成 角色+提示词+技能+流程插件
  GET  /api/library/summary
"""
from __future__ import annotations

import fnmatch
import json
import time

from ..kernel.api import ApiError, Module
from ..kernel.config import path_of
from ..kernel.store import Collection, ensure_dir
from ..kernel.tools import Tool

KINDS = ("roles", "flows", "skills")

BUILTIN_ROLES = {
    "architect": {
        "cn": "架构师", "must_outputs": ["docs/**/*architect*", "docs/**/*架构*"],
        "prompt": "你是架构师。先读清现有代码与约束，再给可落地的架构方案：模块边界、数据流、接口、失败与回滚。"
                  "必须产出架构设计文档（Markdown），里面要有取舍理由。不要写业务实现代码。",
    },
    "developer": {
        "cn": "开发", "must_outputs": ["**/*.py", "**/*.js", "**/*.go", "**/*.sh"],
        "prompt": "你是开发。按任务给出的接口与验收标准实现，改完必须自己跑一遍验证（测试或可复现命令），"
                  "把改动点、验证命令、结果写清楚。",
    },
    "reviewer": {
        "cn": "核验者", "must_outputs": ["docs/**/*review*", "docs/**/*核对*"],
        "prompt": "你是核验者。独立复核别人的产物：逐条对照验收标准，指出证据（文件/命令/输出），"
                  "给出 通过/不通过 结论与缺口清单。不要替人改代码。",
    },
    "ops": {
        "cn": "运维", "must_outputs": ["**/*.txt", "**/*.md"],
        "prompt": "你是运维。只做只读采集与诊断，命令原文必须留档（raw/ 下），不要改系统状态。",
    },
    "writer": {
        "cn": "撰写", "must_outputs": ["docs/**/*.md"],
        "prompt": "你是撰写。把事实写成可读文档：结论先行、数据带来源、不编造。",
    },
    "researcher": {
        "cn": "调研", "must_outputs": ["docs/**/*.md"],
        "prompt": "你是调研。给出信息来源与对比，明确哪些是事实、哪些是推断。",
    },
    "tester": {
        "cn": "测试", "must_outputs": ["docs/**/*test*", "**/*test*.py"],
        "prompt": "你是测试。设计可复现的用例并真实执行，记录命令与输出；不通过要说清复现步骤。",
    },
    "process": {
        "cn": "流程专家", "must_outputs": ["**/*.json"],
        "prompt": "你是流程专家。把模糊的角色需求拆成：角色定义（提示词）、技能（操作手册）、流程插件"
                  "（必交产物与校验规则）。产出必须是结构化 JSON，可被系统直接加载。",
    },
}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Library(Module):
    name = "library"

    def setup(self):
        self.root = ensure_dir(path_of(self.cfg, "library.root", "data/library"))
        self.stores = {}
        for kind in KINDS:
            ensure_dir(self.root + "/" + kind)
            self.stores[kind] = Collection(self.root + "/" + kind)
        self._seed()

        self.api.route("GET", "/api/library/list", name="list")(self.list_api)
        self.api.route("GET", "/api/library/item", name="item")(self.item_api)
        self.api.route("POST", "/api/library/upsert", name="upsert")(self.upsert_api)
        self.api.route("POST", "/api/library/check", name="check")(self.check_api)
        self.api.route("POST", "/api/library/design", name="design")(self.design_api)
        self.api.route("GET", "/api/library/summary", name="summary")(self.summary_api)
        self.api.route("GET", "/api/library/tags", name="tags")(self.tags_api)
        self.api.route("POST", "/api/library/tag_add", name="tag_add")(self.tag_add_api)
        self._register_tools()

    def _seed(self):
        for rid, spec in BUILTIN_ROLES.items():
            if self.stores["roles"].get(rid):
                continue
            self.stores["roles"].put(rid, {
                "id": rid, "name": rid, "cn": spec["cn"], "prompt": spec["prompt"],
                "must_outputs": spec["must_outputs"], "builtin": True, "created": _now(),
            })
            self.stores["flows"].put(rid, {
                "id": rid, "role": rid, "checks": [{"kind": "glob", "path": p} for p in spec["must_outputs"]],
                "max_retry": 2, "builtin": True, "created": _now(),
            })

    # ---------------- 基础 ----------------
    def _store(self, kind):
        if kind not in self.stores:
            raise ApiError("kind 只能是 roles/flows/skills", code="bad_kind")
        return self.stores[kind]

    def get(self, kind, item_id):
        rec = self._store(kind).get(item_id)
        if not rec:
            raise ApiError("%s 不存在: %s" % (kind, item_id), status=404, code="no_item")
        return rec

    def upsert(self, kind, rec):
        rec = dict(rec)
        rec.setdefault("created", _now())
        rec["updated"] = _now()
        self._store(kind).put(rec["id"], rec)
        self.emit("library.upsert", {"kind": kind, "id": rec["id"]})
        return rec

    def role(self, role):
        """按名字取角色卡；没有就返回 None（PM 应该先 design）。"""
        return self.stores["roles"].get(role)

    def flow_for(self, role):
        return self.stores["flows"].get(role)

    def check_files(self, flow_id, files):
        """用流程插件校验：files 是相对路径列表，返回缺失项。"""
        flow = self._store("flows").get(flow_id)
        if not flow:
            return {"flow": flow_id, "missing": [], "checked": 0, "known": False}
        files = [f.replace("\\", "/") for f in files]
        missing = []
        for check in flow.get("checks") or []:
            kind = check.get("kind") or "glob"
            if kind != "glob":
                continue
            pattern = (check.get("path") or "").replace("\\", "/")
            if not pattern:
                continue
            hit = any(fnmatch.fnmatch(f, pattern) or fnmatch.fnmatch(f, pattern.replace("**/", ""))
                      for f in files)
            if not hit:
                missing.append(pattern)
        return {"flow": flow_id, "role": flow.get("role"), "missing": missing,
                "checked": len(flow.get("checks") or []), "known": True,
                "max_retry": flow.get("max_retry", 2)}

    # ---------------- 流程专家 ----------------
    def design(self, role, responsibility, must_outputs=None, prompt="", skills=None, cn=""):
        """把一个“还不存在的角色”落成三件套：角色卡 + 流程插件 + 技能。"""
        role = (role or "").strip().lower().replace(" ", "-")[:40]
        if not role:
            raise ApiError("role 必填", code="missing_role")
        must_outputs = [p for p in (must_outputs or []) if p] or ["docs/**/*.md"]
        body = prompt.strip() or (
            "你是%s。职责：%s\n"
            "要求：1) 先看清现状与边界；2) 产出必须可验证（文件/命令/证据）；"
            "3) 交付前自查是否覆盖全部必交产物；4) 不要编造完成。"
            % (cn or role, responsibility or role)
        )
        card = self.upsert("roles", {
            "id": role, "name": role, "cn": cn or role, "prompt": body,
            "must_outputs": must_outputs, "builtin": False, "source": "process-expert",
            "responsibility": responsibility or "",
        })
        flow = self.upsert("flows", {
            "id": role, "role": role,
            "checks": [{"kind": "glob", "path": p} for p in must_outputs],
            "max_retry": 2, "builtin": False, "source": "process-expert",
        })
        created_skills = []
        for s in skills or []:
            sid = (s.get("id") or s.get("name") or "").strip().lower().replace(" ", "-")[:40]
            if not sid:
                continue
            self.upsert("skills", {"id": sid, "name": s.get("name") or sid,
                                   "body": s.get("body") or "", "role": role})
            created_skills.append(sid)
        self.emit("library.design", {"role": role, "must_outputs": must_outputs, "skills": created_skills})
        self.log.info("library.design", role=role, outputs=len(must_outputs))
        return {"role": card, "flow": flow, "skills": created_skills}

    # ---------------- API ----------------
    def list_api(self, payload):
        kind = payload.get("kind") or "roles"
        items = self._store(kind).list()
        items.sort(key=lambda i: (not i.get("builtin"), i.get("id") or ""))
        return {"kind": kind, "items": items, "total": len(items)}

    def item_api(self, payload):
        return {"kind": payload.get("kind"), "item": self.get(payload.get("kind") or "roles",
                                                              payload.get("id") or "")}

    def upsert_api(self, payload):
        kind = payload.get("kind") or "roles"
        rec = payload.get("item") or payload
        if not rec.get("id"):
            raise ApiError("id 必填", code="missing_id")
        return {"kind": kind, "item": self.upsert(kind, rec)}

    def check_api(self, payload):
        return self.check_files(payload.get("flow") or "", payload.get("files") or [])

    def design_api(self, payload):
        return self.design(payload.get("role") or "", payload.get("responsibility") or "",
                           payload.get("must_outputs") or [], payload.get("prompt") or "",
                           payload.get("skills") or [], payload.get("cn") or "")

    def _tag_path(self, scope, project=""):
        import os
        base = os.path.join(self.root, "tags")
        if scope == "project" and project:
            return os.path.join(base, "projects", project + ".json")
        return os.path.join(base, "public.json")

    def _tags_read(self, scope, project=""):
        import json, os
        p = self._tag_path(scope, project)
        if not os.path.exists(p):
            return []
        try:
            return json.load(open(p, encoding="utf-8")).get("tags") or []
        except Exception:
            return []

    def tag_add(self, name, project=""):
        import json, os
        ensure = os.path.dirname(self._tag_path("project", project or "x"))
        os.makedirs(ensure, exist_ok=True)
        for scope, proj in (("public", ""), ("project", project)):
            if scope == "project" and not project:
                continue
            tags = self._tags_read(scope, proj)
            if name not in tags:
                tags.append(name)
            path = self._tag_path(scope, proj)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"tags": tags}, f, ensure_ascii=False)
        self.emit("library.tag", {"tag": name, "project": project})
        return {"tag": name}

    def tag_add_api(self, payload):
        name = (payload.get("name") or "").strip()
        if not name:
            from ..kernel.api import ApiError
            raise ApiError("name 必填", code="missing_name")
        return self.tag_add(name[:24], payload.get("project") or "")

    def tags_api(self, payload):
        from ..kernel.api import ApiError
        project = payload.get("project") or ""
        return {"public": self._tags_read("public"),
                "project": self._tags_read("project", project) if project else []}

    def summary_api(self, payload):
        return {"root": self.root,
                "counts": {k: len(self._store(k).list()) for k in KINDS},
                "roles": [r["id"] for r in self._store("roles").list()],
                "flows": [f["id"] for f in self._store("flows").list()],
                "skills": [s["id"] for s in self._store("skills").list()]}

    # ---------------- 工具 ----------------
    def _register_tools(self):
        tools = self.ctx.tools

        def list_tool(args, tctx):
            kind = args.get("kind") or "roles"
            rows = self._store(kind).list()
            if not rows:
                return "%s 库是空的" % kind
            return "\n".join("%s | %s%s" % (r.get("id"), r.get("cn") or r.get("name") or "",
                                            "（内置）" if r.get("builtin") else "")
                             for r in rows)

        def get_tool(args, tctx):
            rec = self.get(args.get("kind") or "roles", args.get("id") or "")
            return json.dumps(rec, ensure_ascii=False, indent=1)[:3000]

        def design_tool(args, tctx):
            res = self.design(args.get("role") or "", args.get("responsibility") or "",
                              args.get("must_outputs") or [], args.get("prompt") or "",
                              args.get("skills") or [], args.get("cn") or "")
            return ("已把角色 %s 固化：提示词已入库、流程插件校验 %d 条必交产物、技能 %d 个。"
                    "派活时直接用 role_spawn(role=%s)。" % (
                        res["role"]["id"], len(res["flow"].get("checks") or []),
                        len(res["skills"]), res["role"]["id"]))

        def check_tool(args, tctx):
            res = self.check_files(args.get("flow") or "", args.get("files") or [])
            if not res["known"]:
                return "没有这个流程插件: %s" % args.get("flow")
            if not res["missing"]:
                return "流程校验通过（%d 条检查项全齐）" % res["checked"]
            return "缺 %d 项必交产物：%s" % (len(res["missing"]), ", ".join(res["missing"]))

        tools.register(Tool("library_list", "列出角色库/流程库/技能库。",
                            {"type": "object", "properties": {
                                "kind": {"type": "string", "enum": ["roles", "flows", "skills"]}}},
                            list_tool, origin=self.name))
        tools.register(Tool("library_get", "取一个角色卡/流程插件/技能的内容。",
                            {"type": "object", "properties": {
                                "kind": {"type": "string", "enum": ["roles", "flows", "skills"]},
                                "id": {"type": "string"}}, "required": ["id"]},
                            get_tool, origin=self.name))
        tools.register(Tool(
            "flow_design", "流程专家：把“需要一个某角色”拆成 角色卡+提示词+技能+流程插件（必交产物校验）。"
            "公共角色库里没有的角色，先调它，再 role_spawn。",
            {"type": "object", "properties": {
                "role": {"type": "string", "description": "角色 id，如 architect"},
                "cn": {"type": "string", "description": "中文名，如 架构师"},
                "responsibility": {"type": "string", "description": "它到底负责什么"},
                "must_outputs": {"type": "array", "items": {"type": "string"},
                                 "description": "必交产物的 glob，如 docs/**/*architect*.md"},
                "prompt": {"type": "string", "description": "可选：角色提示词"},
                "skills": {"type": "array", "items": {"type": "object"},
                           "description": "可选：[{id,name,body}] 操作手册"},
            }, "required": ["role", "responsibility"]},
            design_tool, origin=self.name))
        tools.register(Tool("flow_check", "用流程插件校验一批文件是否齐（缺件清单）。",
                            {"type": "object", "properties": {
                                "flow": {"type": "string"},
                                "files": {"type": "array", "items": {"type": "string"}}},
                             "required": ["flow"]},
                            check_tool, origin=self.name))
