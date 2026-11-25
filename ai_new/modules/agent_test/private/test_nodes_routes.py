"""nodes 路由装配：CAS 循环、push 鉴权、只读视图与快照/迁移路由闭环。"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.nodes import (  # noqa: E402
    _auth_node, _mutate, _read_state, _register_tools, _route_acquire,
    _route_assignments, _route_backup_record, _route_backups, _route_fence_check,
    _route_heartbeat, _route_migrations, _route_nodes_view, _route_overview,
    _route_pick_node, _route_project_node, _route_push_heartbeat,
    _route_push_register, _route_reassign, _route_register, _route_release,
    _route_renew, _route_snapshot_plan, _route_status, _route_verify_snapshot,
    setup, _node_secret, _view_state)


class Api:
    def __init__(self, ctx):
        self.ctx = ctx
        self.routes = {}
        self.registered = []

    def call(self, route, payload=None, caller=None):
        if route in self.routes:
            return self.routes[route](payload or {})
        if route == "clock.now":
            return {"ts": self.ctx.now}
        if route == "store.read":
            return {"value": copy.deepcopy(self.ctx.state)}
        if route == "config.get":
            return {"value": self.ctx.secret}
        raise AssertionError(route)

    def register(self, name, fn, desc="", module=None):
        self.registered.append((name, fn, module))
        self.routes.setdefault(name, lambda p, _fn=fn: _fn(self.ctx, p))


class Tools:
    def __init__(self):
        self.rows = []
        self.present = {"nodes_view"}

    def has(self, name):
        return name in self.present

    def register(self, *args, **kwargs):
        self.rows.append((args, kwargs))


class Ctx:
    def __init__(self, state=None, now=100.0, secret=""):
        self.state = state or {"nodes": {}, "leases": {}, "backups": {},
                               "migrations": []}
        self.now = now
        self.secret = secret
        self.cas_outcomes = []
        self.cas_rows = []
        self.api = Api(self)
        self.api.routes["store.cas"] = self._cas

    def _cas(self, payload):
        self.cas_rows.append(copy.deepcopy(payload))
        if self.cas_outcomes:
            out = self.cas_outcomes.pop(0)
            if out.get("ok"):
                self.state = copy.deepcopy(payload["value"])
            return out
        if payload.get("expected") == self.state:
            self.state = copy.deepcopy(payload["value"])
            return {"ok": True}
        return {"ok": False, "conflict": True}


class NodesRoutesTest(unittest.TestCase):
    def ctx(self, **kw):
        ctx = Ctx(**kw)
        setup(ctx)
        return ctx

    def test_setup_and_tools(self):
        ctx = self.ctx()
        self.assertEqual(len(ctx.api.registered), 20)
        plain = Ctx()
        _register_tools(plain)
        self.assertEqual(plain.api.routes.get("nodes.nodes_view") is None, True)
        with_tools = Ctx()
        with_tools.tools = Tools()
        with_tools.api.routes["store.read"] = lambda p: {
            "value": {"tool_nodes_view_desc": "视图"}}
        ctx2 = self.ctx()
        ctx2.tools = Tools()
        ctx2.api.routes["store.read"] = lambda p: {
            "value": {"tool_nodes_register_desc": "登记"}}
        _register_tools(ctx2)
        self.assertEqual(len(ctx2.tools.rows), 6)
        self.assertEqual(ctx2.tools.rows[0][1]["module"], "nodes")
        fn = ctx2.tools.rows[0][0][3]
        self.assertTrue(fn(ctx2, {"id": "z", "endpoint": "e"})["ok"])
        ctx2.api.routes["store.read"] = lambda p: {"value": []}
        self.assertEqual(_read_state(ctx2)["nodes"], {})

    def test_read_state_and_secret(self):
        ctx = self.ctx()
        ctx.state = {"nodes": {"x": {}}, "extra": 1}
        state = _read_state(ctx)
        self.assertEqual(state["nodes"], {"x": {}})
        self.assertNotIn("extra", state)
        self.assertEqual(_node_secret(ctx), "")
        ctx.secret = "s"
        self.assertEqual(_node_secret(ctx), "s")
        denied = _auth_node(ctx, {"node_token": "bad"})
        self.assertEqual(denied["code"], "unauthorized")
        self.assertIsNone(_auth_node(ctx, {"node_token": "s"}))
        self.assertIsNone(_auth_node(Ctx(), {}))

    def test_mutate_success_conflict_error(self):
        ctx = self.ctx()
        ctx.state["nodes"] = {"n": {"status": "alive", "last_seen": 100,
                                    "endpoint": "e"}}
        out = _mutate(ctx, lambda s: __import__(
            "ai_new.modules.agent.nodes.private._pure",
            fromlist=["x"]).heartbeat(s, "n", {"running": 2}, 110))
        self.assertTrue(out["ok"])
        self.assertEqual(out["effects"], [])

        ctx = self.ctx()
        ctx.cas_outcomes = [{"ok": False, "conflict": True}, {"ok": True}]
        out = _mutate(ctx, lambda s: __import__(
            "ai_new.modules.agent.nodes.private._pure",
            fromlist=["x"]).register(s, {"id": "n", "endpoint": "e"}, 110))
        self.assertTrue(out["ok"])

        ctx = self.ctx()
        ctx.cas_outcomes = [{"ok": False, "conflict": False, "code": "boom"}]
        out = _mutate(ctx, lambda s: __import__(
            "ai_new.modules.agent.nodes.private._pure",
            fromlist=["x"]).register(s, {"id": "n", "endpoint": "e"}, 110))
        self.assertEqual(out["code"], "boom")

        ctx = self.ctx()
        ctx.cas_outcomes = [{"ok": False, "conflict": True}] * 8
        out = _mutate(ctx, lambda s: __import__(
            "ai_new.modules.agent.nodes.private._pure",
            fromlist=["x"]).register(s, {"id": "n", "endpoint": "e"}, 110))
        self.assertEqual(out["code"], "conflict_exhausted")

    def test_register_heartbeat_push(self):
        ctx = self.ctx()
        self.assertTrue(_route_register(ctx, {"id": "n1", "endpoint": "e",
                                              "capacity": {"cpu": 2}})["ok"])
        self.assertTrue(_route_heartbeat(ctx, {"node": "n1",
                                              "load": {"running": 1}})["ok"])
        ctx.secret = "s"
        self.assertEqual(_route_push_register(ctx, {"id": "n1"})["code"],
                         "unauthorized")
        self.assertEqual(_route_push_heartbeat(ctx, {"node": "n1"})["code"],
                         "unauthorized")
        ctx.secret = ""
        self.assertTrue(_route_push_register(ctx, {"id": "n2",
                                                  "endpoint": "e2"})["ok"])
        self.assertEqual(_route_push_register(ctx, {"id": "n2",
                                                    "endpoint": "e2"})["channel"],
                         "push")
        self.assertTrue(_route_push_heartbeat(ctx, {"node": "n2"})["ok"])

    def test_lease_routes(self):
        ctx = self.ctx()
        acquired = _route_acquire(ctx, {"project": "p", "node": "n1"})
        self.assertEqual(acquired["code"], "unknown_node")
        _route_register(ctx, {"id": "n1", "endpoint": "e"})
        acquired = _route_acquire(ctx, {"project": "p", "node": "n1", "ttl": 30})
        token = acquired["lease"]["token"]
        self.assertTrue(_route_renew(ctx, {"project": "p", "token": token})["ok"])
        self.assertTrue(_route_fence_check(ctx, {"project": "p", "token": token,
                                                 "epoch": 1})["ok"])
        self.assertTrue(_route_release(ctx, {"project": "p", "token": token})["ok"])
        self.assertEqual(_route_release(ctx, {"project": "p",
                                              "token": "bad"})["code"],
                         "token_mismatch")

    def test_views(self):
        ctx = self.ctx()
        _route_register(ctx, {"id": "n1", "endpoint": "e", "capacity": {"cpu": 2},
                              "region": "r", "public_exposed": True})
        _route_acquire(ctx, {"project": "p", "node": "n1", "ttl": 30})
        self.assertTrue(_route_nodes_view(ctx, {})["ok"])
        self.assertTrue(_route_assignments(ctx, {})["ok"])
        self.assertTrue(_route_overview(ctx, {})["ok"])
        self.assertIn("nodes", _route_status(ctx, {}))
        self.assertTrue(_route_project_node(ctx, {"project": "p"})["ok"])
        self.assertTrue(_route_backups(ctx, {})["ok"])
        self.assertTrue(_route_migrations(ctx, {})["ok"])
        picked = _route_pick_node(ctx, {"project": "p"})
        self.assertEqual(picked["node"], "n1")

    def test_snapshot_backup_and_reassign(self):
        ctx = self.ctx()
        _route_register(ctx, {"id": "n1", "endpoint": "e", "capacity": {"cpu": 2}})
        _route_acquire(ctx, {"project": "p", "node": "n1", "ttl": 30})
        rec = _route_backup_record(ctx, {"project": "p",
                                         "snapshot": {"id": "s1"}})
        self.assertTrue(rec["ok"])
        self.assertEqual(len(_route_backups(ctx, {})["backups"]), 1)
        plan = _route_snapshot_plan(ctx, {"project": "p",
                                          "entries": [{"rel": "a", "digest": "d"}, "../b"]})
        self.assertFalse(plan["ok"])
        self.assertEqual(plan["rejected"], ["../b"])
        verified = _route_verify_snapshot(ctx, {
            "manifest": plan["manifest"], "digests": {"a": "x"}})
        self.assertFalse(verified["ok"])
        self.assertEqual(verified["mismatch"], ["a"])
        self._reassign_flow(ctx)

    def _reassign_flow(self, ctx):
        ctx.state["nodes"]["n1"]["status"] = "lost"
        out = _route_reassign(ctx, {"project": "p", "candidate": "n1",
                                    "reason": "lost"})
        self.assertEqual(out["code"], "node_lost")
        self.assertEqual(len(_route_migrations(ctx, {})["migrations"]), 1)


if __name__ == "__main__":
    unittest.main()
