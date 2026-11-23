"""图模式纯规则测试：并行分支合并、步数上限语义、门禁拒绝原因、子流程清单归属。

覆盖：
- reducer 合并：覆盖 / 追加去重 / 并集 / 冲突保留左值；默认策略；非 dict 更新忽略；
- 步数上限：到限显式正常收口（exhausted_closed），无上限口径；
- 门禁原因：forbid 命中 / must 未交齐归一成结构化原因，能按契约反查清单原文；
- 子流程清单：归子流程自身校验，父级只汇总 must id；
- 纯规则组合：活跃集合并集 + 到限收口的端到端纯函数编排（不起桩、不联网）。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.graph.private import _pure  # noqa: E402


class MergeBranchUpdatesTest(unittest.TestCase):
    def test_replace_scalar(self):
        out = _pure.merge_branch_updates({
            "state": {"a": 1}, "updates": [{"a": 2}]})
        self.assertEqual(out["state"], {"a": 2})
        self.assertEqual(out["conflicts"], [])
        self.assertEqual(out["merged_keys"], ["a"])

    def test_append_list_dedupe(self):
        out = _pure.merge_branch_updates({
            "state": {"m": [1]}, "updates": [{"m": [1, 2]}],
            "policies": {"m": "append"}})
        self.assertEqual(out["state"]["m"], [1, 2])

    def test_union_active_states(self):
        out = _pure.merge_branch_updates({
            "state": {"active": ["arch.study"]},
            "updates": [{"active": ["arch.design"]}, {"active": ["arch.study"]}],
            "policies": {"active": "union"}})
        self.assertEqual(out["state"]["active"], ["arch.study", "arch.design"])

    def test_conflict_keeps_left_and_records(self):
        out = _pure.merge_branch_updates({
            "state": {"stage": "arch.study"},
            "updates": [{"stage": "arch.design"}, {"stage": "arch.review"}],
            "policies": {"stage": "conflict"}})
        self.assertEqual(out["state"]["stage"], "arch.study")
        self.assertEqual(len(out["conflicts"]), 2)
        self.assertEqual(out["conflicts"][0]["left"], "arch.study")
        self.assertEqual(out["conflicts"][0]["right"], "arch.design")

    def test_default_policy_list_append(self):
        # 未声明策略：标量覆盖，列表追加去重。
        out = _pure.merge_branch_updates({
            "state": {"tags": ["x"]}, "updates": [{"tags": ["x", "y"]}]})
        self.assertEqual(out["state"]["tags"], ["x", "y"])

    def test_non_dict_updates_ignored(self):
        out = _pure.merge_branch_updates({
            "state": {"a": 1}, "updates": [None, "x", {"a": 3}]})
        self.assertEqual(out["state"], {"a": 3})

    def test_unknown_policy_raises(self):
        with self.assertRaises(ValueError):
            _pure.merge_branch_updates({
                "state": {"a": 1}, "updates": [{"a": 2}],
                "policies": {"a": "nope"}})


class StepLimitTest(unittest.TestCase):
    def test_running_under_cap(self):
        out = _pure.step_limit({"steps": 3, "cap": 10})
        self.assertTrue(out["running"])
        self.assertFalse(out["exhausted"])
        self.assertEqual(out["remaining"], 7)
        self.assertEqual(out["outcome"], _pure.RUNNING)

    def test_exhausted_at_cap(self):
        out = _pure.step_limit({"steps": 10, "cap": 10})
        self.assertTrue(out["exhausted"])
        self.assertFalse(out["running"])
        self.assertEqual(out["remaining"], 0)
        self.assertEqual(out["outcome"], _pure.EXHAUSTED_CLOSE)

    def test_unlimited_when_cap_zero(self):
        out = _pure.step_limit({"steps": 99, "cap": 0})
        self.assertFalse(out["exhausted"])
        self.assertIsNone(out["remaining"])
        self.assertTrue(out["running"])

    def test_steps_coerced_int(self):
        out = _pure.step_limit({"steps": "4", "cap": "5"})
        self.assertEqual(out["steps"], 4)
        self.assertEqual(out["cap"], 5)
        self.assertTrue(out["running"])


class GateReasonsTest(unittest.TestCase):
    CONTRACT = {
        "arch.study": {
            "id": "arch.study",
            "gate": {
                "must": [{"id": "arch.study.m1", "text": "读完需求原文并列出约束"}],
                "forbid": [{"id": "arch.study.f1", "text": "研读阶段不产出设计文档"}],
            },
        },
    }

    def test_forbid_and_missing_resolve_text(self):
        out = _pure.gate_reasons({
            "contract": self.CONTRACT,
            "violations": ["arch.study.f1"],
            "missing": ["arch.study.m1"]})
        reasons = out["reasons"]
        self.assertEqual(len(reasons), 2)
        forbid, must = reasons[0], reasons[1]
        self.assertEqual(forbid["kind"], "forbid")
        self.assertEqual(forbid["text"], "研读阶段不产出设计文档")
        self.assertEqual(forbid["state"], "arch.study")
        self.assertEqual(must["kind"], "must")
        self.assertEqual(must["text"], "读完需求原文并列出约束")

    def test_dict_violation_passthrough(self):
        out = _pure.gate_reasons({
            "contract": {},
            "violations": [{"id": "x.f1", "text": "禁止脑补", "state": "s"}],
            "missing": []})
        r = out["reasons"][0]
        self.assertEqual(r["text"], "禁止脑补")
        self.assertEqual(r["state"], "s")

    def test_empty(self):
        out = _pure.gate_reasons({"contract": {}, "violations": [], "missing": []})
        self.assertEqual(out["reasons"], [])


class SubprocessChecklistTest(unittest.TestCase):
    REFS = {
        "requirement-owner": [
            {"id": "req.intake", "gate": {
                "must": [{"id": "req.intake.m1", "text": "收齐目标与边界"}],
                "forbid": ["未澄清前不分单"]}},
            {"id": "req.plan", "gate": {
                "must": [{"id": "req.plan.m1", "text": "明确分工与验收标准"}]}},
        ],
    }

    def test_child_gates_owned_and_rollup(self):
        out = _pure.subprocess_checklist({
            "parent": {"ref": "requirement-owner"}, "refs": self.REFS})
        self.assertEqual(out["ref"], "requirement-owner")
        self.assertEqual(len(out["children"]), 2)
        self.assertEqual(out["owned_child_ids"],
                         ["req.intake.m1", "req.plan.m1"])
        self.assertEqual(out["rollup_must"], ["req.intake.m1", "req.plan.m1"])

    def test_no_ref_empty(self):
        out = _pure.subprocess_checklist({"parent": {}, "refs": self.REFS})
        self.assertEqual(out["ref"], "")
        self.assertEqual(out["children"], [])
        self.assertEqual(out["rollup_must"], [])


class CompositionPureTest(unittest.TestCase):
    """纯规则组合：并行分支活跃集合并集 + 到限收口，模拟状态机/ReAct 收口编排。"""

    def test_active_union_then_close_at_cap(self):
        # 两条并行分支各自并入目标态，活跃集按并集合并（不去丢兄弟态）。
        merged = _pure.merge_branch_updates({
            "state": {"active": ["arch.study"]},
            "updates": [{"active": ["arch.design"]}, {"active": ["arch.review"]}],
            "policies": {"active": "union"}})
        self.assertEqual(
            merged["state"]["active"],
            ["arch.study", "arch.design", "arch.review"])

        # 步数到限：按正常收口，不算 failed / cancelled。
        limit = _pure.step_limit({"steps": 10, "cap": 10})
        self.assertEqual(limit["outcome"], _pure.EXHAUSTED_CLOSE)
        self.assertFalse(limit["running"])

    def test_gate_reasons_feed_rejection_shape(self):
        # 拒绝迁移时：结构化原因带 id 与原文，供视图透出与回催。
        reasons = _pure.gate_reasons({
            "contract": GateReasonsTest.CONTRACT,
            "violations": ["arch.study.f1"],
            "missing": ["arch.study.m1"]})["reasons"]
        self.assertTrue(all(r["id"] for r in reasons))
        self.assertTrue(all(r["text"] for r in reasons))


if __name__ == "__main__":
    unittest.main()
