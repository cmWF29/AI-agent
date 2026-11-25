"""装配图扫描边界：错误目录、重复提供、路由/需求接线告警、成环与静态分析细节。"""
import ast
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.boot.private import _graph as g  # noqa: E402


def build(tmp, modules, data=None):
    base = Path(tmp) / "agent_common"
    base.mkdir()
    for name, source in modules.items():
        directory = base / name
        directory.mkdir()
        (directory / "__init__.py").write_text(textwrap.dedent(source), encoding="utf-8")
    data_dir = None
    if data:
        data_dir = Path(tmp) / "data"
        demands = data_dir / "demands"
        demands.mkdir(parents=True)
        for name, text in data.items():
            (demands / name).write_text(textwrap.dedent(text), encoding="utf-8")
    return base, data_dir


P_SOURCE = """
def setup(ctx):
    ctx.x = 1
    ctx.ann: int = 2
    ctx._p = 3
    ctx.root = 4
    ctx.hooks.point("p.x")
    ctx.hooks.point("p.y")
    ctx.hooks.point("p.covered")
    ctx.api.call("p.fn", {})
    ctx.foo.call("x.y")
    ctx.api.call()
    ctx.api.call("nodot")
    ctx.api.call(name)
    ctx.api.notify("p.n")
    other.api.call("x.y")
    ctx.some()
    missing_fn()


def dead(ctx):
    ctx.hooks.emit()
    ctx.hooks.emit(name)
    ctx.hooks.point(1)
    hooks2.emit("p.x")
    ctx.hooks.other("p.x")
    self.ctx.hooks.emit("p.x")
"""

Q_SOURCE = """
def setup(ctx):
    ctx.api.call("q.fn")
    ctx.api.call("zzz.fn")
    ctx.hooks.emit("p.x")
    ctx.hooks.emit("p.covered")
    ctx.hooks.emit("ghost.x")
    ctx.x
    ctx.root
    ctx._p
    ctx.y
"""

ROOT_SOURCE = """
def helper(ctx):
    ctx.hooks.point("root.point")
"""


DEMANDS = {
    "d1.yaml": """\
        id: d1
        enabled: false
        do:
          - call: p.fn
        """,
    "d2.yaml": """\
        id: d2
        callable: true
        'on': p.x
        do:
          - call: p.fn
        """,
    "d3.yaml": """\
        id: d3
        view:
          key: k
        """,
    "d4.yaml": """\
        id: d4
        do:
          - call: p.fn
        """,
    "d5.yaml": """\
        id: d5
        'on': p.x
        """,
    "d6.yaml": """\
        id: d6
        'on': [p.x]
        do:
          - call: nodot
          - call: ghost.fn
          - call: p.missing
          - raw
          - when: 1
          - x: 1
          - call: hooks.emit
            with:
              point:
                lit: p.implicit
          - call: hooks.emit
            with:
              name:
                lit: 3
        """,
}


class PlanErrorTest(unittest.TestCase):
    def test_missing_base_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                g.plan(Path(tmp) / "nope")

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "agent_common"
            base.mkdir()
            (base / "junk").mkdir()
            with self.assertRaises(RuntimeError):
                g.plan(base)

    def test_two_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, _ = build(tmp, {"a": "", "b": ""})
            with self.assertRaises(RuntimeError):
                g.plan(base)

    def test_duplicate_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, _ = build(tmp, {
                "r": "",
                "a": "def setup(ctx):\n    ctx.same = 1\n",
                "b": "def setup(ctx):\n    ctx.same = 2\n",
            })
            with self.assertRaises(RuntimeError):
                g.plan(base)


class WiringTest(unittest.TestCase):
    def test_plan_collects_warnings_and_surfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, data_dir = build(tmp, {"root": ROOT_SOURCE, "p": P_SOURCE, "q": Q_SOURCE},
                                   DEMANDS)
            plan = g.plan(base, data_dir)
            self.assertEqual(plan["roots"], ["root"])
            self.assertIn("p", plan["order"])
            self.assertIn("q", plan["order"])
            self.assertEqual(plan["providers"]["x"], "p")
            self.assertIn("q -> p", plan["reasons"])
            self.assertTrue(plan["stash"][0].startswith("p 把私有状态"))
            warnings = "\n".join(plan["warnings"])
            for needle in ("改写了 Context 自带", "没有模块装填它", "没有对应模块的路由",
                           "未声明的 hook 点", "别的模块的 hook 点", "没有任何代码触发",
                           "callable", "没有声明任何 hook 点", "没有声明任何服务调用",
                           "不是 '模块.服务'", "不存在的模块", "没注册过的服务",
                           "没有任何需求订阅", "可以连同 emit 一起删掉"):
                self.assertIn(needle, warnings)
            detail = plan["hooks"]
            self.assertEqual(detail["declared"]["p.x"], "p")
            self.assertIn("demand", detail["emitted"]["p.implicit"])
            self.assertEqual(detail["demands"][0]["id"], "d1")
            self.assertFalse(detail["demands"][0]["enabled"])
            self.assertEqual(detail["demands"][1]["on"], ["p.x"])
            self.assertEqual(detail["demands"][2]["on"], [])

    def test_plan_multi_group_and_string_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, _ = build(tmp, {"root": ROOT_SOURCE, "p": P_SOURCE})
            plan = g.plan(str(base))
            self.assertEqual(plan["packages"]["p"], "ai_new.modules.agent_common.p")

    def test_data_dir_missing_and_absent(self):
        self.assertEqual(g._read_demands(None), [])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(g._read_demands(Path(tmp)), [])

    def test_demand_helpers(self):
        self.assertEqual(g._as_hooks("a"), ["a"])
        self.assertEqual(g._as_hooks(["a", 1]), ["a", "1"])
        self.assertEqual(g._as_hooks(None), [])
        self.assertEqual(g._demand_routes({"call": "a", "n": [{"call": "b"}]}), ["a", "b"])
        self.assertEqual(g._demand_routes("x"), [])
        out = set()
        g._demand_emit_points({"call": "hooks.emit",
                               "with": {"point": {"lit": "p.a"}}}, out)
        g._demand_emit_points({"call": "hooks.emit",
                               "with": {"name": {"lit": "p.b"}}}, out)
        g._demand_emit_points({"call": "hooks.emit",
                               "with": {"point": {"lit": 3}}}, out)
        g._demand_emit_points([{"call": "hooks.emit",
                                "with": {"point": {"lit": "p.c"}}}], out)
        self.assertEqual(out, {"p.a", "p.b", "p.c"})

    def test_check_stmt_variants(self):
        self.assertIn("非对象语句", g._check_stmt("raw", "d")[0])
        self.assertIn("控制流", g._check_stmt({"when": 1}, "d")[0])
        self.assertIn("未知语句", g._check_stmt({"x": 1}, "d")[0])
        self.assertEqual(g._check_stmt({"send": "a"}, "d"), [])
        self.assertEqual(g._check_stmt({"call": "a"}, "d"), [])


