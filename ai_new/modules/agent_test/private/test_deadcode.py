"""死代码门禁自测：动态引用图该放过的放过、该报红的报红。

覆盖：
(a) 新增一个从未被调用的死函数 → 门禁立刻变红；
(b) 只被 ctx.api.register("x", fn) 绑定、或被需求 yaml call 路由点名的函数 → 不误判；
(d) JS 侧只被 HTML data-* 绑定引用的函数 → 不误判；
另外：门禁不维护人工豁免白名单，未引用定义必须如实上报。
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "gate_deadcode", ROOT / "scripts" / "gate_deadcode.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = _load_gate()


def _kinds(problems):
    return [(p["kind"], p["symbol"]) for p in problems]


class DeadcodeGateTest(unittest.TestCase):
    def test_dead_function_is_reported_red(self):
        src = "def orphan():\n    pass\n"
        result = GATE.scan(py_sources={"mod.py": src})
        self.assertIn(("dead-function", "orphan"), _kinds(result["problems"]))

    def test_register_bound_function_not_dead(self):
        src = (
            "def handler(payload):\n"
            "    return payload\n\n"
            "def setup(ctx):\n"
            "    ctx.api.register(\"x\", handler)\n"
        )
        result = GATE.scan(py_sources={"mod.py": src})
        self.assertNotIn(("dead-function", "handler"), _kinds(result["problems"]))

    def test_demand_route_named_function_not_dead(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            demands = root / "ai_new/modules/agent_common/demand_engine/data/demands"
            demands.mkdir(parents=True)
            (demands / "ops.yaml").write_text(
                "id: ops\ndo:\n  - call: ops.record\n", encoding="utf-8")
            src = "def record():\n    return 1\n"
            result = GATE.scan(root=root, py_sources={"mod.py": src})
            self.assertNotIn(("dead-function", "record"), _kinds(result["problems"]))

    def test_js_html_binding_not_dead(self):
        js = "function helper() {\n    return 1;\n}\n"
        html = '<button data-act="helper">x</button>'
        result = GATE.scan(js_sources={"console/app.js": js}, html_text=html)
        self.assertNotIn(("dead-js-function", "helper"), _kinds(result["problems"]))

    def test_no_manual_allowlist_consumed(self):
        # 扫描器不得读人工豁免清单；模块内不应出现白名单文件路径引用。
        source = (ROOT / "scripts" / "gate_deadcode.py").read_text(encoding="utf-8")
        self.assertNotIn("allow.yaml", source)
        self.assertNotIn("whitelist", source.lower())


if __name__ == "__main__":
    unittest.main()
