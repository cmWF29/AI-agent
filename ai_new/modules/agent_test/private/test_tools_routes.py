"""工具模块路由/注册表：shell cwd 收口、依赖盘点、外部占位、执行权限与缺省参数。"""
import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common import tools as tm  # noqa: E402
from ai_new.modules.agent_common.tools.private import _registry  # noqa: E402


class ApiError(Exception):
    def __init__(self, msg, code="", status=400, payload=None):
        super().__init__(msg)
        self.code = code
        self.status = status
        self.payload = payload


class Api:
    def __init__(self):
        self.calls = []
        self.routes = {}
        self.registered = {}

    def call(self, route, payload, caller=None):
        self.calls.append(("call", route, payload))
        fn = self.routes.get(route)
        if isinstance(fn, Exception):
            raise fn
        if callable(fn):
            return fn(payload)
        return fn if fn is not None else {}

    async def acall(self, route, payload, caller=None):
        self.calls.append(("acall", route, payload))
        fn = self.routes.get(route)
        if isinstance(fn, Exception):
            raise fn
        if callable(fn):
            if asyncio.iscoroutinefunction(fn):
                return await fn(payload)
            return fn(payload)
        return fn if fn is not None else {}

    def register(self, route, fn, desc="", module=None):
        self.registered[route] = fn


class Runtime:
    def __init__(self):
        self.calls = []

    async def acall(self, name, args):
        self.calls.append((name, args))
        return {"ok": True, "name": name}


class Ctx:
    ApiError = ApiError

    def __init__(self, docs=None, routes=None):
        self.api = Api()
        self.api.routes.update(docs or {})
        self.api.routes.update(routes or {})
        self.runtime = Runtime()
        self.tools = _registry.ToolRegistry(self)


def run(coro):
    return asyncio.run(coro)


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.ctx = Ctx({"store.read": lambda p: {"value": {"tool_missing": "缺 {name}",
                                                           "tool_forbidden": "禁 {name}"}}})
        self.reg = self.ctx.tools

    def test_register_duplicate_list_and_tools_for(self):
        self.reg.register("a", "A", [], None, module="m", kinds=["role"])
        self.reg.register("b", "B", [], None, builtin=False)
        self.reg.register_demand("c", "C", [], "demand.x", kinds=None)
        with self.assertRaises(ValueError):
            self.reg.register("a", "A2", [], None)
        self.assertEqual([t["name"] for t in self.reg.list_tools()], ["a", "c"])
        self.assertEqual([t["name"] for t in self.reg.tools_for("role")], ["a", "b", "c"])
        self.assertEqual([t["name"] for t in self.reg.tools_for("other")], ["b", "c"])

    def test_pick_allow_and_kind(self):
        self.reg.register("a", "A", [{"name": "x"}], None, module="m", kinds=["role"])
        self.reg.register("b", "B", [], None)
        self.assertEqual([t["name"] for t in self.reg.pick(["b", "zzz"], None)], ["b"])
        self.assertEqual([t["name"] for t in self.reg.pick([], "role")], ["a", "b"])
        self.assertEqual(self.reg.pick(["a"], None)[0]["params"], [{"name": "x"}])

    def test_execute_missing_forbidden_and_session_defaults(self):
        self.reg.register("ro", "R", [], None, kinds=["role"])
        with self.assertRaises(ApiError) as caught:
            run(self.reg.execute("nope", {}))
        self.assertEqual(caught.exception.code, "no_tool")
        with self.assertRaises(ApiError) as caught:
            run(self.reg.execute("ro", {}, session={"kind": "other"}))
        self.assertEqual(caught.exception.code, "tool_forbidden")
        seen = {}

        async def fn(ctx, args, session=None):
            seen.update(args)
            return {"ok": True}

        self.reg.register("free", "F", [], fn)
        out = run(self.reg.execute("free", {}, session={"kind": "role", "ticket": "T",
                                                        "role": "pm", "id": "S"}))
        self.assertEqual(out, {"ok": True})
        self.assertEqual(seen, {"id": "T", "ticket": "T", "role": "pm", "session": "S"})
        seen.clear()
        run(self.reg.execute("free", {"id": "X", "ticket": "Y", "role": "r", "session": "s"},
                             session={"ticket": "T", "role": "pm", "id": "S"}))
        self.assertEqual(seen, {"id": "X", "ticket": "Y", "role": "r", "session": "s"})

    def test_execute_demand_defer_and_async_runtime(self):
        self.reg.register_demand("d", "D", [], "demand.d")
        out = run(self.reg.execute("d", {"x": 1}, defer=True))
        self.assertEqual(out["demand"], "demand.d")
        self.assertEqual(out["input"], {"tool": "d", "x": 1})
        out = run(self.reg.execute("d", {"x": 1}))
        self.assertEqual(out["name"], "demand.d")

    def test_execute_sync_function(self):
        self.reg.register("s", "S", [], lambda ctx, args, session=None: {"args": args})
        self.assertEqual(run(self.reg.execute("s", {"a": 1})), {"args": {"a": 1}})


