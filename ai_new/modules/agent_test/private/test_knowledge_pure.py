"""knowledge 纯函数：通配、作用域、清单归组、检索、注入拼接与索引合并。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.knowledge.private import _pure as k  # noqa: E402


class KnowledgePureTest(unittest.TestCase):
    def test_glob_edges(self):
        self.assertTrue(k._glob_one("", ""))
        self.assertFalse(k._glob_one("a", ""))
        self.assertTrue(k._glob_one("abc", "*"))
        self.assertTrue(k._glob_one("abc", "*c"))
        self.assertFalse(k._glob_one("abc", "*z"))
        self.assertFalse(k._glob_one("", "?"))
        self.assertTrue(k._glob_one("ab", "?b"))
        self.assertFalse(k._glob_one("ab", "xb"))
        self.assertTrue(k._glob_one("ab", "ab"))
        self.assertTrue(k._glob("a/b/c.md", "**/*.md"))
        self.assertFalse(k._glob("a/b", "a/c"))
        self.assertTrue(k._glob_path([], []))
        self.assertFalse(k._glob_path(["a"], []))
        self.assertFalse(k._glob("a", "**/x"))

    def test_scope_and_doc(self):
        paths = {"public": "pub/", "project": "p/{project}/", "ticket": "t/{ticket}/"}
        self.assertEqual(k.scope({"layer": "public", "paths": paths})["prefix"], "pub/")
        self.assertEqual(k.scope({"layer": "project", "project": "P", "paths": paths})["prefix"],
                         "p/P/")
        self.assertEqual(k.scope({"layer": "project", "project": "P", "paths": {}})["prefix"], "")
        self.assertEqual(k.scope({"layer": "project", "tpl": {"missing_scope_project": "x"}})["code"],
                         "missing_scope")
        self.assertEqual(k.scope({"layer": "ticket", "ticket": "T", "paths": paths})["prefix"],
                         "t/T/")
        self.assertEqual(k.scope({"layer": "ticket", "ticket": "T", "paths": {}})["prefix"], "")
        self.assertEqual(k.scope({"layer": "ticket", "tpl": {"missing_scope_ticket": "x"}})["code"],
                         "missing_scope")
        self.assertEqual(k.scope({"layer": "bad", "tpl": {"bad_layer": "{layer}"}})["error"], "bad")
        self.assertEqual(k.scope({"layer": "bad"})["error"], "")
        self.assertEqual(k.doc({"name": "a.md", "prefix": "p/", "paths": {"doc": "{prefix}{name}"}})
                         ["path"], "p/a")
        self.assertEqual(k.doc({"name": "a", "paths": {}})["path"], "")
        self.assertEqual(k.doc({})["code"], "missing_name")

    def test_view_present_screen_overview(self):
        self.assertEqual(k.view({"path": "p"})["chars"], 0)
        self.assertEqual(k.present({"content": ""})["code"], "not_found")
        self.assertEqual(k.present({"content": "x", "path": "p"})["text"], "x")
        self.assertEqual(k.screen({"rows": ["a/b.md", "c.md"], "sizes": {"a/b.md": 3}})["items"],
                         [{"name": "b.md", "chars": 3, "source": "llm"},
                          {"name": "c.md", "chars": 0, "source": "llm"}])
        counts = k.overview({"rows": [{"path": "public/a.md"}, "projects/P/x.md",
                                     "tickets/T/y.md", "bad"]})["counts"]
        self.assertEqual(counts, {"public": 1, "project": {"P": 1}, "ticket": {"T": 1}})

    def test_index_tree(self):
        out = k.index({"rows": [{"path": "public/a.md"}, {"path": "projects/P/b.md"},
                                {"path": "tickets/T/c.md"}, {"path": "no.md"}],
                       "tickets": [None, {"id": ""}, {"id": "T", "project": "P", "title": "标题"}],
                       "projects": ["bad", {"id": ""}, {"id": "P", "name": "项目"}],
                       "tpl": {"label_public": "公共", "label_project": "项目",
                               "label_ticket": "工单", "label_orphan": "孤儿"}})
        self.assertEqual(out["counts"], {"public": 1, "project": 1, "ticket": 1,
                                          "project_groups": 1, "placed": 1, "orphan": 0})
        self.assertEqual(out["items"][2]["project"], "P")
        self.assertEqual(out["tree"][0]["children"][0]["name"], "a")
        self.assertEqual(out["tree"][1]["label"], "项目")
        self.assertEqual(out["tree"][1]["children"][1]["type"], "ticket")
        # 无项目归属的工单不进树
        orphan = k.index({"rows": [{"path": "tickets/X/c.md"}], "tickets": []})
        self.assertEqual(orphan["counts"]["placed"], 0)

    def test_search_compose(self):
        rows = [{"path": "public/a.md", "text": "Alpha"},
                {"path": "public/b.md", "text": "beta"},
                {"path": "public/c.md", "text": "gamma"}]
        self.assertEqual(k.search({"rows": rows, "query": "alpha", "limit": 1,
                                   "snippet_chars": 2})["items"],
                         [{"path": "public/a.md", "snippet": "Al"}])
        self.assertEqual(k.search({"rows": rows, "query": "b", "limit": 5,
                                   "snippet_chars": 9})["items"][0]["path"], "public/b.md")
        out = k.compose({"rows": rows, "prefixes": ["public/"], "max_chars": 5})
        self.assertTrue(out["truncated"])
        self.assertEqual(out["chars"], 5)
        allout = k.compose({"rows": rows, "prefixes": ["public/", "none/"], "max_chars": 999})
        self.assertLess(allout["chars"], len(allout["text"]))
        self.assertFalse(allout["truncated"])

    def test_misc_and_index_merge(self):
        self.assertEqual(k.missing({"name": "a", "tpl": "缺 {name}"})["error"], "缺 a")
        self.assertEqual(k.missing({"name": "a"})["error"], "")
        self.assertEqual(k.removed({"removed": 1, "project": "P"}),
                         {"removed": True, "project": "P"})
        self.assertEqual(k.project_dir({"project": "P", "paths": {"project_dir": "p/{id}"}})
                         ["path"], "p/P")
        self.assertEqual(k.project_dir({"ticket": "T", "paths": {}})["path"], "")
        self.assertEqual(k.project_prefix({"ticket": "T", "project": "P",
                                           "paths": {"project_dir": "p/{id}"}})["prefix"], "p/T")
        self.assertEqual(k.project_prefix({"project": "P", "paths": {}})["prefix"], "")
        ent = k.entry({"path": "p", "now": "N"})
        self.assertEqual((ent["category"], ent["created"], ent["source"]),
                         ("knowledge", "N", "llm"))
        merged = k.index_upsert({"entry": {"path": "p", "updated": "U", "name": "n"},
                                 "entries": ["bad", {"path": "p", "created": "C"},
                                             {"path": "q"}]})
        self.assertEqual(merged["entries"][0], {"path": "p", "created": "C",
                                                "updated": "U", "name": "n"})
        appended = k.index_upsert({"entry": {"path": "p"}, "entries": []})
        self.assertEqual(len(appended["entries"]), 1)
        purged = k.index_purge({"prefix": "p/", "entries": ["bad", {"path": "p/a"},
                                                           {"path": "q"}]})
        self.assertEqual(purged["entries"], [{"path": "q"}])
        self.assertEqual(k.index_purge({"prefix": "", "entries": [{"path": "p"}]})["entries"],
                         [{"path": "p"}])


if __name__ == "__main__":
    unittest.main()
