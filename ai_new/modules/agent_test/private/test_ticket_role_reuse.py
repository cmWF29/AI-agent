"""同工单同岗位复用：role_spawn 不重复建会话（T-20261128-0003 AC1-AC6）。

判定归 `sessions.reuse_target`（读会话记录，含 idle/spawned），记账归
`tickets.bindrole`；本文件锁纯函数形状与需求接线，真实路由由 test_core 的
idle 复用用例覆盖。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.sessions.private import _run_pure as sp  # noqa: E402
from ai_new.modules.agent.tickets.private import _pure as tp  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]


def session(sid, role="tester", ticket="T-1", status="idle",
            created=0.0, updated=0.0):
    return {"id": sid, "role": role, "ticket": ticket, "status": status,
            "created": created, "updated": updated}


def rec(*rows):
    return {"id": "T-1", "roles": list(rows), "history": []}


def row(sid, role="tester", status="spawned"):
    return {"session": sid, "role": role, "status": status}


class ReuseTargetCase(unittest.TestCase):
    def test_idle_and_spawned_are_reusable_not_only_active(self):
        """AC1 真实历史：T-0002 的 tester 是 idle/spawned，不能因为不在途就再建。"""
        for status in ("idle", "spawned"):
            got = sp.reuse_target({"ticket": "T-1", "role": "tester",
                                   "records": [session("S-OLD", status=status)]})
            self.assertEqual(got["item"]["id"], "S-OLD")

    def test_active_wins_then_latest(self):
        records = [session("S-OLD", updated=10.0),
                   session("S-LIVE", status="running", updated=1.0),
                   session("S-NEW", updated=20.0)]
        got = sp.reuse_target({"ticket": "T-1", "role": "tester", "records": records})
        self.assertEqual(got["item"]["id"], "S-LIVE", "在途优先")
        records = [session("S-A", updated=20.0), session("S-B", updated=20.0)]
        picks = {sp.reuse_target({"ticket": "T-1", "role": "tester",
                                  "records": records})["item"]["id"] for _ in range(5)}
        self.assertEqual(picks, {"S-A"}, "同档同时间按 id 定序，结果恒定")

    def test_cross_ticket_role_and_gone_are_not_reused(self):
        records = [session("S-OTHER-T", ticket="T-2"),
                   session("S-OTHER-R", role="developer"),
                   session("S-GONE", status="gone")]
        self.assertIsNone(sp.reuse_target({"ticket": "T-1", "role": "tester",
                                           "records": records})["item"])
        self.assertIsNone(sp.reuse_target({"ticket": "", "role": "tester",
                                           "records": records})["item"])

    def test_gone_does_not_block_new(self):
        got = sp.reuse_target({"ticket": "T-1", "role": "tester",
                               "records": [session("S-GONE", status="gone")]})
        self.assertIsNone(got["item"])


class BindRoleCase(unittest.TestCase):
    def test_create_then_reuse_keeps_one_row_and_marks_receipt(self):
        r = tp.bindrole({"rec": rec(), "session": "S-NEW", "role": "tester",
                         "reuse": False, "task": "第一次", "now": "t1"})
        self.assertEqual(len(r["roles"]), 1)
        self.assertFalse(r["roles"][0]["reused"])
        self.assertEqual(r["history"][-1]["event"], "role_spawn")
        r = tp.bindrole({"rec": r, "session": "S-NEW", "role": "tester",
                         "reuse": True, "task": "第二次", "now": "t2"})
        self.assertEqual(len(r["roles"]), 1, "同会话不并出第二条同岗线")
        self.assertTrue(r["roles"][0]["reused"])
        self.assertEqual(r["history"][-1]["event"], "role_reuse")

    def test_different_session_same_role_stays_parallel(self):
        """历史脏数据不合并：不同会话各有记录，清理另开工单。"""
        r = tp.bindrole({"rec": rec(), "session": "S-1", "role": "tester",
                         "reuse": False, "task": "旧", "now": "t1"})
        r = tp.bindrole({"rec": r, "session": "S-2", "role": "tester",
                         "reuse": True, "task": "新", "now": "t2"})
        self.assertEqual([x["session"] for x in r["roles"]], ["S-1", "S-2"])


class DemandPathCase(unittest.TestCase):
    """接线：需求树只允许顺序 call；复用判定下沉 sessions.spawn，yaml 不判分支。"""

    def setUp(self):
        import yaml as _yaml
        path = (ROOT / "ai_new/modules/agent_common/demand_engine/data"
                "/demands/ticket-role-spawn.yaml")
        self.rec = _yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_tree_is_sequential_calls_only(self):
        control = {"when", "each", "until", "wait", "retry", "parallel", "branch"}
        bad = [i for i, st in enumerate(self.rec.get("do") or [])
               if not isinstance(st, dict) or (control & set(st)) or "call" not in st]
        self.assertEqual(bad, [], "需求树出现分支/控制流: %s" % bad)

    def test_one_spawn_call_and_receipt_flows_from_module(self):
        runs = [st for st in self.rec.get("do") or []
                if st.get("call") == "demand_engine.run"]
        ids = [((st.get("with") or {}).get("id") or {}).get("lit") for st in runs]
        self.assertEqual(ids, ["session-spawn"], "复用/新建只能由 sessions.spawn 内部判定")
        bind = [st for st in self.rec.get("do") or [] if st.get("call") == "tickets.bindrole"][0]
        self.assertEqual(bind["with"]["session"], {"get": "sp.result.id"})
        self.assertEqual(bind["with"]["reuse"], {"get": "sp.result.reused"})


if __name__ == "__main__":
    unittest.main()