class ShellCwdTest(unittest.TestCase):
    def setUp(self):
        self.ctx = Ctx({
            "store.read": lambda p: {"value": {"workspace_unavailable": "坏 {error}",
                                               "cwd_outside": "越界 {path}",
                                               "argv_required": "缺 argv"}},
            "exec.run": lambda p: p,
        })

    def test_no_project_and_modes(self):
        self.assertEqual(tm._shell_cwd(self.ctx, "x", None),
                         {"ok": True, "cwd": "x", "ensure": False})
        self.ctx.api.routes["projects.workspace"] = lambda p: {
            "ok": False, "error": "boom", "code": "bad"}
        out = tm._shell_cwd(self.ctx, "x", {"project": "P"})
        self.assertEqual(out["code"], "bad")
        self.assertEqual(out["error"], "坏 boom")
        self.ctx.api.routes["store.read"] = lambda p: {"value": {}}
        out = tm._shell_cwd(self.ctx, "x", {"project": "P"})
        self.assertEqual(out["error"], "boom")
        self.ctx.api.routes["projects.workspace"] = lambda p: {"ok": True, "mode": "ticket"}
        self.assertEqual(tm._shell_cwd(self.ctx, "x", {"project": "P"})["cwd"], "x")
        self.ctx.api.routes["projects.workspace"] = lambda p: {
            "ok": True, "mode": "root", "cwd": "/w", "sandbox": {"engine": "bwrap"}}
        self.assertEqual(tm._shell_cwd(self.ctx, "", {"project": "P"}),
                         {"ok": True, "cwd": "/w", "ensure": True,
                          "sandbox": {"engine": "bwrap"}})

    def test_outside_and_allowed(self):
        self.ctx.api.routes["projects.workspace"] = lambda p: {
            "ok": True, "mode": "root", "cwd": "/w", "cwd_allowed": False}
        out = tm._shell_cwd(self.ctx, "x", {"project": "P"})
        self.assertEqual(out["code"], "cwd_outside")
        self.assertEqual(out["error"], "越界 /w")
        self.ctx.api.routes["store.read"] = lambda p: {"value": {}}
        out = tm._shell_cwd(self.ctx, "x", {"project": "P"})
        self.assertEqual(out["error"], "/w")
        self.ctx.api.routes["projects.workspace"] = lambda p: {
            "ok": True, "mode": "root", "cwd": "/w", "cwd_allowed": True,
            "sandbox": {"engine": "bwrap"}}
        self.assertEqual(tm._shell_cwd(self.ctx, "x", {"project": "P"})["cwd"], "/w")

    def test_tool_shell_argv_cwd_and_exec(self):
        out = run(tm._tool_shell(self.ctx, {}))
        self.assertEqual(out["code"], "bad_request")
        self.assertEqual(out["error"], "缺 argv")
        self.ctx.api.routes["projects.workspace"] = lambda p: {
            "ok": True, "mode": "root", "cwd": "/w", "cwd_allowed": False}
        out = run(tm._tool_shell(self.ctx, {"argv": ["echo"], "cwd": "x"},
                                 {"project": "P"}))
        self.assertEqual(out["code"], "cwd_outside")
        self.ctx.api.routes["projects.workspace"] = lambda p: {
            "ok": True, "mode": "root", "cwd": "/w", "cwd_allowed": True}
        out = run(tm._tool_shell(self.ctx, {"argv": ["echo", 1]}, {"project": "P"}))
        self.assertEqual(out["argv"], ["echo", "1"])
        self.assertEqual(out["ensure_cwd"], True)
        self.assertEqual(out["timeout"], 300)


