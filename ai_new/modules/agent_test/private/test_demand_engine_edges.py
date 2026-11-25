"""需求引擎/需求语言边界：装载缓存、视图地图、幂等派发、失败收口。"""
import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.demand_engine.private import _engine, _lang  # noqa: E402


class ApiError(Exception):
    def __init__(self, msg, code="", status=400):
        super().__init__(msg)
        self.code = code
        self.status = status


class Api:
    def __init__(self):
        self.routes = {}
        self.calls = []

    def call(self, route, payload, caller=None):
        self.calls.append(("call", route, payload))
        fn = self.routes.get(route)
        if isinstance(fn, Exception):
            raise fn
        if callable(fn):
            return fn(payload)
        if fn is not None:
            return fn
        if route == "trace.open":
            return {"span": "s1"}
        if route == "store.claim":
            return {"claimed": True, "status": "claimed"}
        if route == "codec.digest":
            return {"hex": "abc"}
        return {"ok": True}

    async def acall(self, route, payload, caller=None):
        fn = self.routes.get(route)
        if callable(fn) and asyncio.iscoroutinefunction(fn):
            return await fn(payload)
        return self.call(route, payload, caller)

    def notify(self, route, payload, caller=None):
        self.calls.append(("notify", route, payload))
        fn = self.routes.get(route)
        if isinstance(fn, Exception):
            raise fn
        return fn if fn is not None else {"ok": True}


class Codec:
    def __init__(self, fail=False):
        self.fail = fail

    def json_encode(self, payload):
        if self.fail:
            raise ValueError("坏")
        return {"text": '{"seq":1}'}


class Clock:
    def __init__(self, ts=100.0):
        self.ts = ts

    def now(self):
        return {"ts": self.ts}


class Runtime:
    def __init__(self, fail=False):
        self.fail = fail
        self.put = []

    def stream_clear(self, key):
        if self.fail:
            raise OSError("no")

    def stream_put(self, key, text):
        if self.fail:
            raise OSError("no")
        self.put.append((key, text))


class Storage:
    def __init__(self, docs=None, own_raise=False, real_raise=False, junk=False):
        self.docs = docs or {}
        self.own_raise = own_raise
        self.real_raise = real_raise
        self.junk = junk
        self.root = "root-%d" % id(self)
        self.writes = []

    def own(self, _):
        if self.own_raise:
            raise AttributeError("no storage")
        return self

    def _real(self, _):
        if self.real_raise:
            raise KeyError("no base")
        return "base-" + str(id(self))

    def list_dir(self, rel=""):
        names = [k.split("/")[-1] for k in self.docs if k.startswith("demands/")]
        if self.junk:
            names.append("readme.txt")
        return sorted(names)

    def stat_size(self, rel):
        return len(str(self.docs.get(rel) or {}))

    def stat_mtime(self, rel):
        return 1.0

    def yaml_read(self, rel, default=None):
        return self.docs.get(rel, default)

    def yaml_write(self, rel, obj):
        self.docs[rel] = obj
        self.writes.append((rel, obj))


class Ctx:
    ApiError = ApiError

    def __init__(self, docs=None, **kw):
        self.storage = Storage(docs, **kw)
        self.api = Api()
        self.codec = Codec()
        self.clock = Clock()
        self.runtime = Runtime()
        self.demand_engine = None


def rec(**kw):
    base = {"enabled": True, "on": ["hook.x"], "do": []}
    base.update(kw)
    return base


def docs(*records):
    return {("demands/%s.yaml" % rid): r for rid, r in records}


class HelperTest(unittest.TestCase):
    def test_store_base_root_real_and_fail(self):
        self.assertTrue(_engine._store_base(Storage()).startswith("root-"))
        plain = object()

        class Real:
            def _real(self, _):
                return "p"
        self.assertEqual(_engine._store_base(Real()), "p")
        self.assertEqual(_engine._store_base(plain), "")
        real = Real()

        def boom(_):
            raise KeyError("x")
        real._real = boom
        self.assertEqual(_engine._store_base(real), "")

    def test_slug_and_canon(self):
        self.assertEqual(_engine._slug(None), "x")
        self.assertEqual(_engine._slug("a b＋c"), "abc")
        self.assertEqual(_engine._slug("中/文"), "中_文")
        self.assertEqual(_engine._canon({"b": [1, "s"], "a": ("t",)}),
                         '{a:["t"],b:[1,"s"]}')
        self.assertEqual(_engine._canon(3), "3")

    def test_as_hooks(self):
        self.assertEqual(_engine._as_hooks("a"), ["a"])
        self.assertEqual(_engine._as_hooks(["a", 1]), ["a", "1"])
        self.assertEqual(_engine._as_hooks(None), [])


