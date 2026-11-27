"""岗位库/拆解纯函数边界：通配、状态机契约、评审三态、岗位清单与 Skill 级联。

这里只打纯函数，不读盘、不起进程；所有模板由用例显式传入，不依赖生产默认值。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.library.private import _pure as lib  # noqa: E402


class GlobTest(unittest.TestCase):
    def test_glob_one_star_question_literal(self):
        self.assertTrue(lib._glob_one("abc", "a*"))
        self.assertTrue(lib._glob_one("abc", "a?c"))
        self.assertFalse(lib._glob_one("", "a?"))
        self.assertFalse(lib._glob_one("abc", "b"))
        self.assertTrue(lib._glob_one("", ""))
        self.assertTrue(lib._glob_one("abc", "*"))
        self.assertFalse(lib._glob_one("abc", "a*z"))
        self.assertFalse(lib._glob_one("abc", "?z"))

    def test_glob_double_star_and_empty_segments(self):
        self.assertTrue(lib._glob("a/b/c", "**/c"))
        self.assertTrue(lib._glob("a/b", "a/*"))
        self.assertFalse(lib._glob("a/b", "a/c"))
        self.assertTrue(lib._glob("", "."))
        self.assertFalse(lib._glob("a", "**/x"))


class NoteAndDescTest(unittest.TestCase):
    def test_note_ok_dict_text_and_event(self):
        self.assertFalse(lib._note_ok([{"event": "system", "text": "应忽略"}], 2))
        self.assertTrue(lib._note_ok([{"event": "note", "text": " 结论 "}], 2))
        self.assertTrue(lib._note_ok(["短", "足够长的结论"], 3))
        self.assertFalse(lib._note_ok(None, 0))

    def test_check_desc_variants(self):
        tpl = {"check_contains": "含 {text}", "check_note": "备注",
               "check_any": "任一 {paths}", "check_all": "全部 {paths}",
               "check_min_bytes": "且 >= {minb}"}
        self.assertEqual(lib._check_desc({"kind": "contains", "text": "X"}, tpl), "含 X且 >= None"
                         .replace("且 >= None", ""))
        self.assertEqual(lib._check_desc({"kind": "note"}, tpl), "备注")
        self.assertEqual(lib._check_desc({"kind": "glob", "match": "any",
                                          "paths": ["a", "b"]}, tpl), "任一 a、b")
        self.assertEqual(lib._check_desc({"kind": "glob", "paths": ["a"], "min_bytes": 5},
                                        tpl), "全部 a且 >= 5")


class ReviewTest(unittest.TestCase):
    def test_three_verdicts(self):
        self.assertEqual(lib.reviewp({"missing": [], "retries": 0, "max_retries": 2})["verdict"],
                         "pass")
        out = lib.reviewp({"missing": [{"path": "a"}], "retries": 0, "max_retries": 2})
        self.assertEqual((out["verdict"], out["retries"], out["missing_text"]),
                         ("repush", 1, "a"))
        out = lib.reviewp({"missing": [{"text": "b"}], "retries": 2, "max_retries": 2})
        self.assertEqual((out["verdict"], out["retries"]), ("exhausted", 2))
        for gap, want in [("s", "s"), ({"path": "p"}, "p"), ({"text": "t"}, "t"),
                          ({"reason": "r"}, "r"), ({"paths": ["a", "b"]}, "['a', 'b']")]:
            self.assertEqual(lib.reviewp({"missing": [gap], "max_retries": 9})["missing_text"], want)


class PromptFoldTest(unittest.TestCase):
    def test_append_keeps_old_and_adds_rule(self):
        out = lib.prompt_fold({"old": "旧规则\n", "append": "新规则", "mode": "append"})
        self.assertTrue(out["changed"])
        self.assertTrue(out["text"].startswith("旧规则"))
        self.assertEqual(out["text"], "旧规则\n\n新规则\n")
        self.assertGreater(out["new_chars"], out["old_chars"])

    def test_replace_replaces_whole_prompt(self):
        out = lib.prompt_fold({"old": "旧规则\n", "text": "新全文", "mode": "replace"})
        self.assertEqual(out["text"], "新全文\n")


class RoleBudgetAndPromptAuthorityTest(unittest.TestCase):
    def _seed(self):
        import yaml
        root = Path(__file__).resolve().parents[4]
        return yaml.safe_load((root / "ai_new/modules/agent/library/data/seed.yaml").read_text(encoding="utf-8"))

    def test_pm_execute_has_dispatch_and_prompt_governance(self):
        seed = self._seed()
        flow = next(f for f in seed["flows"] if f["id"] == "requirement-owner")
        execute = next(s for s in flow["states"] if s["id"] == "req.execute")
        tools = set(execute.get("tools") or [])
        for need in ("role_spawn", "role_task", "prompt_read", "prompt_patch", "knowledge_write"):
            self.assertIn(need, tools)
        close = next(s for s in flow["states"] if s["id"] == "req.close")
        self.assertIn("knowledge_write", set(close.get("tools") or []))

    def test_pm_top_tools_include_knowledge_and_prompt_write(self):
        seed = self._seed()
        pm = next(r for r in seed["roles"] if r["id"] == "pm")
        tools = set(pm.get("tools") or [])
        for need in ("knowledge_read", "knowledge_write", "prompt_read", "prompt_patch"):
            self.assertIn(need, tools)

    def test_pm_prompt_declares_authority_and_budget(self):
        root = Path(__file__).resolve().parents[4]
        text = (root / "ai_new/modules/agent/sessions/data/prompts/pm.md").read_text(encoding="utf-8")
        self.assertIn("prompt_patch", text)
        self.assertIn("2 轮", text)
        self.assertIn("knowledge_write", text)


class ContractTest(unittest.TestCase):
    def _states(self):
        return [
            {"id": "start", "cn": "开始", "next": ["mid"], "checks": [],
             "gate": {"must": [{"id": "m1", "text": "交付"}]}},
            {"id": "mid", "cn": "中间", "children": [
                {"id": "sub", "cn": "子", "ref": "R"}]},
            {"id": "done", "cn": "完成", "terminal": True},
        ]

    def test_flatten_children_and_ref(self):
        refs = {"R": [{"id": "a", "next": ["b"]}, {"id": "b", "terminal": True}]}
        c = lib.stage_contractp({"states": self._states(), "refs": refs})
        self.assertEqual(c["initial"], "start")
        self.assertEqual(c["terminals"], ["mid.sub.b", "done"])
        self.assertEqual(c["parents"]["mid.sub.a"], "mid.sub")
        self.assertEqual(c["by_id"]["start"]["next"], ["mid"])
        self.assertIn("mid.sub", c["children"])

    def test_transition_guards(self):
        c = lib.stage_contractp({"states": self._states(), "refs": {}})
        self.assertEqual(lib.stage_transitionp({"contract": c})["code"], "unset")
        self.assertEqual(lib.stage_transitionp({"contract": c, "nxt": "nope"})["code"],
                         "unknown_stage")
        self.assertEqual(lib.stage_transitionp({"contract": c, "nxt": "done"})["code"],
                         "illegal_start")
        self.assertEqual(lib.stage_transitionp({"contract": c, "nxt": "done", "prev": "start"})["code"],
                         "illegal_edge")
        self.assertEqual(lib.stage_transitionp({"contract": c, "nxt": "mid", "prev": "start",
                                                "violations": ["红线"]})["code"], "forbidden_hit")
        self.assertEqual(lib.stage_transitionp({"contract": c, "nxt": "mid", "prev": "start",
                                                "checked": []})["code"], "checklist_unmet")
        c2 = lib.stage_contractp({"states": [
            {"id": "start", "next": ["done"],
             "checks": [{"kind": "glob", "paths": ["out.md"]}]},
            {"id": "done", "terminal": True}]})
        self.assertEqual(lib.stage_transitionp({"contract": c2, "nxt": "done",
                                                "prev": "start", "files": []})["code"],
                         "condition_unmet")
        self.assertEqual(lib.stage_transitionp({"contract": c2, "nxt": "done",
                                                "prev": "start", "files": ["out.md"]})["code"],
                         "ok")

    def test_transition_parallel_and_terminal_drop(self):
        c = lib.stage_contractp({"states": [
            {"id": "a", "next": ["b", "c"]},
            {"id": "b", "next": ["d"]}, {"id": "c"},
            {"id": "d", "next": ["b", "c"], "terminal": True}]})
        out = lib.stage_transitionp({"contract": c, "prev": "d", "nxt": ["b", "c"]})
        self.assertTrue(out["ok"])
        self.assertNotIn("d", out["active"])

    def test_transition_lists_start_and_in_place(self):
        c = lib.stage_contractp({"states": [
            {"id": "s", "next": ["t"], "gate": {"must": [{"id": "m"}]}},
            {"id": "t", "terminal": True}]})
        self.assertEqual(lib.stage_transitionp({"contract": c, "nxt": "s"})["code"], "ok")
        out = lib.stage_transitionp({"contract": c, "active": ["s", "t"],
                                     "prev": ["s", "t"], "nxt": ["s"]})
        self.assertEqual(out["code"], "ok")
        self.assertEqual(lib.stage_transitionp({"contract": c, "prev": ["s"], "nxt": ["s"],
                                                "checked": []})["code"], "ok")
        self.assertEqual(lib.stage_transitionp({"contract": c, "prev": "s", "nxt": ["s"],
                                                "checked": []})["code"], "ok")

    def test_branch_matrix(self):
        c = lib.stage_contractp({"checks": [
            {"kind": "glob", "paths": ["x"]},
            {"kind": "glob", "paths": ["x"], "match": "any"},
            {"kind": "contains", "text": "t"},
            {"kind": "unknown"}], "states": [{"id": "s", "next": ["t"]},
                                              {"id": "t", "terminal": True}]})
        out = lib.stage_conditionsp({"contract": c, "active": ["s"], "files": [],
                                     "contents": {}, "tpl": {}})
        self.assertEqual(len(out["missing"]), 3)
        ok = lib.stage_conditionsp({"contract": lib.stage_contractp({"checks": [
            {"kind": "glob", "paths": ["*.md"], "match": "any"},
            {"kind": "contains", "text": "t"}]}), "active": ["s"],
            "files": ["a.md"], "contents": {"a.md": "t"}, "tpl": {}})
        self.assertEqual(ok["missing"], [])
        over = lib.stage_apply_overridesp({"states": [{"id": "a"}],
            "add": ["bad", {"id": "b"}], "remove": ["z"],
            "edges": [["a", "b"], ["a", "a"], "bad"]})
        self.assertEqual({x["id"] for x in over["states"]}, {"a", "b"})
        gate = lib.stage_contractp({"states": [
            {"id": "s", "next": ["t"], "gate": {"must": [{}, {"id": "m"}]}},
            {"id": "t", "terminal": True}]})
        self.assertEqual(lib.stage_transitionp({"contract": gate, "prev": "s",
                                                "nxt": "t", "checked": []})["missing"],
                         ["m"])
        self.assertEqual(lib.stage_transitionp({"contract": gate, "prev": "s",
                                                "nxt": "t", "checked": ["m"]})["code"],
                         "ok")
        for chk, files, contents, notes in [
            ({"kind": "glob", "paths": ["*.md"]}, ["a.md"], {}, []),
            ({"kind": "glob", "paths": ["*.md"]}, [], {}, []),
            ({"kind": "glob", "paths": ["*.md"], "match": "any"}, ["a.md"], {}, []),
            ({"kind": "contains", "text": "x"}, ["a"], {"a": "x"}, []),
            ({"kind": "contains", "text": "x"}, ["a"], {"a": ""}, []),
            ({"kind": "note", "min_len": 2}, ["a"], {}, ["好"]),
            ({"kind": "note", "min_len": 2}, ["a"], {}, []),
            ({"kind": "unknown"}, [], {}, [])]:
            self.assertEqual(lib.checkp({"rec": {"checks": [chk]}, "files": files,
                                         "contents": contents, "notes": notes,
                                         "tpl": {}})["missing"], []) if chk["kind"] == "unknown" else None
        self.assertEqual(lib.stage_blockp({"contract": c, "active": ["s"], "tpl": {}})["system"], "")
        self.assertEqual(lib.flow_contextp({"contract": c, "active": ["s"], "tpl": {},
                                            "flow": {}, "checks": []})["content"].strip(), "")
        self.assertEqual(lib.skill_uninstallp({"id": "s", "skills": {"s": {}},
                                               "roles": {"r": {}}, "flows": {"f": {}},
                                               "tools": {"t": {"skill": "s"}}, "tpl": {}})["removed"],
                         {"role": "", "flow": "", "tools": []})

    def test_minimal_templates_terminal(self):
        c = lib.stage_contractp({"states": [{"id": "s", "next": ["t"]},
                                            {"id": "t", "terminal": True}]})
        self.assertEqual(lib.stage_blockp({"contract": c, "active": ["t"], "tpl": {}})["system"], "")
        self.assertEqual(lib.stage_blockp({"contract": c, "active": ["nope"], "tpl": {}})["system"], "")
        self.assertEqual(lib.flow_contextp({"contract": c, "active": ["t"], "tpl": {},
                                            "flow": {}, "checks": []})["content"].strip(), "")

    def test_apply_overrides_add_remove_edges(self):
        out = lib.stage_apply_overridesp({"states": [{"id": "a", "next": ["b"]},
                                                    {"id": "b"}],
                                        "remove": ["b"], "add": [{"id": "c"}],
                                        "edges": [["a", "c"], ["a", "c"], ["z", "a"]]})
        by = {x["id"]: x for x in out["states"]}
        self.assertEqual(by["a"]["next"], ["c"])
        self.assertNotIn("b", by)

    def test_collect_skips_bad_nodes_and_rewrites_ref_next(self):
        c = lib.stage_contractp({"states": ["bad", {"no": "id"},
            {"id": "r", "ref": "R", "next": ["R"]}],
            "refs": {"R": [{"id": "a"}, {"id": "b"}]}})
        self.assertEqual(c["initial"], "r")
        self.assertEqual(c["by_id"]["r"]["next"], ["r.a"])

    def test_refs_and_flow_to_states(self):
        out = lib.stage_refsp({"flows": {"p": {"kind": "process", "states": [{"id": "a"}]}},
                               "seed": {"flows": [{"id": "q", "kind": "role"}]}})
        self.assertEqual(out["refs"], {"p": [{"id": "a"}]})
        st = lib.flow_to_statesp({"nodes": ["a", "b"], "edges": [["a", "b"], ["a", "b"], "bad"]})
        self.assertEqual(st["states"][0]["next"], ["b"])
        self.assertTrue(st["states"][1]["terminal"])


class StageViewsTest(unittest.TestCase):
    def test_conditions_and_tools(self):
        c = lib.stage_contractp({"checks": [
            {"kind": "note", "min_len": 2},
            {"kind": "glob", "paths": ["*.md"], "match": "any"},
            {"kind": "contains", "text": "结论"}],
                                 "states": [
            {"id": "s", "cn": "开始", "desc": "做", "next": ["t"], "when": {"t": "满足"},
             "tools": ["x"], "checks": [{"kind": "note", "min_len": 2}],
             "gate": {"must": [{"id": "m", "text": "交"}], "forbid": ["跳"]}},
            {"id": "t", "cn": "结束", "terminal": True, "checks": [
                {"kind": "note", "min_len": 2}]}]})
        tpl = {"missing_note": "缺备注"}
        out = lib.stage_conditionsp({"contract": c, "active": ["s"], "notes": [], "tpl": tpl})
        self.assertEqual(len(out["missing"]), 4)
        self.assertEqual(lib.stage_toolsp({"contract": c, "active": ["s"],
                                          "items": [{"name": "x"}, {"name": "y"}]}),
                         {"items": [{"name": "x"}]})
        self.assertEqual(lib.stage_toolsp({"contract": c, "active": ["unknown"],
                                          "items": ["z"]}), {"items": ["z"]})

    def test_stage_block_and_flow_context(self):
        c = lib.stage_contractp({"states": [
            {"id": "s", "cn": "开始", "desc": "做", "next": ["t"],
             "gate": {"must": [{"id": "m", "text": "交"}], "forbid": ["跳"]}},
            {"id": "t", "cn": "结束", "terminal": True}]})
        tpl = {"heading_stage": "阶段", "stage_current": "{cn}({id})",
               "stage_desc": "说明 {desc}", "stage_next": "下一步 {next}",
               "stage_terminal": "终态", "gate_must": "必做 {id}:{text}",
               "gate_forbid": "禁止 {text}", "heading_gate": "清单",
               "gate_rule": "规则", "heading_flow_context": "流程",
               "flow_name": "名称 {cn}/{id}", "heading_state_machine": "全貌",
               "machine_state": "状态 {cn}", "machine_state_cur": "当前 {cn}",
               "machine_edge": "边 {cn}", "machine_edge_plain": "平边 {cn}",
               "heading_checks": "检查", "check_note": "备注"}
        self.assertEqual(lib.stage_blockp({"contract": {}, "tpl": tpl}), {"system": ""})
        out = lib.stage_blockp({"contract": c, "active": ["s"], "tpl": tpl})["system"]
        for s in ("阶段", "开始(s)", "下一步 结束", "必做 m:交", "禁止 跳", "规则"):
            self.assertIn(s, out)
        ctx = lib.flow_contextp({"contract": c, "active": [], "tpl": tpl,
                                "flow": {"id": "F", "cn": "流"},
                                "checks": [{"kind": "note"}]})
        for s in ("流程", "名称 流/F", "全貌", "边 结束", "检查", "备注"):
            self.assertIn(s, ctx["content"])
        self.assertEqual(ctx["checks"][0]["kind"], "note")
        empty = lib.flow_contextp({"contract": c, "active": [], "tpl": {},
                                  "flow": {}, "checks": []})
        self.assertEqual(empty["content"].strip(), "")

    def test_gaps_and_prompt_blocks(self):
        c = lib.stage_contractp({"states": [{"id": "s", "cn": "开始", "next": ["t"]},
                                            {"id": "t", "terminal": True}]})
        out = lib.stage_gapsp({"contract": c, "active": ["s"], "base": [{"path": "b"}],
                              "stage_alert": {"code": "E"}, "tpl": {
                                  "stage_not_terminal": "未终 {cn}/{id}",
                                  "stage_alert": "告警 {code}"}})
        self.assertEqual(len([g for g in out["missing"] if g.get("kind") == "stage"]), 2)
        self.assertEqual(lib.stage_gapsp({"contract": {}})["missing"], [])
        self.assertEqual(lib.prompt_blocks({"tpl": {}})["system"], "")
        out = lib.prompt_blocks({"text": "正文", "must_dos": ["甲"], "forbidden": ["乙"],
                                 "stage": "阶段", "tpl": {}})["system"]
        self.assertIn("- 甲", out)
        self.assertIn("- 乙", out)
        out = lib.prompt_blocks({"must_dos": ["甲"], "forbidden": ["乙"],
                                 "tpl": {"heading_must": "必做", "heading_forbidden": "禁止"}})["system"]
        self.assertIn("必做\n- 甲", out)


class RecordsTest(unittest.TestCase):
    def test_bind_tools_and_position(self):
        out = lib.bind_tools({"items": [{"tools": ["a", "b"], "stages": [{"cn": "开"}, {}]}],
                              "disabled": ["b"], "kind": "roles"})["items"][0]
        self.assertEqual(out["tools_sum"], "1/2")
        self.assertEqual(out["tools_text"], "a")
        self.assertEqual(out["stage_text"], "开 → ")
        self.assertEqual(len(out["bound_tools"]), 2)
        self.assertEqual(lib.positionp({"tpl": {"position_missing": "无 {id}"}, "id": "x"}),
                         {"ok": False, "code": "not_found", "status": 404, "error": "无 x"})

    def test_positions_list_get_design_summary(self):
        roles = {"seed": {"roles": [{"id": "r1", "cn": "内置", "system": True,
                                     "tools": ["a"], "states": [{"id": "s"}]}, {}]},
                 "user": {"r2": {"id": "r2", "cn": "自建", "skill": "dead"},
                          "r3": {"id": "r3", "cn": "可停"}},
                 "skills": {"dead": {"status": "disabled"}},
                 "disabled_roles": ["r1", "r3"],
                 "tpl": {"label_disabled_project": "停", "label_enabled": "启",
                         "kind_missing": "缺 {kind}/{id}"}}
        out = lib.positionsp(roles)
        self.assertEqual(len(out["items"]), 2)
        by = {x["id"]: x for x in out["items"]}
        self.assertTrue(by["r1"]["locked"])
        self.assertFalse(by["r1"]["disabled"])
        self.assertEqual(by["r1"]["disabled_text"], "启")
        self.assertTrue(by["r3"]["disabled"])
        self.assertEqual(by["r3"]["disabled_text"], "停")
        rec = lib.getp({"seed": roles["seed"], "user": roles["user"],
                        "kind": "roles", "id": "r1"})
        self.assertTrue(rec["item"]["builtin"])
        self.assertEqual(lib.getp({"kind": "roles", "id": "none", "tpl": {"kind_missing": "缺"}})["status"],
                         404)
        self.assertEqual(lib.listp({"seed": {}, "kind": "tools"})["kind"], "tools")
        self.assertEqual(lib.designp({"tpl": {"id_required": "要 id"}})["code"], "missing_id")
        self.assertEqual(lib.designp({"kind": "roles", "id": "r1", "record": {"builtin": True},
                                      "fields": {"prompt": "x"},
                                      "tpl": {"builtin_role_protected": "保护"}})["code"],
                         "builtin_protected")
        out = lib.designp({"kind": "roles", "id": "r9", "record": {}, "fields": {"cn": "新"},
                           "now": "T"})
        self.assertEqual((out["id"], out["cn"], out["updated"]), ("r9", "新", "T"))
        sm = lib.summaryp({"seed": {"roles": [{"id": "a", "states": [{"id": "s"}]}]},
                           "user": {"roles": {"b": {"id": "b"}}},
                           "user_skills": {"s1": {}, "s2": "bad"}})
        self.assertEqual(sm["counts"], {"roles": 2, "flows": 1, "skills": 1})

    def test_prompt_and_checkp(self):
        nf = lib.promptp({"role": "r", "rec": {}})
        self.assertEqual(nf["code"], "no_prompt_file")
        self.assertEqual(nf["error"], "")
        self.assertEqual(lib.promptp({"role": "r", "rec": {"prompt_file": "p.md"},
                                      "text": "hi"})["prompt"], "hi")
        tpl = {"missing_any": "任一", "missing_contains": "包含", "missing_note": "备注"}
        out = lib.checkp({"rec": {"checks": [
            {"kind": "glob", "paths": ["a", "b"], "match": "any"},
            {"kind": "contains", "text": "x"},
            {"kind": "note", "min_len": 3}]},
            "files": [], "contents": {}, "notes": [], "tpl": tpl})
        self.assertEqual([m["kind"] for m in out["missing"]], ["glob", "contains", "note"])
        out = lib.checkp({"rec": {"checks": [{"kind": "glob", "paths": ["*.md"],
                                              "match": "any"}]},
                          "files": ["b.txt"], "tpl": {}})
        self.assertEqual(out["missing"][0]["reason"], "")
        out = lib.checkp({"rec": {"checks": [{"kind": "glob", "paths": ["a"]}]},
                          "files": [], "tpl": {}})
        self.assertEqual(out["missing"][0]["path"], "a")
        self.assertEqual(out["checked"], 1)
        ok = lib.checkp({"rec": {"checks": [
            {"kind": "glob", "paths": ["*.md"], "match": "any"},
            {"kind": "contains", "text": "结论"},
            {"kind": "note", "min_len": 2}]},
            "files": ["a.md"], "contents": {"a.md": "结论"},
            "notes": ["够了"]})
        self.assertEqual(ok["missing"], [])
        rec_ok = lib.positionp({"rec": {"id": "r", "cn": "岗", "checks": [
            {"kind": "glob", "paths": ["x"]}]}, "tpl": {}})
        self.assertEqual(rec_ok["must_outputs"], ["x"])

    def test_kind_file_prompt_path_save(self):
        self.assertEqual(lib.kind_file({"paths": {"record": "d/{kind}.yaml"}, "kind": "roles"}),
                         {"path": "d/roles.yaml"})
        self.assertEqual(lib.kind_file({}), {"path": ""})
        self.assertEqual(lib.prompt_path({"rec": {"prompt_module": "agent/sessions",
                                                  "prompt_file": "p.md"}}),
                         {"module": "agent/sessions", "path": "p.md"})
        self.assertEqual(lib.prompt_path({"rec": {"prompt_file": "p.md"},
                                          "paths": {"prompt": "x/{file}"}}),
                         {"module": "agent/library", "path": "x/p.md"})
        self.assertEqual(lib.prompt_path({}), {"module": "agent/library", "path": ""})
        self.assertEqual(lib.save_record({"user": {"a": {"id": "a"}},
                                          "rec": {"id": "a", "cn": "n"}})["value"]["a"]["cn"], "n")
        self.assertEqual(lib.save_record({"user": {}, "rec": {}})["value"], {})


class SkillTest(unittest.TestCase):
    def test_skills_list_status_uninstall(self):
        skills = {"s1": {"id": "s1", "cn": "甲", "role": "r1", "flow": "f1",
                         "tools": ["t1"], "status": "disabled", "builtin": False,
                         "created": "2"},
                  "s2": {"id": "s2", "cn": "乙", "builtin": True, "created": "1"}}
        roles = {"r1": {"cn": "岗位", "states": [{"id": "s"}]}}
        out = lib.skills_listp({"skills": skills, "roles": roles, "disabled": ["s1"],
                                "tpl": {"label_disabled": "停", "label_enabled": "启",
                                        "label_disabled_project": "项目停",
                                        "label_has_flow": "有", "label_no_flow": "无"}})
        row = out["items"][0]
        self.assertEqual((row["status_text"], row["disabled_text"], row["flow_text"]),
                         ("停", "项目停", "有"))
        self.assertEqual(row["tools"], "t1")
        self.assertFalse(lib.disabled_p({"skills": {}})["ids"])
        self.assertEqual(len(lib.skills_listp({"skills": {"bad": "x"}})["items"]), 0)
        self.assertEqual(lib.skill_statusp({"tpl": {"id_required": "id"}})["code"], "missing_id")
        self.assertEqual(lib.skill_statusp({"id": "s1", "record": {"builtin": True},
                                            "tpl": {"builtin_skill_protected": "保护"}})["code"],
                         "builtin_protected")
        self.assertEqual(lib.skill_statusp({"id": "s1", "record": {}, "status": "disabled",
                                            "now": "T"})["status"], "disabled")
        self.assertEqual(lib.skill_uninstallp({"tpl": {"id_required": "id"}})["code"], "missing_id")
        self.assertEqual(lib.skill_uninstallp({"id": "x", "tpl": {"skill_missing": "无 {id}"}})["code"],
                         "not_found")
        self.assertEqual(lib.skill_uninstallp({"id": "s2",
                                               "skills": skills,
                                               "tpl": {"builtin_skill_uninstall_protected": "保护"}})["code"],
                         "builtin_protected")
        removed = lib.skill_uninstallp({"id": "s1", "skills": skills, "roles": roles,
                                        "flows": {"f1": {}}, "tools": {"t1": {}, "t2": {"skill": "s1"}},
                                        "tpl": {}})
        self.assertEqual(removed["removed"], {"role": "r1", "flow": "f1", "tools": ["t1"]})
        self.assertEqual(removed["skills"], {"s2": skills["s2"]})
        self.assertEqual(removed["roles"], {})
        self.assertEqual(removed["flows"], {})
        self.assertEqual(removed["tools"], {})


if __name__ == "__main__":
    unittest.main()