class RouteTest(unittest.TestCase):
    def _ctx(self):
        ext = {"e1": {"desc": "e", "demand": "d1", "deps": {"cli": ["git"], "pip": ["x"],
                                                             "env": ["TOKEN"], "config": ["c"]}},
               "e2": {"desc": "bad"},
               "e3": {"desc": "e3", "deps": {"pip": ["miss"]}},
               "": {"desc": "blank"}, "b1": {"desc": "clash"},
               "s1tool": {"desc": "disabled", "skill": "s1"}}
        skills = {"s1": {"status": "disabled"}}
        project = {"tools": ["dis"]}
        ctx = Ctx({
            "store.read": lambda p: (
                {"value": ext} if p.get("path") == "tools.yaml" else
                {"value": skills} if p.get("path") == "skills.yaml" else
                {"value": project} if p.get("path") == "P.yaml" else
                {"value": {"workspace_unavailable": "坏 {error}", "cwd_outside": "越界 {path}",
                           "tool_disabled": "禁 {name}", "tool_unavailable": "缺 {name}",
                           "tool_missing": "无 {name}"}}),
            "library.disabled_skills": lambda p: {"ids": ["s1"]},
            "projects.override_parts": lambda p: {"tools": ["dis"]},
            "host.which": lambda p: {"found": p["name"] != "bad"},
            "host.importable": lambda p: {"importable": p["name"] not in ("bad", "miss")},
            "host.env": lambda p: {"value": "v"},
            "config.get": lambda p: {"value": "v"},
            "host.readiness": lambda p: {"ready": p["tool"].get("name") != "e2"},
            "host.executable": lambda p: {"path": "/py"},
            "exec.run": lambda p: {"ok": p["argv"][-1] != "bad"},
        })
        ctx.ext = ext
        ctx.tools.register("b1", "B1", [], lambda c, a, session=None: {"ok": True},
                           module="m", kinds=["role"])
        return ctx

    def test_project_external(self):
        ctx = self._ctx()
        ext, disabled, names = tm._project_external(ctx, None)
        self.assertEqual(names, [])
        self.assertIn("e1", ext)
        self.assertEqual(disabled, ["s1"])
        _, _, names = tm._project_external(ctx, "P")
        self.assertEqual(names, ["dis"])

    def test_pick(self):
        ctx = self._ctx()
        out = tm._route_pick(ctx, {"project": "P", "tools": ["b1"], "kind": "role"})
        self.assertEqual([x["name"] for x in out["items"]], ["b1"])
        out = tm._route_pick(ctx, {"kind": "role"})
        self.assertIn("e1", [x["name"] for x in out["items"]])

    def test_execute_disabled_unready_and_builtin(self):
        ctx = self._ctx()
        with self.assertRaises(ApiError) as caught:
            run(tm._route_execute(ctx, {"name": "dis", "session": {"project": "P"}}))
        self.assertEqual(caught.exception.code, "no_tool")
        ctx.api.routes["projects.override_parts"] = lambda p: {"tools": []}
        ctx.api.routes["host.readiness"] = lambda p: {"ready": False, "missing": ["x"]}
        with self.assertRaises(ApiError) as caught:
            run(tm._route_execute(ctx, {"name": "b1"}))
        self.assertEqual(caught.exception.code, "tool_unavailable")
        self.assertEqual(caught.exception.payload["missing"], ["x"])
        ctx.api.routes["host.readiness"] = lambda p: {"ready": True}
        out = run(tm._route_execute(ctx, {"name": "b1", "defer": True}))
        self.assertEqual(out, {"ok": True})

    def test_execute_external_and_missing(self):
        ctx = self._ctx()
        ctx.api.routes["host.readiness"] = lambda p: {"ready": True}
        out = run(tm._route_execute(ctx, {"name": "e1", "args": {"tool": "x", "a": 1}}))
        self.assertEqual(out["tool"], "e1")
        with self.assertRaises(ApiError) as caught:
            run(tm._route_execute(ctx, {"name": "nope"}))
        self.assertEqual(caught.exception.code, "no_tool")

    def test_snapshot_dedup_and_empty(self):
        ctx = self._ctx()
        snap = tm._collect_snapshot(ctx, [
            {"deps": {"cli": ["git", "git", ""], "pip": ["x", "x", ""],
                      "env": ["TOKEN", "TOKEN", ""], "config": ["c", "c", ""]}},
            {"deps": {}},
        ])
        self.assertEqual(snap, {"cli": {"git": True}, "pip": {"x": True},
                                "env": {"TOKEN": "v"}, "config": {"c": "v"}})

    def test_external_run_known_unknown(self):
        ctx = self._ctx()
        out = tm._route_external_run(ctx, {"tool": "e1", "args": {"tool": "z", "a": 1}})
        self.assertEqual(out["tool"], "e1")
        out = tm._route_external_run(ctx, {"tool": "nope"})
        self.assertEqual(out["code"], "external_pending")
        self.assertEqual(out["tool"], "nope")

    def test_list_scope_and_deps(self):
        ctx = self._ctx()
        out = tm._route_list(ctx, {"scope": "builtin"})
        self.assertEqual([x["name"] for x in out["items"]], ["b1"])
        out = tm._route_list(ctx, {"scope": "external", "disabled": ["s1"],
                                   "external": ctx.ext})
        self.assertIn("e1", [x["name"] for x in out["items"]])
        out = tm._route_deps(ctx, {"external": {}, "disabled": []})
        self.assertIn("ready", out)

    def test_install_missing(self):
        ctx = self._ctx()

        async def go():
            out = await tm._route_install_missing(ctx, {"disabled": [], "external": ctx.ext})
            self.assertEqual(out["installs"][0]["pkg"], "miss")
            self.assertTrue(out["installs"][0]["ok"])
            ctx.api.routes["exec.run"] = lambda p: {"ok": False, "error": "e"}
            out = await tm._route_install_missing(ctx, {"disabled": [], "external": ctx.ext})
            self.assertFalse(out["ready"])
            ctx.tools._tools.clear()
            out = await tm._route_install_missing(ctx, {"disabled": [], "external": {}})
            self.assertEqual(out["installs"], [])
        asyncio.run(go())

    def test_setup_start_register_shell(self):
        ctx = self._ctx()
        tm.setup(ctx)
        self.assertIn("tools.execute", ctx.api.registered)
        self.assertTrue(ctx.tools.has("shell"))
        tm.register(ctx, "x", "X", [], lambda c, a, session=None: {"ok": True})
        self.assertTrue(ctx.tools.has("x"))
        tm.start(ctx)
        self.assertTrue(ctx.tools.has("e1"))
        self.assertFalse(ctx.tools.has("missing"))
        self.assertFalse(ctx.tools.has("s1tool"))
        self.assertEqual(tm.list_tools(ctx), ctx.tools.list_tools())
        self.assertEqual(run(tm.execute(ctx, "x", {})), {"ok": True})


if __name__ == "__main__":
    unittest.main()
