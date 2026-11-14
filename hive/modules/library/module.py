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
import os
import time

from ...kernel.api import ApiError, Module
from ...kernel.config import path_of
from ...kernel.store import Collection, ensure_dir, valid_id
from ...kernel.tools import Tool

KINDS = ("roles", "flows", "skills")

BUILTIN_ROLES = {
    "architect": {
        "cn": "架构师", "must_outputs": ["docs/**/*architect*", "docs/**/*架构*"],
        "prompt": "你是架构师。先读公共/项目知识库，再按需要读代码；只做结构层：模块边界、数据流、接口、"
                  "新增/变更规则、失败与回滚，给出取舍理由。必须产出架构设计文档（Markdown），"
                  "不要写业务实现代码，也不要把整段代码贴进方案。",
    },
    "developer": {
        "cn": "开发", "must_outputs": ["**/*.py", "**/*.js", "**/*.go", "**/*.sh"],
        "prompt": "你是开发。先读任务指定的知识与接口，再按验收标准实现；只改工单范围内的文件。"
                  "按项目实际语言交至少一种代码产物（.py/.js/.go/.sh），不要为了凑清单创建项目里不存在的语言文件。"
                  "改完必须自己跑一遍验证（测试或可复现命令），把改动点、验证命令、结果写清楚；"
                  "最后写 docs/handoff/<角色名>.md 交接文档。",
    },
    "reviewer": {
        "cn": "核验者", "must_outputs": ["docs/**/*review*", "docs/**/*核对*"],
        "prompt": "你是核验者。先读知识库和交付件，再独立复核：逐条对照验收标准，指出证据（文件/命令/输出），"
                  "给出 通过/不通过 结论与缺口清单。不要替人改代码。",
    },
    "ops": {
        "cn": "运维", "must_outputs": ["**/*.txt", "**/*.md"],
        "prompt": "你是运维。先读知识库中的运行约束；只做只读采集与诊断，命令原文必须留档（raw/ 下），"
                  "不要改系统状态；给出可回滚步骤与验证命令。",
    },
    "writer": {
        "cn": "撰写", "must_outputs": ["docs/**/*.md"],
        "prompt": "你是撰写。先读知识库与交付件，把事实写成可读文档：结论先行、数据带来源、不编造。",
    },
    "researcher": {
        "cn": "调研", "must_outputs": ["docs/**/*.md"],
        "prompt": "你是调研。先读知识库，再补外部来源；给出信息来源与对比，明确哪些是事实、哪些是推断。",
    },
    "tester": {
        "cn": "测试", "must_outputs": ["docs/**/*test*", "**/*test*.py"],
        "prompt": "你是测试。先读知识库里的验收口径，设计可复现的用例并真实执行，记录命令与输出；"
                  "不通过要说清复现步骤，不要只看代码猜结论。",
    },
    "process": {
        "cn": "流程专家", "must_outputs": ["**/*.json"],
        "prompt": "你是流程专家。把模糊的角色需求拆成：角色定义（提示词）、技能（操作手册）、流程插件"
                  "（必交产物与校验规则）。产出必须是结构化 JSON，可被系统直接加载；"
                  "同时说明它和现有角色/流程的边界，避免重复造岗位。",
    },
    "skill-decomposer": {
        "cn": "Skill 拆解者", "must_outputs": ["**/*.json", "docs/**/*.md"],
        "prompt": "你是 Skill 拆解者。读取一个开源 Skill 的 SKILL.md，把它拆成三层："
                  "1) 角色：谁来做（角色名、职责、提示词、边界）；2) 技能：怎么做（Skill 包路径、"
                  "触发条件、资源/脚本）；3) 流程插件：交什么（必交产物 glob、内容校验、失败重试）。"
                  "先用 skill_sources 看来源，再 skill_install 安装，最后 skill_decompose 固化；"
                  "拆完检查角色卡、流程校验项是否真的可执行，不要把 Skill 原文原样当角色提示词。",
    },
}

# 同一岗位常有两种命名习惯（英文/中文、文档/测试），它们不是“全部都要交”。
# 这些角色用 match=any 的组，避免开发者只改 .js 却被要求补 .go/.sh。
BUILTIN_ROLE_CHECKS = {
    "architect": {"kind": "glob", "paths": ["docs/**/*architect*", "docs/**/*架构*"], "match": "any"},
    "developer": {"kind": "glob", "paths": ["**/*.py", "**/*.js", "**/*.go", "**/*.sh"], "match": "any"},
    "reviewer": {"kind": "glob", "paths": ["docs/**/*review*", "docs/**/*核对*"], "match": "any"},
    "ops": {"kind": "glob", "paths": ["**/*.txt", "**/*.md"], "match": "any"},
    "tester": {"kind": "glob", "paths": ["docs/**/*test*", "**/*test*.py"], "match": "any"},
}


