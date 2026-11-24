"""改动行覆盖率门禁的解析口径：只认产品代码新增行，可执行性由 coverage 判定。"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location(
    "gate_diff_coverage", ROOT / "scripts" / "gate_diff_coverage.py")
GATE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GATE)


class DiffCoverageParseTest(unittest.TestCase):
    def test_only_product_python_lines_are_counted(self):
        diff = """diff --git a/ai_new/modules/agent/demo/private/_pure.py b/ai_new/modules/agent/demo/private/_pure.py
+++ b/ai_new/modules/agent/demo/private/_pure.py
@@ -1,2 +1,5 @@
 old
+# 注释不算
+
+value = 1
+value = 2
 context
"""
        self.assertEqual(GATE._added_lines(diff),
                         {"ai_new/modules/agent/demo/private/_pure.py": {4, 5}})

    def test_test_code_and_non_python_are_excluded(self):
        diff = """diff --git a/ai_new/modules/agent_test/private/test_x.py b/ai_new/modules/agent_test/private/test_x.py
+++ b/ai_new/modules/agent_test/private/test_x.py
@@ -0,0 +1,2 @@
+def test_x():
+    assert True
diff --git a/ai_new/modules/agent/web/data/console/manage.html b/ai_new/modules/agent/web/data/console/manage.html
+++ b/ai_new/modules/agent/web/data/console/manage.html
@@ -1 +1 @@
-old
+new
"""
        self.assertEqual(GATE._added_lines(diff), {})

    def test_coverage_lookup_uses_executed_and_missing(self):
        report = {"files": {
            str(ROOT / "ai_new/modules/agent/demo/private/_pure.py"): {
                "executed_lines": [2, 4], "missing_lines": [5, 9]}}}
        executed, missing = GATE._coverage_lines(report)[
            "ai_new/modules/agent/demo/private/_pure.py"]
        self.assertEqual(executed, {2, 4})
        self.assertEqual(missing, {5, 9})

    def test_evaluate_ignores_non_executable_and_rejects_low_coverage(self):
        path = "ai_new/modules/agent/demo/private/_pure.py"
        total, covered, gaps, ok = GATE.evaluate(
            {path: {2, 3, 99}}, {path: ({2}, {3})}, 90.0)
        self.assertEqual((total, covered), (2, 1))
        self.assertEqual(len(gaps), 1)
        self.assertFalse(ok)

    def test_unmeasured_new_file_fails_even_when_other_lines_are_covered(self):
        path = "ai_new/modules/agent/newfile.py"
        other = "ai_new/modules/agent/old/pure.py"
        total, covered, gaps, ok = GATE.evaluate(
            {path: {2}, other: {8}}, {other: ({8}, set())}, 90.0)
        self.assertFalse(ok)
        self.assertEqual(total, 2)
        self.assertEqual(len(gaps), 1)

    def test_evaluate_zero_executable_is_pass_but_visible(self):
        path = "ai_new/modules/agent/demo/private/_pure.py"
        total, covered, gaps, ok = GATE.evaluate(
            {path: {99}}, {path: ({10}, {11})}, 90.0)
        self.assertEqual((total, covered, gaps), (0, 0, []))
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
