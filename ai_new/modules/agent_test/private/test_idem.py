"""幂等台账原语：占位/租约/结算/回收 的行为契约。

直接打 store 的四个原语（不起装配），数据落在临时 AI_NEW_DATA 下，不碰源码树。
"""
from __future__ import annotations

import os
import tempfile
import threading
import unittest

from ai_new.modules.agent_common.store.private import _idem


class _Clock:
    ts = 1000.0

    def now(self):
        return {"ts": _Clock.ts, "iso": "2026-11-21T00:00:00"}


class _Ctx:
    clock = _Clock()


CTX = _Ctx()
MOD = "agent_test"


def _claim(key, lease=60, bucket="t"):
    return _idem._route_claim(CTX, {"module": MOD, "bucket": bucket, "key": key,
                                    "route": "probe.run", "scope": "s", "lease_seconds": lease})


def _settle(key, status, digest="", code="", bucket="t"):
    return _idem._route_settle(CTX, {"module": MOD, "bucket": bucket, "key": key,
                                     "status": status, "result_digest": digest,
                                     "error_code": code})


class IdemTest(unittest.TestCase):
    def setUp(self):
        _Clock.ts = 1000.0
        self.tmp = tempfile.mkdtemp(prefix="idem-")
        os.environ["AI_NEW_DATA"] = self.tmp

    def tearDown(self):
        os.environ.pop("AI_NEW_DATA", None)

    def test_first_claim_wins_and_second_sees_in_flight(self):
        first = _claim("k1")
        self.assertTrue(first["claimed"])
        self.assertEqual(first["attempt"], 1)
        second = _claim("k1")
        self.assertFalse(second["claimed"])
        self.assertTrue(second["in_flight"])

    def test_done_is_reused_not_reexecuted(self):
        _claim("k2")
        _settle("k2", "done", digest="ticket:T-1")
        again = _claim("k2")
        self.assertFalse(again["claimed"])
        self.assertEqual(again["status"], "done")
        self.assertTrue(again["reused"])
        self.assertEqual(again["result_digest"], "ticket:T-1")

    def test_failed_allows_takeover_with_attempt_bump(self):
        _claim("k3")
        _settle("k3", "failed", code="timeout")
        again = _claim("k3")
        self.assertTrue(again["claimed"])
        self.assertEqual(again["attempt"], 2)
        self.assertTrue(again["takeover"])

    def test_abandoned_is_not_taken_over(self):
        _claim("k4")
        _settle("k4", "abandoned", code="lease_expired")
        again = _claim("k4")
        self.assertFalse(again["claimed"])
        self.assertEqual(again["status"], "abandoned")

    def test_lease_expiry_allows_takeover(self):
        _claim("k5", lease=10)
        _Clock.ts = 1005.0
        live = _claim("k5")  # 租约未过：不给执行权，等着
        self.assertFalse(live["claimed"])
        self.assertTrue(live["in_flight"])
        _Clock.ts = 1020.0
        again = _claim("k5")
        self.assertTrue(again["claimed"])
        self.assertEqual(again["attempt"], 2)

    def test_renew_extends_lease(self):
        _claim("k6", lease=10)
        _Clock.ts = 1005.0
        self.assertTrue(_idem._route_renew(CTX, {"module": MOD, "bucket": "t",
                                                 "key": "k6", "lease_seconds": 10})["renewed"])
        _Clock.ts = 1012.0
        self.assertFalse(_claim("k6")["claimed"])  # 续租生效，1020 才过期
        _Clock.ts = 1022.0
        self.assertTrue(_claim("k6")["claimed"])

    def test_sweep_lists_and_marks_expired(self):
        _claim("k7", lease=5)
        _settle("k7", "done")
        _claim("k8", lease=5)
        _Clock.ts = 1030.0
        out = _idem._route_sweep(CTX, {"module": MOD, "bucket": "t", "mark": True})
        self.assertEqual(out["expired"], ["k8"])
        self.assertEqual(out["marked"], 1)
        later = _claim("k8")
        self.assertEqual(later["status"], "abandoned")

    def test_unsafe_key_chars_do_not_escape_bucket(self):
        out = _claim("../../etc/passwd")
        self.assertTrue(out["claimed"])
        files = []
        for root, _dirs, names in os.walk(self.tmp):
            files.extend(os.path.join(root, n) for n in names)
        self.assertTrue(files)
        self.assertFalse(any("etc" in p and "passwd" in p and "idem" not in p for p in files))

    def test_concurrent_claims_allow_exactly_one(self):
        results = []
        lock = threading.Lock()

        def worker():
            r = _claim("k9")
            with lock:
                results.append(r["claimed"])

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(True), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class _DispatchApi:
    """假注册表：只管三条平台原语（摘要/占位/结算），其余路由计数。"""

    def __init__(self):
        self.n = 0

    def call(self, route, payload, caller=None, **_):
        if route == "codec.digest":
            from ai_new.modules.agent_common.codec.private import _codec
            return _codec.digest(payload.get("text"))
        if route == "store.claim":
            return _idem._route_claim(CTX, payload)
        if route == "store.settle":
            return _idem._route_settle(CTX, payload)
        self.n += 1
        return {"ok": True}


class DispatchIdemTest(unittest.TestCase):
    """一条事件 + 一条需求 = 一个键：重放不再执行第二次。"""

    def setUp(self):
        _Clock.ts = 1000.0
        self.tmp = tempfile.mkdtemp(prefix="idem-dispatch-")
        os.environ["AI_NEW_DATA"] = self.tmp
        from ai_new.modules.agent_common.demand_engine.private import _engine
        self.api = _DispatchApi()
        ctx = type("Ctx", (), {"api": self.api})()
        self.engine = _engine.Engine(ctx)
        self.engine._cache = [{"id": "probe-demand", "on": ["probe.hook"], "enabled": True,
                               "do": [{"call": "ops.record"}]}]

    def tearDown(self):
        os.environ.pop("AI_NEW_DATA", None)

    def test_same_event_runs_once(self):
        ev = {"id": "T-1", "kind": "done"}
        self.engine.dispatch("probe.hook", ev)
        self.assertEqual(self.api.n, 1)
        again = self.engine.dispatch("probe.hook", ev)
        self.assertEqual(self.api.n, 1, "同一事件被重放时不该再执行")
        self.assertEqual(again[0].get("skipped"), "done")
        self.assertFalse(again[0].get("reused") is False)

    def test_different_event_runs_again(self):
        self.engine.dispatch("probe.hook", {"id": "T-1"})
        self.engine.dispatch("probe.hook", {"id": "T-2"})
        self.assertEqual(self.api.n, 2)
