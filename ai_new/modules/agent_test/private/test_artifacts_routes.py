"""交付件路由单测：装配、分层归属解析、写入路径与索引合并。"""
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.artifacts import (_as_handler, _cfg, _cfg_paths, _msg_tpl,
                                          _route_resolve, _route_save, setup)
from ai_new.modules.agent.artifacts.private import _pure

TPL = {"missing_project": "找不到项目", "missing_scope_project": "缺项目",
       "missing_scope_ticket": "缺工单", "bad_path": "坏路径", "path_escape": "越界",
       "bad_layer": "坏层 {layer}", "bad_doc_kind": "类型 {kind}",
       "bad_source": "来源 {source}"}


class FakeApi:
    def __init__(self, ticket_rec=None, index=None, cfg=None):
        self.ticket_rec = ticket_rec
        self.index = index
        self.cfg = {"artifacts.paths": {"public": "pub", "project": "projects/{project}/item",
                                        "ticket": "projects/{project}/tickets/{ticket}/item",
                                        "index": "products/index.yaml"},
                    "taxonomy": {"doc_kinds": ["artifact", "docs"], "sources": ["llm", "system"]}}
        self.cfg.update(cfg or {})
        self.registered = []
        self.demands = []

    def register(self, name, fn, desc=None, module=None):
        self.registered.append(name)

    def call(self, name, payload=None, caller=None):
        p = payload or {}
        if name.startswith("artifacts."):
            return getattr(_pure, name.split(".", 1)[1])(p)
        if name == "config.get":
            return {"value": self.cfg.get(p.get("key"))}
        if name == "tickets.record_path":
            return {"path": "tickets/%s.yaml" % (p.get("id") or "")}
        if name == "store.read":
            if p.get("module") == "agent/artifacts" and p.get("path") == "messages.yaml":
                return {"value": TPL}
            if p.get("module") == "agent/tickets":
                return {"value": self.ticket_rec}
            if p.get("module") == "agent/artifacts":
                return {"value": {"entries": self.index or []}}
            raise AssertionError(p)
        if name == "store.id":
            value = p.get("value")
            return {"id": value or ""}
        if name == "codec.hex_from_base64":
            return {"hex": "41424344"}
        if name == "clock.now":
            return {"iso": "2026-01-01T00:00:00Z"}
        raise AssertionError(name)


class FakeTools:
    def __init__(self):
        self.demands = []

    def register_demand(self, name, desc, params, demand=None, module=None):
        self.demands.append((name, demand, len(params)))


def make_ctx(**kw):
    api = FakeApi(**kw)
    return SimpleNamespace(api=api, tools=FakeTools()), api


class SetupTest(unittest.TestCase):
    def test_setup_registers_routes_and_demands(self):
        ctx, api = make_ctx()
        self.assertTrue(setup(ctx))
        for name in ("artifacts.base", "artifacts.rel", "artifacts.written",
                     "artifacts.viewed", "artifacts.screen", "artifacts.stats",
                     "artifacts.group", "artifacts.resolve", "artifacts.save"):
            self.assertIn(name, api.registered)
        self.assertEqual(ctx.tools.demands,
                         [("artifact_write", "artifacts-write", 7),
                          ("artifact_read", "artifacts-read", 4)])

    def test_cfg_helpers(self):
        ctx, api = make_ctx()
        self.assertEqual(_cfg_paths(ctx)["public"], "pub")
        self.assertEqual(_msg_tpl(ctx), TPL)
        self.assertEqual(_cfg(ctx, "taxonomy")["doc_kinds"], ["artifact", "docs"])

    def test_as_handler_injects_tpl(self):
        seen = {}

        def fn(payload):
            seen.update(payload)
            return {"ok": True}

        handler = _as_handler(fn)
        ctx, api = make_ctx()
        handler(ctx, {"path": "a", "tpl": {"x": 1}})
        self.assertEqual(seen["tpl"], {"x": 1})
        handler(ctx, None)
        self.assertEqual(seen["tpl"], TPL)
        handler(ctx, {"path": "a"})
        self.assertEqual(seen["path"], "a")


