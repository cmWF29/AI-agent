"""会话纯函数：开局消息、约束/阶段/分派刷新、视图、裁剪、状态机回写与 wire 取文。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.sessions.private import _pure as s  # noqa: E402


class SessionsPureTest(unittest.TestCase):
    def test_seed_and_refresh(self):
        msgs = s._seed("sys", "intro", {"content": "c"})
        self.assertEqual([m["role"] for m in msgs], ["system", "system", "user"])
        self.assertEqual(s._seed("sys", "", None)[0]["content"], "sys")
        msgs = [{"role": "system"}, {"role": "system", "kind": "flow-context"},
                {"role": "user"}]
        out = s.refresh_constraint_message({"messages": msgs, "constraint": {"content": "n"}})
        self.assertEqual(out["messages"][1]["constraint"], {"content": "n"})
        self.assertEqual(len(s.refresh_constraint_message({"messages": msgs})["messages"]), 3)
        self.assertFalse(any(m.get("kind") == "flow-context"
                             for m in s.refresh_constraint_message(
                                 {"messages": [{"role": "user"}],
                                  "constraint": {"content": "x"}})["messages"]))

    def test_refresh_stage(self):
        msgs = [{"role": "user"}, {"role": "system", "content": "old\n\nStage A\nbody"}]
        out = s.refresh_stage_message({"messages": msgs, "stage": "Stage A\nnew"})
        self.assertIn("new", out["messages"][1]["content"])
        out = s.refresh_stage_message({"messages": [{"role": "system", "content": "old"}],
                                       "stage": "S2\nx"})
        self.assertTrue(out["messages"][0]["content"].endswith("S2\nx"))
        self.assertEqual(s.refresh_stage_message({"messages": [], "stage": ""})["messages"], [])
        quiet = s.refresh_stage_message({"messages": [{"role": "system",
                                                       "content": "s"}], "stage": ""})
        self.assertEqual(quiet["messages"][0]["content"], "s")

    def test_inject_assigned(self):
        msgs = [{"role": "user"}, {"role": "system", "content": "head\nold"}]
        out = s.inject_assigned_message({"messages": msgs, "heading": "head",
                                         "roles": [{"role": "a"}, "b", "a", ""]})
        self.assertEqual(out["messages"][1]["content"].count("head"), 1)
        self.assertIn("- b", out["messages"][1]["content"])
        nosys = s.inject_assigned_message({"messages": [{"role": "user"}],
                                           "heading": "h", "roles": ["a"]})
        self.assertEqual(nosys["messages"], [{"role": "user"}])
        other = s.inject_assigned_message({"messages": [{"role": "system",
                                                         "content": "x"}],
                                           "heading": "h", "roles": ["a"]})
        self.assertTrue(other["messages"][0]["content"].endswith("- a"))
        blank = s.inject_assigned_message({"messages": msgs, "heading": "",
                                           "roles": ["a"]})
        self.assertEqual(blank["messages"], [{"role": "user"},
                                             {"role": "system", "content": "head\nold"}])

    def test_build(self):
        rec = s.build({"kind": "role", "seq": 2, "now": 1, "task": "t",
                       "tpl": {"task_heading": "任务"}})
        self.assertEqual(rec["id"], "role-2")
        self.assertIn("任务\nt", rec["messages"][0]["content"])
        s.build({})
        plain = s.build({"kind": "pm", "task": "t"})
        self.assertTrue(plain["messages"][0]["content"].endswith("\n\nt"))
        rec2 = s.build({"kind": "pm", "task": "t", "constraint": {"content": "c"}})
        self.assertEqual(rec2["messages"][1]["kind"], "flow-context")

    def test_machine_brief_and_view(self):
        rec = {"stages": [{"id": "a", "next": ["b"], "terminal": True}, "bad"],
               "meta": {"stages": [{"id": "m"}], "flow": {"x": 1}, "stage": "s",
                        "machine": {"initial": "i"}},
               "machine": "not-dict", "todos": None}
        brief = s.view({"rec": rec})["machine"]
        self.assertEqual(brief["stage"], "s")
        self.assertEqual(brief["initial"], "i")
        self.assertEqual(brief["states"][0]["next"], ["b"])
        self.assertEqual(s.view({"rec": {"machine": {"x": 1}}})["machine"], {"x": 1})
        brief2 = s._machine_brief({})
        self.assertEqual(brief2["states"], [])

    def test_present_screen_gone(self):
        self.assertEqual(s.present({"id": "x", "tpl": "missing {id}"})["error"],
                         "missing x")
        self.assertEqual(s.present({"id": "x"})["error"], "")
        rec = {"id": "1", "status": "running"}
        self.assertEqual(s.present({"rec": rec})["id"], "1")
        out = s.screen({"rows": [None, {"id": "a", "status": "idle"},
                                 {"id": "b", "status": "run"}],
                        "status": "run"})
        self.assertEqual([i["id"] for i in out["items"]], ["b"])
        self.assertEqual(s.gone({"rec": rec, "now": 2})["status"], "gone")

    def test_compact_and_machine_apply(self):
        rec = {"messages": [{"role": "system", "content": "s"},
                            {"role": "user", "content": "u1"},
                            {"role": "user", "content": "u2"}]}
        out = s.compactp({"rec": rec, "keep": "2", "now": 3})
        self.assertEqual([m["content"] for m in out["messages"]], ["s", "u1", "u2"])
        self.assertEqual(s.compactp({"rec": rec, "keep": 0})["messages"][-1]["content"], "u2")
        rec2 = {"meta": {"active": ["x"]}}
        out = s.machine_applyp({"rec": rec2, "contract": {"by_id": {}, "initial": "i"}})
        self.assertEqual(out["meta"]["active"], ["i"])
        out = s.machine_applyp({"rec": rec2, "contract": {"by_id": {"x": 1}}})
        self.assertEqual(out["meta"]["active"], ["x"])
        out = s.machine_applyp({"rec": {}, "contract": {"by_id": {}, "initial": ""}})
        self.assertEqual(out["meta"]["active"], [])

    def test_members_path_and_wire(self):
        out = s.members({"role": "r", "display": "D", "tpl": {"member_user": "我"}})
        self.assertEqual(out["items"][0]["display"], "我")
        self.assertEqual(s.members({"role": "r"})["items"][1]["display"], "r")
        self.assertEqual(s.record_path({"id": "1", "paths": {"session": "s/{id}"}})["path"],
                         "s/1")
        self.assertEqual(s.record_path({"id": "1"})["path"], "1")
        msgs = [{"role": "assistant", "at": 1, "wire": {"url": "u"}},
                {"role": "user", "wire": "bad"}]
        self.assertEqual(s.wire_at({"rec": {"id": "s", "messages": msgs}, "seq": 0})["wire"],
                         {"url": "u"})
        self.assertEqual(s.wire_at({"rec": {"messages": msgs}, "seq": 1})["code"], "no_wire")
        self.assertEqual(s.wire_at({"rec": {"messages": msgs}, "seq": "bad"})["code"],
                         "not_found")
        self.assertEqual(s.wire_at({"rec": {"messages": msgs}, "seq": 9,
                                    "tpl": "bad"})["error"], "bad")
        self.assertEqual(s.role_name({"role": "r", "id": "1"})["name"], "r-1")


if __name__ == "__main__":
    unittest.main()
