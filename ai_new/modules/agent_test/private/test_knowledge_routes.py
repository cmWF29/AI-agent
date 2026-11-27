"""知识模块路由：装配注册、保存链路的回退与冲突模板、文档元数据读取与越界拒绝。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent.knowledge import _as_handler, _route_doc_meta, _route_save, setup  # noqa: E402


class _Tools:
    def __init__(self, ctx):
        self.ctx = ctx

    def register_demand(self, name, desc, args, demand=None, module=None):
        self.ctx.demands.append({"name": name, "demand": demand, "args": args})
        return True


class _Api:
    def __init__(self, ctx):
        self.ctx = ctx

    def register(self, name, fn, desc="", module=None):
        self.ctx.registered.append(name)
        self.ctx.handlers[name] = fn
        return True

    def call(self, name, params=None, caller=None):
        return self.ctx.call(name, params or {})


class _Ctx:
    def __init__(self):
        self.registered, self.demands, self.handlers = [], [], {}
        self.scope = {"ok": True, "prefix": "p"}
        self.doc = {"ok": True, "path": "p/x.md"}
        self.rev = {"ok": True, "version": 2, "author": "a", "updated": "u",
                    "chars": 5, "history": []}
        self.chk = {"ok": True}
        self.tpl = {"conflict": "c{current_version}", "token_required": "t{token}",
                    "conflict_hint": "h"}
        self.tools = _Tools(self)
        self.api = _Api(self)

    def call(self, name, params):
        if name == "config.get":
            if params.get("key") == "knowledge.paths":
                return {"value": {"index": "index.yaml"}}
            return {"value": {"knowledge_source": "llm"}}
        if name == "store.id":
            value = params.get("value")
            return {"id": str(value).lower() if value else ""}
        if name == "knowledge.scope":
            return self.scope
        if name == "knowledge.doc":
            return self.doc
        if name == "clock.now":
            return {"iso": "2026-11-26T08:00:00"}
        if name == "store.doc_revision":
            return self.rev
        if name == "knowledge.view":
            return {"ok": True, "path": params.get("path")}
        if name == "store.resolve_doc":
            return self.chk
        if name == "store.read":
            path = params.get("path")
            if path == "messages.yaml":
                return {"value": self.tpl}
            if path and path.endswith(".meta.yaml"):
                return {"value": {"version": 3, "author": "a", "updated": "u",
                                  "history": ["h"]}}
            return {"value": {"entries": []}}
        return {"ok": True}


class KnowledgeRoutesTest(unittest.TestCase):
    def test_setup_registers_routes_and_demands(self):
        ctx = _Ctx()
        self.assertTrue(setup(ctx))
        for name in ("knowledge.scope", "knowledge.doc", "knowledge.save",
                     "knowledge.doc_meta"):
            self.assertIn(name, ctx.registered)
        self.assertEqual([d["demand"] for d in ctx.demands],
                         ["knowledge-read", "knowledge-write", "knowledge-search"])
        by_demand = {d["demand"]: [a["name"] for a in d["args"] if isinstance(a, dict)] for d in ctx.demands}
        self.assertNotIn("content", by_demand["knowledge-read"])
        self.assertNotIn("content", by_demand["knowledge-search"])
        self.assertIn("content", by_demand["knowledge-write"])

    def test_handler_injects_tpl_only_when_missing(self):
        ctx = _Ctx()
        handler = _as_handler(lambda payload: {"tpl": payload.get("tpl")})
        self.assertEqual(handler(ctx, None)["tpl"], ctx.tpl)
        self.assertEqual(handler(ctx, {"tpl": {"a": 1}})["tpl"], {"a": 1})

    def test_save_success_overwrite_and_append(self):
        ctx = _Ctx()
        got = _route_save(ctx, {"layer": "public", "name": "X", "content": "c",
                                "version": 1})
        self.assertTrue(got["ok"])
        self.assertEqual(got["effects"][0]["path"], "index.yaml")
        self.assertEqual(got["revision"]["version"], 2)
        appended = _route_save(ctx, {"layer": "project", "project": "P",
                                     "name": "Y", "content": "c", "mode": "append",
                                     "force": True, "base_version": 7})
        self.assertTrue(appended["ok"])

    def test_save_scope_and_doc_rejections(self):
        ctx = _Ctx()
        ctx.scope = {"ok": False, "code": "bad_layer"}
        self.assertEqual(_route_save(ctx, {})["code"], "bad_layer")
        ctx.scope = {"ok": True}
        ctx.doc = {"ok": False, "code": "bad_name"}
        self.assertEqual(_route_save(ctx, {})["code"], "bad_name")

    def test_save_conflict_templates(self):
        ctx = _Ctx()
        ctx.rev = {"ok": False, "code": "token_required", "current_version": "9"}
        got = _route_save(ctx, {"version": 1})
        self.assertEqual(got["status"], 409)
        self.assertEqual(got["error"], "t1")
        self.assertEqual(got["hint"], "h")
        self.assertEqual(got["requester"], {"version": 1, "author": ""})

        ctx.rev = {"ok": False, "code": "conflict", "current_version": "9"}
        got = _route_save(ctx, {"base_version": 2, "author": "b"})
        self.assertEqual(got["error"], "c9")

        ctx.tpl = {}
        got = _route_save(ctx, {})
        self.assertEqual(got["error"], "")
        self.assertEqual(got["hint"], "")

    def test_doc_meta_paths_and_guard(self):
        ctx = _Ctx()
        ctx.chk = {"ok": False, "code": "path_escape"}
        self.assertEqual(_route_doc_meta(ctx, {"path": "../x.md"})["code"], "path_escape")
        ctx.chk = {"ok": True}
        md = _route_doc_meta(ctx, {"path": "doc.md"})
        self.assertEqual((md["ok"], md["version"]), (True, 3))
        other = _route_doc_meta(ctx, {"path": "doc.txt"})
        self.assertEqual(other["history"], ["h"])

    def test_msg_tpl_empty_fallback(self):
        ctx = _Ctx()
        ctx.tpl = {}
        self.assertEqual(_as_handler(lambda p: p)(ctx, {})["tpl"], {})


if __name__ == "__main__":
    unittest.main()