class LoadTest(unittest.TestCase):
    def test_signature_cache_reload_and_junk(self):
        ctx = Ctx(docs(("a", rec(view={"key": "home"})), ("z", rec())))
        eng = _engine.Engine(ctx)
        self.assertEqual([r["id"] for r in eng.items()], ["a", "z"])
        self.assertEqual(eng._sig, (("a.yaml", len(str(ctx.storage.docs["demands/a.yaml"])), 1.0),
                                    ("z.yaml", len(str(ctx.storage.docs["demands/z.yaml"])), 1.0)))
        eng.reload()
        eng._load()
        self.assertIsNotNone(eng._cache)

    def test_signature_without_storage_returns_none(self):
        eng = _engine.Engine(Ctx(own_raise=True))
        self.assertIsNone(eng._signature())

    def test_parse_cache_clear_when_huge(self):
        ctx = Ctx(docs(("a", rec())))
        _engine._PARSE_CACHE.clear()
        for i in range(2002):
            _engine._PARSE_CACHE[("k", str(i))] = {}
        eng = _engine.Engine(ctx)
        eng._load()
        self.assertLess(len(_engine._PARSE_CACHE), 10)

    def test_store_base_and_signature_junk_names(self):
        ctx = Ctx(docs(("a", rec()), ("b", rec())), junk=True)
        eng = _engine.Engine(ctx)
        self.assertEqual(len(eng._signature()), 2)
        self.assertEqual([r["id"] for r in eng._load()], ["a", "b"])


