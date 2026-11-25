"""timer 纯函数边界：调用方归一、规格校验、作用域裁决、配额与视图聚合。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.timer.private import _pure as p  # noqa: E402


class TimerEdgeTest(unittest.TestCase):
    def test_normalize_and_idem(self):
        self.assertEqual(p.normalize_caller({"caller": "bad"})["scope"], "project")
        self.assertEqual(p.normalize_caller({"caller": {"scope": "bad"}})["scope"],
                         "project")
        row = p.normalize_caller({"caller": {"scope": "ticket", "ticket": "t"},
                                  "project": "p", "source_session": "s",
                                  "creator": "r"})
        self.assertEqual((row["project"], row["ticket"], row["session"], row["role"]),
                         ("p", "t", "s", "r"))
        self.assertEqual(p.idem_signature({"project": None, "title": "x"}),
                         "|x||||||")

    def test_validate(self):
        self.assertEqual(p.validate_shape({})["code"], "bad_kind")
        self.assertEqual(p.validate_shape({"kind": "once"})["code"], "bad_action")
        self.assertEqual(p.validate_shape({"kind": "once", "action": "notify"})["code"],
                         "bad_cron")
        self.assertEqual(p.validate_shape({"kind": "once", "action": "notify",
                                           "expr": "x"})["code"], "bad_title")
        self.assertEqual(p.validate_shape({"kind": "once", "action": "notify",
                                           "expr": "x", "title": "t"})["code"],
                         "missing_project")
        self.assertEqual(p.validate_shape({"kind": "cron", "action": "notify",
                                           "expr": "x", "title": "t",
                                           "project": "p"}), {"ok": True})
        self.assertFalse(p.validate_spec({"kind": "bad"}, {})["ok"])
        self.assertEqual(p.validate_spec({"kind": "once", "action": "notify",
                                          "expr": "x", "title": "t",
                                          "project": "p"}, {"ok": False})["code"],
                         "bad_cron")
        self.assertEqual(p.validate_spec({"kind": "once", "action": "notify",
                                          "expr": "x", "title": "t",
                                          "project": "p"},
                                         {"ok": True, "ts": 1, "iso": "i",
                                          "slot": "s", "tz": "z"})["next_at"], 1)

    def test_quota_and_scope(self):
        self.assertEqual(p.quota_check([1, 2], {"max_per_project": 2})["code"],
                         "quota_exceeded")
        self.assertTrue(p.quota_check([1], {"max_per_project": 2})["ok"])
        self.assertTrue(p.authorize({"scope": "global"}, {}, "list")["ok"])
        rec = {"project": "p", "ticket": "t"}
        self.assertEqual(p.authorize({"scope": "ticket", "project": "x",
                                      "ticket": "t"}, rec, "list")["reason"],
                         "cross_project")
        self.assertEqual(p.authorize({"scope": "ticket", "project": "p",
                                      "ticket": "x"}, rec, "list")["reason"],
                         "cross_ticket")
        self.assertTrue(p.authorize({"scope": "ticket", "project": "p",
                                     "ticket": "t"}, rec, "list")["ok"])
        self.assertEqual(p.authorize({"scope": "project", "project": "x"}, rec,
                                     "list")["reason"], "cross_project")
        self.assertTrue(p.authorize({"scope": "project", "project": "p"}, rec,
                                    "list")["ok"])
        self.assertEqual(len(p.filter_scope([rec, {"project": "x"}],
                                            {"project": "p"})), 1)

    def test_selection_and_views(self):
        self.assertEqual(p.due_select({}, ["a", "b", "c"], ["a"], 1), ["b"])
        self.assertEqual(p.due_select({}, None, None, 0), [])
        self.assertEqual(p.run_record({}, "s", 0, None, "2", 9, "notify"),
                         {"at": 9, "slot": "s", "ok": False, "detail": "",
                          "attempt": 2, "action": "notify", "timer_id": None,
                          "project": None, "ticket": None})
        self.assertEqual(p.last_run_view({}), {"at": None, "ok": None,
                                               "detail": "", "attempt": 0})
        self.assertEqual(p.view_row({})["kind_expr"], "None · None")
        self.assertEqual(p.view_rows(None), [])
        rows = [{"project": "b", "status": "active",
                 "last_run": {"at": "2026-01-01", "ok": True}},
                {"project": "a", "status": "paused",
                 "last_run": {"at": "2026-01-02", "ok": False}},
                {"project": "a", "status": "weird"}]
        groups = p.project_groups(rows, "2026-01-01T10:00")
        self.assertEqual([g["project"] for g in groups], ["b", "a"])
        self.assertEqual(groups[1]["today"], 0)
        self.assertEqual(p.index_stats(rows, "2026-01-01T10:00"),
                         {"active": 1, "paused": 1, "today": 1, "done": 0,
                          "error": 0})


if __name__ == "__main__":
    unittest.main()
