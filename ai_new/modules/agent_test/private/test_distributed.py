"""分布式协调验收：跨进程 CAS、节点登记不丢更新、同项目租约单持有者。

每个子进程独立装配 Context（独立文件视图），只共享暂存数据根；用真实
``store.cas`` + 跨进程文件锁证明协调状态不是进程内全局副本。
"""
from __future__ import annotations

import base64
import multiprocessing
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from _fixtures import stage, write_config  # noqa: E402

MASTER_KEY = base64.b64encode(b"0" * 32).decode()
MP = multiprocessing.get_context("spawn")


def _child_ctx(root):
    os.environ["AI_NEW_DATA"] = str(root)
    os.environ["AI_NEW_SECRET_KEY"] = MASTER_KEY
    os.environ["AI_NEW_SECRET_KEY_FILE"] = str(Path(root) / "secrets.key")
    from ai_new.modules.agent_common.boot.private._boot import _build as build
    from ai_new.modules.agent_common.boot.private._context import Context
    ctx = Context(Path(root))
    build(ctx)
    return ctx


def _cas_add(root, key, count, queue):
    try:
        ctx = _child_ctx(root)
        for _ in range(count):
            row = ctx.api.call("store.read", {"module": "agent/nodes", "path": key},
                               caller=None)
            current = row.get("value") if isinstance(row.get("value"), dict) else {"n": 0}
            nxt = {"n": int(current.get("n") or 0) + 1}
            for _attempt in range(20):
                res = ctx.api.call("store.cas", {
                    "module": "agent/nodes", "path": key,
                    "expected": current, "create": True, "value": nxt}, caller=None)
                if res.get("ok"):
                    break
                if not res.get("conflict"):
                    raise RuntimeError(res.get("code") or "cas_error")
                current = res.get("current") or {"n": 0}
                nxt = {"n": int(current.get("n") or 0) + 1}
            else:
                raise RuntimeError("cas retry exhausted")
        queue.put("ok")
    except Exception as exc:  # noqa: BLE001 - 子进程错误必须回传主进程
        queue.put("ERR:%s" % exc)


def _register(root, nid, barrier, queue):
    try:
        ctx = _child_ctx(root)
        barrier.wait(timeout=20)
        res = ctx.api.call("nodes.register", {
            "id": nid, "endpoint": "unix://" + nid,
            "capacity": {"cpu": 1}}, caller=None)
        queue.put("ok" if res.get("ok") else "ERR:%s" % res.get("code"))
    except Exception as exc:  # noqa: BLE001
        queue.put("ERR:%s" % exc)


def _acquire(root, node, project, barrier, queue):
    try:
        ctx = _child_ctx(root)
        barrier.wait(timeout=20)
        res = ctx.api.call("nodes.acquire", {
            "project": project, "node": node, "ttl": 30}, caller=None)
        queue.put((node, bool(res.get("ok")), res.get("code") or ""))
    except Exception as exc:  # noqa: BLE001
        queue.put(("ERR", False, str(exc)))


class DistributedCoordinationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        stage(root)
        write_config(root, {
            "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
            "llm": {"base_url": "http://stub.local/v1", "api_key": "k", "model": "stub"},
            "tickets": {"stall_check": {"enabled": False}},
        })
        cls.root = root
        os.environ["AI_NEW_DATA"] = str(root)
        os.environ["AI_NEW_SECRET_KEY"] = MASTER_KEY
        os.environ["AI_NEW_SECRET_KEY_FILE"] = str(root / "secrets.key")
        from ai_new.modules.agent_common.boot.private._boot import _build as build
        from ai_new.modules.agent_common.boot.private._context import Context
        cls.ctx = Context(root)
        build(cls.ctx)

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("AI_NEW_DATA", None)
        os.environ.pop("AI_NEW_SECRET_KEY", None)
        os.environ.pop("AI_NEW_SECRET_KEY_FILE", None)
        shutil.rmtree(cls.tmp.name, ignore_errors=True)

    def _run(self, target, args, timeout=45):
        p = MP.Process(target=target, args=args)
        p.start()
        p.join(timeout)
        self.assertFalse(p.is_alive(), "子进程超时未退出: %s" % target.__name__)
        self.assertEqual(p.exitcode, 0, "子进程异常退出: %s" % p.exitcode)

    def test_cas_compare_and_swap_rejects_stale_writer(self):
        key = "cas-basic.json"
        base = {"n": 0}
        first = self.ctx.api.call("store.cas", {
            "module": "agent/nodes", "path": key, "expected": None,
            "value": base}, caller=None)
        self.assertTrue(first["ok"], first)
        stale = self.ctx.api.call("store.cas", {
            "module": "agent/nodes", "path": key, "expected": None,
            "value": {"n": 1}}, caller=None)
        self.assertFalse(stale["ok"])
        self.assertTrue(stale["conflict"])
        self.assertEqual(stale["current"], {"n": 0})
        ok = self.ctx.api.call("store.cas", {
            "module": "agent/nodes", "path": key, "expected": base,
            "value": {"n": 1}}, caller=None)
        self.assertTrue(ok["ok"], ok)

    def test_cas_multiprocess_no_lost_updates(self):
        key = "cas-counter.json"
        self.ctx.api.call("store.cas", {
            "module": "agent/nodes", "path": key, "expected": None,
            "value": {"n": 0}}, caller=None)
        q = MP.Queue()
        workers = 4
        per_worker = 20
        procs = [MP.Process(target=_cas_add, args=(str(self.root), key, per_worker, q))
                 for _ in range(workers)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
            self.assertFalse(p.is_alive())
            self.assertEqual(p.exitcode, 0)
        results = [q.get(timeout=5) for _ in range(workers)]
        self.assertEqual(results, ["ok"] * workers)
        row = self.ctx.api.call("store.read", {
            "module": "agent/nodes", "path": key}, caller=None)
        self.assertEqual(row["value"]["n"], workers * per_worker)

    def test_node_registry_concurrent_register_keeps_all_nodes(self):
        barrier = MP.Barrier(6)
        q = MP.Queue()
        procs = [MP.Process(target=_register,
                            args=(str(self.root), "race-node-%d" % i,
                                  barrier, q)) for i in range(6)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
            self.assertFalse(p.is_alive())
            self.assertEqual(p.exitcode, 0)
        results = [q.get(timeout=5) for _ in range(6)]
        self.assertEqual(results, ["ok"] * 6)
        view = self.ctx.api.call("nodes.nodes_view", {}, caller=None)
        ids = {row["id"] for row in view["nodes"]}
        for i in range(6):
            self.assertIn("race-node-%d" % i, ids)

    def test_same_project_lease_has_single_holder_under_race(self):
        for nid in ("lease-node-a", "lease-node-b"):
            res = self.ctx.api.call("nodes.register", {
                "id": nid, "endpoint": "unix://" + nid,
                "capacity": {"cpu": 2}}, caller=None)
            self.assertTrue(res["ok"], res)
        barrier = MP.Barrier(2)
        q = MP.Queue()
        procs = [
            MP.Process(target=_acquire, args=(str(self.root), "lease-node-a",
                                              "race-project", barrier, q)),
            MP.Process(target=_acquire, args=(str(self.root), "lease-node-b",
                                              "race-project", barrier, q)),
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
            self.assertFalse(p.is_alive())
            self.assertEqual(p.exitcode, 0)
        rows = [q.get(timeout=5) for _ in range(2)]
        winners = [r for r in rows if r[1]]
        losers = [r for r in rows if not r[1]]
        self.assertEqual(len(winners), 1, rows)
        self.assertEqual(len(losers), 1, rows)
        self.assertEqual(losers[0][2], "lease_held")

    def test_migration_ledger_survives_process_reload(self):
        for nid in ("mig-node-a", "mig-node-b"):
            self.ctx.api.call("nodes.register", {
                "id": nid, "endpoint": "unix://" + nid,
                "capacity": {"cpu": 2}}, caller=None)
        acquired = self.ctx.api.call("nodes.acquire", {
            "project": "mig-project", "node": "mig-node-a", "ttl": 30}, caller=None)
        self.assertTrue(acquired["ok"], acquired)
        released = self.ctx.api.call("nodes.release", {
            "project": "mig-project", "token": acquired["lease"]["token"]}, caller=None)
        self.assertTrue(released["ok"], released)
        moved = self.ctx.api.call("nodes.reassign", {
            "project": "mig-project", "candidate": "mig-node-b",
            "reason": "ops_move"}, caller=None)
        self.assertTrue(moved["ok"], moved)
        reloaded = _child_ctx(self.root)
        rows = reloaded.api.call("nodes.migrations", {}, caller=None)["migrations"]
        row = next(r for r in rows if r["project"] == "mig-project")
        self.assertEqual(row["to_node"], "mig-node-b")
        self.assertEqual(row["state"], "done")

    def test_read_only_assignment_view_never_leaks_fencing_token(self):
        for nid in ("mask-node",):
            self.ctx.api.call("nodes.register", {
                "id": nid, "endpoint": "unix://" + nid,
                "capacity": {"cpu": 1}}, caller=None)
        acquired = self.ctx.api.call("nodes.acquire", {
            "project": "mask-project", "node": "mask-node", "ttl": 30}, caller=None)
        self.assertTrue(acquired["ok"], acquired)
        status = self.ctx.api.call("nodes.status", {}, caller=None)
        row = next(a for a in status["assignments"] if a["project"] == "mask-project")
        self.assertNotIn("token", row)
        project = self.ctx.api.call("nodes.project_node", {
            "project": "mask-project"}, caller=None)["assignment"]
        self.assertNotIn("token", project)
        self.assertTrue(acquired["lease"]["token"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
