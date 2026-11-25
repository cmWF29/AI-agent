"""decompose 纯函数边界：包解析、提示成形、模型返回归一、扫描与环境计划。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.decompose.private import _pure as d


class ParseTextTest(unittest.TestCase):
    def test_split_and_meta(self):
        self.assertEqual(d._split_frontmatter(""), ([], ""))
        self.assertEqual(d._split_frontmatter("body"), ([], "body"))
        self.assertEqual(d._split_frontmatter("---\na: 1"), ([], "---\na: 1"))
        self.assertEqual(d._split_frontmatter("---\na: 1\n---\nbody"),
                         (["a: 1"], "body"))
        self.assertEqual(d._parse_meta_lines(["", "  nested: v", "no-colon", " : x",
                                              "name: 'x'"]),
                         {"metadata": {"nested": "v"}, "name": "x", "no-colon": ""})

    def test_req_package_and_list(self):
        for line in ("", "# c", "  "):
            self.assertEqual(d._req_package(line), "")
        self.assertEqual(d._req_package("pkg==1.0"), "pkg")
        self.assertEqual(d._req_package("pkg>=1; python_version<'3'"), "pkg")
        self.assertEqual(d._req_package("pkg < 2"), "pkg")
        self.assertEqual(d._as_list([" a ", "", None]), ["a"])
        self.assertEqual(d._as_list("a,b，c\nd"), ["a", "b", "c", "d"])
        self.assertEqual(d._as_list("  "), [])

    def test_safe_pkg_edges(self):
        self.assertEqual(d.safe_pkg("")["pkg"], "")
        self.assertEqual(d.safe_pkg("==1.0")["pkg"], "")
        self.assertFalse(d.safe_pkg("1pkg; rm")["ok"])
        self.assertFalse(d.safe_pkg("-pkg")["ok"])
        self.assertTrue(d.safe_pkg("pkg==1.0", {"pkg_bad": "bad {pkg}"})["ok"])

    def test_parse_skill_doc(self):
        out = d.parse_skill_doc({"skill_md": "---\nname: s\nmetadata:\n  version: '1'\n---\nbody",
                                 "requirements": "a==1\n# x\nb", "scripts": "x.py\ny.py"})
        self.assertEqual(out["meta"], {"id": "s", "doc": "", "version": "1"})
        self.assertEqual(out["pip"], ["a", "b"])
        self.assertEqual(out["scripts"], ["x.py", "y.py"])
        self.assertEqual(out["body"], "body")
        self.assertEqual(d.parse_skill_doc({})["meta"]["version"], "")


class PromptTest(unittest.TestCase):
    def test_promptize_full_and_plain(self):
        out = d.promptize({"system": "sys", "meta": {"id": "s", "doc": "d", "version": "v"},
                           "pip": ["a"], "scripts": ["b"], "body": "body",
                           "tools": [{"name": "t"}, {}],
                           "tpl": {"meta_id_label": "ID", "meta_doc_label": "DOC",
                                   "meta_version_label": "V", "pip_label": "PIP",
                                   "scripts_label": "SC", "body_label": "BODY",
                                   "tools_label": "TOOLS"}})
        self.assertEqual(out["messages"][0], {"role": "system", "content": "sys"})
        self.assertEqual(out["messages"][1]["content"],
                         "ID：s\n\nDOC：d\n\nV：v\n\nPIP：a\n\nSC：b\n\nBODY：\nbody\n\nTOOLS：t")
        self.assertEqual([t["name"] for t in d.tool_defs()],
                         ["fetch_url", "pip_install", "shell"])
        no_id = d.promptize({"meta": {}, "tpl": {"no_tools": "none"}})["messages"]
        self.assertEqual(no_id[0]["content"], "none")
        plain = d.promptize({"meta": {"id": "s"}, "tpl": {"no_tools": "none"}})["messages"]
        self.assertEqual(len(plain), 1)
        self.assertEqual(plain[0]["content"], "s\n\nnone")


class NormTest(unittest.TestCase):
    def test_norm_deps_tool_check(self):
        deps = d._norm_deps({"cli": "a", "env": ["E"], "resources": "r"}, ["p"])
        self.assertEqual(deps["pip"], ["p"])
        self.assertEqual(deps["env"], ["E"])
        self.assertEqual(deps["resources"], ["r"])
        self.assertIsNone(d._norm_tool("x", set(), [], [])[0])
        self.assertIsNone(d._norm_tool({}, set(), [], [])[0])
        self.assertEqual(d._norm_tool({"name": "t"}, {"t"}, [], [])[1], ["t"])
        tool, _ = d._norm_tool({"name": "n", "params": ["x", {"name": "", "type": 1},
                                                        {"name": "p", "required": 1}],
                                "desc": 3, "deps": {"resources": "r"}}, set(), ["p"], ["s"])
        self.assertEqual(tool["params"], [{"name": "p", "type": "string", "required": True,
                                           "desc": ""}])
        self.assertEqual(tool["deps"]["resources"], ["r"])
        self.assertEqual(tool["desc"], "3")
        self.assertEqual(d._norm_check({"kind": "", "paths": [" p ", ""], "match": "m",
                                        "text": 0, "min_bytes": 0, "min_len": 0}),
                         {"kind": "note", "paths": ["p"], "match": "m", "text": "0",
                          "min_bytes": 0, "min_len": 0})
        self.assertIsNone(d._norm_check("  "))

    def test_parse_collects_new_and_dropped(self):
        out = d.parse({"draft": {"role": {"tools": ["a", "", "x"]},
                                 "new_tools": [{"name": "n"}, {"bad": 1}],
                                 "flow": {"checks": ["note", {}]}},
                       "tools": [{"name": "a"}], "meta": {"id": "s"},
                       "pip": ["p"], "scripts": ["s"]})
        self.assertEqual(out["draft"]["role"]["tools"], ["a"])
        self.assertEqual(out["dropped"], ["x", "新工具缺少 name"])
        self.assertEqual(out["draft"]["tools"][0]["name"], "n")
        self.assertEqual(out["draft"]["flow"]["checks"],
                         [{"kind": "note", "text": "note"}, {"kind": "note"}])
        self.assertEqual(out["tools"], ["a"])


class InstallTest(unittest.TestCase):
    def test_install_parts_and_effects(self):
        self.assertEqual(d.install_parts({})["code"], "missing_id")
        parts = d.install_parts({"draft": {"id": "s", "role": {"cn": "C", "tools": ["t"]},
                                           "flow": {"checks": [{"kind": "x"}],
                                                    "nodes": [{"id": "n"}], "edges": []},
                                           "tools": [{"name": "t"}, {"name": ""}, "bad"]},
                                 "meta": {"doc": "D", "version": "V"}, "now": "N"})
        self.assertEqual(parts["role"]["tools"], ["t"])
        self.assertEqual(parts["role"]["kind"], "process")
        self.assertEqual(len(parts["tools"]), 1)
        self.assertEqual(parts["skill"]["created"], "N")
        self.assertEqual(d.install_effects({"parts": {}})["ok"], False)
        minimal = d.install_parts({"draft": {"id": "m",
                                              "tools": ["bad", {"name": ""}, {"name": "t"}]}})
        self.assertEqual(minimal["role"]["tools"], ["t"])
        self.assertNotIn("checks", minimal["role"])
        self.assertNotIn("kind", minimal["role"])
        self.assertEqual(d.install_effects({"parts": {"skill": {"id": "s"}}})["ok"], True)
        self.assertEqual(d.install_effects({"parts": {"skill": {"id": "s"},
                                                       "role": {"id": "r"},
                                                       "tools": ["bad", {}, {"name": "t"}]}})["ok"], True)


class ScanTest(unittest.TestCase):
    def test_scan_rejections(self):
        limits = {"max_files": 1, "max_file_bytes": 2, "max_text_chars": 1,
                  "max_bundle_bytes": 1, "ignored": 0}
        out = d.scan_bundle({"files": ["bad", {"path": ""}, {"path": "a\\b"},
                                        {"path": "/x"}, {"path": "../x"}, {"path": "C:x"},
                                        {"path": "x", "is_link": True, "link": "../e"},
                                        {"path": "x.exe"}, {"path": "x.md", "text": "long"},
                                        {"path": "y.md", "text": "xx"},
                                        {"path": "z.md", "text": "z"},
                                        {"path": "w.md", "text": "w"}],
                             "limits": limits, "tpl": {"empty_path": "E"}})
        codes = [r["code"] for r in out["rejected"]]
        self.assertEqual(codes, ["bad_entry", "empty_path", "bad_separator", "absolute_path",
                                 "path_traversal", "absolute_path", "symlink_escape",
                                 "disallowed_type", "oversized_file", "oversized_text",
                                 "too_many_files", "oversized_bundle"])
        self.assertFalse(out["ok"])
        self.assertEqual(out["rejected"][1]["reason"], "E")
        self.assertEqual(out["limits"]["max_files"], 1)
        self.assertFalse(d.scan_bundle({})["ok"])

    def test_scan_accepts_whitelisted(self):
        out = d.scan_bundle({"files": [{"path": "README", "text": "x"},
                                       {"path": "a/b.md", "text": "y"},
                                       {"path": "b.txt", "link": "ok", "is_link": True}]})
        self.assertTrue(out["ok"])
        self.assertEqual(out["totals"]["files"], 3)
        self.assertEqual(out["accepted"][1]["path"], "a/b.md")


class EnvPlanTest(unittest.TestCase):
    def test_env_probe_and_dep_plan(self):
        self.assertEqual(d.env_probe({"runtime": "py", "snapshot": {}}),
                         {"ready": False, "missing": {"cli": ["py"], "env": []},
                          "checked": {"cli": ["py"], "env": []}})
        self.assertEqual(d.env_probe({"deps": {"cli": ["a"], "env": ["E"]},
                                       "snapshot": {"cli": {"a": 1}, "env": {"E": " "}}}),
                         {"ready": False, "missing": {"cli": [], "env": ["E"]},
                          "checked": {"cli": ["a"], "env": ["E"]}})
        plan = d.dep_plan({"requirements": ["", "# c", "bad;x", "a==1", "B"],
                           "installed": ["a"], "tpl": {"pkg_bad": "bad"}})
        self.assertEqual(plan["rejected"][0]["code"], "bad_pkg")
        self.assertEqual(plan["missing"], [{"pkg": "B", "requirement": "B", "installed": False}])
        self.assertEqual(plan["installed"], ["a"])

    def test_audit_guard_key(self):
        self.assertEqual(d.audit_record({}), {"action": "", "at": "", "source": "",
                                              "license": "", "version": "", "skill": "",
                                              "bundle": {"files": [], "bytes": 0},
                                              "deps": {}, "result": {}})
        simple = d.register_guard({"products": {"tools": []}})
        self.assertEqual(simple["writable"], {"role": None, "tools": []})
        out = d.register_guard({"products": {"role": {"id": "r"},
                                             "tools": [{"name": "b"}, "bad", {"name": ""},
                                                       {"name": "n"}]},
                                "existing": {"roles": {"r": 1}, "tools": {"n": 1}},
                                "builtin_ids": ["r"], "builtin_tools": ["b"]})
        self.assertFalse(out["ok"])
        self.assertEqual([r["code"] for r in out["rejected"]],
                         ["builtin_protected", "builtin_tool_collision"])
        self.assertEqual(out["writable"], {"role": None,
                                           "tools": [{"name": "n", "override": True}]})
        normal = d.register_guard({"products": {"role": {"id": "n"}}})
        self.assertEqual(normal["writable"]["role"], {"id": "n", "override": False})
        self.assertEqual(d.idempotent_key({"id": " s ", "version": 1}), {"id": "s", "version": "1"})


if __name__ == "__main__":
    unittest.main()
