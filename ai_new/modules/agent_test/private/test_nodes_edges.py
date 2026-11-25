"""nodes 纯函数边界：登记校验、布尔归一、租约失败分支、快照与再分配。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.nodes.private import _pure as n  # noqa: E402


def seed():
    state = n.empty_state()
    n.register(state, {"id": "n1", "endpoint": "unix:///n1", "region": "r1",
                       "capacity": {"cpu": 2}, "public_exposed": "yes"}, 100.0)
    n.register(state, {"id": "n2", "endpoint": "unix:///n2", "region": "r2",
                       "capacity": {"cpu": 4}}, 100.0)
    return state


class NodesEdgeTest(unittest.TestCase):
    def test_coercion_and_validation(self):
        self.assertTrue(n._coerce_bool(1))
        self.assertFalse(n._coerce_bool(0))
        self.assertTrue(n._coerce_bool("TRUE"))
        self.assertFalse(n._coerce_bool("no"))
        self.assertEqual(n._coerce_role("", {"role": "entry"}), "entry")
        self.assertEqual(n._coerce_role("bad"), "executor")
        self.assertEqual(n._ts("bad"), 0.0)
        self.assertTrue(n.token_matches("x", ""))
        self.assertEqual(n.validate_node([]), ["node_not_object"])
        self.assertEqual(n.validate_node({}), ["missing_id", "missing_endpoint"])
        self.assertEqual(n.validate_node({"id": "a", "endpoint": "e",
                                          "capacity": []}), ["capacity_not_object"])
        self.assertEqual(n.register(n.empty_state(), {"id": ""}, 1)["errors"],
                         ["missing_id", "missing_endpoint"])
        self.assertEqual(n.mask_endpoint(""), "")
        self.assertEqual(n.mask_endpoint("unix:///tmp/x"), "unix://***")
        self.assertEqual(n.mask_endpoint("bad"), "***")

    def test_lease_failure_branches(self):
        state = seed()
        self.assertEqual(n.acquire(state, "", "n1", 1)["code"],
                         "missing_project_or_node")
        lease = n.acquire(state, "p", "n1", 1, ttl=30)["lease"]
        self.assertEqual(n.renew(state, "none", lease["token"], 2)["code"],
                         "unknown_project")
        self.assertEqual(n.renew(state, "p", "bad", 2)["code"], "token_mismatch")
        self.assertEqual(n.renew(state, "p", lease["token"], 100)["code"],
                         "lease_expired")
        self.assertTrue(n.renew(state, "p", lease["token"], 2,
                                checkpoint={"step": 1})["ok"])
        lease["state"] = n.LEASE_RELEASED
        self.assertEqual(n.renew(state, "p", lease["token"], 2)["code"], "not_held")
        self.assertEqual(n.release(state, "none", "x", 2)["code"], "unknown_project")
        self.assertEqual(n.release(state, "p", "bad", 2)["code"], "token_mismatch")
        fresh = n.acquire(state, "q", "n1", 2, ttl=30)["lease"]
        self.assertEqual(n.fence_check(state, "q", fresh["token"], "bad")["code"],
                         "epoch_invalid")
        fresh["state"] = n.LEASE_RELEASED
        self.assertEqual(n.fence_check(state, "q", fresh["token"], 1)["code"],
                         "not_held")

    def test_snapshot_and_pick(self):
        self.assertFalse(n._rel_ok(""))
        self.assertFalse(n._rel_ok("/abs"))
        self.assertFalse(n._rel_ok("C:/x"))
        self.assertFalse(n._rel_ok("a/../b"))
        self.assertTrue(n._rel_ok("a/b"))
        plan = n.plan_snapshot("p", [{"rel": "a", "digest": "d"}, "b", "../x"], 5)
        self.assertEqual([r["rel"] for r in plan["manifest"]["entries"]], ["a", "b"])
        self.assertEqual(plan["rejected"], ["../x"])
        state = seed()
        state["leases"]["rel"] = {"state": n.LEASE_RELEASED, "node": "n1"}
        state["leases"]["held"] = {"state": n.LEASE_HELD, "node": "n1",
                                   "expires_at": 999}
        n.sweep_expired(state, 10)
        view = n.nodes_view(state, 10)
        self.assertEqual(view[0]["id"], "n1")
        n.migrations_view({"migrations": [{"project": "a", "migrated_at": 1},
                                          {"project": "b", "migrated_at": 2}]})
        self.assertEqual(n._running({"load": {"running": "bad"}}), 0.0)
        picked = n.pick_node(state, "p", 10, {"region": "r2",
                                              "weights": {"region": 5}})
        self.assertEqual(picked["node"], "n2")
        self.assertIn("region", picked["reasons"])

    def test_reassign_failure_and_preempt(self):
        state = seed()
        state["leases"]["p"] = {"project": "p", "node": "n1", "epoch": 1,
                                "state": n.LEASE_HELD, "token": "t", "tier": "weak",
                                "expires_at": 0}
        state["nodes"]["n1"]["status"] = "lost"
        n.register(state, {"id": "n3", "endpoint": "unix:///n3",
                           "capacity": {"cpu": 1}}, 100)
        state["nodes"]["n3"]["status"] = "lost"
        out = n.reassign(state, "p", 200, candidate="n3")
        self.assertEqual(out["code"], "node_lost")
        self.assertEqual(out["migration"]["state"], n.MIG_FAILED)
        self.assertEqual(n.reassign(state, "none", 200)["code"],
                         "unknown_project")
        state["leases"]["z"] = {"project": "z", "node": "n1", "epoch": 1,
                                "state": n.LEASE_HELD, "token": "t", "tier": "weak",
                                "expires_at": 999}
        state["nodes"]["n1"]["status"] = "alive"
        n.register(state, {"id": "n1", "endpoint": "unix:///n1",
                           "capacity": {"cpu": 2}}, 200)
        preempt = n.reassign(state, "z", 200, policy={"preempt_back": True})
        self.assertTrue(preempt["ok"])
        self.assertIn("preempt-back-allowed", preempt["steps"])


if __name__ == "__main__":
    unittest.main()