class ViewsTest(unittest.TestCase):
    def setUp(self):
        self.ctx = Ctx(docs(
            ("a", rec(title="甲", tags=["ui"], callable=True, touch=["b"],
                      view={"key": "home", "screen_label": "首页", "subheading": "看板",
                            "parent": {"view": "projects"},
                            "menu": {"key": "nav-home", "label": "首页", "short": "家",
                                     "group": {"name": "基础", "order": 1},
                                     "tab": {"order": 2}, "mobile": False},
                            "actions": [
                                {"modal": "f1", "label": "新建"},
                                {"view": "projects"},
                                {"view": {"key": "detail"}, "label": "详情"},
                                {"demand": "projects-archive"},
                                {"demand": "run-me", "label": "运行"},
                                {"confirm": "yes", "label": "确认"},
                                {"flash": "ok", "label": "提示"},
                                {"label": "不计"},
                            ],
                            "sections": [
                                {"actions": [{"demand": "x", "label": "动作"}],
                                 "submit": {"modal": "f2", "label": "提交"},
                                 "on_click": {"modal": "f3"}},
                            ],
                            "data": [{"demand": "b", "as": "rows"}]},
                      do=[{"call": "cap.one", "with": {"x": {"lit": 1}}},
                          {"send": "cap.two"}],
                      expect={"calls": ["cap.one", "cap.other"], "promise": "p",
                              "payload": {"x": 1}})),
            ("b", rec(title="乙", tags=[], view={
                "key": "projects", "menu": "项目",
                "actions": [{"view": "home"}, {"view": {"view": "detail"}}]},
                expect={"calls": ["x"]})),
            ("c", rec(view={"key": "detail", "heading": "{x}", "crumb": ["{bad}", "静态"]})),
            ("d", rec(view={"forms": [{"name": "f"}]})),
            ("e", rec(title="戊", view={"key": "empty", "menu": {"label": "空"}}, tags=["core"])),
        ))
        self.eng = _engine.Engine(self.ctx)

    def test_items(self):
        got = self.eng.items()
        self.assertEqual(got[0]["on"], ["hook.x"])
        self.assertEqual(got[0]["do"], ["cap.one", "cap.two"])
        self.assertEqual(got[1]["tags"], [])

    def test_view_index_forms_and_slim(self):
        idx = self.eng.view_index()
        keys = [x["view"].get("key") for x in idx]
        self.assertIn("home", keys)
        self.assertIn("projects", keys)
        self.assertTrue(any("forms" in x["view"] for x in idx))
        home = next(x["view"] for x in idx if x["view"].get("key") == "home")
        self.assertEqual(home["parent"], {"view": "projects"})
        self.assertEqual(home["menu"]["label"], "首页")
        self.assertNotIn("heading", home)

    def test_view_spec_and_missing(self):
        self.assertEqual(self.eng.view_spec("home")["screen_label"], "首页")
        self.assertEqual(self.eng.view_spec(None), {"forms": [{"name": "f"}]})
        with self.assertRaises(ApiError) as caught:
            self.eng.view_spec("nope")
        self.assertEqual(caught.exception.code, "no_view")

    def test_manifest(self):
        got = self.eng.manifest()
        self.assertEqual(got["count"], 5)
        self.assertGreaterEqual(got["steps"], 2)
        a = next(x for x in got["items"] if x["id"] == "a")
        self.assertTrue(a["callable"])
        self.assertEqual(a["drift"], ["cap.other", "cap.two"])
        self.assertEqual(a["expect_calls"], ["cap.one", "cap.other"])
        b = next(x for x in got["items"] if x["id"] == "b")
        self.assertFalse(b["callable"])
        self.assertEqual(b["drift"], ["x"])
        d_steps = [n for n in got["nodes"] if n["label"] == "d"][0]["children"]
        self.assertEqual(d_steps, [])
        self.assertIn("ui", [g["sub"] for g in got["groups"]])
        self.assertEqual(got["nodes"][0]["badge"], "可调")

    def test_manifest_non_structured_steps_and_tags(self):
        ctx = Ctx(docs(("a", rec(do=["raw", {"send": "s"}]))), junk=True)
        got = _engine.Engine(ctx).manifest()
        self.assertEqual(got["items"][0]["steps"], 2)
        self.assertEqual(got["nodes"][0]["children"][0]["name"], "raw")
        self.assertEqual(got["nodes"][0]["children"][0]["path"], "非结构语句")
        self.assertEqual(got["groups"][0]["sub"], "core")

    def test_console(self):
        shell = self.eng.console()
        menu = shell["menus"][0]
        self.assertEqual(menu["key"], "nav-home")
        self.assertEqual(menu["short"], "家")
        self.assertEqual(menu["group"], "基础")
        self.assertEqual(menu["tab_order"], 2)
        self.assertFalse(menu["mobile"])
        self.assertEqual(menu["demand"], "a")

    def test_console_skips_non_dict_and_blank(self):
        ctx = Ctx(docs(
            ("a", rec(view={"menu": "项目", "key": "a"})),
            ("b", rec(view={"menu": {"label": "没有 key"}})),
            ("c", rec(view={})),
        ))
        got = _engine.Engine(ctx).console()["menus"]
        self.assertEqual([m["key"] for m in got], [])
        self.assertEqual(got, [])

    def test_screens_map(self):
        got = self.eng.screens()
        keys = {p["key"] for p in got["pages"]}
        self.assertIn("view:home", keys)
        self.assertIn("view:projects", keys)
        self.assertIn("view:detail", keys)
        self.assertIn("overlay:form:f1", [s["id"] for s in got["states"]])
        self.assertIn("overlay:sidebar", [s["id"] for s in got["states"]])
        self.assertTrue(any(c["effect"] == "只改本页显示" for c in got["controls"]))
        self.assertTrue(any(c["effect"].startswith("跳到") for c in got["controls"]))
        self.assertTrue(got["routes"])
        labels = {p["key"]: p["label"] for p in got["pages"]}
        self.assertEqual(labels["view:home"], "首页")
        self.assertEqual(labels["view:projects"], "项目")
        self.assertEqual(labels["view:detail"], "静态")
        self.assertFalse(next(p for p in got["pages"] if p["key"] == "view:home")["main"].startswith("{"))

    def test_screens_duplicate_and_parents(self):
        got = self.eng.screens()
        sigs = [(r["from_key"], r["to_key"], r["by"]) for r in got["routes"]]
        self.assertEqual(len(sigs), len(set(sigs)))
        self.assertTrue(any(r["to_key"] == "view:projects" for r in got["routes"]))

    def test_inventory_and_chrome(self):
        self.ctx.storage.docs["ui-inventory.json"] = {"x": 1}
        self.ctx.storage.docs["console.yaml"] = {"brand": {"name": "b"}, "login": {"title": "t"}}
        self.assertEqual(self.eng.inventory(), {"x": 1})
        self.assertEqual(self.eng.chrome(), {"brand": {"name": "b"}, "login": {"title": "t"}})


