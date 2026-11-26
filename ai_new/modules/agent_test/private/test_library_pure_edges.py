"""岗位库纯函数残余分支：分叉后目标已在活跃集、无后继非终态的段渲染、
模板缺项时的清单降级、状态机红线规则行、glob 命中不报缺、工具名单含未登记名。
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.library.private import _pure  # noqa: E402


def _contract(by_id, initial="a"):
    return {"initial": initial, "by_id": by_id}


class StageTransitionResidualTest(unittest.TestCase):
    def test_target_already_active(self):
        """并行分叉：目标态已在活跃集里时不重复并入，仍合法。"""
        by = {
            "a": {"cn": "甲", "next": ["b"], "checks": []},
            "b": {"cn": "乙", "next": [], "terminal": False},
        }
        out = _pure.stage_transitionp({
            "contract": _contract(by),
            "active": ["a", "b"],
            "nxt": ["b"],
        })
        self.assertTrue(out["ok"])
        self.assertEqual(out["active"], ["b"])
        self.assertEqual(out["stage"], "b")


class StageBlockResidualTest(unittest.TestCase):
    def _payload(self, tpl):
        by = {
            "a": {"cn": "甲", "desc": "", "next": [], "terminal": False,
                  "gate": {"must": [{"id": "m1", "text": "交件"}], "forbid": ["抄答案"]}},
        }
        return {"contract": _contract(by), "active": ["a"], "tpl": tpl}

    def test_missing_forbid_template_skips_line(self):
        """模板无 forbid 句式：红线项不生成空行，must 清单照常输出并带总则。"""
        out = _pure.stage_blockp(self._payload({
            "heading_stage": "当前阶段",
            "stage_current": "【{id}】{cn}",
            "gate_must": "- [ ] {id} {text}",
            "gate_forbid": "",
            "heading_gate": "本步清单",
            "gate_rule": "清单未清不得转移",
        }))
        text = out["system"]
        self.assertIn("【a】甲", text)
        self.assertIn("- [ ] m1 交件", text)
        self.assertNotIn("抄答案", text)
        self.assertIn("清单未清不得转移", text)

    def test_missing_must_template_skips_line(self):
        """模板无 must 句式：打勾项不生成空行，只有红线行，也不带总则。"""
        out = _pure.stage_blockp(self._payload({
            "heading_stage": "当前阶段",
            "stage_current": "【{id}】{cn}",
            "gate_must": "",
            "gate_forbid": "- 禁止：{text}",
            "heading_gate": "本步清单",
        }))
        text = out["system"]
        self.assertIn("- 禁止：抄答案", text)
        self.assertNotIn("m1", text)


class FlowContextResidualTest(unittest.TestCase):
    def test_gate_rule_after_gate_lines(self):
        """流程约束块：清单非空且模板给总则时，总则行随清单一起下发。"""
        by = {
            "a": {"cn": "甲", "desc": "", "next": ["b"], "gate": {
                "must": [{"id": "m1", "text": "交件"}], "forbid": ["抄答案"]}},
            "b": {"cn": "乙", "next": [], "terminal": True},
        }
        out = _pure.flow_contextp({
            "contract": _contract(by),
            "active": ["a"],
            "flow": {"id": "f1", "cn": "流程一"},
            "tpl": {
                "heading_flow_context": "流程约束",
                "flow_name": "流程 {cn}（{id}）",
                "stage_current": "【{id}】{cn}",
                "heading_gate": "本步清单",
                "gate_must": "- [ ] {id} {text}",
                "gate_forbid": "- 禁止：{text}",
                "gate_rule": "清单未清不得转移",
            },
        })
        content = out["content"]
        self.assertIn("- [ ] m1 交件", content)
        self.assertIn("- 禁止：抄答案", content)
        self.assertIn("清单未清不得转移", content)
        self.assertEqual([s["id"] for s in out["states"]], ["a", "b"])


class StageTransitionNoteResidualTest(unittest.TestCase):
    def test_note_check_satisfied(self):
        """note 类交付条件：备注长度达标即放行，不再报缺。"""
        by = {
            "a": {"cn": "甲", "next": ["b"], "terminal": False,
                  "checks": [{"kind": "note", "min_len": 3}]},
            "b": {"cn": "乙", "next": [], "terminal": True},
        }
        out = _pure.stage_transitionp({
            "contract": _contract(by),
            "active": ["a"],
            "nxt": ["b"],
            "notes": ["本轮结论写完了"],
            "tpl": {},
        })
        self.assertTrue(out["ok"])
        self.assertEqual(out["active"], ["b"])


class FlowContextTerminalResidualTest(unittest.TestCase):
    def test_plain_active_state_without_next(self):
        """活跃态既无后继也非终态：只出境况行，不追加迁移行。"""
        by = {"a": {"cn": "甲", "desc": "", "next": [], "terminal": False}}
        out = _pure.flow_contextp({
            "contract": _contract(by),
            "active": ["a"],
            "tpl": {"heading_flow_context": "流程约束", "stage_current": "【{id}】{cn}"},
        })
        self.assertEqual(out["content"], "流程约束\n【a】甲")

    def test_checks_without_heading(self):
        """流程约束块：验收规则非空但模板不给标题时，规则照列不造标题。"""
        by = {"a": {"cn": "甲", "next": [], "terminal": True}}
        out = _pure.flow_contextp({
            "contract": _contract(by),
            "active": ["a"],
            "checks": [{"kind": "glob", "paths": ["*.md"]}],
            "tpl": {"stage_current": "【{id}】{cn}"},
        })
        self.assertTrue(out["content"].startswith("【a】甲"))
        self.assertEqual(len(out["checks"]), 1)
        self.assertIn("- ", out["content"])

    def test_gate_lines_without_rule(self):
        """有清单但模板不给总则：只下发清单，不补规则行。"""
        by = {
            "a": {"cn": "甲", "next": [], "terminal": True,
                  "gate": {"must": [{"id": "m1", "text": "交件"}]}},
        }
        out = _pure.flow_contextp({
            "contract": _contract(by),
            "active": ["a"],
            "tpl": {"heading_gate": "本步清单", "gate_must": "- [ ] {id} {text}"},
        })
        self.assertIn("本步清单", out["content"])
        self.assertIn("- [ ] m1 交件", out["content"])


class CheckGlobResidualTest(unittest.TestCase):
    def test_glob_matched_reports_nothing(self):
        """glob 条件已命中：不报缺，checked 计数仍为规则条数。"""
        out = _pure.checkp({
            "rec": {"checks": [{"kind": "glob", "paths": ["*.md"], "match": "all"}]},
            "files": ["a.md"],
            "tpl": {"missing_any": "缺文件"},
        })
        self.assertEqual(out["missing"], [])
        self.assertEqual(out["checked"], 1)


class CheckHeadingResidualTest(unittest.TestCase):
    def test_checks_without_heading(self):
        """有验收规则但模板不给标题：规则直接列出，不造标题行。"""
        out = _pure.checkp({
            "rec": {"checks": [{"kind": "contains", "text": "结论"}]},
            "files": ["a.md"],
            "contents": {"a.md": "有结论"},
            "tpl": {},
        })
        self.assertEqual(out["missing"], [])
        self.assertEqual(out["checked"], 1)


class SkillUninstallResidualTest(unittest.TestCase):
    def test_tool_name_not_registered(self):
        """登记名单里有未落地的工具名：跳过不报错，已登记的工具被摘除。"""
        out = _pure.skill_uninstallp({
            "id": "s1",
            "skills": {"s1": {"tools": ["t1", "ghost"], "role": "", "flow": ""}},
            "tools": {"t1": {"name": "一"}, "t2": {"skill": "s1"}},
        })
        self.assertEqual(out["tools"], {})
        self.assertEqual(out["removed"]["tools"], ["t1", "ghost"])

    def test_non_dict_tool_entry_kept(self):
        """工具字典里存在非字典项：按 skill 归属清理时跳过，不误删。"""
        out = _pure.skill_uninstallp({
            "id": "s1",
            "skills": {"s1": {"tools": []}},
            "tools": {"t-shadow": "占位"},
        })
        self.assertEqual(out["tools"], {"t-shadow": "占位"})


class SetupResidualTest(unittest.TestCase):
    def test_setup_registers_all_routes(self):
        """装配：26 条岗位库路由按名登记到 library 模块。"""
        class Api:
            def __init__(self):
                self.rows = []

            def register(self, name, fn, module=""):
                self.rows.append((name, module))

        from ai_new.modules.agent import library
        api = Api()
        self.assertTrue(library.setup(types.SimpleNamespace(api=api)))
        self.assertEqual(len(api.rows), 26)
        self.assertTrue(all(m == "library" for _, m in api.rows))


if __name__ == "__main__":
    unittest.main()
