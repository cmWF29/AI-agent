"""需求引擎路由层：整页取数、批处理、视图回退、代码文档索引。

路由层不碰真 HTTP：用假 ctx 把每条分支喂进去，重点不是"能跑"，而是
失败语义（bad_* / no_view / data_fail）和依赖分层必须成立。
"""
import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common import demand_engine as de  # noqa: E402


class ApiError(Exception):
    def __init__(self, msg, code="", status=400):
        super().__init__(msg)
        self.code = code
        self.status = status


class StubEngine:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def arun_callable(self, name, payload):
        self.calls.append((name, payload))
        val = self.responses.get(name, {})
        if callable(val):
            return val(payload)
        if isinstance(val, Exception):
            raise val
        return val

    def view_index(self):
        return [{"view": {"key": "home", "default": True}},
                {"view": {"key": "projects", "sections": [{"name": "list"}]}}]

    def view_spec(self, key):
        return {"key": key, "data": [{"as": "projects", "demand": "projects-list"},
                                     {"as": "stats", "demand": "stats", "params": {"p": "{projects.0.id}"}}]}

    def console(self):
        return {"click_machine": {"transitions": {"a": ["b", "c"], "b": ["a"]}}}

    def screens(self):
        return {"screens": ["manage"]}

    def inventory(self):
        return {"instances": 2}

    def items(self):
        return []

    def manifest(self):
        return {}

    def chrome(self):
        return {}


class StubStorage:
    def __init__(self, docs):
        self.docs = docs
        self.store = {}

    def own(self, _):
        return self

    def list_dir(self, rel=""):
        return []

    def stat_size(self, rel):
        return 0

    def stat_mtime(self, rel):
        return 0.0

    def json_read(self, rel, default=None):
        return self.store.get(rel, default)

    def json_write(self, rel, obj):
        self.store[rel] = obj

    def yaml_read(self, name, default=None):
        return self.docs if name == "code-docs.json" else self.store.get(name, default)

    def yaml_write(self, name, obj):
        self.store[name] = obj

    def repo_text(self, rel):
        return "text:" + rel


class Ctx:
    ApiError = ApiError

    def __init__(self, responses=None, docs=None):
        self.demand_engine = StubEngine(responses or {})
        self.storage = StubStorage(docs or {})


def run(coro):
    return asyncio.run(coro)


class RouteRunTest(unittest.TestCase):
    def test_run_accepts_valid_payload_and_defaults_input(self):
        ctx = Ctx({"probe": {"ok": True}})
        out = run(de._route_run(ctx, {"id": "probe"}))
        self.assertEqual(out, {"ok": True})
        self.assertEqual(ctx.demand_engine.calls[0], ("probe", {}))

    def test_run_rejects_blank_id(self):
        for payload in ({}, {"id": ""}, {"id": "  "}, {"id": 1}):
            with self.assertRaises(ApiError) as caught:
                run(de._route_run(ctx := Ctx(), payload))
            self.assertEqual(caught.exception.code, "bad_id")
            self.assertEqual(caught.exception.status, 400)

    def test_run_rejects_non_object_input(self):
        with self.assertRaises(ApiError) as caught:
            run(de._route_run(Ctx(), {"id": "probe", "input": []}))
        self.assertEqual(caught.exception.code, "bad_input")


class RouteBatchTest(unittest.TestCase):
    def test_batch_returns_each_item_and_isolates_failure(self):
        def boom(_):
            raise ApiError("坏了", code="bad_thing")

        ctx = Ctx({"good": {"n": 1}, "bad": boom})
        out = run(de._route_batch(ctx, {"calls": [
            {"id": "good", "input": {"x": 1}}, {"id": "bad"}]}))
        self.assertEqual(out["items"][0], {"ok": True, "result": {"n": 1}})
        self.assertFalse(out["items"][1]["ok"])
        self.assertEqual(out["items"][1]["code"], "bad_thing")
        self.assertEqual(out["items"][1]["error"], "坏了")

    def test_batch_rejects_non_list_and_tolerates_empty(self):
        with self.assertRaises(ApiError) as caught:
            run(de._route_batch(Ctx(), {"calls": {"id": "x"}}))
        self.assertEqual(caught.exception.code, "bad_calls")
        self.assertEqual(run(de._route_batch(Ctx(), {})), {"items": []})

    def test_batch_tolerates_non_dict_call_items(self):
        ctx = Ctx({"": {"ok": True}})
        out = run(de._route_batch(ctx, {"calls": [None, "x"]}))
        self.assertEqual(len(out["items"]), 2)