class ResolveTest(unittest.TestCase):
    def test_explicit_project(self):
        ctx, api = make_ctx()
        got = _route_resolve(ctx, {"layer": "ticket", "project": "p1", "ticket": "t1"})
        self.assertEqual(got, {"layer": "ticket", "project": "p1", "ticket": "t1"})

    def test_project_layer_ignores_ticket_record(self):
        ctx, api = make_ctx(ticket_rec={"project": "wrong"})
        got = _route_resolve(ctx, {"layer": "project", "project": "p2"})
        self.assertEqual(got["project"], "p2")
        self.assertEqual(got["ticket"], "")

    def test_ticket_record_supplies_project(self):
        ctx, api = make_ctx(ticket_rec={"project": "p3"})
        got = _route_resolve(ctx, {"ticket": "t3"})
        self.assertEqual(got["layer"], "ticket")
        self.assertEqual(got["project"], "p3")

    def test_missing_project_returns_404(self):
        ctx, api = make_ctx(ticket_rec={})
        got = _route_resolve(ctx, {"ticket": "t4"})
        self.assertEqual(got["code"], "missing_project")
        self.assertEqual(got["status"], 404)
        self.assertEqual(got["error"], "找不到项目")

    def test_missing_project_without_template(self):
        ctx, api = make_ctx(ticket_rec=None)
        api.cfg["artifacts.paths"] = {"public": "pub"}
        ctx.api.call = _no_tpl(api.call)
        self.assertEqual(_route_resolve(ctx, {"ticket": "t5"})["error"], "")


def _no_tpl(orig):
    def call(name, payload=None, caller=None):
        if name == "store.read" and (payload or {}).get("module") == "agent/artifacts":
            return {"value": {}}
        return orig(name, payload, caller)
    return call


class SaveTest(unittest.TestCase):
    def test_bad_doc_kind_rejected(self):
        ctx, api = make_ctx()
        got = _route_save(ctx, {"path": "a.md", "doc_kind": "bogus"})
        self.assertEqual(got["code"], "bad_doc_kind")

    def test_bad_source_rejected(self):
        ctx, api = make_ctx()
        got = _route_save(ctx, {"path": "a.md", "source": "robot"})
        self.assertEqual(got["code"], "bad_source")

    def test_ticket_layer_text_with_index_merge(self):
        ctx, api = make_ctx(ticket_rec={"project": "p9"}, index=[{"path": "old.md"}])
        got = _route_save(ctx, {"path": "docs/a.md", "content": "文",
                                "layer": "ticket", "ticket": "t1"})
        self.assertEqual(got["path"], "projects/p9/tickets/t1/item/docs/a.md")
        self.assertEqual(got["size"], 3)
        self.assertEqual(got["doc_kind"], "artifact")
        self.assertEqual(got["source"], "llm")
        kinds = [e["kind"] for e in got["effects"]]
        self.assertEqual(kinds, ["write_text", "write"])
        entries = got["effects"][1]["value"]["entries"]
        self.assertEqual(len(entries), 2)

    def test_ticket_without_record_keeps_underscore(self):
        ctx, api = make_ctx(ticket_rec={})
        got = _route_save(ctx, {"path": "a.md", "layer": "ticket", "ticket": "t1"})
        self.assertEqual(got["path"], "projects/_/tickets/t1/item/a.md")

    def test_base64_content(self):
        ctx, api = make_ctx()
        got = _route_save(ctx, {"path": "a.bin", "content": "QUJDRA==",
                                "encoding": "base64", "layer": "public"})
        self.assertEqual(got["size"], 4)
        self.assertEqual(got["effects"][0]["kind"], "write_bytes")
        self.assertEqual(got["effects"][0]["hex"], "41424344")

    def test_project_layer_missing_scope(self):
        ctx, api = make_ctx()
        got = _route_save(ctx, {"path": "a.md", "layer": "project", "project": ""})
        self.assertEqual(got["code"], "missing_scope")
        self.assertEqual(got["error"], "缺项目")

    def test_ticket_layer_missing_ticket(self):
        ctx, api = make_ctx(ticket_rec={"project": "p"})
        got = _route_save(ctx, {"path": "a.md", "layer": "ticket", "ticket": ""})
        self.assertEqual(got["code"], "missing_scope")
        self.assertEqual(got["error"], "缺工单")

    def test_path_escape_rejected(self):
        ctx, api = make_ctx()
        got = _route_save(ctx, {"path": "../x", "layer": "public"})
        self.assertEqual(got["code"], "path_escape")
        self.assertEqual(got["status"], 403)

    def test_empty_path_rejected(self):
        ctx, api = make_ctx()
        self.assertEqual(_route_save(ctx, {"path": "", "layer": "public"})["code"], "bad_path")

    def test_default_index_path_without_config(self):
        ctx, api = make_ctx()
        api.cfg["artifacts.paths"] = {"public": "pub"}
        got = _route_save(ctx, {"path": "a.md", "layer": "public"})
        self.assertEqual(got["effects"][1]["path"], "index.yaml")


if __name__ == "__main__":
    unittest.main()