BUILTIN_FLOWS = {
    "project-lifecycle": {
        "cn": "项目生命周期",
        "nodes": ["project.active", "project.archived", "project.delete.preview",
                  "project.delete.confirm", "project.data.purge", "project.done"],
        "edges": [["project.active", "project.archived"],
                  ["project.active", "project.delete.preview"],
                  ["project.delete.preview", "project.delete.confirm"],
                  ["project.delete.confirm", "project.data.purge"],
                  ["project.data.purge", "project.done"],
                  ["project.archived", "project.done"]],
        "checks": [],
    },
    "architecture-gate": {
        "cn": "架构静态门禁",
        "nodes": ["scan.modules", "scan.imports", "scan.api-edges", "scan.flows",
                  "scan.web-state", "gate.report", "gate.pass", "gate.block"],
        "edges": [["scan.modules", "scan.imports"], ["scan.modules", "scan.api-edges"],
                  ["scan.imports", "gate.report"], ["scan.api-edges", "gate.report"],
                  ["scan.flows", "gate.report"], ["scan.web-state", "gate.report"],
                  ["gate.report", "gate.pass"], ["gate.report", "gate.block"]],
        "checks": [],
    },
    "system-timeline": {
        "cn": "群聊系统消息",
        "nodes": ["ticket.history", "system.event", "chat.timeline", "module.trace.optional"],
        "edges": [["ticket.history", "system.event"], ["system.event", "chat.timeline"],
                  ["module.trace.optional", "chat.timeline"]],
        "checks": [],
    },
    "project-idle": {
        "cn": "项目级忙闲与队列",
        "nodes": ["project.config", "idle.judge", "queue.enqueue", "queue.flush", "queue.done"],
        "edges": [["project.config", "idle.judge"], ["idle.judge", "queue.enqueue"],
                  ["queue.enqueue", "queue.flush"], ["queue.flush", "queue.done"]],
        "checks": [],
    },
    "requirement-to-flow": {
        "cn": "需求入库流程",
        "nodes": ["requirement.intake", "requirement.classify", "flow.design",
                  "flow.dag.check", "flow.library.upsert"],
        "edges": [["requirement.intake", "requirement.classify"],
                  ["requirement.classify", "flow.design"], ["flow.design", "flow.dag.check"],
                  ["flow.dag.check", "flow.library.upsert"]],
        "checks": [],
    },
    "requirement-owner": {
        "cn": "总需求负责流程",
        "kind": "process",
        "nodes": ["requirement.owner", "requirement.structure", "plan.document",
                  "ticket.split", "child.run", "child.report", "requirement.verify",
                  "requirement.close"],
        "edges": [["requirement.owner", "requirement.structure"],
                  ["requirement.structure", "plan.document"],
                  ["plan.document", "ticket.split"],
                  ["ticket.split", "child.run"],
                  ["child.run", "child.report"],
                  ["child.report", "requirement.verify"],
                  ["requirement.verify", "requirement.close"]],
        "checks": [],
    },
    "ticket-health": {
        "cn": "停滞工单健康检查",
        "kind": "process",
        "nodes": ["ticket.scan", "stall.judge", "audit.ticket", "ops.diagnose",
                  "resume.or.close", "ticket.health.report"],
        "edges": [["ticket.scan", "stall.judge"],
                  ["stall.judge", "audit.ticket"],
                  ["audit.ticket", "ops.diagnose"],
                  ["ops.diagnose", "resume.or.close"],
                  ["resume.or.close", "ticket.health.report"]],
        "checks": [],
    },
    "web-state-contract": {
        "cn": "网页状态机契约",
        "nodes": ["state-machine.json", "component.inventory", "event.binding",
                  "webstate.validate", "gate.report"],
        "edges": [["state-machine.json", "component.inventory"],
                  ["component.inventory", "event.binding"],
                  ["event.binding", "webstate.validate"], ["webstate.validate", "gate.report"]],
        "checks": [],
    },
}