class EnableTest(unittest.TestCase):
    def test_toggle_existing_and_missing(self):
        ctx = Ctx(docs(("a", rec()), ("b", rec())), junk=True)
        eng = _engine.Engine(ctx)
        self.assertEqual(eng.set_enabled("a", False), {"id": "a", "enabled": False})
        self.assertFalse(ctx.storage.docs["demands/a.yaml"]["enabled"])
        self.assertIn("demands/a.yaml", [w[0] for w in ctx.storage.writes])
        with self.assertRaises(ApiError) as caught:
            eng.set_enabled("zzz", True)
        self.assertEqual(caught.exception.code, "no_demand")


class NotifyTest(unittest.TestCase):
    def _ctx(self):
        ctx = Ctx(docs(
            ("a", rec(tags=["write"], touch=["b", "nope"], view={"key": "v"})),
            ("b", rec(view={"key": "other", "data": [{"demand": "a", "as": "rows"}]})),
            ("c", rec(view={"key": "third", "data": [{"demand": "a"}]})),
            ("d", rec(view={"key": "d", "data": [{"demand": "b", "as": "x"}]})),
        ))
        return ctx

    def test_no_touch_no_hits(self):
        ctx = self._ctx()
        eng = _engine.Engine(ctx)
        rec_a = next(r for r in eng._load() if r["id"] == "a")
        rec_d = next(r for r in eng._load() if r["id"] == "d")
        eng.notify_write("a", rec_d)
        self.assertEqual(eng._badge_seq, 0)
        eng._badge_items = []
        eng._views_using({"zzz"})
        eng.notify_write("a", {"touch": ["zzz"]})
        self.assertEqual(eng._badge_seq, 0)
        self.assertEqual(rec_a["touch"], ["b", "nope"])

    def test_hits_publish_and_dedupe(self):
        ctx = self._ctx()
        eng = _engine.Engine(ctx)
        rec_a = next(r for r in eng._load() if r["id"] == "a")
        eng.notify_write("a", rec_a)
        self.assertEqual(eng._badge_seq, 1)
        self.assertEqual(ctx.runtime.put[0][0], "console.invalidate")
        eng.notify_write("a", rec_a)
        self.assertEqual(eng._badge_seq, 1)
        ctx.clock.ts = 200
        eng.notify_write("a", rec_a)
        self.assertEqual(eng._badge_seq, 2)
        self.assertEqual(len(eng._badge_items), 2)

    def test_publish_no_runtime_and_failures(self):
        ctx = self._ctx()
        eng = _engine.Engine(ctx)
        rec_a = next(r for r in eng._load() if r["id"] == "a")
        ctx.runtime = None
        eng.notify_write("a", rec_a)
        self.assertEqual(eng._badge_seq, 1)
        ctx.runtime = Runtime()
        ctx.codec = Codec(fail=True)
        eng.notify_write("a", rec_a)
        self.assertEqual(len(ctx.runtime.put), 0)
        ctx.codec = Codec()
        ctx.runtime = Runtime(fail=True)
        eng.notify_write("a", rec_a)
        self.assertEqual(len(ctx.runtime.put), 0)

    def test_badge_ring_trims(self):
        ctx = self._ctx()
        eng = _engine.Engine(ctx)
        rec_a = next(r for r in eng._load() if r["id"] == "a")
        for i in range(35):
            ctx.clock.ts = 100 + i * 2
            eng.notify_write("a", rec_a)
        self.assertEqual(len(eng._badge_items), 30)
        self.assertEqual(eng._badge_seq, 35)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.ctx = Ctx(docs(
            ("a", rec(callable=True, do=[{"call": "cap.ok"}])),
            ("b", rec(callable=True, do=[])),
            ("c", rec(callable=False)),
            ("d", rec(enabled=False, callable=True)),
            ("e", rec(callable=True, tags=["write"], touch=["b"],
                      do=[{"call": "cap.bad"}, {"call": "cap.ok"}])),
            ("f", rec(callable=True, do=[{"send": "cap.send"}])),
            ("g", rec(callable=True, do=[{"call": "cap.list"}])),
            ("h", rec(callable=True, do=[{"call": "demand_engine.run",
                                         "with": {"id": {"lit": "a"}, "input": {"lit": {"x": 1}}}}])),
        ))
        self.ctx.api.routes.update({
            "cap.ok": {"ok": True, "v": 1},
            "cap.bad": {"ok": False, "code": "bad_thing", "error": "坏", "status": 409},
            "cap.list": [1, 2],
            "cap.send": {"ok": True},
        })
        self.eng = _engine.Engine(self.ctx)
        self.ctx.demand_engine = self.eng
        # b 需要一页供失效反查
        self.ctx.storage.docs["demands/b.yaml"]["view"] = {"key": "v",
                                                          "data": [{"demand": "b", "as": "x"}]}
        self.eng.reload()

    def test_callable_shapes(self):
        self.assertEqual(self.eng.run_callable("a")["result"], {"ok": True, "v": 1})
        self.assertEqual(self.eng.run_callable("g")["result"], [1, 2])
        self.assertTrue(self.eng.run_callable("g")["ok"])
        self.assertEqual(self.eng.run_callable("b")["code"], "empty")
        self.assertEqual(self.eng.run_callable("d")["code"], "disabled")
        self.assertEqual(self.eng.run_callable("h")["result"]["result"], {"ok": True, "v": 1})

    def test_callable_not_callable_and_missing(self):
        with self.assertRaises(ApiError) as caught:
            self.eng.run_callable("c")
        self.assertEqual(caught.exception.code, "not_callable")
        with self.assertRaises(ApiError) as caught:
            self.eng.run_callable("zzz")
        self.assertEqual(caught.exception.code, "no_demand")

    def test_callable_bad_step_reports_failure_and_notifies(self):
        got = self.eng.run_callable("e")
        self.assertFalse(got["ok"])
        self.assertEqual(got["failed"]["call"], "cap.bad")
        self.assertEqual(got["failed"]["code"], "bad_thing")
        self.assertEqual(self.eng._badge_items[-1]["demand"], "e")

    def test_callable_route_exception_is_recorded(self):
        self.ctx.api.routes["cap.ok"] = ValueError("boom")
        got = self.eng.run_callable("a")
        self.assertFalse(got["ok"])
        self.assertEqual(got["calls"], ["cap.ok"])
        self.assertTrue(got["failed"]["error"].startswith("ValueError"))

    def test_send_only_counts_as_no_call(self):
        got = self.eng.run_callable("f")
        self.assertEqual(got["calls"], ["cap.send"])
        self.assertEqual(got["result"], {"ok": True})

    def test_run_callable_exception_closure(self):
        with self.assertRaises(ApiError) as caught:
            self.eng.run_callable("c")
        self.assertEqual(caught.exception.code, "not_callable")
        self.assertIn("trace.close", [c[1] for c in self.ctx.api.calls])
        close = [c for c in self.ctx.api.calls if c[1] == "trace.close"][-1]
        self.assertEqual(close[2]["status"], "error")
        self.assertEqual(close[2]["code"], "not_callable")

    def test_span_failures_degrade(self):
        self.ctx.api.routes["trace.open"] = RuntimeError("trace down")
        self.ctx.api.routes["trace.close"] = RuntimeError("trace down")
        self.assertEqual(self.eng.run_callable("a")["ok"], True)
        self.assertEqual(self.eng.dispatch("hook.x", {})[0]["demand"], "a")

    def test_dispatch(self):
        got = self.eng.dispatch("hook.x", {"v": 1})
        self.assertEqual(got[0]["demand"], "a")
        self.assertEqual([c for c in self.ctx.api.calls if c[1] == "store.settle"][0][2]["status"], "done")

    def test_dispatch_skip_and_failure(self):
        self.ctx.api.routes["store.claim"] = {"claimed": False, "status": "running", "reused": True}
        got = self.eng.dispatch("hook.x", {"v": 1})
        self.assertTrue(got[0]["skipped"])
        self.assertTrue(got[0]["reused"])
        self.ctx.api.routes["store.claim"] = {"claimed": True}
        self.ctx.api.routes["store.settle"] = RuntimeError("ledger")
        self.ctx.api.routes["cap.ok"] = {"ok": False, "code": "bad"}
        got = self.eng.dispatch("hook.x", None)
        self.assertFalse(got[0]["ok"])
        self.assertEqual(got[0]["code"], "bad")

    def test_dispatch_degraded_and_digest_fallback(self):
        self.ctx.api.routes["store.claim"] = RuntimeError("ledger")
        self.ctx.api.routes["codec.digest"] = RuntimeError("no codec")
        got = self.eng.dispatch("hook.x", {})
        self.assertEqual(got[0]["demand"], "a")

    def test_dispatch_ignores_other_hooks(self):
        got = self.eng.dispatch("hook.other", {})
        self.assertEqual(got, [])

    def test_async_callable_and_dispatch(self):
        async def go():
            self.assertEqual((await self.eng.arun_callable("a"))["ok"], True)
            self.assertEqual((await self.eng.arun_callable("b"))["code"], "empty")
            self.assertEqual((await self.eng.arun_callable("d"))["code"], "disabled")
            got = await self.eng.adispatch("hook.x", {"v": 1})
            self.assertEqual(got[0]["demand"], "a")
            self.assertEqual((await self.eng.arun_callable("e"))["failed"]["code"], "bad_thing")
            await self.eng.arun_callable("f")
            await self.eng.arun_callable("h")
        self.ctx.api.routes["store.claim"] = {"claimed": True}
        asyncio.run(go())

    def test_async_not_callable_missing(self):
        async def go():
            with self.assertRaises(ApiError):
                await self.eng.arun_callable("c")
            with self.assertRaises(ApiError):
                await self.eng.arun_callable("zzz")
        asyncio.run(go())

    def test_async_skip_and_settle_error(self):
        async def go():
            self.ctx.api.routes["store.claim"] = {"claimed": False, "status": "running"}
            got = await self.eng.adispatch("hook.x", {})
            self.assertTrue(got[0]["skipped"])
            self.ctx.api.routes["store.claim"] = {"claimed": True}
            self.ctx.api.routes["store.settle"] = RuntimeError("ledger")
            self.ctx.api.routes["cap.ok"] = {"ok": False, "code": "bad"}
            got = await self.eng.adispatch("hook.x", {})
            self.assertFalse(got[0]["ok"])
        asyncio.run(go())

    def test_async_dispatch_span_error(self):
        self.ctx.api.routes["trace.open"] = RuntimeError("trace down")

        async def boom(_payload=None):
            raise ValueError("x")

        self.ctx.api.routes["store.claim"] = boom
        async def go():
            with self.assertRaises(ValueError):
                await self.eng.adispatch("hook.x", {})
        asyncio.run(go())