class StaticDetailTest(unittest.TestCase):
    def test_hook_call_negative_shapes(self):
        tree = ast.parse(textwrap.dedent("""
            def f(ctx):
                x = 1
                ctx.hooks.point()
                ctx.hooks.emit(name)
                ctx.hooks.point(1)
                hooks2.emit("a.b")
                ctx.hooks.other("a.b")
                other.point("a.b")
                ctx.hooks.point("a.b")
        """))
        found = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        results = [g._hook_call(call) for call in found]
        self.assertIn(("point", "a.b"), results)
        self.assertTrue(all(r is None for r in results if r != ("point", "a.b")))

    def test_reachable_missing_entry_and_local_targets(self):
        self.assertEqual(g._reachable({}), set())
        tree = ast.parse(textwrap.dedent("""
            def helper():
                pass

            def setup(ctx):
                ctx.some()
                missing_fn()
                helper()
                obj.method()
                lambda_fn()
        """))
        funcs = {("__init__", "setup"): tree.body[1], ("__init__", "helper"): tree.body[0]}
        self.assertEqual(g._reachable(funcs), {("__init__", "setup"), ("__init__", "helper")})
        calls = [n for n in ast.walk(tree.body[1]) if isinstance(n, ast.Call)]
        self.assertEqual([g._local_target(c, "__init__", funcs) for c in calls],
                         [None, None, ("__init__", "helper"), None, None])

    def test_api_route_negative_shapes(self):
        tree = ast.parse(textwrap.dedent("""
            def setup(ctx):
                ctx.api.notify("a.b")
                ctx.foo.call("a.b")
                other.api.call("a.b")
                ctx.api.call()
                ctx.api.call(name)
                ctx.api.call("nodot")
                ctx.api.call("a.b")
        """))
        calls = [n for n in ast.walk(tree.body[0]) if isinstance(n, ast.Call)]
        routes = [g._api_call_route(c) for c in calls]
        self.assertEqual(routes[-1], "a.b")
        self.assertEqual(routes[:-1], [None] * 6)

    def test_assign_targets_ann_assign_no_target(self):
        node = ast.AnnAssign(target=None, annotation=ast.Name(id="int", ctx=ast.Load()),
                             value=None, simple=1)
        self.assertEqual(g._assign_targets(node), [])
        assign = ast.Assign(targets=[ast.Name(id="a", ctx=ast.Store())], value=ast.Constant(1))
        self.assertEqual(len(g._assign_targets(assign)), 1)

    def test_surface_stash(self):
        tree = ast.parse("def setup(ctx):\n    ctx._secret = 1\n    ctx.read_me\n")
        funcs = {("__init__", "setup"): tree.body[0]}
        surface = g._surface(funcs, {("__init__", "setup")})
        self.assertEqual(surface["stash"], {"_secret"})
        # ctx.read_me 同时被当成读；赋值本身不算普通读
        self.assertIn("read_me", surface["reads"])

    def test_find_cycle_no_cycle_and_fallback(self):
        self.assertEqual(g._find_cycle({"a": {"b"}, "b": set()}, ["a"]), ["a"])
        self.assertEqual(g._find_cycle({"a": {"b", "c"}, "b": set(), "c": set()}, ["a"]), ["a"])
        self.assertEqual(g._find_cycle({"a": {"b"}, "b": set()}, ["a", "b"]), ["a", "b"])
        self.assertEqual(g._find_cycle({"a": {"b", "c"}, "b": {"c"}, "c": set()}, ["a"]), ["a"])
        self.assertEqual(g._find_cycle({"a": {"b"}, "b": set()}, ["missing"]), ["missing"])
        self.assertEqual(g._find_cycle({"a": {"b"}, "b": {"a"}}, ["a"]), ["a", "b", "a"])

    def test_toposort_leftover(self):
        meta = {"a": {}, "b": {}}
        edges = {"a": {"b"}, "b": {"a"}}
        order, leftover = g._toposort(meta, edges)
        self.assertEqual(order, [])
        self.assertEqual(leftover, ["a", "b"])