class ValueTest(unittest.TestCase):
    def test_dig_handles_dict_list_and_scalars(self):
        self.assertEqual(de._dig({"a": {"b": [1, 2]}}, "a.b.1"), 2)
        self.assertIsNone(de._dig({"a": {}}, "a.b"))
        self.assertEqual(de._dig({}, ""), {})
        self.assertIsNone(de._dig({"a": [1]}, "a.9"))
        self.assertIsNone(de._dig({"a": [1]}, "a.x"))
        self.assertIsNone(de._dig(7, "a"))
        self.assertIsNone(de._dig(None, "a"))

    def test_value_reads_route_data_cache_and_bare_sources(self):
        route = {"row": 9}
        data = {"projects": [{"id": "p1"}]}
        cache = {"stats": {"total": 3}}
        self.assertEqual(de._value("route.row", route, data, cache), 9)
        self.assertEqual(de._value("data.projects.0.id", route, data, cache), "p1")
        self.assertEqual(de._value("cache.stats.total", route, data, cache), 3)
        self.assertEqual(de._value("projects.0.id", route, data, cache), "p1")
        self.assertEqual(de._value("stats.total", route, data, cache), 3)
        self.assertIsNone(de._value("nope.x", route, data, cache))
        self.assertIsNone(de._value("route.nope", route, data, cache))

    def test_fill_handles_braces_bare_paths_containers_and_literals(self):
        route, data, cache = {"id": "p1"}, {"projects": [{"id": "p1"}]}, {}
        self.assertEqual(de._fill("{route.id}", route, data, cache), "p1")
        self.assertEqual(de._fill("{route.id|默认}", route, data, cache), "p1")
        self.assertEqual(de._fill("{route.nope}", route, data, cache), "")
        self.assertEqual(de._fill("data.projects.0.id", route, data, cache), "p1")
        self.assertEqual(de._fill("data.projects.9.id", route, data, cache), "")
        self.assertEqual(de._fill("literal text", route, data, cache), "literal text")
        self.assertEqual(de._fill(["a", "{route.id}"], route, data, cache), ["a", "p1"])
        self.assertEqual(de._fill({"k": "{route.id}"}, route, data, cache), {"k": "p1"})
        self.assertEqual(de._fill(5, route, data, cache), 5)
        self.assertIsNone(de._fill(None, route, data, cache))

    def test_refs_collects_dependencies_from_every_shape(self):
        self.assertEqual(de._refs("data.projects.0.id"), {"projects"})
        self.assertEqual(de._refs("cache.stats.total"), {"stats"})
        self.assertEqual(de._refs("{data.projects.0.id}"), {"projects"})
        self.assertEqual(de._refs("{route.id}"), set())
        self.assertEqual(de._refs("{data.a.x}{cache.b.y}"), {"a", "b"})
        self.assertEqual(de._refs("{data.}"), set())
        self.assertEqual(de._refs(["data.a.x", {"k": "cache.b.y"}]), {"a", "b"})
        self.assertEqual(de._refs(5), set())

    def test_unwrap_handles_nested_and_plain_shapes(self):
        self.assertEqual(de._unwrap({"demand": "x", "result": {"ok": True, "result": 7}}), 7)
        self.assertEqual(de._unwrap({"demand": "x", "result": {"ok": True}}), {"ok": True})
        self.assertEqual(de._unwrap({"result": 3}), {"result": 3})
        self.assertEqual(de._unwrap(5), 5)