class LangTest(unittest.TestCase):
    def test_eval_expr_shapes(self):
        self.assertEqual(_lang.eval_expr([1, {"lit": 2}], {}), [1, 2])
        self.assertEqual(_lang.eval_expr({"a": {"get": "a.b"}}, {"a": {"b": 3}}), {"a": 3})
        self.assertEqual(_lang.eval_expr("plain", {}), "plain")
        self.assertEqual(_lang.eval_expr(1, {}), 1)
        with self.assertRaises(ValueError):
            _lang.eval_expr("x", {}, 13)
        with self.assertRaises(ValueError):
            _lang.eval_expr({"op": "+", "a": 1, "b": 2}, {})

    def test_get_paths(self):
        scope = {"a": {"b": [1, 2]}, "s": "str"}
        self.assertEqual(_lang._get(scope, "a.b.1"), 2)
        self.assertIsNone(_lang._get(scope, "a.b.x"))
        self.assertIsNone(_lang._get(scope, "a.b.9"))
        self.assertIsNone(_lang._get(scope, "s.x"))

    def test_routes_of(self):
        tree = {"call": "a", "send": "b", "x": [{"call": 1, "nested": {"send": "c"}}]}
        self.assertEqual(_lang.routes_of(tree), ["a", "b", "c"])

    def test_run_required_and_recovery(self):
        class Api:
            def __init__(self):
                self.calls = []
                self.routes = {}

            def call(self, route, payload, caller=None):
                self.calls.append((route, payload))
                v = self.routes.get(route)
                if isinstance(v, Exception):
                    raise v
                return v

            def notify(self, route, payload, caller=None):
                self.calls.append(("send:" + route, payload))
                return self.routes.get(route, {"ok": True})

        api = Api()
        api.routes.update({"a": {"ok": False, "code": "no"}, "apply": {"ok": True}})
        rows = _lang.run([{"call": "a", "required": True}, {"call": "runtime.apply"}],
                         {"event": {"e": 1}}, api, None, "d")
        self.assertEqual([r["call"] for r in rows], ["a", "runtime.apply"])
        self.assertFalse(rows[0]["ok"])
        self.assertEqual(rows[0]["code"], "no")
        rows = _lang.run([{"call": "a", "required": True}, {"call": "b"}], {}, api, None)
        self.assertEqual(len(rows), 1)
        rows = _lang.run([{"call": "a"}, {"call": "b"}], {}, api, None)
        self.assertEqual(len(rows), 2)

    def test_run_exceptions_and_unknown(self):
        class Api:
            def call(self, route, payload, caller=None):
                if route == "boom":
                    raise ValueError("x")
                return {"ok": True}

        rows = _lang.run([{"call": "boom"}, {"call": "b"}], {}, Api(), None, "d")
        self.assertEqual(len(rows), 1)
        self.assertIn("ValueError", rows[0]["error"])
        rows = _lang.run(["raw"], {}, Api(), None, "d")
        self.assertEqual(len(rows), 1)
        rows = _lang.run([{"noop": 1}], {}, Api(), None, "d")
        self.assertEqual(len(rows), 1)

    def test_mark_status(self):
        out = []
        self.assertTrue(_lang._mark(out, "d", "r", {"ok": True}))
        self.assertTrue(_lang._mark(out, "d", "r", [1], send=True))
        self.assertTrue(out[-1]["send"])
        ok = _lang._mark(out, "d", "r", {"ok": False, "status": None})
        self.assertFalse(ok)
        self.assertEqual(out[-1]["status"], None)

    def test_run_one_nested_and_as(self):
        class Eng:
            def run_callable(self, rid, inp):
                return {"ok": True, "id": rid, "inp": inp}

        class Ctx:
            demand_engine = Eng()

        class Api:
            def call(self, route, payload, caller=None):
                return {"ok": True, "route": route, "payload": payload}

            def notify(self, route, payload, caller=None):
                return {"ok": False, "code": "reject"}

        stmts = [
            {"call": "cap", "with": {"x": {"get": "event.e"}, "y": {"lit": 2}}, "as": "v"},
            {"call": "demand_engine.run", "with": {"id": {"lit": "n"}, "input": {"lit": {"a": 1}}}},
            {"send": "evt", "with": {"z": {"get": "v"}}},
            {"noop": 1},
        ]
        scope = {"event": {"e": 1}, "caller": "c"}
        rows = _lang.run(stmts, scope, Api(), Ctx(), "d")
        self.assertEqual(rows[0]["result"]["payload"], {"e": 1, "x": 1, "y": 2})
        self.assertEqual(scope["v"]["route"], "cap")
        self.assertEqual(rows[1]["result"]["id"], "n")
        self.assertEqual(rows[2]["call"], "evt")
        self.assertEqual(rows[2]["code"], "reject")
        self.assertIn("noop", rows[3]["error"])

    def test_arun_failure_and_recovery(self):
        class Api:
            async def acall(self, route, payload, caller=None):
                v = {"a": {"ok": False, "code": "no"}, "apply": {"ok": True},
                     "boom": ValueError("x")}.get(route, {"ok": True})
                if isinstance(v, Exception):
                    raise v
                return v

            def notify(self, route, payload, caller=None):
                return {"ok": False, "code": "reject"}

        rows = asyncio.run(_lang.arun([{"call": "a", "required": True}, {"call": "runtime.apply"}], {}, Api(), None, "d"))
        self.assertEqual([r["call"] for r in rows], ["a", "runtime.apply"])
        rows = asyncio.run(_lang.arun([{"call": "boom"}, {"call": "b"}], {}, Api(), None, "d"))
        self.assertEqual(len(rows), 1)
        rows = asyncio.run(_lang.arun(["raw"], {}, Api(), None, "d"))
        self.assertEqual(len(rows), 1)
        rows = asyncio.run(_lang.arun([{"send": "evt"}], {}, Api(), None, "d"))
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["ok"])

    def test_arun_nested_and_as(self):
        class Eng:
            async def arun_callable(self, rid, inp):
                return {"ok": True, "id": rid, "inp": inp}

        class Ctx:
            demand_engine = Eng()

        class Api:
            async def acall(self, route, payload, caller=None):
                return {"ok": True, "route": route, "payload": payload}

        stmts = [{"call": "cap", "with": {"x": {"lit": 1}}, "as": "v"},
                 {"call": "demand_engine.run", "with": {"id": {"lit": "n"}}}]
        scope = {"caller": "c"}
        rows = asyncio.run(_lang.arun(stmts, scope, Api(), Ctx(), "d"))
        self.assertEqual(scope["v"], {"ok": True, "route": "cap", "payload": {"x": 1}})
        self.assertNotIn("send", rows[0])
        self.assertEqual(rows[1]["result"]["id"], "n")