def _load_requirement_flows():
    """历史需求逐条沉淀为可扫描流程；放在 docs/ 下随 git 部署，不依赖运行期 data。"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    path = os.path.join(root, "docs", "requirement-flows.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        return {}


REQUIREMENT_FLOWS = _load_requirement_flows()


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
        # 兼容内部调用名 library.get；对外仍保留 /api/library/item
        self.api.route("GET", "/api/library/get", name="get")(self.item_api)
        self.api.route("POST", "/api/library/upsert", name="upsert")(self.upsert_api)
        self.api.route("POST", "/api/library/check", name="check")(self.check_api)
        self.api.route("POST", "/api/library/design", name="design")(self.design_api)
        self.api.route("POST", "/api/library/update_prompt", name="update_prompt")(
            lambda payload: self.update_prompt(payload.get("role") or "", payload.get("prompt") or "",
                                               payload.get("must_outputs") or [], payload.get("checks") or [],
                                               payload.get("change_note") or ""))
        self.api.route("GET", "/api/library/summary", name="summary")(self.summary_api)
        self.api.route("GET", "/api/library/tags", name="tags")(self.tags_api)
        self.api.route("POST", "/api/library/tag_add", name="tag_add")(self.tag_add_api)
        self._register_tools()

    def _seed(self):
        """内置库随代码版本同步。

        内置角色/流程是公共基线，不允许在线改写；旧版本已经落盘的 builtin 记录
        必须在新版本启动时同步，否则修复永远进不到已有环境。自定义角色/流程不动。
        """
        for rid, spec in BUILTIN_ROLES.items():
            old = self.stores["roles"].get(rid)
            rec = {
                "id": rid, "name": rid, "cn": spec["cn"], "prompt": spec["prompt"],
                "must_outputs": list(spec["must_outputs"]), "builtin": True,
                "created": (old or {}).get("created") or _now(),
                "updated": _now(),
            }
            if old and not old.get("builtin"):
                continue
            if old and all(old.get(k) == rec.get(k) for k in ("cn", "prompt", "must_outputs")):
                continue
            self.stores["roles"].put(rid, rec)

            flow = self.stores["flows"].get(rid)
            checks = [dict(BUILTIN_ROLE_CHECKS[rid])] if rid in BUILTIN_ROLE_CHECKS else \
                [{"kind": "glob", "path": p} for p in spec["must_outputs"]]
            flow_rec = {
                "id": rid, "role": rid, "checks": checks, "max_retry": 2,
                "builtin": True, "created": (flow or {}).get("created") or _now(),
                "updated": _now(),
            }
            if flow and not flow.get("builtin"):
                continue
            if flow and flow.get("checks") == checks:
                continue
            self.stores["flows"].put(rid, flow_rec)
        # 需求级流程：不是角色插件，而是对用户历史需求的可扫描 DAG 表达。
        for fid, spec in dict(BUILTIN_FLOWS, **REQUIREMENT_FLOWS).items():
            old = self.stores["flows"].get(fid)
            if old and not old.get("builtin"):
                continue
            rec = {
                "id": fid, "role": "", "cn": spec["cn"], "kind": spec.get("kind") or "process",
                "nodes": spec["nodes"], "edges": spec["edges"], "checks": spec["checks"],
                "requirement_no": spec.get("requirement_no"), "status": spec.get("status"),
                "evidence": spec.get("evidence"), "source": spec.get("source"),
                "max_retry": spec.get("max_retry", 0), "builtin": True,
                "created": (old or {}).get("created") or _now(), "updated": _now(),
            }
            if old and all(old.get(k) == rec.get(k) for k in ("cn", "kind", "nodes", "edges", "checks")):
                continue
            self.stores["flows"].put(fid, rec)

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

    def check_files(self, flow_id, files, root=""):
        """用流程插件校验：files 是相对路径列表，返回缺失项。

        检查项（可组合）：
          {"kind":"glob","path":"docs/**/*architect*.md"}
          {"kind":"glob","paths":["**/*.py","**/*.js"],"match":"any"}   # 任一语言即可
          {"kind":"glob","path":"docs/**/*.md","min_bytes":120}
          {"kind":"glob","path":"docs/**/*.md","contains":["取舍","回滚"]}
        只给 glob 时是“文件存在”；加了 min_bytes / contains 就是“文件真的写了东西”，
        防止交一个空文件骗过流程校验。paths+match=any 用于“同一类产物有多个可接受写法”的岗位。
        """
        import os
        flow = self._store("flows").get(flow_id)
        if not flow:
            return {"flow": flow_id, "missing": [], "checked": 0, "known": False}
        files = [f.replace("\\", "/") for f in files]
        missing = []
        for check in flow.get("checks") or []:
            kind = check.get("kind") or "glob"
            if kind not in ("glob", "contains"):
                continue
            patterns = [p for p in (check.get("paths") or [check.get("path") or ""]) if p]
            patterns = [p.replace("\\", "/") for p in patterns]
            if not patterns:
                continue
            match_mode = (check.get("match") or "all").lower()
            matched_map = {p: [f for f in files if self._glob_match(f, p)] for p in patterns}
            if match_mode == "any":
                matched = []
                for p in patterns:
                    matched.extend(matched_map[p])
                label = " 或 ".join(patterns)
            else:
                matched = []
                for p in patterns:
                    matched.extend(matched_map[p])
                label = " + ".join(patterns)
                absent = [p for p in patterns if not matched_map[p]]
                if absent:
                    missing.append(label)
                    continue
            if not matched:
                missing.append(label)
                continue
            min_bytes = int(check.get("min_bytes") or 0)
            needles = check.get("contains") or []
            if (min_bytes or needles) and not root:
                missing.append("%s（校验内容需要工作树 root）" % label)
                continue
            if min_bytes and root:
                ok = False
                for f in matched:
                    try:
                        ok = ok or os.path.getsize(os.path.join(root, f)) >= min_bytes
                    except OSError:
                        continue
                if not ok:
                    missing.append("%s（至少 %d bytes）" % (label, min_bytes))
                    continue
            if needles and root:
                # 必须是“同一份文件”里同时包含这些要点；把所有文件拼起来会放过分散敷衍
                ok = False
                for f in matched:
                    try:
                        text = open(os.path.join(root, f), encoding="utf-8", errors="ignore").read()
                    except OSError:
                        continue
                    if all(str(n) in text for n in needles):
                        ok = True
                        break
                if not ok:
                    missing.append("%s（包含：%s）" % (label, "、".join(map(str, needles))))
        return {"flow": flow_id, "role": flow.get("role"), "missing": missing,
                "checked": len(flow.get("checks") or []), "known": True,
                "max_retry": flow.get("max_retry", 2)}

    @staticmethod
    def _glob_match(path, pattern):
        """真正的 glob：**/ 可跨任意层级，* 不跨 /。Python fnmatch 做不到 **。"""
        import re
        rx = []
        i = 0
        while i < len(pattern):
            c = pattern[i]
            if c == "*" and i + 1 < len(pattern) and pattern[i + 1] == "*":
                if i + 2 < len(pattern) and pattern[i + 2] == "/":
                    rx.append("(?:.*/)?")
                    i += 3
                    continue
                rx.append(".*")
                i += 2
                continue
            if c == "*":
                rx.append("[^/]*")
            elif c == "?":
                rx.append("[^/]")
            elif c == "/":
                rx.append("/")
            else:
                rx.append(re.escape(c))
            i += 1
        return re.match("".join(rx) + "$", path) is not None

    # ---------------- 流程专家 ----------------
    def design(self, role, responsibility, must_outputs=None, prompt="", skills=None, cn="",
               checks=None, overwrite=False, backend=""):
        """把一个“还不存在的角色”落成三件套：角色卡 + 流程插件 + 技能。"""
        role = (role or "").strip().lower().replace(" ", "-")[:40]
        if not role:
            raise ApiError("role 必填", code="missing_role")
        if not valid_id(role):
            raise ApiError("role 只能用字母/数字/中文/下划线/连字符: %r" % role,
                           status=400, code="bad_role")
        old = self._store("roles").get(role)
        if old and old.get("builtin") and not overwrite:
            raise ApiError("角色 %s 是公共库内置角色，不能被流程专家覆盖；请换一个名字或显式 overwrite"
                           % role, status=409, code="builtin_role")
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
            "checks": checks or [{"kind": "glob", "path": p} for p in must_outputs],
            "max_retry": 2, "builtin": False, "source": "process-expert",
        })
        if backend:
            flow["backend"] = backend
            self.upsert("flows", flow)
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

    def update_prompt(self, role, prompt, must_outputs=None, checks=None, change_note=""):
        """提示词自迭代：只改非内置角色，保留 id/来源，流程校验同步更新。"""
        rec = self.get("roles", role)
        if not rec:
            raise ApiError("角色不存在: %s" % role, status=404, code="no_role")
        if rec.get("builtin"):
            raise ApiError("内置角色 %s 不允许在线改写；请用 flow_design 新建 v2 角色，避免污染公共基线"
                           % role, status=409, code="builtin_role")
        before = rec.get("prompt") or ""
        rec["prompt"] = prompt or before
        if must_outputs:
            rec["must_outputs"] = list(must_outputs)
        rec["updated"] = _now()
        self.upsert("roles", rec)
        flow = self.get("flows", role) or {"id": role, "role": role, "checks": [], "max_retry": 2}
        if checks:
            flow["checks"] = list(checks)
        elif must_outputs:
            flow["checks"] = [{"kind": "glob", "path": p} for p in must_outputs]
        flow["source"] = flow.get("source") or "prompt-iteration"
        flow["updated"] = _now()
        self.upsert("flows", flow)
        self.emit("library.prompt.updated", {"role": role, "before_chars": len(before),
                                             "after_chars": len(rec["prompt"]),
                                             "note": change_note[:200]})
        return {"role": rec, "flow": flow, "before_chars": len(before),
                "after_chars": len(rec["prompt"])}

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
        return self.check_files(payload.get("flow") or "", payload.get("files") or [],
                                root=payload.get("root") or "")

    def design_api(self, payload):
        return self.design(payload.get("role") or "", payload.get("responsibility") or "",
                           payload.get("must_outputs") or [], payload.get("prompt") or "",
                           payload.get("skills") or [], payload.get("cn") or "",
                           payload.get("checks") or [], backend=payload.get("backend") or "")

    def _tag_path(self, scope, project=""):
        import os
        base = os.path.join(self.root, "tags")
        if scope == "project":
            if not valid_id(project):
                raise ApiError("非法 project id", status=400, code="bad_project")
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
            from ...kernel.api import ApiError
            raise ApiError("name 必填", code="missing_name")
        return self.tag_add(name[:24], payload.get("project") or "")

    def tags_api(self, payload):
        from ...kernel.api import ApiError
        project = payload.get("project") or ""
        if project and not valid_id(project):
            raise ApiError("非法 project id", status=400, code="bad_project")
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
                              args.get("skills") or [], args.get("cn") or "",
                              args.get("checks") or [])
            return ("已把角色 %s 固化：提示词已入库、流程插件校验 %d 条必交产物、技能 %d 个。"
                    "派活时直接用 role_spawn(role=%s)。" % (
                        res["role"]["id"], len(res["flow"].get("checks") or []),
                        len(res["skills"]), res["role"]["id"]))

        def update_prompt_tool(args, tctx):
            res = self.update_prompt(args.get("role") or "", args.get("prompt") or "",
                                     args.get("must_outputs") or [], args.get("checks") or [],
                                     args.get("change_note") or "")
            return ("已更新角色 %s 的提示词（%d -> %d 字），流程校验 %d 项。"
                    % (res["role"]["id"], res["before_chars"], res["after_chars"],
                       len(res["flow"].get("checks") or [])))

        def check_tool(args, tctx):
            res = self.check_files(args.get("flow") or "", args.get("files") or [],
                                   root=args.get("root") or getattr(tctx, "workspace", "") or "")
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
                "checks": {"type": "array", "items": {"type": "object"},
                           "description": "可选：流程校验项，如 {kind:glob,path:docs/**/*architect*.md,min_bytes:200,contains:[取舍]}"},
            }, "required": ["role", "responsibility"]},
            design_tool, origin=self.name))
        tools.register(Tool(
            "library_update_prompt", "流程专家：在回顾工单里迭代非内置角色/流程提示词；内置角色受保护。",
            {"type": "object", "properties": {
                "role": {"type": "string"}, "prompt": {"type": "string"},
                "must_outputs": {"type": "array", "items": {"type": "string"}},
                "checks": {"type": "array", "items": {"type": "object"}},
                "change_note": {"type": "string", "description": "为什么改、来自哪张旧工单"},
            }, "required": ["role", "prompt"]},
            update_prompt_tool, origin=self.name))
        tools.register(Tool("flow_check", "用流程插件校验一批文件是否齐（缺件清单）。",
                            {"type": "object", "properties": {
                                "flow": {"type": "string"},
                                "files": {"type": "array", "items": {"type": "string"}},
                                "root": {"type": "string", "description": "可选：工作树根目录，用于 min_bytes/contains"}},
                             "required": ["flow"]},
                            check_tool, origin=self.name))
