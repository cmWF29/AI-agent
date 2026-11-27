"""sessions/private/_run_pure.py 全分支单测。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.sessions.private import _run_pure as rp


class RunPureTest(unittest.TestCase):
    def test_append_mark(self):
        rec = rp.appendmsg({"rec": {"status": "idle", "messages": [{"role": "x"}]},
                            "kind": "note", "text": "t", "now": "n"})
        self.assertEqual(rec["status"], "queued")
        self.assertEqual(rec["messages"][-1]["kind"], "note")
        self.assertEqual(rec["messages"][-1]["at"], "n")
        self.assertNotIn("kind", rp.appendmsg({"rec": {"status": "running"}})["messages"][-1])
        rec2 = rp.appendmsg({"rec": {"status": "idle"},
                             "text": "答", "qid": "q1",
                             "answers": [{"qid": "q1#0", "values": ["代码"]}, "bad"]})
        self.assertEqual(rec2["messages"][-1]["qid"], "q1")
        self.assertEqual(rec2["messages"][-1]["answers"], [{"qid": "q1#0", "values": ["代码"]}])
        rec3 = rp.appendmsg({"rec": {"status": "idle"}, "text": "答", "answers": []})
        self.assertNotIn("answers", rec3["messages"][-1])
        self.assertEqual(rp.mark({})["status"], "running")
        self.assertEqual(rp.mark({"status": "idle"})["updated"], "")
        self.assertTrue(rp._retrospect_enabled({"retrospect_enabled": True}))
        self.assertFalse(rp._retrospect_enabled({"retrospect_enabled": False}))
        self.assertTrue(rp._retrospect_enabled({"retrospect_default": True}))

    def test_finish_core(self):
        base = [{"role": "user", "content": "a"}]
        out = rp.finish({"rec": {"messages": base}, "result_chars": 4,
                         "out": {"messages": base + [{"role": "assistant", "content": "ok"}],
                                 "steps": 2, "summary": "s", "last": {"content": "oooo"},
                                 "failed": {"code": "c", "error": "bad"}},
                         "latest": {"messages": base + [{"role": "assistant",
                                                         "content": "wrong"},
                                                        {"role": "assistant",
                                                         "content": "ok"},
                                                        {"role": "user", "content": "new"}]},
                         "now": "n", "tools": ["t"]})
        self.assertEqual(out["messages"][-1]["content"], "new")
        self.assertEqual(out["steps"], 2)
        self.assertEqual(out["summary"], "s")
        self.assertEqual(out["meta"]["last_error"], {"code": "c", "error": "bad"})
        self.assertEqual(out["result"]["summary"], "bad")
        self.assertEqual(out["meta"]["tools"], ["t"])
        out = rp.finish({"rec": {"messages": base, "meta": {"last_error": 1}},
                         "result_chars": 4, "out": {"messages": [], "last": {"content": "abc"}},
                         "latest": {"messages": base}, "now": "n"})
        self.assertNotIn("last_error", out["meta"])
        self.assertEqual(out["result"]["summary"], "abc")
        self.assertEqual(out["messages"], base)
        out = rp.finish({"rec": {}, "result_chars": 2,
                         "out": {"cancelled": True}, "now": "n",
                         "cancelled_text": "stop"})
        self.assertEqual(out["result"], {"summary": "stop", "at": "n", "cancelled": True})
        out = rp.finish({"rec": {}, "result_chars": 3, "now": "n",
                         "out": {"failed": {"error": ""}}, "no_reply_text": "none"})
        self.assertEqual(out["result"]["summary"], "non")

    def test_mark_keeps_later_messages(self):
        rec = {"messages": [{"role": "user", "content": "a"}], "status": "idle"}
        got = rp.mark({"rec": rec, "latest": {"messages": rec["messages"] +
                                              [{"role": "user", "content": "插话"}]}})
        self.assertEqual([m["content"] for m in got["messages"]], ["a", "插话"])
        self.assertEqual(rp.mark({"rec": rec, "latest": {"messages": rec["messages"]}})
                         ["messages"], rec["messages"])
        self.assertEqual(rp.mark({"rec": rec, "latest": {"messages": []}})["messages"],
                         rec["messages"])

    def test_finish_restores_tail_dropped_by_rebuild(self):
        base = [{"role": "user", "content": "a"}, {"role": "user", "content": "插话"}]
        out = rp.finish({"rec": {"messages": base}, "result_chars": 9, "now": "n",
                         "out": {"messages": [{"role": "user", "content": "a"},
                                              {"role": "assistant", "content": "ok"}]},
                         "latest": {"messages": [{"role": "user", "content": "a"},
                                                 {"role": "assistant", "content": "ok"}]}})
        self.assertEqual([m["content"] for m in out["messages"]],
                         ["a", "插话", "ok"])

    def test_finish_extra_no_match(self):
        base = [{"role": "user", "content": "a"}]
        out = rp.finish({"rec": {"messages": base}, "result_chars": 9, "now": "n",
                         "out": {"messages": base + [{"role": "assistant", "content": "x"}]},
                         "latest": {"messages": base + [{"role": "user", "content": "n"}]}})
        self.assertEqual(len(out["messages"]), 3)

    def test_finish_stage(self):
        rec = {"meta": {"stage_alert": 1, "gate_alert": 2}}
        out = rp.finish({"rec": rec, "result_chars": 9, "now": "n",
                         "out": {"stage": "out", "checklist": ["c"], "violations": ["v"]},
                         "stage_check": {"ok": True, "stage": "in", "active": None}})
        self.assertEqual(out["meta"]["active"], ["in"])
        self.assertNotIn("stage_alert", out["meta"])
        self.assertEqual(out["meta"]["checklist"], {"checked": ["c"], "violations": ["v"]})
        self.assertEqual(out["meta"]["stage"], "in")
        out = rp.finish({"rec": {}, "result_chars": 9, "now": "n",
                         "out": {"stage": "out"},
                         "stage_check": {"ok": False, "code": "checklist_unmet",
                                         "missing": ["m"], "violations": ["v"],
                                         "active": [], "stage": ""}})
        self.assertEqual(out["meta"]["gate_alert"]["missing"], ["m"])
        self.assertNotIn("active", out["meta"])
        out = rp.finish({"rec": {"meta": {"gate_alert": 1}}, "result_chars": 9,
                         "now": "n", "out": {},
                         "stage_check": {"ok": False, "code": "x", "active": ["a"]}})
        self.assertNotIn("gate_alert", out["meta"])
        self.assertEqual(out["meta"]["active"], ["a"])

    def test_resume(self):
        rows = [{"path": "p", "rec": {"id": "a", "status": "idle"}},
                {"path": "p", "rec": {"id": "b", "status": "running",
                                      "meta": {"resumed": 1}}},
                {"path": "q", "rec": {"id": "c", "status": "running"}}]
        out = rp.resume_plan({"rows": rows, "now": "n", "max": 1})
        self.assertEqual([i["id"] for i in out["resume"]], ["b"])
        self.assertEqual([i["id"] for i in out["stale"]], ["c"])
        out = rp.resume_plan({"rows": rows[2:], "enabled": False})
        self.assertEqual([i["id"] for i in out["stale"]], ["c"])
        out = rp.resume_plan({"rows": rows[2:], "max": 0})
        self.assertEqual([i["id"] for i in out["resume"]], ["c"])

    def test_stuck(self):
        rows = [{"path": "p", "rec": {"id": "a", "status": "idle"}},
                {"path": "p", "rec": {"id": "b", "status": "running"},
                 "idle_seconds": 5},
                {"path": "p", "rec": {"id": "c", "status": "running"},
                 "idle_seconds": 9},
                {"path": "p", "rec": {"id": "d", "status": "running"},
                 "idle_seconds": 100}]
        out = rp.stuck_plan({"rows": rows, "active": ["c", "d"], "idle_seconds": 10,
                             "now": "n", "stale_text": "s"})
        self.assertEqual([i["id"] for i in out["stuck"]], ["b", "d"])
        self.assertEqual(out["keep"], ["c"])
        out = rp.stuck_plan({"rows": rows, "active": [], "enabled": False})
        self.assertEqual(out["stuck"], [])
        self.assertEqual(out["keep"], ["b", "c", "d"])

    def test_reply_stats_active(self):
        self.assertEqual(rp.reply({"id": "i", "rec": {}})["id"], "i")
        self.assertEqual(rp.reply({"rec": {"id": "r", "messages": [
            {"role": "assistant", "content": "a"}, {"role": "user"}]}})["content"], "a")
        out = rp.statsp({"items": [{"status": "running"}, {}, {"status": "idle"}]})
        self.assertEqual(out["statuses"], {"running": 1, "idle": 1, "unknown": 1})
        self.assertEqual(out["active"], 1)
        self.assertEqual(rp.statsp({})["max_concurrent"], 0)
        self.assertEqual(rp.active_same_role({})["items"], [])
        recs = [None, {"ticket": "t", "role": "r", "status": "queued"},
                {"ticket": "t", "role": "r", "status": "idle"},
                {"ticket": "x", "role": "r", "status": "running"}]
        self.assertEqual(len(rp.active_same_role({"ticket": "t", "role": "r",
                                                  "records": recs})["items"]), 1)

    def test_waiting(self):
        self.assertEqual(rp.waitingp({"kind": "pm"})["reason"], "auto_session")
        self.assertEqual(rp.waitingp({"messages": []})["reason"], "empty")
        self.assertEqual(rp.waitingp({"messages": [{"role": "assistant",
                                                    "tool_calls": [1]}]})["reason"], "active")
        self.assertEqual(rp.waitingp({"messages": [{"role": "user"}]})["reason"], "active")
        self.assertEqual(rp.waitingp({"messages": [
            {"role": "user"}, {"role": "tool", "name": "artifact_write"},
            {"role": "assistant", "content": "?"}]})["reason"], "advanced")
        self.assertTrue(rp.waitingp({"messages": [
            {"role": "user"}, {"role": "assistant", "content": "?"}]})["waiting"])

    def test_flow(self):
        self.assertEqual(rp.flow_plan({"rec": {}})["effects"], [])
        wait = rp.flow_plan({"rec": {"id": "s", "messages": [
            {"role": "assistant", "content": "?"}]}, "review": {"verdict": "repush"}})
        self.assertEqual(wait["verdict"], "waiting")
        out = rp.flow_plan({"rec": {"id": "s", "messages": [{"role": "user"}]},
                            "review": {"verdict": "repush", "retries": 2},
                            "repush_text": "r", "now": "n"})
        self.assertEqual([e["kind"] for e in out["effects"]], ["write", "dispatch"])
        out = rp.flow_plan({"rec": {"id": "s", "meta": {"machine": {"terminals": ["end"]},
                                                          "stage": "mid"}},
                            "review": {"verdict": "pass"}})
        self.assertEqual([e["kind"] for e in out["effects"]], ["write", "dispatch"])
        out = rp.flow_plan({"rec": {"id": "s", "meta": {"machine": {"terminals": ["end"]},
                                                          "stage": "end",
                                                          "retrospected": True}},
                            "review": {"verdict": "pass"}})
        self.assertEqual(len(out["effects"]), 1)
        out = rp.flow_plan({"rec": {"id": "s"}, "review": {"verdict": "pass"},
                            "retrospect_enabled": True, "retrospect_text": "r",
                            "now": "n"})
        self.assertTrue(out["rec"]["meta"]["retrospected"])
        self.assertEqual(len(out["effects"]), 2)
        out = rp.flow_plan({"rec": {"id": "s"}, "review": {"verdict": "exhausted"},
                            "ticket": "t", "exhausted_text": "e"})
        self.assertEqual(out["effects"][-1]["kind"], "demand")


if __name__ == "__main__":
    unittest.main()
