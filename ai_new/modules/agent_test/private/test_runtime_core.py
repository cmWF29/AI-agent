"""运行设施：defer 队列持久化、打断位、草稿槽订阅、effect 照单执行、后台接管。"""
from __future__ import annotations

import asyncio
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.runtime.private import _core as r  # noqa: E402


class Future:
    def __init__(self, done=False, result=None, error=None):
        self._done = done
        self._result = result
        self._error = error
        self.cancelled = False

    def done(self):
        return self._done

    def cancel(self):
        self.cancelled = True

    def result(self, timeout=None):
        if self._error:
            raise self._error
        return self._result


class Api:
    def __init__(self):
        self.calls = []
        self.fail = set()

    def call(self, name, payload=None, caller=None):
        self.calls.append(name)
        if name in self.fail:
            raise ValueError("x")
        if name == "store.read":
            return {"value": {"items": [{"hook": "a"}]}}
        if name == "clock.now":
            return {"ts": 1}
        return {"ok": True}


class Engine:
    def run_callable(self, demand, data):
        return {"result": {"x": 1}}

    async def arun_callable(self, demand, data):
        return {"result": {"x": 2}}


class Ctx:
    def __init__(self):
        self.cfg = {"runtime": {"session_workers": "bad"}}
        self.api = Api()
        self.demand_engine = Engine()


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.ctx = Ctx()
        with mock.patch.object(r.Runtime, "_restore_hooks"):
            self.rt = r.Runtime(self.ctx)

    def test_restore_and_cfg(self):
        self.rt._restore_hooks()
        self.assertEqual(self.rt._hook_queue, [{"hook": "a"}])
        self.ctx.api.fail.add("store.read")
        self.rt._restore_hooks()
        self.assertEqual(self.rt._hook_queue, [])
        self.assertEqual(self.rt._cfg_int("runtime.hook_batch", 3), 3)
        self.assertEqual(self.rt._queue_path(), "hook-queue.yaml")
        self.ctx.cfg["logs"] = {"paths": {"hook_queue": "q"}}
        self.assertEqual(self.rt._queue_path(), "q")

    def test_hook_queue(self):
        self.rt.enqueue_hook("a", {"level": "warn", "data": {"x": 1}})
        self.assertEqual(self.rt.pending_hooks(), 1)
        self.ctx.api.fail.add("store.write")
        self.rt.enqueue_hook("b", None)
        self.assertEqual(self.rt.pending_hooks(), 2)
        for i in range(r.HOOK_QUEUE_LIMIT + 5):
            self.rt.enqueue_hook("x", {})
        self.assertEqual(self.rt.pending_hooks(), r.HOOK_QUEUE_LIMIT)
        self.assertEqual(len(self.rt.claim_hooks(1)), 1)
        self.assertEqual(len(self.rt.claim_hooks()), 10)
        self.rt.clear_hooks()
        self.assertEqual(self.rt.pending_hooks(), 0)

    def test_stop_and_cancel(self):
        self.assertEqual(self.rt.stop("")["code"], "no_key")
        fut = Future(done=False)
        self.rt._runs["k"] = fut
        self.rt._cancel["k"] = 1
        self.assertTrue(self.rt.cancelled("k", 0))
        self.assertTrue(self.rt.active_keys())
        out = self.rt.stop("k")
        self.assertTrue(out["ok"])
        self.assertTrue(fut.cancelled)
        fut = Future(done=True, error=ValueError("x"))
        self.rt._runs["k2"] = fut
        self.rt.stop("k2")
        self.assertNotIn("k2", self.rt._runs)
        self.assertNotIn("k2", self.rt._cancel)
        self.assertEqual(self.rt.active_keys(), set())
        self.rt.ctx.cfg["runtime"]["future_timeout"] = 1
        self.rt._await_future(Future(done=True, error=ValueError("x")))

    def test_stream(self):
        self.rt.stream_put("", "x")
        self.rt.stream_put("k", None)
        ev = self.rt.stream_subscribe("k")
        self.rt.stream_put("k", "a")
        self.rt.stream_put("k", "b")
        self.assertEqual(self.rt.stream_get("k"), {"text": "ab", "running": True, "at": 1})
        self.assertEqual(self.rt.stream_get("")["text"], "")
        self.assertEqual(self.rt.stream_get("none")["text"], "")
        self.assertTrue(ev.is_set())
        self.assertEqual(self.rt.stream_events("k", cursor=None, timeout=0)["cursor"], 1)
        self.assertEqual(self.rt.stream_events("k", cursor=1, timeout=0)["items"], [])
        self.assertEqual(self.rt.stream_events("none", timeout=0)["items"][0]["text"], "")
        self.rt.stream_clear("")
        self.rt.stream_clear("k")
        self.assertFalse(self.rt.stream_get("k")["running"])
        self.assertIsNone(self.rt.stream_subscribe(""))
        self.rt.stream_unsubscribe("", ev)
        self.rt.stream_unsubscribe("k", None)
        self.rt.stream_unsubscribe("k", ev)
        ev2 = self.rt.stream_subscribe("k")
        self.rt.stream_unsubscribe("k", threading.Event())
        self.rt.stream_unsubscribe("k", ev2)
        self.assertEqual(self.rt._subs.get("k"), [])
        self.rt.ctx.cfg["runtime"]["stream_timeout"] = 0
        self.assertEqual(self.rt.stream_events("k")["blocked"], True)

    def test_apply(self):
        self.assertEqual(self.rt.apply({})["skipped"], True)
        self.rt.ctx.api.call = lambda *a, **k: {"ok": True}
        self.assertEqual(self.rt.apply({"effect": [{"kind": "write"}]})["count"], 1)
        self.assertEqual(self.rt.apply({"effect": {"kind": "write"}})["count"], 1)
        echo = {"x": 1}
        self.assertIs(self.rt.apply({"effect": [], "echo": echo}), echo)
        self.assertEqual(echo["applied"], [])

    def test_one(self):
        self.assertEqual(self.rt._one({"kind": "demand", "id": "d"})["ok"], True)
        with mock.patch.object(self.rt, "dispatch", return_value={"ok": True}) as d:
            self.rt._one({"kind": "dispatch", "id": "d"})
            d.assert_called_once()
        self.assertEqual(self.rt._one({"kind": "nope"})["code"], "unknown_effect")
        self.ctx.api.fail.add("store.write")
        self.assertEqual(self.rt._one({"kind": "write"})["code"], "apply_error")

    def test_call(self):
        self.assertEqual(self.rt._run_demand("d", {}), {"ok": True})
        self.assertEqual(self.rt.call("d"), {"x": 1})
        self.assertEqual(asyncio.run(self.rt.acall("d")), {"x": 2})

    def test_dispatch(self):
        self.assertEqual(self.rt.dispatch({})["code"], "no_demand")
        with mock.patch.object(self.rt._session_pool, "submit", return_value=Future()) as sub:
            out = self.rt.dispatch({"demand": "d"})
            self.assertTrue(out["ok"])
            sub.assert_called_once()
        fut = Future(done=False)
        self.rt._runs["k"] = fut
        with mock.patch.object(self.rt._session_pool, "submit", return_value=Future()):
            self.assertTrue(self.rt.dispatch({"demand": "d", "key": "k"})["interrupted"])

    def test_work(self):
        prev = Future(done=False, error=ValueError("x"))
        slot = {"t": "self"}
        self.rt._runs["k"] = "self"
        with mock.patch.object(self.rt, "_run_demand") as rd:
            self.rt._work("k", slot, prev, "d", {})
            rd.assert_called_once()
        slot2 = {"t": "other"}
        self.rt._runs["k"] = "self"
        with mock.patch.object(self.rt, "_run_demand") as rd:
            self.rt._work("k", slot2, None, "d", {})
            rd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
