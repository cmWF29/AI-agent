"""API 注册表：注册/替换、契约校验、调用方授权、span、同步/异步/单向通道。"""
from __future__ import annotations

import asyncio
import inspect
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.api.private import _registry as r  # noqa: E402


class ApiError(Exception):
    def __init__(self, message, code="error", status=500):
        super().__init__(message)
        self.code = code
        self.status = status


class Md:
    def __init__(self, files):
        self.files = files

    def exists(self, name):
        return name in self.files

    def read_text(self, name):
        return self.files[name]


class Storage:
    def __init__(self, files):
        self.files = files

    def own(self, path):
        return Md(self.files.get(Path(path).name, {}))


class BoomMd:
    def exists(self, name):
        raise ValueError("read")


class BoomStorage:
    def __init__(self, own=False):
        self._own = own

    def own(self, path):
        if self._own:
            raise ValueError("own")
        return BoomMd()


class Codec:
    def __init__(self, value=None, fail=False):
        self.value = value or {}
        self.fail = fail

    def yaml_decode(self, text):
        if self.fail:
            raise ValueError("yaml")
        return {"value": self.value}


class Transport:
    def __init__(self, ctx):
        self.ctx = ctx
        self.kinds = {}
        self.sent = []
        self.notified = []

    def kind_for(self, name):
        return self.kinds.get(name, ("direct", None))

    def send(self, name, payload, handler, caller=None):
        self.sent.append((name, payload, caller))
        out = handler(self.ctx, payload or {})
        if inspect.isawaitable(out):
            return asyncio.run(out)
        return out

    def notify(self, name, payload, handler, caller=None):
        self.notified.append((name, payload, caller))
        return {"transport": "remote", "sent": name}


class Ctx:
    def __init__(self):
        self.cfg = {"runtime": {"api_workers": "bad"}, "api": {}}
        self.loaded = {}
        self.storage = Storage({})
        self.codec = Codec()
        self.ApiError = ApiError