if __name__ == "__main__":
    unittest.main()


class TargetedRemainderTest(unittest.TestCase):
    def test_view_index_without_view_and_without_forms(self):
        ctx = Ctx(docs(("a", rec()), ("b", rec(view={"key": "k"}))))
        idx = _engine.Engine(ctx).view_index()
        self.assertEqual(idx, [{"view": {"key": "k"}}])

    def test_view_labels_heading_crumb_key_and_duplicate_edges(self):
        ctx = Ctx(docs(
            ("a", rec(view={"key": "home"})),
            ("b", rec(view={"key": "projects", "heading": "项目标题",
                            "screen_label": "", "menu": "",
                            "actions": [{"view": "projects"}, {"view": "home"},
                                        {"view": "home"}],
                            "sections": [{"actions": []}]})),
            ("c", rec(view={"key": "detail", "heading": "", "crumb": []})),
        ))
        ctx.storage.docs["console.yaml"] = {"screen_machine": {
            "entry": "view:home",
            "overlays": [{"key": "overlay:sidebar", "label": "侧栏", "close_ctl": "x",
                          "close_note": "n"}]}}
        got = _engine.Engine(ctx).screens()
        labels = {p["key"]: p["label"] for p in got["pages"]}
        self.assertEqual(labels["view:projects"], "项目标题")
        self.assertEqual(labels["view:detail"], "detail")
        self.assertEqual(got["overlays"][0]["id"], "overlay:sidebar")
        routes = [(r["from_key"], r["to_key"], r["by"]) for r in got["routes"]]
        self.assertEqual(len(routes), len(set(routes)))

    def test_notify_codec_and_stream_errors_force_new_seq(self):
        ctx = Ctx(docs(
            ("a", rec(tags=["write"], touch=["b"])),
            ("b", rec(view={"key": "v", "data": [{"demand": "b", "as": "x"}]})),
        ))
        eng = _engine.Engine(ctx)
        rec_a = next(r for r in eng._load() if r["id"] == "a")
        ctx.codec = Codec(fail=True)
        ctx.clock.ts = 200
        eng.notify_write("a", rec_a)
        self.assertEqual(eng._badge_seq, 1)
        self.assertEqual(ctx.runtime.put, [])
        ctx.codec = Codec()
        ctx.runtime = Runtime(fail=True)
        ctx.clock.ts = 300
        eng.notify_write("a", rec_a)
        self.assertEqual(eng._badge_seq, 2)
        self.assertEqual(ctx.runtime.put, [])

    def test_trace_close_failure_is_swallowed(self):
        ctx = Ctx(docs(("a", rec(callable=True))))
        eng = _engine.Engine(ctx)
        ctx.api.routes["trace.open"] = {"span": "s"}
        ctx.api.routes["trace.close"] = RuntimeError("down")
        eng.run_callable("a")
        self.assertEqual([c[1] for c in ctx.api.calls].count("trace.close"), 1)

    def test_dispatch_wrapper_marks_span_error(self):
        ctx = Ctx(docs(("a", rec())))
        eng = _engine.Engine(ctx)
        ctx.api.routes["trace.open"] = {"span": "s"}
        eng._load = lambda: (_ for _ in ()).throw(RuntimeError("load down"))
        with self.assertRaises(RuntimeError):
            eng.dispatch("hook.x", {})
        close = [c for c in ctx.api.calls if c[1] == "trace.close"][-1]
        self.assertEqual(close[2]["status"], "error")
        self.assertEqual(close[2]["code"], "RuntimeError")

    def test_lang_async_send_with_and_unknown(self):
        class Api:
            async def acall(self, route, payload, caller=None):
                return {"ok": True}

            def notify(self, route, payload, caller=None):
                return {"ok": True, "payload": payload}

        scope = {"event": {"n": 2}, "caller": "c"}
        rows = asyncio.run(_lang.arun([{"send": "evt", "with": {"x": {"get": "event.n"}}}],
                                      scope, Api(), None, "d"))
        self.assertEqual(rows[0]["result"], {"ok": True, "payload": {"n": 2, "x": 2}})
        rows = asyncio.run(_lang.arun([{"noop": 1}], {}, Api(), None, "d"))
        self.assertEqual(len(rows), 1)
        self.assertIn("noop", rows[0]["error"])
