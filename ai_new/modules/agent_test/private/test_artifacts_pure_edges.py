"""交付件纯函数：分层前缀、路径越界、清单合并/剔除、三级归属树。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.artifacts.private import _pure as a  # noqa: E402


class ArtifactsPureTest(unittest.TestCase):
    def test_base(self):
        paths = {"public": "/pub", "project": "/p/{project}", "ticket": "/p/{project}/t/{ticket}"}
        self.assertEqual(a.base({"layer": "public", "paths": paths})["base"], "/pub")
        self.assertEqual(a.base({"layer": "public", "paths": {}})["base"], "")
        self.assertEqual(a.base({"layer": "project"})["code"], "missing_scope")
        self.assertEqual(a.base({"layer": "project", "project": "P",
                                  "paths": paths})["base"], "/p/P")
        self.assertEqual(a.base({"layer": "project", "project": "P",
                                  "paths": {}})["base"], "")
        self.assertEqual(a.base({"layer": "ticket"})["code"], "missing_scope")
        self.assertEqual(a.base({"layer": "ticket", "ticket": "T", "project": "P",
                                  "paths": paths})["base"], "/p/P/t/T")
        self.assertEqual(a.base({"layer": "ticket", "ticket": "T",
                                  "paths": {}})["base"], "")
        self.assertEqual(a.base({"layer": "x"})["code"], "bad_layer")
        self.assertEqual(a.base({"layer": "x", "tpl": {"bad_layer": "bad {layer}"}})["error"],
                         "bad x")

    def test_rel(self):
        self.assertEqual(a.rel({})["code"], "bad_path")
        self.assertEqual(a.rel({"path": "a\x00b"})["code"], "bad_path")
        self.assertEqual(a.rel({"path": "../x"})["status"], 403)
        self.assertEqual(a.rel({"path": "x"})["path"], "x")
        self.assertEqual(a.rel({"path": "\\x", "base": "b"})["path"], "b/x")

    def test_views(self):
        self.assertEqual(a.written({}), {"path": None, "size": 0, "layer": None})
        self.assertEqual(a.viewed({"text": "t"})["encoding"], "utf8")
        rows = [{"path": "a", "text": "abc"}, {"path": "a2", "text": "é"}, ["b", "2"]]
        out = a.screen({"rows": rows})
        self.assertEqual([i["size"] for i in out["items"]], [3, 2, 2])
        self.assertEqual(a.screen({})["layer"], "ticket")
        stats = a.statsp({"rows": [{"size": 4, "text": "é"}, {"text": "abc"}]})
        self.assertEqual(stats, {"files": 2, "bytes": 4 + 3, "chars": 1 + 3})
        self.assertEqual(a.statsp({"rows": [{"text": "é"}]})["bytes"], 2)

    def test_classify_entry(self):
        self.assertEqual(a.classify({}), {"ok": True, "doc_kind": "artifact",
                                          "source": "llm"})
        self.assertEqual(a.classify({"doc_kinds": ["a"], "doc_kind": "b"})["code"],
                         "bad_doc_kind")
        self.assertEqual(a.classify({"sources": ["a"], "source": "b"})["code"],
                         "bad_source")
        self.assertEqual(a.entry({})["category"], "document")
        self.assertEqual(a.entry({})["source"], "llm")

    def test_index(self):
        merged = a.index_upsert({"entry": {"path": "p", "updated": 2, "name": "n",
                                           "source": "x"},
                                 "entries": [{"path": "p", "created": 1, "name": "old"},
                                             {"path": "x"}, "bad"]})
        self.assertEqual(merged["entries"][0]["created"], 1)
        self.assertEqual(merged["entries"][0]["updated"], 2)
        self.assertEqual(len(merged["entries"]), 2)
        self.assertEqual(a.index_upsert({"entry": {"path": "q"}})["entries"],
                         [{"path": "q"}])
        self.assertEqual(a.index_upsert({"entry": {}})["entries"], [])
        purged = a.index_purge({"prefix": "p/", "entries": [
            {"path": "p/a"}, {"path": "x"}, "bad"]})
        self.assertEqual(len(purged["entries"]), 1)
        self.assertEqual(len(a.index_purge({"entries": [{"path": "x"}]})["entries"]), 1)

    def test_group(self):
        out = a.group({
            "entries": [
                {"layer": "public", "path": "a", "name": "A"},
                {"layer": "ticket", "ticket": "T1", "project": "", "path": "b"},
                {"layer": "ticket", "ticket": "T9", "path": "c"},
                {"layer": "project", "project": "P", "path": "d"},
                "bad"],
            "tickets": [None, {}, {"id": ""}, {"id": "T1", "project": "P2",
                                              "title": "Title"}]})
        self.assertEqual(out["counts"], {"public": 1, "project": 1, "ticket": 2})
        self.assertEqual([t["type"] for t in out["tree"]], ["public", "project", "project"])
        labels = {t["label"] for t in out["tree"][1:]}
        self.assertEqual(labels, {"P", "P2"})
        self.assertEqual(len(out["tree"]), 3)


if __name__ == "__main__":
    unittest.main()
