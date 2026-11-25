"""工具库纯函数边界：合并优先级、岗位裁剪、依赖判定、安装计划与清单行。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.tools.private import _pure as t  # noqa: E402


def tool(name, kinds=None, builtin=False, deps=None, skill=""):
    return {"name": name, "kinds": kinds, "builtin": builtin, "deps": deps,
            "skill": skill, "module": "m", "desc": "d",
            "params": [{"name": "p", "type": "string", "required": True}]}


class ToolsPureTest(unittest.TestCase):
    def test_merge(self):
        out = t.merge({"builtin": [tool("a", builtin=True), {"n": 1}],
                       "external": {"a": {"desc": "x"}, "b": {"skill": "s"},
                                    "c": None, "": {}},
                       "disabled": ["s"]})["items"]
        self.assertEqual([x.get("name") for x in out if x.get("name")], ["a", "c"])
        self.assertFalse(t.merge({"external": {"b": {}}})["items"][0]["builtin"])

    def test_pick_and_scope(self):
        items = [tool("a", ["pm"]), tool("b", ["admin"]), tool("c")]
        self.assertEqual([x["name"] for x in t.pickp({"items": items,
                                                      "tools": ["a", "b"],
                                                      "disabled": ["b"]})["items"]],
                         ["a"])
        self.assertEqual([x["name"] for x in t.pickp({"items": items, "kind": "pm"})["items"]],
                         ["a", "c"])
        self.assertEqual([x["name"] for x in t.pickp({"items": items})["items"]], ["c"])
        self.assertEqual([x["name"] for x in t.scope(items, "builtin")], [])
        self.assertEqual([x["name"] for x in t.scope(items, "external")], ["a", "b", "c"])
        self.assertEqual(len(t.scope(items, "all")), 3)

    def test_missing_and_probe(self):
        snap = {"cli": {"git": True}, "pip": {"x": True}, "env": {"E": "1"},
                "config": {"c": False}}
        deps = {"cli": ["git", "missing", ""], "pip": ["x", "y"],
                "env": ["E", "F"], "config": ["c"], "resources": ["r"]}
        probe = t.probe({"deps": deps, "snapshot": snap})
        self.assertEqual(probe["status"], "missing")
        self.assertEqual([m["name"] for m in probe["missing"]],
                         ["missing", "y", "F", "c"])
        self.assertEqual(t.probe({})["status"], "ok")

    def test_texts(self):
        tpl = {"label_cli": "命令", "label_none": "无"}
        self.assertEqual(t._dep_label(tpl, "cli"), "命令")
        self.assertEqual(t._dep_label({}, "cli"), "cli")
        self.assertEqual(t._deps_text({"cli": ["a", ""], "env": ["E"]}, tpl),
                         "命令: a；env: E")
        self.assertEqual(t._deps_text({}, tpl), "无")
        self.assertEqual(t._missing_text([], tpl), "")
        self.assertEqual(t._missing_text([{"kind": "cli", "name": "a"}], tpl),
                         "命令:a")

    def test_install_plan(self):
        snap = {"pip": {"ok": True}}
        tools = [tool("a", deps={"pip": ["x", "x", ""], "cli": ["g"], "env": ["E"],
                                 "config": ["c"], "resources": ["r"]}),
                 tool("b", deps={"pip": ["x"]}),
                 tool("a", deps={"pip": ["x", "x", ""], "cli": ["g"],
                                 "env": ["E"], "config": ["c"],
                                 "resources": ["r"]})]
        plan = t.install_plan({"tools": tools, "snapshot": snap})
        self.assertEqual(plan["pip"], ["x"])
        self.assertEqual([m["name"] for m in plan["manual"]["cli"]], ["g"])
        self.assertEqual(len(plan["manual"]["env"]), 1)
        self.assertFalse(plan["ready"])
        self.assertTrue(t.install_plan({"tools": [tool("c")]})["ready"])

    def test_group_deps(self):
        tools = [tool("a", deps={"cli": ["g", "", "g"], "pip": ["x"],
                                 "env": ["E", "F"], "config": ["c"],
                                 "resources": ["r"]}),
                 tool("b", deps={"cli": ["g"], "env": ["E", "F"],
                                 "resources": ["r", "s"]}),
                 tool("a", deps={"cli": ["g"], "env": ["E", "F"],
                                 "config": ["c"]})]
        groups = t._group_deps(tools, {"cli": {"g": True}, "pip": {"x": True},
                                       "env": {"E": "1"}, "config": {"c": False}})
        self.assertEqual(groups["cli"]["present"], ["g"])
        self.assertEqual(groups["cli"]["missing"], [])
        self.assertEqual(groups["config"]["missing"][0]["tools"], ["a"])
        self.assertEqual(groups["resources"], ["r", "s"])

    def test_deps_report(self):
        out = t.deps_report({"tools": [tool("a", deps={"pip": ["x"]}),
                                       tool("b")], "snapshot": {}})
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["ready"], 1)
        self.assertEqual(out["can_install"], True)
        self.assertEqual(out["install_blocked"], False)
        self.assertEqual(out["manual_missing"], 0)

    def test_external_pending(self):
        out = t.external_pending({"tool": "x", "rec": {"desc": "d",
                                                       "deps": {"pip": ["p"]}},
                                  "tpl": {"external_pending": "待接入 {name}"},
                                  "args": {"a": 1}})
        self.assertEqual(out["message"], "待接入 x")
        self.assertEqual(out["deps"], "pip: p")
        self.assertEqual(t.external_pending({})["message"], "")

    def test_listing(self):
        tpl = {"label_all": "全部", "label_ready": "就绪",
               "label_deps_missing": "缺依赖", "label_disabled_project": "禁用",
               "label_builtin": "内置", "label_external": "外部"}
        rows = t.listing({"tools": [tool("a", kinds=[], builtin=True,
                                         deps={"pip": ["x"]}),
                                    tool("b", kinds=["pm"], builtin=False)],
                          "snapshot": {"pip": {"x": True}},
                          "disabled_names": ["b"], "tpl": tpl})["items"]
        self.assertEqual(rows[0]["kinds"], "全部")
        self.assertEqual(rows[0]["params"], "p: string*")
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[0]["source"], "内置")
        self.assertEqual(rows[1]["disabled_project"], True)
        self.assertEqual(rows[1]["source"], "外部")


if __name__ == "__main__":
    unittest.main()
