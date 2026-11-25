"""archive 压缩引擎闭环：扫描、压缩、透明读、观测与索引查询，全部落在临时数据根。"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.archive.private import _backend, _engine, _index  # noqa: E402


class Ctx:
    def __init__(self, root, cfg=None):
        self.root = Path(root)
        self.ctx = self
        self.cfg = {"archive": cfg or {}}
        self.api = self
        self.storage = self
        self._index_dir = self.root / "archive-index"
        self._index_dir.mkdir(parents=True, exist_ok=True)
        self.own_path = self._index_dir
        self.codec = self
        self.fail_digest = False

    def call(self, name, payload=None, caller=None):
        payload = payload or {}
        if name == "clock.now":
            return {"ts": 1000, "iso": "T"}
        if name == "codec.digest":
            if self.fail_digest:
                return {"ok": False, "error": "bad"}
            return {"ok": True, "hex": hashlib.sha256(payload["text"]).hexdigest()}
        raise AssertionError(name)

    def own(self, _file):
        return self

    def exists(self, name):
        return (self.own_path / name).exists()

    def read_text(self, name):
        p = self.own_path / name
        return p.read_text() if p.exists() else None

    def json_write(self, name, value):
        (self.own_path / name).write_text(json.dumps(value))

    def yaml_read(self, name, default=None):
        p = self.own_path / name
        return json.loads(p.read_text()) if p.exists() else default

    def json_decode(self, raw):
        try:
            return {"ok": True, "value": json.loads(raw)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = os.environ.get("AI_NEW_DATA")
        os.environ["AI_NEW_DATA"] = str(self.root / "data")
        self.mod = self.root / "data" / "m"
        self.mod.mkdir(parents=True)
        self.ctx = Ctx(self.root, {"scan": [{"module": "m", "category": "c", "glob": "*.txt"}],
                                   "categories": {"c": {"age_days": 0, "min_bytes": 0, "grace_seconds": 0}},
                                   "cache_max_bytes": 8, "cache_max_entries": 2,
                                   "metrics_max_samples": 10})

    def tearDown(self):
        if self.old is None:
            os.environ.pop("AI_NEW_DATA", None)
        else:
            os.environ["AI_NEW_DATA"] = self.old
        self.tmp.cleanup()

    def _file(self, name="a.txt", text="hello", age=100):
        p = self.mod / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        os.utime(p, (1000 - age, 1000 - age))
        return p

    def test_scan_helpers_and_layers(self):
        p = self._file()
        self.assertEqual(_engine._layer("projects/x"), "project")
        self.assertEqual(_engine._layer("tickets/x"), "ticket")
        self.assertEqual(_engine._layer("x"), "public")
        self.assertTrue(_engine.policy_is_skipped("index.yaml"))
        self.assertEqual(_engine._modules_root(__file__).name, "modules")
        with self.assertRaises(ValueError):
            _engine._modules_root("/tmp/not-modules")
        old = os.environ.pop("AI_NEW_DATA")
        try:
            self.assertFalse(str(_engine._dir_of("")) .startswith(old or "\0"))
        finally:
            os.environ["AI_NEW_DATA"] = old
        out = _engine.scan(self.ctx, {})
        self.assertEqual(out["summary"], {"scanned": 1, "cold": 1, "cold_bytes": 5})
        self.assertEqual(out["candidates"][0]["layer"], "public")
        (self.mod / "index.yaml").write_text("x")
        self.ctx.cfg["archive"]["scan"] = [{"module": "m", "category": "c", "glob": "**/*"},
                                           {"module": "nope", "category": "c"}]
        self.assertEqual(_engine.scan(self.ctx, {})["summary"]["scanned"], 1)
        self.ctx.cfg["archive"]["scan"] = [{"module": "m", "category": "c", "glob": "*.txt"}]
        self.ctx.cfg["archive"]["min_file_bytes"] = 10
        self.assertFalse(_engine.scan(self.ctx, {})["candidates"][0]["cold"])
        self.ctx.cfg["archive"]["min_file_bytes"] = 0

    def test_compress_resolve_and_observe(self):
        p = self._file()
        out = _engine.compress(self.ctx, {})
        self.assertEqual(out["summary"]["compressed"], 1)
        self.assertTrue(Path(str(p) + ".gz").is_file())
        self.assertFalse(p.exists())
        raw = _engine.resolve_abs(self.ctx, {"abs": str(p)})
        self.assertEqual(raw["raw"], b"hello")
        self.assertFalse(raw["cached"])
        self.assertTrue(_engine.resolve_abs(self.ctx, {"abs": str(p)})["cached"])
        self.assertEqual(_engine.resolve_raw(self.ctx, "m", "a.txt")["raw"], b"hello")
        text = _engine.read_text(self.ctx, {"module": "m", "path": "a.txt"})
        self.assertEqual(text["value"], "hello")
        b = _engine.read_bytes(self.ctx, {"module": "m", "path": "a.txt"})
        self.assertEqual(b["size"], 5)
        lines = _engine.read_lines(self.ctx, {"module": "m", "path": "a.txt",
                                              "start": 0, "end": 1, "limit": 1})
        self.assertEqual(lines["lines"], ["hello"])
        missing = _engine.resolve_abs(self.ctx, {"abs": str(self.mod / "none")})
        self.assertFalse(missing["exists"])
        self.assertEqual(_engine.read_text(self.ctx, {"module": "m", "path": "none"}),
                         {"exists": False, "value": ""})
        self.assertEqual(_engine.read_bytes(self.ctx, {"module": "m", "path": "none"})["size"], 0)
        self.assertEqual(_engine.read_lines(self.ctx, {"module": "m", "path": "none"})["total"], 0)
        self.assertEqual(_engine.read_lines(self.ctx, {"module": "m", "path": "a.txt"})["lines"],
                         ["hello"])
        self.assertEqual(_engine.read_lines(self.ctx, {"module": "m", "path": "a.txt",
                                                       "start": 0})["total"], 1)
        stats = _engine.stats(self.ctx)
        self.assertEqual(stats["index"]["count"], 1)
        met = _engine.metrics(self.ctx)
        self.assertEqual(met["decompress"]["status"], "insufficient_samples")
        self.assertIn("decompress_status", met["labels"])
        q = _engine.index_query(self.ctx, {"category": "c", "limit": 1})
        self.assertEqual(q["rows"][0]["status"], "archived")
        self.assertEqual(q["rows"][0]["path"], str(p))

    def test_compress_idempotent_and_explicit_paths(self):
        p = self._file()
        self.assertEqual(_engine.compress(self.ctx, {"paths": [str(p)]})["items"][0]["status"],
                         "compressed")
        self.assertEqual(_engine.compress(self.ctx, {"paths": [str(p)]})["items"][0]["status"],
                         "skipped")
        self.assertEqual(_engine.compress(self.ctx, {"paths": ["/none"]})["items"][0]["status"],
                         "failed")

    def test_register_raw_and_index_failures(self):
        _engine._register_raw(self.ctx, {})
        _engine._register_raw(self.ctx, {"abs": "/x", "module": "m", "size_bytes": 0})
        md = self.ctx
        _index.upsert(md, {"original": "/x", "status": "archived", "category": "c"})
        _engine._register_raw(self.ctx, {"abs": "/x", "module": "m"})
        self.assertEqual(_index.get(_index.load(md), "/x")["status"], "archived")
        self.assertEqual(_engine.ctx_now(md), {"ts": 1000, "iso": "T"})
        self.assertEqual(_engine._messages(self.ctx), {})
        self.assertEqual(_engine._rel_of("/outside"), "")
        self.assertEqual(_engine._module_of("/outside"), "")
        root = _engine._modules_root(__file__)
        self.assertEqual(_engine._rel_of(str(root / "x")), "")
        self.assertEqual(_engine._module_of(str(root / "agent" / "logs")), "agent/logs")
        self.assertEqual(_engine._config(self.ctx), self.ctx.cfg["archive"])

    def test_corrupt_index_and_cleanup_temp(self):
        (self.ctx.own_path / "index.json").write_text("{bad")
        with self.assertRaises(ValueError):
            _index.load(self.ctx)
        tmp = self.mod / "a.txt.1.tmp"
        tmp.write_text("x")
        _engine._cleanup_temp(self.mod, "a.txt")
        self.assertFalse(tmp.exists())
        self.assertEqual(_engine._unlink_retry("/nonexistent"), None)
        real_name = os.name
        real_unlink = Path.unlink
        real_sleep = time.sleep
        state = {"n": 0}

        def flaky_unlink(self):
            state["n"] += 1
            if state["n"] == 1:
                raise PermissionError("locked")
            return None

        os.name = "nt"
        Path.unlink = flaky_unlink
        time.sleep = lambda _s: None
        try:
            self.assertIsNone(_engine._unlink_retry("/p", attempts=2))
            self.assertIsNone(_engine._unlink_retry("/p", attempts=0))
            state["n"] = 0
            with self.assertRaises(PermissionError):
                _engine._unlink_retry("/p", attempts=1)
        finally:
            os.name = real_name
            Path.unlink = real_unlink
            time.sleep = real_sleep

    def test_original_file_read_and_metrics_ok(self):
        p = self._file()
        self.assertEqual(_engine.resolve_abs(self.ctx, {"abs": str(p)})["raw"], b"hello")
        self.assertTrue(_engine.resolve_abs(self.ctx, {"abs": str(p)})["cached"])
        self.assertEqual(_engine.resolve_abs(self.ctx, {"abs": ""}),
                         {"exists": False, "raw": b"", "cached": False})
        for i in range(6):
            _engine._metrics_singleton(self.ctx.cfg["archive"]).record(i / 1000.0)
        self.assertEqual(_engine.metrics(self.ctx)["decompress"]["status"], "ok")

    def test_compress_oserror_retry_then_success(self):
        p = self._file()
        real = _backend.compress_bytes
        calls = {"n": 0}

        def flaky(data, level=6, algorithm="gzip"):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("busy")
            return real(data, level=level, algorithm=algorithm)

        _backend.compress_bytes = flaky
        try:
            out = _engine.compress(self.ctx, {"paths": [str(p)]})
        finally:
            _backend.compress_bytes = real
        self.assertEqual(out["items"][0]["status"], "compressed")

    def test_replace_and_checksum_mismatch(self):
        p = self._file()
        real_replace = os.replace

        def bad_replace(*a, **k):
            raise OSError("replace")

        os.replace = bad_replace
        try:
            self.assertEqual(_engine.compress(self.ctx, {"paths": [str(p)]})["items"][0]["status"],
                             "failed")
        finally:
            os.replace = real_replace
        self.assertEqual(list(self.mod.glob("*.tmp")), [])
        def consume_replace(src, dst):
            Path(src).unlink()
            raise OSError("replace after consume")

        os.replace = consume_replace
        try:
            self.assertEqual(_engine.compress(self.ctx, {"paths": [str(p)]})["items"][0]["status"],
                             "failed")
        finally:
            os.replace = real_replace
        real_mkstemp = tempfile.mkstemp

        def bad_mkstemp(*a, **k):
            raise OSError("temp")

        tempfile.mkstemp = bad_mkstemp
        try:
            self.assertEqual(_engine.compress(self.ctx, {"paths": [str(p)]})["items"][0]["status"],
                             "failed")
        finally:
            tempfile.mkstemp = real_mkstemp
        real_checksum = _engine._checksum
        seq = {"n": 0}

        def bad_checksum(ctx, raw):
            seq["n"] += 1
            return "good" if seq["n"] == 1 else "bad"

        _engine._checksum = bad_checksum
        try:
            self.assertEqual(_engine.compress(self.ctx, {"paths": [str(p)]})["items"][0]["status"],
                             "failed")
        finally:
            _engine._checksum = real_checksum

    def test_digest_failure_and_bad_stream(self):
        p = self._file()
        self.ctx.fail_digest = True
        self.assertEqual(_engine.compress(self.ctx, {"paths": [str(p)]})["items"][0]["status"],
                         "failed")
        self.ctx.fail_digest = False
        real = _backend.decompress_bytes
        _backend.decompress_bytes = lambda data, algorithm="gzip": b"other"
        try:
            self.assertEqual(_engine.compress(self.ctx, {"paths": [str(p)]})["items"][0]["status"],
                             "failed")
        finally:
            _backend.decompress_bytes = real

    def test_cleanup_unlink_oserror(self):
        p = self.mod / "a.txt.1.tmp"
        p.write_text("x")
        real = Path.unlink

        def fail(self):
            raise OSError("busy")

        Path.unlink = fail
        try:
            _engine._cleanup_temp(self.mod, "a.txt")
        finally:
            Path.unlink = real
        self.assertTrue(p.exists())

    def test_resolve_corrupt_cases(self):
        p = self._file()
        _engine.compress(self.ctx, {"paths": [str(p)]})
        rec = _index.get(_index.load(self.ctx), str(p))
        comp = Path(rec["compressed"])
        raw = comp.read_bytes()
        comp.unlink()
        with self.assertRaises(_engine.ArchiveCorrupt) as e:
            _engine.resolve_abs(self.ctx, {"abs": str(p)})
        self.assertEqual(e.exception.code, "archive_companion_missing")
        comp.write_bytes(raw)
        real = _backend.decompress_bytes

        def broken(data, algorithm="gzip"):
            raise ValueError("bad stream")

        _backend.decompress_bytes = broken
        try:
            with self.assertRaises(_engine.ArchiveCorrupt) as e2:
                _engine.resolve_abs(self.ctx, {"abs": str(p)})
        finally:
            _backend.decompress_bytes = real
        self.assertEqual(e2.exception.code, "archive_corrupt")
        # 索引丢失但压缩流仍在
        _index.remove(self.ctx, str(p))
        with self.assertRaises(_engine.ArchiveCorrupt) as e3:
            _engine.resolve_abs(self.ctx, {"abs": str(p)})
        self.assertEqual(e3.exception.code, "archive_index_missing")

    def test_resolve_checksum_mismatch_and_cached_compressed(self):
        p = self._file()
        _engine.compress(self.ctx, {"paths": [str(p)]})
        self.ctx.fail_digest = False
        self.assertFalse(_engine.resolve_abs(self.ctx, {"abs": str(p)})["cached"])
        self.assertTrue(_engine.resolve_abs(self.ctx, {"abs": str(p)})["cached"])
        md = self.ctx
        index = _index.load(md)
        index["records"][str(p)]["checksum"] = "bad"
        _index.save(md, index)
        # 清缓存：换一个新 ctx，复用同一索引与压缩流
        _engine._cache_instance = None
        fresh = Ctx(self.root)
        with self.assertRaises(_engine.ArchiveCorrupt):
            _engine.resolve_abs(fresh, {"abs": str(p)})


if __name__ == "__main__":
    unittest.main()
