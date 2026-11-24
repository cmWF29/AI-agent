"""nodes 协调模块靶向单测：注册/心跳/租约/fencing/分配/快照台账。

直接打纯函数层（不起装配、不碰源码树数据目录）；时间戳用可控时钟传入。
"""
from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.nodes.private import _pure  # noqa: E402

import importlib.util as _ilu  # noqa: E402

_spec = _ilu.spec_from_file_location(
    "push_node_client",
    Path(__file__).resolve().parents[4] / "scripts" / "push_node_client.py")
_push = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_push)


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


class LeaseExpirySemanticsTest(unittest.TestCase):
    def test_expired_lease_released_even_if_node_still_alive(self):
        state = _seed()
        _pure.heartbeat(state, "n1", {"running": 1}, 199.0)
        _pure.acquire(state, "p1", "n1", 201.0, ttl=5)
        sweep = _pure.sweep_expired(state, 207.0)
        self.assertNotIn("n1", sweep["expired"])
        self.assertEqual(sweep["released"], ["p1"])
        self.assertEqual(state["leases"]["p1"]["state"], "released")

    def test_reacquire_after_expiry_bumps_epoch(self):
        state = _seed()
        first = _pure.acquire(state, "p1", "n1", 101.0, ttl=5)
        second = _pure.acquire(state, "p1", "n1", 107.0, ttl=30)
        self.assertTrue(second["ok"])
        self.assertFalse(second["reused"])
        self.assertEqual(second["lease"]["epoch"], first["lease"]["epoch"] + 1)

    def test_fence_check_rejects_expired_lease_when_now_passed(self):
        state = _seed()
        acquired = _pure.acquire(state, "p1", "n1", 101.0, ttl=5)
        res = _pure.fence_check(state, "p1", acquired["lease"]["token"],
                                acquired["lease"]["epoch"], now=107.0)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "lease_expired")


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


class PushRegisterIdempotencyTest(unittest.TestCase):
    """push 注册：同 id 重复登记幂等，不产生第二条节点记录。"""

    def test_repeat_register_keeps_first_seen_and_refreshes_fields(self):
        state = _pure.empty_state()
        first = _pure.register(state, {"id": "n1", "endpoint": "http://10.0.0.1:8791",
                                        "capacity": {"cpu": 2}}, 100.0)
        registered_at = first["node"]["registered_at"]
        second = _pure.register(state, {"id": "n1", "endpoint": "http://10.0.0.1:8792",
                                        "capacity": {"cpu": 4}}, 120.0)
        self.assertEqual(len(state["nodes"]), 1)
        self.assertEqual(second["node"]["registered_at"], registered_at)
        self.assertEqual(second["node"]["endpoint"], "http://10.0.0.1:8792")
        self.assertEqual(second["node"]["capacity"]["cpu"], 4)

    def test_heartbeat_expiry_marks_lost_and_releases_lease(self):
        state = _seed()
        _pure.acquire(state, "p1", "n1", 101.0, ttl=30)
        sweep = _pure.sweep_expired(state, 200.0)
        self.assertIn("n1", sweep["expired"])
        self.assertIn("p1", sweep["released"])
        self.assertEqual(state["leases"]["p1"]["state"], "released")


class _CfgApi:
    """假装配 api：config.get 回喂配置密钥，clock.now 给可控时间戳。"""

    def __init__(self, secret, now=100.0):
        self._secret = secret
        self._now = now

    def call(self, route, payload, caller=None):
        if route == "config.get":
            return {"value": self._secret}
        if route == "clock.now":
            return {"ts": self._now}
        return {"value": None}


class _CfgCtx:
    def __init__(self, secret, now=100.0):
        self.api = _CfgApi(secret, now)


