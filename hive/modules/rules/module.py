"""业务规则/流程层。

模块是能力，不是关系。工单不 import 项目，也不直接调项目 API：
它只调用规则 id，由本模块把“工单必须归属项目”翻译成对 projects.ensure 的调用。
规则目录在 data/rules/catalog.json，实体词表在 data/rules/ontology.json。
"""
from __future__ import annotations

import json
import os
import re
import time

from ...kernel.api import ApiError, Module
from ...kernel.config import path_of


class RuleBook:
    def __init__(self, root, available_modules=None, known_routes=None, requirements=None):
        self.root = root
        self.available_modules = set(available_modules or [])
        self.known_routes = set(known_routes or [])
        self.requirements = dict(requirements or {})
        self.ontology = {}
        self.relations = []
        self.processes = []
        self.events = []
        self.by_id = {}
        self.errors = []
        self.warnings = []
        self._load()
        self._validate()

    def _read(self, name):
        with open(os.path.join(self.root, name), encoding="utf-8") as f:
            return json.load(f)

    def _load(self):
        try:
            self.ontology = self._read("ontology.json")
        except Exception as exc:
            self.errors.append("ontology.json 读取失败: %r" % exc)
            self.ontology = {}
        try:
            catalog = self._read("catalog.json")
        except Exception as exc:
            self.errors.append("catalog.json 读取失败: %r" % exc)
            catalog = {}
        self.relations = list(catalog.get("relations") or [])
        self.processes = list(catalog.get("processes") or [])
        self.events = list(catalog.get("events") or [])
        for item in self.relations + self.processes + self.events:
            rid = item.get("id")
            if rid:
                self.by_id[rid] = item

    def _module_present(self, name):
        return name in self.available_modules

    def _route_present(self, route):
        return route in self.known_routes

    def _entities(self):
        return set((self.ontology.get("entities") or {}).keys())

    def _predicates(self):
        return set((self.ontology.get("predicates") or {}).keys())

    def _validate(self):
        errors, warnings = self.errors, self.warnings
        entities, predicates = self._entities(), self._predicates()
        ids = {}
        for item in self.relations + self.processes + self.events:
            rid = item.get("id")
            if not rid:
                errors.append("规则缺少 id: %r" % item.get("cn"))
                continue
            if rid in ids:
                errors.append("规则 id 重复: %s" % rid)
            ids[rid] = item

        for rule in self.relations:
            rid = rule.get("id")
            if not rid:
                continue
            if rule.get("kind") not in ("relation", "projection"):
                errors.append("%s: relation 的 kind 必须是 relation/projection" % rid)
            if rule.get("subject") not in entities:
                errors.append("%s: 未知 subject %r" % (rid, rule.get("subject")))
            if rule.get("object") not in entities:
                errors.append("%s: 未知 object %r" % (rid, rule.get("object")))
            if rule.get("predicate") not in predicates:
                errors.append("%s: 未知 predicate %r" % (rid, rule.get("predicate")))
            if rule.get("cardinality") not in ("1:1", "1:N", "N:1", "N:N"):
                errors.append("%s: 非法 cardinality %r" % (rid, rule.get("cardinality")))
            from_mod, to_mod = rule.get("from"), rule.get("to")
            optional = bool(rule.get("optional"))
            for side, mod in (("from", from_mod), ("to", to_mod)):
                if mod and not self._module_present(mod):
                    msg = "%s: %s 模块 %s 不存在" % (rid, side, mod)
                    (warnings if optional else errors).append(msg)
            steps = rule.get("steps") or []
            if not steps:
                errors.append("%s: 可执行规则至少需要一个 step" % rid)
            for step in steps:
                call = step.get("call")
                if not call:
                    errors.append("%s: step 缺少 call" % rid)
                    continue
                target = call.split(".", 1)[0]
                if to_mod and target != to_mod:
                    errors.append("%s: step 调用 %s，但 to 声明为 %s" % (rid, call, to_mod))
                if not self._route_present(call):
                    mod_present = self._module_present(target)
                    msg = "%s: 规则依赖路由 %s 不存在" % (rid, call)
                    (warnings if (optional and not mod_present) else errors).append(msg)

        for proc in self.processes:
            pid = proc.get("id")
            if not pid:
                continue
            if proc.get("kind") != "process":
                errors.append("%s: process 的 kind 必须是 process" % pid)
            if proc.get("subject") not in entities:
                errors.append("%s: 未知 process subject %r" % (pid, proc.get("subject")))
            if proc.get("object") not in entities:
                errors.append("%s: 未知 process object %r" % (pid, proc.get("object")))
            if proc.get("predicate") not in predicates:
                errors.append("%s: 未知 process predicate %r" % (pid, proc.get("predicate")))
            for child in proc.get("composes") or []:
                if child not in ids:
                    errors.append("%s: composes 引用不存在的规则 %s" % (pid, child))
                elif ids[child].get("kind") == "process":
                    errors.append("%s: process 不能直接嵌套 process %s" % (pid, child))
                elif ids[child].get("kind") == "event":
                    errors.append("%s: process 不能把事件订阅当步骤 %s" % (pid, child))
            for req in proc.get("requirements") or []:
                if self.requirements and req not in self.requirements:
                    warnings.append("%s: 引用了未知需求 %s" % (pid, req))

        # 关系冲突：同一 subject+predicate 下，排他谓词不能同时指向两个对象；
        # 同一 subject+predicate+object 不能出现两种基数。
        groups = {}
        for rule in self.relations:
            key = (rule.get("subject"), rule.get("predicate"))
            if not all(key):
                continue
            groups.setdefault(key, []).append(rule)
        predicates = self.ontology.get("predicates") or {}
        for key, rows in groups.items():
            objects = {r.get("object") for r in rows}
            if predicates.get(key[1], {}).get("exclusive") and len(objects) > 1:
                errors.append("关系冲突: %s %s 是排他关系，却同时指向 %s" % (
                    key[0], key[1], ", ".join(sorted(str(x) for x in objects))))
            by_object = {}
            for r in rows:
                by_object.setdefault(r.get("object"), set()).add(r.get("cardinality"))
            for obj, cards in by_object.items():
                if len(cards) > 1:
                    errors.append("关系冲突: %s %s -> %s 的基数不一致: %s" % (
                        key[0], key[1], obj, ", ".join(sorted(str(x) for x in cards))))

        for ev in self.events:
            eid = ev.get("id")
            if not eid:
                continue
            if ev.get("kind") != "event":
                errors.append("%s: event 的 kind 必须是 event" % eid)
            topic = ev.get("topic") or ""
            if not topic:
                errors.append("%s: event 缺少 topic" % eid)
            elif topic != "*" and not re.match(r"^[a-z][a-z0-9_-]*:[a-z0-9_.:*-]+$", topic):
                errors.append("%s: 非法 topic %r" % (eid, topic))
            from_mod, to_mod = ev.get("from"), ev.get("to")
            optional = bool(ev.get("optional"))
            if not from_mod:
                errors.append("%s: event 缺少 from" % eid)
            if not to_mod:
                errors.append("%s: event 缺少 to" % eid)
            if from_mod and from_mod != "*" and not self._module_present(from_mod):
                (warnings if optional else errors).append("%s: from 模块 %s 不存在" % (eid, from_mod))
            if to_mod and not self._module_present(to_mod):
                (warnings if optional else errors).append("%s: to 模块 %s 不存在" % (eid, to_mod))

        for req in self.relations + self.processes + self.events:
            for req_id in req.get("requirements") or []:
                if self.requirements and req_id not in self.requirements:
                    warnings.append("%s: 引用未知需求 %s" % (req.get("id"), req_id))

        self.errors = errors
        self.warnings = warnings

    def rule(self, rid):
        return self.by_id.get(rid)

    def active(self, rule):
        return all(m == "*" or self._module_present(m)
                   for m in (rule.get("from"), rule.get("to")) if m)

    def status(self):
        counts = {"relations": len(self.relations), "processes": len(self.processes),
                  "events": len(self.events),
                  "active": sum(1 for r in self.relations if self.active(r)),
                  "active_events": sum(1 for e in self.events if self.active(e))}
        reqs = set()
        for item in self.relations + self.processes + self.events:
            reqs.update(item.get("requirements") or [])
        counts["requirements"] = len(reqs)
        counts["requirement_total"] = len(self.requirements)
        return counts

    def catalog(self):
        return {
            "ok": not self.errors,
            "stats": self.status(),
            "entities": self.ontology.get("entities") or {},
            "predicates": self.ontology.get("predicates") or {},
            "relations": [
                dict(r, active=self.active(r)) for r in self.relations
            ],
            "processes": list(self.processes),
            "events": [dict(e, active=self.active(e)) for e in self.events],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }

    def graph(self):
        nodes, edges = [], []
        for key, cn in (self.ontology.get("entities") or {}).items():
            nodes.append({"id": "entity:" + key, "type": "entity", "label": key, "cn": cn})
        mods = sorted({m for item in (self.relations + self.events)
                       for m in (item.get("from"), item.get("to")) if m and m != "*"})
        for m in mods:
            nodes.append({"id": "module:" + m, "type": "module", "label": m,
                          "active": self._module_present(m)})
        for rule in self.relations:
            rid = rule["id"]
            nodes.append({"id": "rule:" + rid, "type": "rule", "label": rule.get("cn") or rid,
                          "active": self.active(rule)})
            if rule.get("from"):
                edges.append({"from": "rule:" + rid, "to": "module:" + rule["from"], "kind": "from"})
            if rule.get("to"):
                edges.append({"from": "rule:" + rid, "to": "module:" + rule["to"], "kind": "to"})
            if rule.get("subject"):
                edges.append({"from": "rule:" + rid, "to": "entity:" + rule["subject"], "kind": "subject"})
            if rule.get("object"):
                edges.append({"from": "rule:" + rid, "to": "entity:" + rule["object"], "kind": "object"})
        for ev in self.events:
            eid = ev["id"]
            nodes.append({"id": "event:" + eid, "type": "event",
                          "label": ev.get("cn") or eid, "active": self.active(ev),
                          "topic": ev.get("topic") or ""})
            if ev.get("from") and ev["from"] != "*":
                edges.append({"from": "event:" + eid, "to": "module:" + ev["from"], "kind": "publishes"})
            if ev.get("to"):
                edges.append({"from": "event:" + eid, "to": "module:" + ev["to"], "kind": "subscribes"})
            for req in ev.get("requirements") or []:
                edges.append({"from": "event:" + eid, "to": "requirement:" + req, "kind": "requirement"})
        for proc in self.processes:
            pid = proc["id"]
            nodes.append({"id": "process:" + pid, "type": "process", "label": proc.get("cn") or pid})
            for child in proc.get("composes") or []:
                if child in self.by_id:
                    edges.append({"from": "process:" + pid, "to": "rule:" + child, "kind": "composes"})
            for req in proc.get("requirements") or []:
                edges.append({"from": "process:" + pid, "to": "requirement:" + req, "kind": "requirement"})
        for req in sorted(self.requirements):
            nodes.append({"id": "requirement:" + req, "type": "requirement",
                          "label": req, "cn": (self.requirements.get(req) or {}).get("cn") or req})
        return {"ok": not self.errors, "nodes": nodes, "edges": edges,
                "stats": self.status(), "errors": list(self.errors), "warnings": list(self.warnings)}