class ViewRoutesTest(unittest.TestCase):
    def test_index_and_spec_routes_delegate(self):
        ctx = Ctx()
        self.assertEqual(run(de._route_views_index(ctx, {})),
                         [{"view": {"key": "home", "default": True}},
                          {"view": {"key": "projects", "sections": [{"name": "list"}]}}])
        self.assertEqual(run(de._route_view_spec(ctx, {"key": "projects"})),
                         StubEngine({}).view_spec("projects"))

    def test_resolve_known_view_runs_dependencies_in_layers(self):
        ctx = Ctx({"views-index": [{"view": {"key": "projects", "default": True}}],
                   "view-spec": {"key": "projects", "data": [
                       {"as": "projects", "demand": "projects-list"},
                       {"as": "stats", "demand": "stats", "params": {"p": "{projects.0.id}"}}]},
                   "projects-list": [{"id": "p1"}],
                   "stats": {"total": 2}})
        out = run(de._route_resolve(ctx, {"view": "projects"}))
        self.assertEqual(out["view"], "projects")
        self.assertEqual(out["data"]["projects"], [{"id": "p1"}])
        self.assertEqual(out["data"]["stats"], {"total": 2})
        self.assertEqual([c[0] for c in ctx.demand_engine.calls],
                         ["views-index", "view-spec", "projects-list", "stats"])

    def test_resolve_falls_back_to_default_for_unknown_view(self):
        ctx = Ctx({"views-index": [{"view": {"key": "home", "default": True}},
                                  {"view": {"key": "projects"}}, {}],
                   "view-spec": {"key": "home", "data": []}, "home": {"ok": True}})
        out = run(de._route_resolve(ctx, {"view": "old-bookmark"}))
        self.assertEqual(out["view"], "home")
        self.assertEqual(out["fallback_from"], "old-bookmark")

    def test_resolve_raises_when_no_view_can_be_resolved(self):
        ctx = Ctx({"views-index": [], "view-spec": {}})
        with self.assertRaises(ApiError) as caught:
            run(de._route_resolve(ctx, {"view": "x"}))
        self.assertEqual(caught.exception.code, "no_view")
        self.assertEqual(caught.exception.status, 404)

    def test_resolve_returns_empty_state_for_missing_required_params(self):
        ctx = Ctx({"views-index": [{"view": {"key": "projects"}}],
                   "view-spec": {"key": "projects", "require": ["project"], "data": []}})
        out = run(de._route_resolve(ctx, {"view": "projects"}))
        self.assertEqual(out["missing"], ["project"])
        self.assertEqual(out["data"], {})

    def test_resolve_rejects_non_object_params(self):
        with self.assertRaises(ApiError) as caught:
            run(de._route_resolve(Ctx(), {"view": "x", "params": [1]}))
        self.assertEqual(caught.exception.code, "bad_params")

    def test_resolve_only_filter_keeps_requested_sources(self):
        ctx = Ctx({"views-index": [{"view": {"key": "projects"}}],
                   "view-spec": {"key": "projects", "data": [
                       {"as": "a", "demand": "a"}, {"as": "b", "demand": "b"},
                       {"as": "c", "demand": "c", "cache": "cached"}]},
                   "a": {"v": 1}, "b": {"v": 2}, "c": {"v": 3}})
        out = run(de._route_resolve(ctx, {"view": "projects", "only": ["b", "c"]}))
        self.assertEqual(out["data"], {"b": {"v": 2}, "c": {"v": 3}})
        self.assertEqual(out["cache"], {"cached": {"v": 3}})

    def test_resolve_wraps_shell_and_views_when_requested(self):
        ctx = Ctx({"views-index": [{"view": {"key": "projects"}}],
                   "console-shell": {"brand": "Hive"},
                   "view-spec": {"key": "projects", "data": []}})
        out = run(de._route_resolve(ctx, {"view": "projects", "shell": True}))
        self.assertEqual(out["shell"], {"brand": "Hive"})
        self.assertEqual(len(out["views"]), 1)

    def test_resolve_breaks_dependency_cycle_by_declaration_order(self):
        ctx = Ctx({"views-index": [{"view": {"key": "projects"}}],
                   "view-spec": {"key": "projects", "data": [
                       {"as": "a", "demand": "a", "params": {"x": "{data.b.0.id}"}},
                       {"as": "b", "demand": "b", "params": {"x": "{data.a.0.id}"}}]},
                   "a": [{"id": "a1"}], "b": [{"id": "b1"}]})
        out = run(de._route_resolve(ctx, {"view": "projects"}))
        self.assertIn("a", out["data"])
        self.assertIn("b", out["data"])

    def test_resolve_raises_data_fail_with_source_name(self):
        ctx = Ctx({"views-index": [{"view": {"key": "projects"}}],
                   "view-spec": {"key": "projects", "data": [{"as": "bad", "demand": "bad"}]},
                   "bad": RuntimeError("down")})
        with self.assertRaises(ApiError) as caught:
            run(de._route_resolve(ctx, {"view": "projects"}))
        self.assertEqual(caught.exception.code, "data_fail")
        self.assertEqual(caught.exception.status, 502)
        self.assertIn("bad", str(caught.exception))

    def test_resolve_unknown_view_without_any_default_uses_first(self):
        ctx = Ctx({"views-index": [{"view": {"key": "projects"}}],
                   "view-spec": {"key": "projects", "data": []}})
        out = run(de._route_resolve(ctx, {}))
        self.assertEqual(out["view"], "projects")


