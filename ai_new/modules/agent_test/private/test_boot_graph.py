"""装配图验收：扫描出的 DAG 必须无环、可复现、覆盖全部模块、面都真的接上。

这些断言盯着的是同事最常犯的退化：把顺序改回手写清单、漏装某个 ctx 面、
或者给模块加上一条没人认领的依赖。
"""
import ast
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.boot.private._boot import _build, _plan  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from _fixtures import module_dir, stage, write_config  # noqa: E402

MODULE_DIR = ROOT / "ai_new" / "modules"


def module_path(name):
    """模块目录（组下面一层）；这里不猜布局，按名字搜。"""
    for group in ("agent_common", "agent", "agent_test"):
        candidate = MODULE_DIR / group / name
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("找不到模块目录: %s" % name)


def module_dirs():
    """运行时模块（按 data/profiles.json 的 agent 剖面读，不维护第二份名单）。"""
    profiles = json.loads((module_dir("agent_common", "boot") / "data" / "profiles.json")
                          .read_text(encoding="utf-8"))
    groups = (profiles.get("profiles") or {}).get("agent") or ["agent_common", "agent"]
    names = []
    for group in groups:
        for entry in sorted((MODULE_DIR / group).iterdir()):
            if (entry.is_dir() and not entry.name.startswith("_")
                    and (entry / "__init__.py").is_file()):
                names.append(entry.name)
    return sorted(names)


class BootGraphTest(unittest.TestCase):
    def test_plan_covers_every_module_except_root(self):
        plan = _plan()
        self.assertIsNone(plan["cycle"], "装配依赖成环: %s" % plan["cycle"])
        self.assertEqual(plan["roots"], ["boot"], "组合根声明丢了")
        expect = [name for name in module_dirs() if name not in plan["roots"]]
        self.assertEqual(sorted(plan["order"]), expect)
        self.assertEqual(len(plan["order"]), len(set(plan["order"])))

    def test_order_respects_every_edge(self):
        plan = _plan()
        index = {name: i for i, name in enumerate(plan["order"])}
        for module, deps in plan["edges"].items():
            for dep in deps:
                self.assertLess(index[dep], index[module],
                                "%s 依赖 %s，但 %s 排在它后面" % (module, dep, module))

    def test_plan_is_deterministic(self):
        self.assertEqual(_plan()["order"], _plan()["order"])

    def test_http_serves_only_in_start_phase(self):
        """监听不在 setup 里发生：http.setup 只绑端口，http.start 才 serve_forever。"""
        source = (module_path("http") / "private" / "_server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        setup_fn = next(n for n in tree.body
                        if isinstance(n, ast.FunctionDef) and n.name == "setup")
        called = [n.attr for n in ast.walk(setup_fn) if isinstance(n, ast.Attribute)]
        self.assertNotIn("serve_forever", called, "setup 里不许开始接收请求")

        import ai_new.modules.agent_common.http as http_module
        self.assertTrue(callable(getattr(http_module, "start", None)),
                        "http 模块必须导出 start(ctx)")

    def test_no_undeclared_ctx_surface(self):
        plan = _plan()
        unresolved = [w for w in plan["warnings"] if "没有模块装填" in w]
        self.assertEqual(unresolved, [],
                         "setup 读了没人装填的 ctx 面（漏了装填它的模块，或拼错了属性名）: %s"
                         % unresolved)

    def test_no_private_state_on_ctx(self):
        """模块私有状态必须放模块自己的 private/_state.py，不许往 ctx 上挂 ctx._xxx。"""
        self.assertEqual(_plan()["stash"], [],
                         "setup 期把私有状态挂在了 ctx 上: %s" % _plan()["stash"])

    def test_no_assembly_labels(self):
        """装配关系不许用模块级标签声明：谁提供 ctx.X 由赋值动作本身说明。"""
        labels = {"PROVIDES", "NEEDS", "PHASE", "ASSEMBLY_ROOT"}
        hits = []
        for name in module_dirs():
            init = module_path(name) / "__init__.py"
            tree = ast.parse(init.read_text(encoding="utf-8"), filename=str(init))
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in labels:
                        hits.append((name, target.id))
        self.assertEqual(hits, [], "装配关系又被写成模块级标签: %s" % hits)

    def test_demands_are_closed_over_hook_points(self):
        """需求层闭合：点、触发、需求三者互相证明，没有"留了不用的点"。"""
        plan = _plan()
        detail = plan["hooks"]
        self.assertEqual(detail["warnings"], [], "需求接线有悬挂: %s" % detail["warnings"])
        covered = set()
        for rec in detail["demands"]:
            if rec["enabled"]:
                covered.update(rec["on"])
        # 每个被触发的点都必须有需求订阅；否则就是在往空气里喊
        unwired = sorted(name for name in detail["emitted"] if name not in covered)
        self.assertEqual(unwired, [], "这些 hook 点被触发了但没有任何需求订阅: %s" % unwired)
        # 声明者必须是名字前缀那个模块
        for name, module in detail["declared"].items():
            self.assertEqual(module, name.split(".")[0],
                             "%s 声明了不属于自己的 hook 点: %s" % (module, name))
        # 反过来：没有需求用的点不该留着（先有需求，才有扩展点）
        unused = sorted(name for name, module in detail["declared"].items()
                        if name not in covered and module not in plan["roots"])
        self.assertEqual(unused, [], "这些 hook 点没有需求使用，应连同 emit 一起删掉: %s" % unused)

    def test_cycle_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name in ("a", "b"):
                directory = base / name
                directory.mkdir()
                other = "b" if name == "a" else "a"
                # a 装填 ctx.a 并读 ctx.b；b 反过来 —— 互相依赖，必成环
                (directory / "__init__.py").write_text(
                    "def setup(ctx):\n"
                    "    ctx.%s = ctx.%s\n" % (name, other), encoding="utf-8")
            plan = _plan(base)
            self.assertIsNotNone(plan["cycle"], "互相依赖的两个模块应该被判成环")
            self.assertEqual(set(plan["cycle"]), {"a", "b"})
            self.assertEqual(plan["cycle"][0], plan["cycle"][-1], "环路径必须首尾相接")

    def test_every_provided_surface_is_wired(self):
        plan = _plan()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage(root)
            write_config(root, {
                "server": {"host": "127.0.0.1", "port": 0, "token": ""},
                "tickets": {"stall_check": {"enabled": False}},
            })
            os.environ["AI_NEW_DATA"] = str(root)
            ctx = Context(root)
            _build(ctx)
            try:
                for attr, owner in plan["providers"].items():
                    self.assertTrue(hasattr(ctx, attr),
                                    "模块 %s 声明了 ctx.%s，但装配后不存在" % (owner, attr))
                self.assertTrue(ctx.api.route("llm.encode"), "llm 没有提供纯语义路由")
                self.assertTrue(ctx.api.route("demand_engine.run"), "编排需求没有入口")
            finally:
                ctx.http.shutdown()
                ctx.http.server_close()
                os.environ.pop("AI_NEW_DATA", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