class Rules(Module):
    name = "rules"

    def setup(self):
        # 规则目录是代码资产，不在临时 data 根下；测试用临时 cfg 时也读仓库规则。
        repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        root = path_of(self.cfg, "rules.root", os.path.join(repo, "data", "rules"))
        req_path = os.path.join(repo, "docs", "requirement-flows.json")
        requirements = {}
        try:
            requirements = json.loads(open(req_path, encoding="utf-8").read())
        except Exception as exc:
            self.log.warn("rules.requirements.unavailable", path=req_path, error=repr(exc))
        self.book = RuleBook(
            root,
            available_modules=list(self.ctx.modules.keys()),
            known_routes=[r["id"] for r in self.ctx.router.list()],
            requirements=requirements,
        )
        self.api.route("GET", "/api/rules/catalog", name="catalog")(self.catalog_api)
        self.api.route("GET", "/api/rules/graph", name="graph")(self.graph_api)
        self.api.route("POST", "/api/rules/validate", name="validate")(self.validate_api)
        self.api.route("POST", "/api/rules/run", name="run")(self.run_api)
        self.api.route("POST", "/api/rules/process", name="process")(self.process_api)
        self._bind_events()
        for err in self.book.errors:
            self.log.error("rules.invalid", error=err)
        for warn in self.book.warnings:
            self.log.warn("rules.warning", warning=warn)
        self.log.info("rules.ready", relations=len(self.book.relations),
                      processes=len(self.book.processes), events=len(self.book.events),
                      errors=len(self.book.errors))

    def _bind_events(self):
        """把各模块 setup 阶段登记的事件订阅，按规则目录统一绑定到总线。"""
        for sub in list(self.ctx.event_subscriptions):
            event = self.book.rule(sub["event"])
            if not event or event.get("kind") != "event":
                raise RuntimeError("模块 %s 订阅了不存在的事件规则 %s" % (
                    sub["source"], sub["event"]))
            if event.get("to") != sub["source"]:
                raise RuntimeError("模块 %s 不能订阅事件 %s（to=%s）" % (
                    sub["source"], sub["event"], event.get("to")))
            if not self.book.active(event):
                self.log.warn("rules.event.inactive", event=sub["event"], source=sub["source"])
                continue
            self.bus.subscribe(event.get("topic") or "", sub["handler"], name=sub["name"])

    def catalog_api(self, payload):
        return self.book.catalog()

    def graph_api(self, payload):
        return self.book.graph()

    def validate_api(self, payload):
        return {"ok": not self.book.errors, "errors": list(self.book.errors),
                "warnings": list(self.book.warnings), "stats": self.book.status()}

    def run_api(self, payload):
        rule_id = payload.get("rule") or payload.get("id")
        data = payload.get("payload") or {}
        source = payload.get("source") or "api"
        if not rule_id:
            raise ApiError("规则执行缺少 rule", status=400, code="rule_required")
        rule = self.book.rule(rule_id)
        if not rule:
            raise ApiError("规则不存在: %s" % rule_id, status=404, code="rule_not_found")
        if rule.get("kind") in ("process", "event") or not rule.get("steps"):
            raise ApiError("规则不可直接执行: %s" % rule_id, status=409, code="rule_not_executable")
        if source and source != "api" and rule.get("from") and source != rule.get("from"):
            raise ApiError("模块 %s 不能执行规则 %s（from=%s）" % (
                source, rule_id, rule.get("from")), status=403, code="rule_forbidden")
        if not self.book.active(rule):
            raise ApiError("规则依赖的模块未装配: %s" % rule_id, status=409, code="rule_inactive")
        t0 = time.time()
        try:
            last = self._execute(rule, data)
            self.log.info("rule.run", rule=rule_id, source=source,
                          ms=int((time.time() - t0) * 1000))
            return last
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError("规则执行失败: %s (%r)" % (rule_id, exc), status=500, code="rule_failed")

    def process_api(self, payload):
        """按流程组合顺序执行子规则；不做跨模块事务回滚（模块 API 只保证单步原子）。"""
        pid = payload.get("process") or payload.get("id")
        data = payload.get("payload") or {}
        if not pid:
            raise ApiError("流程执行缺少 process", status=400, code="process_required")
        proc = self.book.rule(pid)
        if not proc or proc.get("kind") != "process":
            raise ApiError("流程不存在: %s" % pid, status=404, code="process_not_found")
        if not self.book.active(proc):
            raise ApiError("流程依赖的模块未装配: %s" % pid, status=409, code="process_inactive")
        completed, results = [], []
        for child in proc.get("composes") or []:
            rule = self.book.rule(child)
            if not rule or rule.get("kind") != "relation":
                raise ApiError("流程引用了不可执行规则: %s" % child, status=409, code="process_bad_child")
            if not self.book.active(rule):
                raise ApiError("流程子规则依赖的模块未装配: %s" % child, status=409, code="process_inactive")
            try:
                results.append({"rule": child, "result": self._execute(rule, data)})
                completed.append(child)
            except Exception as exc:
                raise ApiError("流程 %s 在 %s 失败，已完成 %s (%r)" % (
                    pid, child, ", ".join(completed) or "无", exc), status=500, code="process_failed")
        self.log.info("process.run", process=pid, steps=len(completed))
        return {"ok": True, "process": pid, "completed": completed, "results": results}

    def _execute(self, rule, data):
        last = {}
        for step in rule.get("steps") or []:
            call = step.get("call")
            args = self._step_payload(step, data)
            target = call.split(".", 1)[0]
            if target not in self.ctx.modules:
                raise ApiError("规则目标模块未装配: %s" % call, status=409, code="rule_inactive")
            last = self.ctx.api(call, **args)
        return last

    @staticmethod
    def _step_payload(step, data):
        mapping = step.get("payload")
        if not mapping:
            return dict(data)
        out = {}
        for key, value in mapping.items():
            if isinstance(value, str) and value.startswith("$input."):
                out[key] = data.get(value[7:])
            else:
                out[key] = value
        return out