def module(name, file):
    return types.SimpleNamespace(__name__=name, __file__=file)


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.ctx = Ctx()
        self.reg = r.Registry(self.ctx)
        self.reg.transport = Transport(self.ctx)

    def test_cfg_and_loop_and_adapt(self):
        self.assertEqual(self.reg._cfg_int("api_workers", 1), 1)
        self.assertEqual(self.reg._cfg_str("api", "x", "d"), "d")
        self.ctx.cfg["api"]["x"] = "v"
        self.assertEqual(self.reg._cfg_str("api", "x", "d"), "v")
        loop = self.reg._ensure_loop()
        self.assertIs(loop, self.reg._ensure_loop())

        class Locker:
            def __enter__(self):
                self.reg._loop = "raced"
                return self

            def __exit__(self, *a):
                return False

        fake = Locker()
        fake.reg = self.reg
        old = self.reg._loop
        self.reg._loop = None
        self.reg._loop_lock = fake
        self.assertEqual(self.reg._ensure_loop(), "raced")
        self.reg._loop_lock = r.Registry.__dict__["_loop_lock"] if False else self.reg._loop_lock
        self.reg._loop = old
        one = self.reg._adapt(lambda p: p)
        two = self.reg._adapt(lambda c, p: p)
        self.assertEqual(one(None, {"a": 1}), {"a": 1})
        self.assertEqual(two(None, {"a": 1}), {"a": 1})

    def test_register_and_substitute(self):
        self.reg.register("a.b", lambda c, p: p, module="a")
        with self.assertRaises(ValueError):
            self.reg.register("a.b", lambda c, p: p)
        with self.assertRaises(ValueError):
            self.reg.substitute("x", lambda c, p: p)
        self.reg.substitute("a.b", lambda c, p: 1)
        self.assertEqual(self.reg.route("a.b")["fn"](None, {}), 1)
        self.assertIsNone(self.reg.route("none"))
        self.reg.register("trace.open", lambda p: {"span": "s"})
        self.reg.register("trace.close", lambda p: {})
        self.assertEqual(self.reg._trace_open(None, {"name": "x"})["span"], "s")

    def test_routes_and_contracts(self):
        self.reg.register("a.b", lambda c, p: p, internal=True)
        self.reg.register("a.c", lambda c, p: p)
        self.ctx.storage = Storage({"api.py": {"api.yaml": "routes: {}"}})
        self.ctx.loaded = {"a": module("a", "/x/modules/a/api.py")}
        with mock.patch.object(self.ctx, "codec", Codec({"routes": {"a.c": {"in": {"x": {}}}}})):
            rows = self.reg.routes()
        self.assertEqual(rows[0]["in"], ["x"])
        self.assertEqual(len(rows), 1)
        self.reg._contracts = None
        with mock.patch.object(self.ctx, "storage", BoomStorage(own=True)):
            self.assertEqual(self.reg._load_contracts(), {})
        with mock.patch.object(self.ctx, "storage", BoomStorage()):
            self.assertEqual(self.reg._load_contracts(), {})
        self.reg._contracts = None
        self.ctx.loaded = {"a": module("a", "/x/modules/a/api.py")}
        self.ctx.storage = Storage({"api.py": {}})
        self.assertEqual(self.reg._load_contracts(), {})
        self.ctx.storage = Storage({"api.py": {"api.yaml": "x"}})
        self.assertEqual(self.reg._load_contracts(), {})
        self.reg._contracts = None
        self.ctx.loaded = {}
        self.assertEqual(self.reg._load_contracts(), {})

    def test_check(self):
        self.reg._contracts = {"a.b": {"in": {"x": {"req": True}}}}
        self.reg._contracts_seen = len(self.ctx.loaded)
        self.ctx.cfg["api"]["contract_mode"] = "warn"
        self.reg._check("a.b", {})
        self.reg._check("a.b", {"x": 1})
        self.ctx.cfg["api"]["contract_mode"] = "enforce"
        with self.assertRaises(ApiError):
            self.reg._check("a.b", {})
        self.ctx.cfg["api"]["contract_mode"] = "warn"
        self.reg._check("a.b", {})
        self.assertEqual(self.reg.violations(), [])
        self.assertEqual(len(self.reg._warned), 2)
        for i in range(200):
            self.reg._warned.append({"i": i})
        self.reg._check("a.b", {})
        self.assertEqual(len(self.reg._warned), 202)

    def test_group_implicit_and_internal_calls(self):
        self.ctx.loaded = {"a": module("a", "/x/modules/agent/a.py"),
                           "z": module("z", "/x/modules/z"),
                           "p": module("p", "/x/modules/agent_common/p.py")}
        self.assertEqual(self.reg._group_of("a"), "agent")
        self.assertEqual(self.reg._group_of("p"), "agent_common")
        self.assertEqual(self.reg._group_of("none"), "")
        self.ctx.loaded["z"] = module("z", "/x/modules/z")
        self.assertEqual(self.reg._group_of("z"), "")
        token = r._SCOPE.set("a")
        self.assertEqual(self.reg._implicit_caller(), "module:a")
        r._SCOPE.set("p")
        self.assertEqual(self.reg._implicit_caller(), "platform:p")
        r._SCOPE.reset(token)
        self.assertEqual(self.reg._implicit_caller(), "platform:boot")

        self.ctx.storage = Storage({"api.py": {"internal-calls.yaml":
                                               "calls:\n- caller: a\n  targets: [b]"}})
        self.ctx.codec = Codec({"calls": [{"caller": "a", "targets": ["b"]}]})
        self.assertEqual(self.reg._internal_calls(), {"a": ("b",)})
        self.assertEqual(self.reg._internal_calls(), {"a": ("b",)})
        self.reg._calls = None
        with mock.patch.object(self.ctx, "storage", BoomStorage(own=True)):
            self.assertEqual(self.reg._internal_calls(), {})
        self.reg._calls = None
        self.ctx.loaded = {}
        self.assertEqual(self.reg._internal_calls(), {"a": ("b",)})

    def test_authorize(self):
        for caller in ("demand_engine", "boot", "platform:x"):
            self.reg._authorize("a.b", caller)
        self.reg._authorize("a.b", "module:a")
        self.reg._authorize("a.b", "module:agent_test")
        self.reg._authorize("config.x", "module:a")
        self.reg._internal_calls = lambda: {"a": ("b",)}
        self.reg._authorize("b.c", "module:a")
        self.ctx.cfg["api"]["internal_call_mode"] = "enforce"
        with self.assertRaises(ApiError):
            self.reg._authorize("c.d", "module:a")
        self.ctx.cfg["api"]["internal_call_mode"] = "warn"
        self.reg._authorize("c.d", "module:a")
        self.assertEqual(self.reg.violations()[-1]["route"], "c.d")
        self.reg._violations = [{"i": 0}] * 400
        self.reg._authorize("c.d", "module:a")
        self.assertEqual(len(self.reg.violations()), 400)
        with self.assertRaises(ApiError):
            self.reg._authorize("a.b", "weird")

    def test_spans_and_scoped(self):
        self.reg._trace_open = lambda ctx, p: {"span": "s"}
        self.reg._trace_close = lambda ctx, p: None
        self.assertEqual(self.reg._span_ctx(), "")
        prev = self.reg._span_enter("s")
        self.assertEqual(self.reg._span_ctx(), "s")
        self.reg._span_exit(prev)
        self.assertEqual(self.reg._span_open("n"), "s")
        self.reg._span_close("s", "ok")
        self.reg._trace_open = lambda ctx, p: (_ for _ in ()).throw(ValueError())
        self.assertEqual(self.reg._span_open("n"), "")
        self.reg._trace_close = lambda ctx, p: (_ for _ in ()).throw(ValueError())
        self.reg._span_close("s")
        self.reg._trace_open = None
        self.reg._span_close("")
        self.reg._trace_close = None
        self.reg._span_close("s")

        route = {"owner": "a", "module": "a", "fn": lambda c, p: p}
        self.assertEqual(self.reg._scoped(route, None, {"x": 1}), {"x": 1})
        self.reg._trace_open = lambda ctx, p: {"span": "s"}
        self.reg._trace_close = lambda ctx, p: None
        bad = {"owner": "a", "module": "a", "fn": lambda c, p: (_ for _ in ()).throw(ValueError())}
        with self.assertRaises(ValueError):
            self.reg._scoped(bad, None, {})
        trace_route = {"owner": "trace", "module": "trace", "fn": lambda c, p: p}
        self.assertEqual(self.reg._scoped(trace_route, None, {"x": 1}), {"x": 1})
        trace_bad = {"owner": "trace", "module": "trace",
                     "fn": lambda c, p: (_ for _ in ()).throw(ValueError())}
        with self.assertRaises(ValueError):
            self.reg._scoped(trace_bad, None, {})

    def test_async_scoped(self):
        async def ok(c, p):
            return p

        async def bad(c, p):
            raise ValueError("x")

        self.reg._trace_open = lambda ctx, p: {"span": "s"}
        self.reg._trace_close = lambda ctx, p: None
        route = {"owner": "a", "module": "a", "fn": ok}
        self.assertEqual(asyncio.run(self.reg._ascoped(route, None, {"x": 1})), {"x": 1})
        route2 = {"owner": "a", "module": "a", "fn": lambda c, p: p}
        self.assertEqual(asyncio.run(self.reg._ascoped(route2, None, {"x": 1})), {"x": 1})
        bad_route = {"owner": "a", "module": "a", "fn": bad}
        with self.assertRaises(ValueError):
            asyncio.run(self.reg._ascoped(bad_route, None, {}))
        trace_bad = {"owner": "trace", "module": "trace", "fn": bad}
        with self.assertRaises(ValueError):
            asyncio.run(self.reg._ascoped(trace_bad, None, {}))
        trace_ok = {"owner": "trace", "module": "trace", "fn": lambda c, p: p}
        self.assertEqual(asyncio.run(self.reg._ascoped(trace_ok, None, {"x": 1})), {"x": 1})

    def test_call_paths(self):
        self.reg.register("a.sync", lambda c, p: p, module="a")
        self.reg.register("a.async", lambda c, p: p, module="a")
        self.reg._routes["a.async"]["fn"] = self._async_fn
        self.reg._routes["a.async"]["is_async"] = True
        self.assertEqual(self.reg.call("a.sync", {"x": 1}, direct=True), {"x": 1})
        self.assertEqual(self.reg.call("a.sync", {"x": 1}), {"x": 1})
        self.reg.transport.kinds["a.async"] = ("unix", "addr")
        self.assertEqual(self.reg.call("a.async", {"x": 1}), {"x": 1})
        self.reg.transport.kinds["a.async"] = ("direct", None)
        self.assertEqual(self.reg.call("a.async", {"x": 1}), {"x": 1})
        with self.assertRaises(ApiError):
            self.reg.call("none", {})

    def test_acall_and_notify(self):
        self.reg._ensure_loop = lambda: asyncio.get_running_loop()
        self.reg.register("a.sync", lambda c, p: p, module="a")
        self.reg.register("a.async", self._async_fn, module="a")
        self.assertEqual(asyncio.run(self.reg.acall("a.sync", {"x": 1}, direct=True)),
                         {"x": 1})
        self.assertEqual(asyncio.run(self.reg.acall("a.sync", {"x": 1})), {"x": 1})
        self.reg.transport.kinds["a.async"] = ("unix", "addr")
        self.assertEqual(asyncio.run(self.reg.acall("a.async", {"x": 1})), {"x": 1})
        self.reg.transport.kinds["a.async"] = ("direct", None)
        self.assertEqual(asyncio.run(self.reg.acall("a.async", {"x": 1})), {"x": 1})
        self.reg.transport.kinds["a.sync"] = ("unix", "addr")
        out = self.reg.notify("a.sync", {"x": 1})
        self.assertEqual(out["transport"], "remote")
        self.reg.transport.kinds["a.sync"] = ("direct", None)
        out = self.reg.notify("a.sync", {"x": 1})
        self.assertEqual(out["sent"], "a.sync")

    async def _async_fn(self, c, p):
        return p


if __name__ == "__main__":
    unittest.main()
