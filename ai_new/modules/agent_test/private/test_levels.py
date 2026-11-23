# -*- coding: utf-8 -*-
"""层级判定门禁契约测试：判定表完整性、center/node 互斥、命名空间不变量、证据真实。

覆盖：
- 判定表完整性：capability-routes + platform-routes 全部能力已登记，无悬空条目；
- 互斥规则：node 级不在中心平台路由，center 级不在节点专属通道；
- 命名空间不变量：knowledge/library 必须 center，sandbox/host/exec 必须 node；
- 证据文件逐条真实存在；
- 负向用例：构造错误声明，断言校验函数返回违规。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

import gate_levels  # noqa: E402

CAP_DOC = gate_levels._load(gate_levels.CAP_YAML)
PLAT_DOC = gate_levels._load(gate_levels.PLAT_YAML)
LEVELS_DOC = gate_levels._load(gate_levels.LEVELS_YAML)
UNIVERSE = gate_levels.build_universe(CAP_DOC, PLAT_DOC)
LEVELS = LEVELS_DOC.get("levels") or {}


class LevelsCompletenessTest(unittest.TestCase):
    def test_every_capability_declared(self):
        missing = [name for name in UNIVERSE if name not in LEVELS]
        self.assertEqual(missing, [], "未登记层级声明：%s" % missing)

    def test_no_orphan_declarations(self):
        orphan = [name for name in LEVELS if name not in UNIVERSE]
        self.assertEqual(orphan, [], "层级表悬空条目：%s" % orphan)

    def test_declaration_shape(self):
        for name, decl in LEVELS.items():
            self.assertIn(decl.get("level"), gate_levels.VALID_LEVELS, name)
            self.assertTrue(str(decl.get("why") or "").strip(), "%s 缺 why" % name)
            self.assertTrue(decl.get("evidence"), "%s 缺 evidence" % name)


class LevelsMutexTest(unittest.TestCase):
    def test_node_not_in_center_platform_route(self):
        platform = PLAT_DOC.get("routes") or {}
        bad = []
        for name, decl in LEVELS.items():
            if decl.get("level") == "node" and name in platform:
                if gate_levels._is_center_facing(platform[name]):
                    bad.append("%s(caller=%s)" % (name, platform[name].get("caller")))
        self.assertEqual(bad, [], "node 级能力出现在中心平台路由：%s" % bad)

    def test_center_not_in_node_channel(self):
        platform = PLAT_DOC.get("routes") or {}
        bad = []
        for name, decl in LEVELS.items():
            if decl.get("level") == "center" and name in platform:
                if gate_levels._is_node_channel(name, platform[name]):
                    bad.append(name)
        self.assertEqual(bad, [], "center 级能力登记在节点专属通道：%s" % bad)


class LevelsNamespaceTest(unittest.TestCase):
    def test_knowledge_library_center(self):
        for name, decl in LEVELS.items():
            if name.startswith(("knowledge.", "library.")):
                self.assertEqual(decl.get("level"), "center", name)

    def test_sandbox_host_exec_node(self):
        for name, decl in LEVELS.items():
            if name.startswith(("sandbox.", "host.", "exec.")):
                self.assertEqual(decl.get("level"), "node", name)


class LevelsEvidenceTest(unittest.TestCase):
    def test_evidence_files_exist(self):
        missing = []
        for name, decl in LEVELS.items():
            for rel in decl.get("evidence") or []:
                if not (ROOT / str(rel)).exists():
                    missing.append("%s -> %s" % (name, rel))
        self.assertEqual(missing, [], "证据文件不存在：%s" % missing)


class LevelsNegativeTest(unittest.TestCase):
    def _evaluate(self, levels):
        return gate_levels.evaluate(UNIVERSE, {"levels": levels}, PLAT_DOC, ROOT)

    def test_missing_declaration_flagged(self):
        violations = self._evaluate({})
        codes = {(v.code, v.capability) for v in violations}
        self.assertIn(("L1", next(iter(UNIVERSE))), codes)

    def test_wrong_namespace_level_flagged(self):
        levels = dict(LEVELS)
        # knowledge.* 错标 node
        for name in list(levels):
            if name.startswith("knowledge."):
                levels[name] = dict(levels[name], level="node")
        violations = gate_levels.evaluate(UNIVERSE, {"levels": levels}, PLAT_DOC, ROOT)
        self.assertTrue(any(v.code == "L4" for v in violations), "L4 命名空间不变量未命中")

    def test_node_in_center_route_flagged(self):
        levels = dict(LEVELS)
        # 找一个中心平台路由上的能力，错标 node
        platform = PLAT_DOC.get("routes") or {}
        target = next(iter(platform))
        levels[target] = dict(levels.get(target) or {"why": "x", "evidence": []}, level="node")
        violations = gate_levels.evaluate(UNIVERSE, {"levels": levels}, PLAT_DOC, ROOT)
        self.assertTrue(any(v.code == "L2" and v.capability == target for v in violations),
                        "L2 跨节点不可见未命中")

    def test_bad_evidence_flagged(self):
        levels = dict(LEVELS)
        target = next(iter(levels))
        levels[target] = dict(levels[target], evidence=["ai_new/modules/agent/does-not-exist.py"])
        violations = gate_levels.evaluate(UNIVERSE, {"levels": levels}, PLAT_DOC, ROOT)
        self.assertTrue(any(v.code == "L5" and v.capability == target for v in violations),
                        "L5 证据不存在未命中")


if __name__ == "__main__":
    unittest.main()