class CodeDocsTest(unittest.TestCase):
    DOCS = {"total": 3, "generated": "2026-11-25", "groups": [
        {"docs": [{"source": "ai_new/a.py", "doc": "docs/a.md", "kind": "python", "symbols": 2, "hash": "h"},
                  {"source": "ai_new/sub/b.py", "doc": "docs/b.md"}]},
        {"docs": [{"source": "scripts/c.py", "doc": "docs/c.md"}]},
        {"docs": [{"bad": True}, "x"]},
    ]}

    def test_flatten_filters_invalid_groups_and_docs(self):
        rows = de._all_docs(self.DOCS)
        self.assertEqual([r["source"] for r in rows], ["ai_new/a.py", "ai_new/sub/b.py", "scripts/c.py"])
        self.assertEqual(de._all_docs({}), [])
        self.assertEqual(de._all_docs({"groups": ["bad", {"docs": [{"source": "x"}]}]}), [{"source": "x"}])

    def test_path_nodes_splits_dirs_and_files(self):
        nodes = de._path_nodes(self.DOCS)
        self.assertEqual(nodes[0]["label"], "ai_new")
        self.assertEqual(nodes[0]["badge"], "2")
        self.assertIn("scripts", [n["label"] for n in nodes])
        files = de._path_nodes(self.DOCS, "ai_new")
        leaf = next(n for n in files if n.get("name") == "a.py")
        self.assertEqual(leaf["path"], "源码 ai_new/a.py · 文档 docs/a.md")
        self.assertEqual(de._path_nodes(self.DOCS, "missing"), [])

    def test_find_doc_matches_source_or_doc_path(self):
        self.assertEqual(de._find_doc(self.DOCS, "docs/b.md")["source"], "ai_new/sub/b.py")
        self.assertIsNone(de._find_doc(self.DOCS, "nope"))

    def test_code_docs_route_returns_root_and_group(self):
        ctx = Ctx(docs=self.DOCS)
        root = run(de._route_code_docs(ctx, {}))
        self.assertEqual(root["total"], 3)
        self.assertEqual(root["groups"][0]["label"], "ai_new")
        sub = run(de._route_code_docs(ctx, {"group": "ai_new"}))
        self.assertEqual(sub["label"], "ai_new")
        self.assertEqual(sub["count"], len(sub["children"]))

    def test_code_docs_read_returns_text_or_error(self):
        ctx = Ctx(docs=self.DOCS)
        found = run(de._route_code_docs_read(ctx, {"path": "ai_new/a.py"}))
        self.assertTrue(found["ok"])
        self.assertEqual(found["source_text"], "text:ai_new/a.py")
        missing = run(de._route_code_docs_read(ctx, {"path": "nope"}))
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"], "路径不在源码文档索引里")

    def test_click_machine_counts_edges_from_transitions(self):
        out = run(de._route_click_machine(Ctx(), {}))
        self.assertEqual(out["click_machine"]["edges"], 3)
        self.assertEqual(out["screen_machine"], {"screens": ["manage"]})
        self.assertEqual(out["inventory"], {"instances": 2})

    def test_noop_returns_none(self):
        self.assertIsNone(run(de._noop()))


class SetupTest(unittest.TestCase):
    def test_dispatch_delegates_to_engine(self):
        class Engine:
            def __init__(self):
                self.calls = []

            def dispatch(self, hook, envelope):
                self.calls.append((hook, envelope))
                return ["ran"]

        ctx = type("Ctx", (), {})()
        ctx.demand_engine = Engine()
        self.assertEqual(de.dispatch(ctx, "x.happened", {"n": 1}), ["ran"])
        self.assertEqual(ctx.demand_engine.calls, [("x.happened", {"n": 1})])

    def test_setup_registers_every_demand_engine_route(self):
        class Api:
            def __init__(self):
                self.routes = {}

            def register(self, name, fn, desc, module=""):
                self.routes[name] = fn

        class Ctx2(Ctx):
            def __init__(self):
                super().__init__()
                self.api = Api()

        ctx = Ctx2()
        engine = de.setup(ctx)
        self.assertEqual(set(ctx.api.routes), {
            "demand_engine.run", "demand_engine.batch", "demand_engine.resolve",
            "demand_engine.views_index", "demand_engine.view_spec", "demand_engine.list",
            "demand_engine.manifest", "demand_engine.console", "demand_engine.code_docs_read",
            "demand_engine.code_docs", "demand_engine.click_machine", "demand_engine.chrome"})
        self.assertEqual(engine.items(), [])


if __name__ == "__main__":
    unittest.main()

