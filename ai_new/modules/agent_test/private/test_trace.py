"""trace 链路：开关/采样、span 开关、按天读回、列表与慢调用聚合。"""
from __future__ import annotations

import json
import queue
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.trace.private import _trace as t  # noqa: E402


class Storage:
    def __init__(self):
        self.files = {}
        self.dirs = set()
        self.fail_read = False

    def dir(self, rel):
        self.dirs.add(rel)

    def append_text(self, rel, text):
        self.files[rel] = self.files.get(rel, "") + text

    def read_text(self, rel):
        if self.fail_read:
            raise OSError("read")
        return self.files.get(rel)

    def is_dir(self, rel):
        return rel in self.dirs

    def list_dir(self, rel):
        prefix = rel.rstrip("/") + "/"
        return sorted({p[len(prefix):].split("/")[0] for p in self.files if p.startswith(prefix)})


class Ctx:
    def __init__(self, cfg=None):
        self.cfg = cfg if cfg is not None else {"trace": {}}
        self.storage = Storage()
        self.storage.own = lambda _file: self.storage
        self.registered = []
        self.api = self

    def own(self, _file):
        return self.storage

    def register(self, name, fn, desc=None, module=None):
        self.registered.append((name, fn))


class TraceTest(unittest.TestCase):
    def setUp(self):
        t._S.update({"tag": "tag", "st": None, "enabled": True, "sample": 1.0,
                     "dropped": 0, "thread": None})
        t._PEND.clear()
        t._CUR.set(None)
        t._Q = queue.Queue(maxsize=50000)

    def test_setup_attach_open_close(self):
        ctx = Ctx()
        self.assertTrue(t.setup(ctx))
        self.assertEqual(len(ctx.registered), 7)
        t._S["enabled"] = False
        self.assertTrue(t._route_open(ctx, {})["off"])
        self.assertEqual(t._route_close(ctx, {})["off"], True)
        t._S["enabled"] = True
        out = t._route_open(ctx, {"trace": "T", "parent": "", "name": "x" * 200,
                                  "caller": "c", "attrs": {"a": 1}})
        self.assertEqual(out["parent"], "")
        self.assertEqual(len(t._PEND[out["span"]]["name"]), 120)
        t._route_attach(ctx, {})
        t._route_attach(ctx, {"trace": "T2"})
        self.assertEqual(t._trace_ctx()["trace"], "T2")
        closed = t._route_close(ctx, {"span": out["span"], "status": "err",
                                      "code": "C", "attrs": {"n": 1, "s": "x" * 300}})
        self.assertTrue(closed["written"])
        self.assertEqual(t._PEND, {})
        self.assertEqual(t._route_close(ctx, {"span": "none"})["missing"], True)
        s2 = t._route_open(ctx, {"trace": "T3"})["span"]
        self.assertTrue(t._route_close(ctx, {"span": s2, "attrs": {}})["written"])
        t._S["sample"] = 0
        s3 = t._route_open(ctx, {"trace": "T4"})["span"]
        self.assertTrue(t._route_close(ctx, {"span": s3})["written"])
        self.assertIsNone(t._trace_ctx().get("span") or None)

    def test_sampling_and_queue_overflow(self):
        ctx = Ctx()
        t.setup(ctx)
        t._S["sample"] = 0
        self.assertFalse(t._sampled({"span": "tag-1"}))
        t._S["sample"] = 1
        self.assertTrue(t._sampled({"span": "tag-1"}))
        t._Q = queue.Queue(maxsize=1)
        t._Q.put("x")
        self.assertFalse(t._fetch("y"))
        self.assertEqual(t._S["dropped"], 1)
        t._Q = queue.Queue(maxsize=50000)
        self.assertTrue(t._fetch("z"))
        for i in range(500):
            t._fetch(str(i))
        time.sleep(0.6)

    def test_read_day_filters_and_errors(self):
        self.assertEqual(t._read_day("20260101"), [])
        ctx = Ctx()
        t.setup(ctx)
        st = ctx.storage
        self.assertEqual(t._read_day("20260101"), [])
        st.dir("trace/20260101")
        st.files["trace/20260101/a.jsonl"] = '{"trace": "T"}\n\n{bad}\n'
        st.files["trace/20260101/b.txt"] = "x"
        st.files["trace/20260101/c.jsonl"] = '{"trace": "U"}\n'
        self.assertEqual(t._read_day("20260101"), [{"trace": "T"}, {"trace": "U"}])
        st.fail_read = True
        self.assertEqual(t._read_day("20260101"), [])

    def test_get_list_slow_recent(self):
        ctx = Ctx()
        t.setup(ctx)
        st = ctx.storage
        st.dir("trace/20260101")
        rows = [
            {"trace": "T", "span": "s1", "parent": "", "name": "a", "start": 10,
             "dur_ms": 5, "status": "ok"},
            {"trace": "T", "span": "s2", "parent": "s1", "name": "a", "start": 12,
             "dur_ms": 8, "status": "err"},
            {"trace": "U", "span": "s3", "parent": "", "name": "b", "start": 20,
             "dur_ms": 1, "status": "ok"},
            {"trace": "", "span": "s4", "name": "", "start": 20},
        ]
        st.files["trace/20260101/x.jsonl"] = "\n".join(json.dumps(r) for r in rows)
        got = t._route_get(ctx, {"trace": "T", "date": "20260101"})
        self.assertEqual(got["count"], 2)
        self.assertEqual(got["total_ms"], 2008.0)
        fallback = t._route_get(ctx, {"trace": "T"})
        self.assertEqual(fallback["count"], 0)
        lst = t._route_list(ctx, {"date": "20260101"})
        self.assertEqual(lst["total"], 2)
        self.assertEqual(lst["items"][0]["trace"], "U")
        self.assertEqual(t._route_list(ctx, {"date": "20260101", "limit": 1})["total"], 2)
        slow = t._route_slow(ctx, {"date": "20260101"})
        self.assertEqual(slow["spans"], 4)
        self.assertEqual(slow["items"][0]["name"], "a")
        self.assertEqual(slow["items"][0]["n"], 2)
        self.assertEqual(slow["items"][0]["err"], 1)
        self.assertEqual(len(slow["items"][0]["samples"]), 2)
        self.assertEqual(t._route_slow(ctx, {"date": "20260101"})["updated_at"] > 0, True)
        recent = t._route_recent(ctx, {"date": "20260101", "prefix": "a", "limit": 1})
        self.assertEqual(recent["total"], 2)
        self.assertEqual(len(recent["items"]), 1)
        self.assertEqual(t._route_recent(ctx, {"date": "20260101"})["total"], 4)

    def test_flush_and_sampling_fallbacks(self):
        ctx = Ctx()
        t.setup(ctx)
        self.assertIn("-", t._new_id())
        time.sleep(0.6)
        st = t._S["st"]
        t._S["st"] = None
        t._Q.put("line")
        time.sleep(0.6)
        class BadStorage(Storage):
            def append_text(self, rel, text):
                raise OSError("write")
        t._S["st"] = BadStorage()
        t._Q.put("line")
        time.sleep(0.6)
        t._S["st"] = st
        t._S["sample"] = 0.5
        self.assertTrue(t._sampled({"span": "bad"}))

    def test_setup_config_fallbacks(self):
        class BadCfg(dict):
            def get(self, key, default=None):
                raise RuntimeError("cfg")

        ctx = Ctx(BadCfg())
        self.assertTrue(t.setup(ctx))
        self.assertTrue(t._S["enabled"])
        t._S["st"] = None
        ctx2 = Ctx({"trace": {"enabled": False, "sample": "bad"}})
        self.assertTrue(t.setup(ctx2))
        self.assertFalse(t._S["enabled"])
        self.assertEqual(t._S["sample"], 1.0)


if __name__ == "__main__":
    unittest.main()
