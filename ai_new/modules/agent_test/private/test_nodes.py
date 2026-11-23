"""nodes 协调模块靶向单测：注册/心跳/租约/fencing/分配/快照台账。

直接打纯函数层（不起装配、不碰源码树数据目录）；时间戳用可控时钟传入。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.nodes.private import _pure  # noqa: E402


def _seed():
    state = _pure.empty_state()
    _pure.register(state, {"id": "n1", "endpoint": "unix:///n1",
                           "capacity": {"cpu": 2, "memory_mb": 2048}}, 100.0)
    _pure.register(state, {"id": "n2", "endpoint": "unix:///n2",
                           "capacity": {"cpu": 4, "memory_mb": 4096}}, 100.0)
    return state


class RegisterHeartbeatTest(unittest.TestCase):
    def test_register_records_node_alive(self):
        state = _seed()
        node = state["nodes"]["n1"]
        self.assertEqual(node["status"], "alive")
        self.assertEqual(node["endpoint"], "unix:///n1")
        self.assertEqual(node["capacity"]["cpu"], 2)

    def test_heartbeat_refreshes_load_and_seen(self):
        state = _seed()
        res = _pure.heartbeat(state, "n1", {"running": 3}, 150.0)
        self.assertTrue(res["ok"])
        self.assertEqual(res["node"]["last_seen"], 150.0)
        self.assertEqual(res["node"]["load"]["running"], 3)

    def test_heartbeat_unknown_node_rejected(self):
        state = _seed()
        res = _pure.heartbeat(state, "nope", {}, 150.0)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "unknown_node")


class LeaseAcquireTest(unittest.TestCase):
    def test_first_acquire_issues_epoch_and_token(self):
        state = _seed()
        res = _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        self.assertTrue(res["ok"])
        lease = res["lease"]
        self.assertEqual(lease["epoch"], 1)
        self.assertTrue(lease["token"])
        self.assertEqual(lease["state"], "held")
        self.assertEqual(lease["expires_at"], 131.0)

    def test_conflict_acquire_rejected_while_held(self):
        state = _seed()
        _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        res = _pure.acquire(state, "p1", "n2", 102.0, ttl=30)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "lease_held")
        self.assertEqual(res["holder"], "n1")

    def test_same_node_reacquire_renews_without_epoch_bump(self):
        state = _seed()
        first = _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        second = _pure.acquire(state, "p1", "n1", 110.0, ttl=30)
        self.assertTrue(second["ok"])
        self.assertTrue(second["reused"])
        self.assertEqual(second["lease"]["epoch"], first["lease"]["epoch"])
        self.assertEqual(second["lease"]["expires_at"], 140.0)

    def test_acquire_unknown_or_lost_node_rejected(self):
        state = _seed()
        res = _pure.acquire(state, "p1", "n-x", 101.0)
        self.assertEqual(res["code"], "unknown_node")
        _pure.sweep_expired(state, 200.0)
        res = _pure.acquire(state, "p1", "n1", 201.0)
        self.assertEqual(res["code"], "node_lost")


class FailoverFenceTest(unittest.TestCase):
    def test_expired_lease_released_then_standby_bumps_epoch(self):
        state = _seed()
        first = _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        old_token = first["lease"]["token"]
        # 待命节点持续心跳；主节点失联
        _pure.heartbeat(state, "n2", {"running": 0}, 199.0)
        sweep = _pure.sweep_expired(state, 200.0)
        self.assertEqual(sweep["expired"], ["n1"])
        self.assertEqual(sweep["released"], ["p1"])
        second = _pure.acquire(state, "p1", "n2", 201.0, ttl=30)
        self.assertTrue(second["ok"])
        self.assertEqual(second["lease"]["epoch"], 2)
        # 旧 token 回写必须被 fencing 拒
        stale = _pure.fence_check(state, "p1", old_token, 2)
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["code"], "token_mismatch")
        ok = _pure.fence_check(state, "p1", second["lease"]["token"], 2)
        self.assertTrue(ok["ok"])

    def test_stale_epoch_rejected(self):
        state = _seed()
        res = _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        lease = res["lease"]
        bad = _pure.fence_check(state, "p1", lease["token"], lease["epoch"] + 1)
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["code"], "stale_epoch")
        self.assertEqual(bad["current_epoch"], lease["epoch"])

    def test_fence_unknown_project_and_token_mismatch(self):
        state = _seed()
        _pure.acquire(state, "p1", "n1", 101.0)
        self.assertEqual(_pure.fence_check(state, "none", "t", 1)["code"],
                         "unknown_project")
        self.assertEqual(_pure.fence_check(state, "p1", "wrong", 1)["code"],
                         "token_mismatch")


class RenewReleaseTest(unittest.TestCase):
    def test_renew_extends_expiry(self):
        state = _seed()
        res = _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        token = res["lease"]["token"]
        renewed = _pure.renew(state, "p1", token, 120.0)
        self.assertTrue(renewed["ok"])
        self.assertEqual(renewed["lease"]["expires_at"], 150.0)

    def test_renew_mismatch_or_expired_rejected(self):
        state = _seed()
        res = _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        token = res["lease"]["token"]
        self.assertEqual(_pure.renew(state, "p1", "bad", 102.0)["code"],
                         "token_mismatch")
        self.assertEqual(_pure.renew(state, "p1", token, 132.0)["code"],
                         "lease_expired")

    def test_release_mismatch_rejected(self):
        state = _seed()
        res = _pure.acquire(state, "p1", "n1", 101.0)
        self.assertEqual(_pure.release(state, "p1", "bad", 102.0)["code"],
                         "token_mismatch")
        rel = _pure.release(state, "p1", res["lease"]["token"], 102.0)
        self.assertTrue(rel["ok"])
        self.assertEqual(rel["lease"]["state"], "released")


class ViewTest(unittest.TestCase):
    def test_nodes_view_carries_health_and_projects(self):
        state = _seed()
        _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        _pure.acquire(state, "p2", "n1", 101.0, ttl=30)
        _pure.heartbeat(state, "n2", {}, 101.0)
        view = {n["id"]: n for n in _pure.nodes_view(state, 102.0)}
        self.assertEqual(view["n1"]["health"], "alive")
        self.assertEqual(sorted(view["n1"]["projects"]), ["p1", "p2"])
        self.assertEqual(view["n2"]["projects"], [])

    def test_project_node_lookup(self):
        state = _seed()
        self.assertIsNone(_pure.project_node(state, "p1"))
        res = _pure.acquire(state, "p1", "n1", 101.0)
        row = _pure.project_node(state, "p1")
        self.assertEqual(row["node"], "n1")
        self.assertEqual(row["epoch"], res["lease"]["epoch"])
        self.assertEqual(row["tier"], "weak")

    def test_assignments_include_released_for_audit(self):
        state = _seed()
        _pure.acquire(state, "p1", "n1", 101.0)
        _pure.release(state, "p1", state["leases"]["p1"]["token"], 102.0)
        rows = _pure.assignments_view(state)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "released")


class ReassignMigrationTest(unittest.TestCase):
    def test_reassign_after_failover_bumps_epoch_and_records_migration(self):
        state = _seed()
        first = _pure.acquire(state, "p1", "n1", 101.0, ttl=30,
                              checkpoint={"ticket": "T1", "seq": 3, "stage": "review"})
        old_token = first["lease"]["token"]
        _pure.heartbeat(state, "n2", {"running": 0}, 199.0)
        sweep = _pure.sweep_expired(state, 200.0)
        self.assertEqual(sweep["expired"], ["n1"])
        res = _pure.reassign(state, "p1", 201.0, reason="node_lost")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["lease"]["node"], "n2")
        self.assertEqual(res["lease"]["epoch"], 2)
        self.assertEqual(res["previous_epoch"], 1)
        mig = res["migration"]
        self.assertEqual(mig["from_node"], "n1")
        self.assertEqual(mig["to_node"], "n2")
        self.assertEqual(mig["reason"], "node_lost")
        self.assertEqual(mig["state"], "done")
        self.assertEqual(mig["checkpoint"]["seq"], 3)
        self.assertIn("fence", res["steps"])
        self.assertIn("reassign", res["steps"])
        # 旧 token 回写必须被 fencing 拒
        stale = _pure.fence_check(state, "p1", old_token, 1)
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["code"], "token_mismatch")

    def test_reassign_refuses_live_lease_without_preempt(self):
        state = _seed()
        _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        res = _pure.reassign(state, "p1", 102.0)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "lease_held")
        self.assertEqual(res["holder"], "n1")
        self.assertEqual(state["migrations"], [])

    def test_reassign_no_candidate_records_failed(self):
        state = _seed()
        _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        _pure.sweep_expired(state, 200.0)
        state["nodes"]["n2"]["status"] = "lost"  # 候选也不可用
        res = _pure.reassign(state, "p1", 201.0)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "no_candidate")
        self.assertEqual(res["migration"]["state"], "failed")
        self.assertIsNone(res["migration"]["to_node"])

    def test_pick_node_scores_alive_nodes_with_affinity(self):
        state = _seed()
        _pure.acquire(state, "p1", "n1", 101.0)
        picked = _pure.pick_node(state, "p1", 102.0)
        self.assertTrue(picked["ok"])
        self.assertIn(picked["node"], ("n1", "n2"))
        n1 = next(n for n in picked["all"] if n["node"] == "n1")
        self.assertIn("history", n1["reasons"])

    def test_recovered_node_does_not_reclaim_held_lease(self):
        state = _seed()
        first = _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        old_token = first["lease"]["token"]
        _pure.heartbeat(state, "n2", {"running": 0}, 199.0)
        _pure.sweep_expired(state, 200.0)
        second = _pure.acquire(state, "p1", "n2", 201.0, ttl=30)
        self.assertTrue(second["ok"])
        # n1 恢复心跳后抢回 p1 必须被拒（默认不抢回）
        _pure.heartbeat(state, "n1", {"running": 0}, 202.0)
        back = _pure.acquire(state, "p1", "n1", 203.0, ttl=30)
        self.assertEqual(back["code"], "lease_held")
        self.assertEqual(back["holder"], "n2")
        stale = _pure.fence_check(state, "p1", old_token, 1)
        self.assertFalse(stale["ok"])

    def test_idem_key_stable_and_scoped(self):
        k1 = _pure.idem_key("p1", "T1", "create", 3)
        self.assertEqual(k1, "p1:T1:create:3")
        self.assertNotEqual(k1, _pure.idem_key("p1", "T1", "create", 4))
        self.assertNotEqual(k1, _pure.idem_key("p1", "T2", "create", 3))


class StatusDataPlaneTest(unittest.TestCase):
    def test_nodes_view_carries_lease_count_and_remaining(self):
        state = _seed()
        _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        _pure.acquire(state, "p2", "n1", 101.0, ttl=30)
        _pure.heartbeat(state, "n2", {}, 101.0)
        view = {n["id"]: n for n in _pure.nodes_view(state, 102.0)}
        self.assertEqual(view["n1"]["lease_count"], 2)
        self.assertAlmostEqual(view["n1"]["lease_remaining"], 29.0, places=2)
        self.assertEqual(view["n2"]["lease_count"], 0)
        self.assertIsNone(view["n2"]["lease_remaining"])
        self.assertEqual(view["n1"]["health"], "alive")

    def test_assignments_view_carries_remaining(self):
        state = _seed()
        _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        _pure.release(state, "p1", state["leases"]["p1"]["token"], 102.0)
        rows = {r["project"]: r for r in _pure.assignments_view(state, now=101.0)}
        self.assertIsNone(rows["p1"]["remaining"])

    def test_backups_view_normalizes_time_and_state(self):
        state = _pure.empty_state()
        _pure.record_backup(state, "p1", {"snapshot_id": "s1",
                                          "created_at": 200.0, "state": "verified"})
        rows = _pure.backups_view(state)
        self.assertEqual(rows[0]["last_backup_at"], 200.0)
        self.assertEqual(rows[0]["backup_state"], "verified")

    def test_status_view_composite_shape(self):
        state = _seed()
        _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        _pure.record_backup(state, "p1", {"snapshot_id": "s1",
                                          "created_at": 200.0, "state": "verified"})
        view = _pure.status_view(state, 102.0)
        self.assertEqual(sorted(view.keys()), ["assignments", "backups", "nodes"])
        n1 = next(n for n in view["nodes"] if n["id"] == "n1")
        self.assertEqual(n1["lease_count"], 1)
        self.assertAlmostEqual(n1["lease_remaining"], 29.0, places=2)
        a1 = next(a for a in view["assignments"] if a["project"] == "p1")
        self.assertEqual(a1["node"], "n1")
        self.assertAlmostEqual(a1["remaining"], 29.0, places=2)
        b1 = next(b for b in view["backups"] if b["project"] == "p1")
        self.assertEqual(b1["last_backup_at"], 200.0)
        self.assertEqual(b1["backup_state"], "verified")


class NodeRoleMaskTest(unittest.TestCase):
    def test_default_role_executor_and_not_exposed(self):
        state = _seed()
        node = state["nodes"]["n1"]
        self.assertEqual(node["role"], "executor")
        self.assertFalse(node["public_exposed"])

    def test_entry_node_marked_exposed(self):
        state = _pure.empty_state()
        res = _pure.register(state, {"id": "gw", "endpoint": "https://10.0.0.8:8443",
                                     "role": "entry", "public_exposed": True}, 100.0)
        self.assertTrue(res["ok"])
        self.assertEqual(res["node"]["role"], "entry")
        self.assertTrue(res["node"]["public_exposed"])

    def test_view_exposes_masked_address_only(self):
        state = _seed()
        view = _pure.nodes_view(state, 150.0)
        row = next(r for r in view if r["id"] == "n1")
        self.assertNotIn("endpoint", row)
        self.assertEqual(row["endpoint_masked"], "unix://***")
        self.assertFalse(row["public_exposed"])

    def test_mask_endpoint_hides_host_and_port(self):
        self.assertEqual(_pure.mask_endpoint("https://192.168.1.23:8443"), "https://***")
        self.assertEqual(_pure.mask_endpoint("10.0.0.5:9000"), "***")
        self.assertEqual(_pure.mask_endpoint(""), "")


class RouteRegistrationTest(unittest.TestCase):
    def test_status_route_registered(self):
        from ai_new.modules.agent.nodes import setup as nodes_setup

        class _Api:
            def __init__(self):
                self.routes = {}

            def register(self, name, fn, *args, **kwargs):
                self.routes[name] = fn

            def call(self, route, payload, caller=None):
                return {"value": None}

        ctx = type("Ctx", (), {"api": _Api()})()
        nodes_setup(ctx)
        self.assertIn("nodes.status", ctx.api.routes)
        self.assertIn("nodes.nodes_view", ctx.api.routes)
        self.assertIn("nodes.assignments", ctx.api.routes)
        self.assertIn("nodes.backups", ctx.api.routes)


class SnapshotTest(unittest.TestCase):
    def test_plan_rejects_traversal_and_absolute(self):
        plan = _pure.plan_snapshot("p1", ["tickets/a.yaml", "../escape.md",
                                           "/abs/b.md", "docs/c.md"], 202.0)
        self.assertFalse(plan["ok"])
        self.assertEqual(sorted(plan["rejected"]),
                         ["../escape.md", "/abs/b.md"])
        rels = [e["rel"] for e in plan["manifest"]["entries"]]
        self.assertEqual(rels, ["tickets/a.yaml", "docs/c.md"])

    def test_verify_manifest_reports_missing_and_mismatch(self):
        plan = _pure.plan_snapshot("p1", ["a.txt", "b.txt"], 202.0)
        plan["manifest"]["entries"][0]["digest"] = "da"
        plan["manifest"]["entries"][1]["digest"] = "db"
        good = _pure.verify_manifest(plan["manifest"], {"a.txt": "da", "b.txt": "db"})
        self.assertTrue(good["ok"])
        bad = _pure.verify_manifest(plan["manifest"], {"a.txt": "da"})
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["missing"], ["b.txt"])
        mm = _pure.verify_manifest(plan["manifest"], {"a.txt": "da", "b.txt": "xx"})
        self.assertEqual(mm["mismatch"], ["b.txt"])

    def test_backup_record_and_view(self):
        state = _pure.empty_state()
        rec = _pure.record_backup(state, "p1", {"snapshot_id": "snap-1",
                                                "state": "verified"})
        self.assertEqual(rec["project"], "p1")
        view = _pure.backups_view(state)
        self.assertEqual(view[0]["snapshot_id"], "snap-1")


if __name__ == "__main__":
    unittest.main()
