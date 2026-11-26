"""archive 边角：压缩索引容错/查询过滤、源文件锁失败收尾、时延分位与缓存淘汰。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.archive.private import _cache, _index, _lock, _metrics


class FakeMd:
    def __init__(self, files=None, payload=None):
        self.files = dict(files or {})
        self.written = {}
        self.payload = payload
        self.ctx = mock.Mock()
        self.ctx.codec.json_decode.side_effect = lambda raw: (
            self.payload if self.payload is not None else
            {"ok": True, "value": __import__("json").loads(raw)})

    def exists(self, name):
        return name in self.files

    def read_text(self, name):
        return self.files[name]

    def json_write(self, name, body):
        self.written[name] = body


class IndexTest(unittest.TestCase):
    def rec(self, original, **kw):
        base = {"original": original, "created": "2026-01-01", "category": "logs",
                "orig_size": 100, "comp_size": 40, "status": "archived"}
        base.update(kw)
        return base

    def test_load_missing_and_bad_shapes(self):
        self.assertEqual(_index.load(FakeMd()), {"version": 1, "records": {}})
        bad = FakeMd({"index.json": "{}"}, payload={"ok": False, "error": "bad"})
        with self.assertRaises(ValueError):
            _index.load(bad)
        self.assertEqual(_index.load(FakeMd({"index.json": "{}"}, payload={"ok": True, "value": None})),
                         {"version": 1, "records": {}})
        self.assertEqual(_index.load(FakeMd({"index.json": "{}"},
                                           payload={"ok": True, "value": {"records": []}})),
                         {"version": 1, "records": {}})

    def test_load_keeps_version(self):
        md = FakeMd({"index.json": "{}"}, payload={"ok": True, "value": {"version": 7, "records": {"a": {}}}})
        self.assertEqual(_index.load(md), {"version": 7, "records": {"a": {}}})

    def test_save_defaults(self):
        md = FakeMd()
        _index.save(md, {})
        self.assertEqual(md.written["index.json"], {"version": 1, "records": {}})

    def test_upsert_get_all_and_remove(self):
        md = FakeMd()
        got = _index.upsert(md, self.rec("/a"))
        self.assertEqual(list(got["records"]), ["/a"])
        self.assertEqual(md.written["index.json"]["records"]["/a"]["original"], "/a")
        idx = {"records": {"/a": self.rec("/a")}}
        self.assertEqual(_index.get(idx, "/a")["orig_size"], 100)
        self.assertIsNone(_index.get(idx, "/z"))
        self.assertIsNone(_index.get({}, "/a"))
        self.assertEqual([r["original"] for r in _index.all_records(idx)], ["/a"])
        self.assertEqual(_index.all_records({}), [])
        md3 = FakeMd({"index.json": "{}"}, payload={"ok": True, "value": {"records": {"/a": self.rec("/a")}}})
        out = _index.remove(md3, "/a")
        self.assertEqual(out["records"], {})
        self.assertEqual(md3.written["index.json"]["records"], {})
        md2 = FakeMd()
        self.assertEqual(_index.remove(md2, "/nope")["records"], {})  # 无此条不写盘
        self.assertEqual(md2.written, {})

    def test_query_filters_sort_and_limit(self):
        now = 1000.0
        day = _index._policy.SECONDS_PER_DAY
        idx = {"records": {
            "/old": self.rec("/old", category="db", created="2025-01-01", created_ts=now - 3 * day),
            "/new": self.rec("/new", category="logs", created="2026-06-01", created_ts=now - 1),
            "/fresh": self.rec("/fresh", category="logs", created="2026-07-01", created_ts=0),
        }}
        self.assertEqual([r["original"] for r in _index.query(idx, category="logs")], ["/fresh", "/new"])
        self.assertEqual([r["original"] for r in _index.query(idx, category="db")], ["/old"])
        self.assertEqual([r["original"] for r in _index.query(idx, older_than=2, now_ts=now,
                                                              category="logs")], ["/fresh"])
        self.assertEqual([r["original"] for r in _index.query(idx, older_than=2, now_ts=now,
                                                              category="db")], ["/old"])
        self.assertEqual([r["original"] for r in _index.query(idx, limit=1)], ["/fresh"])

    def test_stats_and_summary(self):
        idx = {"records": {"/a": self.rec("/a"), "/b": self.rec("/b", status="raw", orig_size=50, comp_size=0)}}
        st = _index.stats(idx)
        self.assertEqual((st["count"], st["saved_bytes"]), (2, 110))
        self.assertEqual(st["by_category"]["logs"]["count"], 2)
        self.assertEqual(_index.stats({})["compression_ratio"], 0.0)
        summ = _index.archived_summary(idx)
        self.assertEqual((summ["count"], summ["saved_bytes"]), (1, 60))
        self.assertEqual(summ["by_category"]["logs"]["compression_ratio"], 0.4)
        self.assertEqual(_index.archived_summary({})["saved_ratio"], 0.0)


class SourceLockTest(unittest.TestCase):
    def test_lock_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "a.md")
            Path(target).write_text("x")
            with _lock.source_lock(target):
                self.assertTrue(Path(target).is_file())
            plain = _lock.source_lock(target)
            plain.__enter__()
            plain.__enter__() if False else None  # 只进一次，避免同线程重复取锁
            plain.__exit__(None, None, None)

    def test_enter_failure_releases_inproc_lock(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "a.md")
            with mock.patch.object(_lock.plat_lock, "ExclusiveLock",
                                   mock.Mock(side_effect=OSError("no lock"))):
                with self.assertRaises(OSError):
                    _lock.source_lock(target).__enter__()
            with _lock.source_lock(target):
                pass  # 进程内锁已释放，还能再次获取

    def test_exit_without_oslock_and_with_fd(self):
        inst = _lock.source_lock("x")
        inst._in = mock.Mock()
        fd = os.open(os.devnull, os.O_RDWR)
        inst._fd = fd
        self.assertFalse(inst.__exit__(None, None, None))
        self.assertIsNone(inst._fd)
        inst._in.release.assert_called_once_with()
        inst2 = _lock.source_lock("y")
        inst2._in = mock.Mock()
        self.assertFalse(inst2.__exit__(None, None, None))

    def test_capability_both_platforms(self):
        posix = _lock.lock_capability()
        self.assertEqual(posix["cross_process"]["mechanism"], "fcntl.flock 排他锁")
        self.assertFalse(posix["cross_process"]["verified"])
        with mock.patch.object(_lock.plat_lock, "PLATFORM", "nt"):
            nt = _lock.lock_capability()
        self.assertIn("msvcrt", nt["cross_process"]["mechanism"])
        self.assertIn("Windows", nt["cross_process"]["note"])


class MetricsTest(unittest.TestCase):
    def test_percentile_empty(self):
        self.assertEqual(_metrics._percentile([], 50), 0.0)

    def test_record_ignores_invalid(self):
        rec = _metrics.LatencyRecorder()
        rec.record(None)
        rec.record(-1)
        self.assertEqual(rec.snapshot(1)["status"], "insufficient_samples")
        rec.record(0.01)
        self.assertEqual(rec.snapshot(1)["p50_ms"], 10.0)

    def test_configure_shrinks(self):
        rec = _metrics.LatencyRecorder(max_samples=4)
        for i in range(4):
            rec.record(0.001 * (i + 1))
        rec.configure()
        rec.configure(max_samples=2)
        snap = rec.snapshot(2)
        self.assertEqual(snap["samples"], 2)
        self.assertEqual(snap["p95_ms"], 4.0)
        self.assertEqual(_metrics._percentile([1, 2, 3], 95), 3)


class CacheTest(unittest.TestCase):
    def test_hit_miss_and_mtime_invalidation(self):
        c = _cache.LRUCache(max_bytes=10, max_entries=2)
        self.assertIsNone(c.get(("m", "a")))
        c.put(("m", "a"), b"abc", mtime=1)
        self.assertEqual(c.get(("m", "a"), mtime=1), b"abc")
        self.assertIsNone(c.get(("m", "a"), mtime=2))
        stats = c.stats() if hasattr(c, "stats") else None
        self.assertTrue(stats is None or stats["evictions"] >= 1)

    def test_put_replaces_and_evicts(self):
        c = _cache.LRUCache(max_bytes=10, max_entries=2)
        c.put(("m", "a"), b"12345")
        c.put(("m", "a"), b"1234")
        c.put(("m", "b"), b"12345")
        self.assertEqual(c.get(("m", "a")), b"1234")  # a(4)+b(5)=9，未超容量
        c.put(("m", "c"), b"12345")  # 14 > 10 → 淘汰最久未用的 b（a 刚被读过）
        self.assertIsNone(c.get(("m", "b")))
        self.assertEqual(c.get(("m", "c")), b"12345")
        self.assertEqual(c.stats()["evictions"], 1)
        self.assertEqual(c.capacity(), {"max_entries": 2, "max_bytes": 10})
        c.configure(max_bytes=6)
        self.assertEqual(c.stats()["bytes"], 5)  # 只剩 c（5 字节）


if __name__ == "__main__":
    unittest.main()
