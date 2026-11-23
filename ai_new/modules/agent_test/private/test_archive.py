"""存储治理（archive）靶向测试：压缩/解压一致性、幂等、损坏校验、LRU、透明兼容。

不跑全量门禁；只覆盖本模块新增行为。桩 ctx 只接 clock / codec / storage 三个面。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.archive.private import _backend, _cache, _engine, _policy  # noqa: E402
from ai_new.modules.agent_common.store.private._panel import ModuleData, module_data  # noqa: E402


class _Codec:
    def json_encode(self, obj):
        return {"ok": True, "text": json.dumps(obj, ensure_ascii=False)}

    def json_decode(self, text):
        try:
            return {"ok": True, "value": json.loads(text or "{}")}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def yaml_decode(self, text):
        return self.json_decode(text)


class _Api:
    def call(self, route, payload=None, caller=None, direct=False):
        if route == "clock.now":
            return {"ts": time.time(), "iso": "2026-11-23T00:00:00+08:00"}
        if route == "codec.digest":
            raw = bytes(payload.get("text") or b"")
            return {"ok": True, "hex": hashlib.sha256(raw).hexdigest()}
        raise KeyError(route)


class _Storage:
    def __init__(self, ctx):
        self._ctx = ctx

    def own(self, anchor):
        return ModuleData(module_data(anchor), self._ctx)


def _ctx(cfg):
    ctx = type("Ctx", (), {})()
    ctx.cfg = {"archive": cfg}
    ctx.api = _Api()
    ctx.codec = _Codec()
    ctx.storage = _Storage(ctx)
    return ctx


def _default_cfg(**over):
    cfg = {
        "algorithm": "gzip",
        "compress_level": 6,
        "min_file_bytes": 0,
        "grace_seconds": 0,
        "cache_max_bytes": 1_000_000,
        "cache_max_entries": 16,
        "max_attempts": 2,
    }
    cfg.update(over)
    return cfg


class PolicyTest(unittest.TestCase):
    def _ev(self, size, age, threshold):
        return _policy.evaluate({"size_bytes": size, "age_seconds": age, "category": "x"},
                                threshold)

    def test_cold_when_age_and_size_meet(self):
        out = self._ev(5000, 10 * 86400, {"age_days": 7, "min_bytes": 2048})
        self.assertTrue(out["cold"])
        self.assertEqual(out["reason"], "cold")

    def test_hot_within_grace_window(self):
        out = self._ev(5000, 600, {"age_days": 7, "min_bytes": 2048, "grace_seconds": 3600})
        self.assertFalse(out["cold"])
        self.assertEqual(out["reason"], "grace")

    def test_below_age_threshold(self):
        out = self._ev(5000, 2 * 86400, {"age_days": 7, "min_bytes": 2048})
        self.assertFalse(out["cold"])
        self.assertEqual(out["reason"], "age_below")

    def test_below_size_threshold(self):
        out = self._ev(100, 10 * 86400, {"age_days": 7, "min_bytes": 2048})
        self.assertFalse(out["cold"])
        self.assertEqual(out["reason"], "size_below")


class BackendTest(unittest.TestCase):
    def test_gzip_roundtrip_text(self):
        raw = "链路追踪 · 日志行\n" * 100
        comp = _backend.compress_bytes(raw.encode("utf-8"), 6, "gzip")
        self.assertEqual(comp["algorithm"], "gzip")
        back = _backend.decompress_bytes(comp["data"], "gzip")
        self.assertEqual(back.decode("utf-8"), raw)

    def test_gzip_roundtrip_binary(self):
        raw = bytes(range(256)) * 4 + b"\x00\x01\x02\xff"
        comp = _backend.compress_bytes(raw, 6, "gzip")
        back = _backend.decompress_bytes(comp["data"], "gzip")
        self.assertEqual(back, raw)

    def test_zstd_unavailable_falls_back_report(self):
        info = _backend.backend_info()
        if not info["zstd"]["installed"]:
            with self.assertRaises(ValueError):
                _backend.compress_bytes(b"x", 6, "zstd")


class CacheTest(unittest.TestCase):
    def test_hit_miss_and_entries_cap(self):
        cache = _cache.LRUCache(max_bytes=10_000, max_entries=3)
        self.assertIsNone(cache.get("a"))
        cache.put("a", b"1")
        cache.put("b", b"2")
        self.assertEqual(cache.get("a"), b"1")
        cache.put("c", b"3")
        cache.put("d", b"4")  # 挤出最久未访问的 b
        stats = cache.stats()
        self.assertEqual(stats["entries"], 3)
        self.assertEqual(stats["evictions"], 1)
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)

    def test_bytes_capacity_evicts(self):
        cache = _cache.LRUCache(max_bytes=20, max_entries=100)
        cache.put("a", b"1" * 15)
        cache.put("b", b"2" * 15)  # 超字节上限，挤出 a
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.stats()["evictions"], 1)


class EngineRoundtripTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="archive-")
        os.environ["AI_NEW_DATA"] = self.tmp
        self.ctx = _ctx(_default_cfg())
        self.root = _engine._dir_of("agent/logs")
        self.rel = "sessions/demo.yaml"
        self.abs = self.root / self.rel

    def tearDown(self):
        os.environ.pop("AI_NEW_DATA", None)

    def _write(self, data: bytes):
        self.abs.parent.mkdir(parents=True, exist_ok=True)
        self.abs.write_bytes(data)

    def test_compress_then_transparent_read_identical(self):
        original = ("会话记录正文 · " * 200).encode("utf-8")
        self._write(original)
        res = _engine.compress(self.ctx, {"paths": [str(self.abs)]})
        self.assertEqual(res["summary"]["compressed"], 1)
        self.assertFalse(self.abs.exists(), "压缩后原文应移除")
        self.assertTrue(Path(str(self.abs) + ".gz").is_file())

        text = _engine.read_text(self.ctx, {"module": "agent/logs", "path": self.rel})
        self.assertEqual(text["value"], original.decode("utf-8"))
        self.assertFalse(text["cached"])  # 首次解压未命中缓存
        text = _engine.read_text(self.ctx, {"module": "agent/logs", "path": self.rel})
        self.assertTrue(text["cached"])  # 二次读取命中解压缓存

        bro = _engine.read_bytes(self.ctx, {"module": "agent/logs", "path": self.rel})
        import base64
        self.assertEqual(base64.b64decode(bro["value"]), original)
        self.assertEqual(bro["size"], len(original))

    def test_compress_is_idempotent(self):
        original = b"idempotent-body" * 100
        self._write(original)
        first = _engine.compress(self.ctx, {"paths": [str(self.abs)]})
        self.assertEqual(first["summary"]["compressed"], 1)
        second = _engine.compress(self.ctx, {"paths": [str(self.abs)]})
        self.assertEqual(second["summary"]["skipped"], 1)
        self.assertEqual(second["summary"]["compressed"], 0)

    def test_corrupt_companion_reports_checksum_mismatch(self):
        original = b"tamper-me-body" * 100
        self._write(original)
        _engine.compress(self.ctx, {"paths": [str(self.abs)]})
        comp = Path(str(self.abs) + ".gz")
        raw = bytearray(comp.read_bytes())
        raw[len(raw) // 2] ^= 0xFF
        comp.write_bytes(bytes(raw))
        with self.assertRaises(_engine.ArchiveCorrupt):
            _engine.resolve_raw(self.ctx, "agent/logs", self.rel)

    def test_read_lines_slice_and_total(self):
        lines = ["line-%d" % i for i in range(100)]
        self._write("\n".join(lines).encode("utf-8"))
        _engine.compress(self.ctx, {"paths": [str(self.abs)]})
        out = _engine.read_lines(self.ctx, {"module": "agent/logs", "path": self.rel,
                                            "start": 10, "end": 15, "limit": 3})
        self.assertEqual(out["total"], 100)
        self.assertEqual(out["lines"], ["line-10", "line-11", "line-12"])

    def test_large_text_roundtrip(self):
        original = ("大文本 · " + "x" * 50) * 20000  # 约 1 MB
        self._write(original.encode("utf-8"))
        _engine.compress(self.ctx, {"paths": [str(self.abs)]})
        back = _engine.read_text(self.ctx, {"module": "agent/logs", "path": self.rel})
        self.assertEqual(back["value"], original)

    def test_index_query_rows_shape_and_status(self):
        original = b"index-query-body" * 100
        self._write(original)
        _engine.compress(self.ctx, {"paths": [str(self.abs)]})
        out = _engine.index_query(self.ctx, {})
        self.assertEqual(len(out["rows"]), 1)
        row = out["rows"][0]
        self.assertEqual(row["status"], "archived")
        self.assertEqual(row["size_orig"], len(original))
        self.assertEqual(row["algorithm"], "gzip")
        self.assertEqual(len(row["checksum"]), 64)
        self.assertTrue(row["compressed_at"])
        for field in ("path", "module", "layer", "category"):
            self.assertIn(field, row)

    def test_concurrent_reads_do_not_corrupt(self):
        original = b"concurrent-" * 200
        self._write(original)
        _engine.compress(self.ctx, {"paths": [str(self.abs)]})
        errors = []

        def worker():
            try:
                for _ in range(20):
                    got = _engine.resolve_raw(self.ctx, "agent/logs", self.rel)
                    if got["raw"] != original:
                        errors.append("mismatch")
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