class PushRegisterAuthTest(unittest.TestCase):
    """push 通道鉴权：密钥来自配置；空密钥开放，配了密钥后错 token 拒认。"""

    def setUp(self):
        from ai_new.modules.agent import nodes as nodes_mod
        self.mod = nodes_mod

    def test_open_mode_when_secret_empty(self):
        self.assertIsNone(self.mod._auth_node(_CfgCtx(""), {"node_token": "x"}))

    def test_wrong_token_rejected(self):
        res = self.mod._auth_node(_CfgCtx("secret-123"), {"node_token": "wrong"})
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "unauthorized")

    def test_matching_token_allowed(self):
        self.assertIsNone(
            self.mod._auth_node(_CfgCtx("secret-123"), {"node_token": "secret-123"}))

    def test_missing_token_rejected_when_secret_configured(self):
        res = self.mod._auth_node(_CfgCtx("secret-123"), {})
        self.assertEqual(res["code"], "unauthorized")


class _FakeResp:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    def __init__(self, payload=None, exc=None):
        self.calls = []
        self.payload = payload or {"ok": True, "result": {"ok": True}}
        self.exc = exc

    def open(self, req, timeout=None):
        self.calls.append({"method": req.get_method(), "url": req.full_url,
                           "body": req.data.decode("utf-8") if req.data else ""})
        if self.exc:
            raise self.exc
        return _FakeResp(self.payload)


class PushClientBackoffTest(unittest.TestCase):
    """出站客户端：注册/心跳报文、幂等补注册、指数退避与失败复位。"""

    def _client(self, opener, **kw):
        return _push.PushNodeClient(
            "http://cp:8787", "n1", "tok-1",
            endpoint="http://10.0.0.5:8790", capacity={"cpu": 2},
            lease_ttl=2.0, interval=0.1, opener=opener, **kw)

    def test_register_posts_capability_and_token(self):
        opener = _FakeOpener()
        client = self._client(opener)
        client.register()
        self.assertEqual(len(opener.calls), 1)
        self.assertTrue(opener.calls[0]["url"].endswith("/nodes/push_register"))
        body = json.loads(opener.calls[0]["body"])
        self.assertEqual(body["id"], "n1")
        self.assertEqual(body["node_token"], "tok-1")
        self.assertEqual(body["capacity"]["cpu"], 2)
        self.assertEqual(body["role"], "executor")

    def test_heartbeat_posts_load(self):
        opener = _FakeOpener()
        client = self._client(opener)
        client.register()
        client.heartbeat({"running": 3})
        self.assertEqual(len(opener.calls), 2)
        body = json.loads(opener.calls[1]["body"])
        self.assertEqual(body["node"], "n1")
        self.assertEqual(body["load"]["running"], 3)

    def test_ensure_registered_does_not_reregister(self):
        opener = _FakeOpener()
        client = self._client(opener)
        client.register()
        client.ensure_registered()
        self.assertEqual(len(opener.calls), 1)

    def test_reconnect_reregisters_after_registry_lost(self):
        opener = _FakeOpener()
        client = self._client(opener)
        client.register()
        client.registered = False  # 控制面已按 TTL 判出表
        client.ensure_registered()
        self.assertEqual(len(opener.calls), 2)
        self.assertTrue(opener.calls[1]["url"].endswith("/nodes/push_register"))

    def test_backoff_grows_and_caps(self):
        opener = _FakeOpener()
        client = self._client(opener, backoff_base=0.2, backoff_max=1.0)
        self.assertEqual(client.backoff_delay(), 0.0)
        client.mark_failure()
        self.assertAlmostEqual(client.backoff_delay(), 0.2)
        client.mark_failure()
        self.assertAlmostEqual(client.backoff_delay(), 0.4)
        client.mark_failure()
        self.assertAlmostEqual(client.backoff_delay(), 0.8)
        client.mark_failure()
        self.assertEqual(client.backoff_delay(), 1.0)  # 封顶

    def test_network_failure_marked_then_reset_on_success(self):
        opener = _FakeOpener(exc=urllib.error.URLError("down"))
        client = self._client(opener)
        with self.assertRaises(_push.PushError) as cm:
            client.heartbeat({"running": 1})
        self.assertEqual(cm.exception.code, "network")
        self.assertGreater(client.backoff_delay(), 0.0)
        # 恢复后成功心跳，失败计数复位
        opener.exc = None
        client.heartbeat({"running": 1})
        self.assertEqual(client.backoff_delay(), 0.0)


if __name__ == "__main__":
    unittest.main()
