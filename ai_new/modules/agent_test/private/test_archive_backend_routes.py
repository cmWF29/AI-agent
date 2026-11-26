"""archive 装配面与压缩后端：路由注册/包装、zstd 可选接入、不支持的算法显式报错。"""
import gzip
import hashlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common import archive as archive_mod
from ai_new.modules.agent_common.archive.private import _backend, _engine


class Reg:
    def __init__(self):
        self.calls = []

    def register(self, name, fn, module=None, internal=False):
        self.calls.append((name, fn, module, internal))


class RouteTest(unittest.TestCase):
    def test_setup_registers_all_routes(self):
        reg = Reg()
        ctx = mock.Mock(api=reg)
        self.assertTrue(archive_mod.setup(ctx))
        names = [c[0] for c in reg.calls]
        self.assertEqual(names[0], "archive.resolve_abs")
        self.assertIs(reg.calls[0][3], True)
        self.assertEqual(len(names), 9)
        for name, _fn, module, internal in reg.calls[1:]:
            self.assertEqual(module, "archive")
            self.assertFalse(internal)

    def test_wrappers_forward_payload(self):
        ctx = mock.Mock()
        with mock.patch.object(archive_mod._engine, "resolve_abs", return_value="abs") as ra, \
                mock.patch.object(archive_mod._engine, "scan", return_value={"s": 1}) as scan, \
                mock.patch.object(archive_mod._engine, "compress", return_value={"c": 1}) as comp, \
                mock.patch.object(archive_mod._engine, "stats", return_value={"t": 1}) as st, \
                mock.patch.object(archive_mod._engine, "metrics", return_value={"m": 1}) as me:
            self.assertEqual(archive_mod._resolve_abs(ctx, None), "abs")
            self.assertEqual(archive_mod._resolve_abs(ctx, {"module": "m"}), "abs")
            self.assertEqual(archive_mod._route_scan(ctx, None), {"s": 1})
            self.assertEqual(archive_mod._route_compress(ctx, {}), {"c": 1})
            self.assertEqual(archive_mod._route_stats(ctx, None), {"t": 1})
            self.assertEqual(archive_mod._route_metrics(ctx, {}), {"m": 1})
        ra.assert_any_call(ctx, {}); ra.assert_any_call(ctx, {"module": "m"})
        scan.assert_any_call(ctx, {})
        comp.assert_any_call(ctx, {})
        st.assert_any_call(ctx, {})
        me.assert_any_call(ctx, {})


class FakeZstd(types.ModuleType):
    def __init__(self):
        super().__init__("zstandard")
        self.calls = []

    def ZstdCompressor(self, level=6):
        outer = self

        class C:
            def compress(self, data):
                outer.calls.append(("comp", level, data))
                return b"z" + data
        return C()

    def ZstdDecompressor(self):
        outer = self

        class D:
            def decompress(self, data):
                outer.calls.append(("decomp", data))
                return data[1:]
        return D()


class BackendTest(unittest.TestCase):
    def test_available_and_info_without_zstd(self):
        with mock.patch.object(_backend, "_ZSTD_INSTALLED", False):
            self.assertEqual(_backend.available_algorithms(), ["gzip"])
            info = _backend.backend_info()
            self.assertFalse(info["zstd"]["installed"])
            self.assertIn("zstandard", info["zstd"]["note"])

    def test_available_and_info_with_zstd(self):
        with mock.patch.object(_backend, "_ZSTD_INSTALLED", True):
            self.assertEqual(_backend.available_algorithms(), ["gzip", "zstd"])
            self.assertEqual(_backend.backend_info()["zstd"]["note"], "zstandard 已可导入。")

    def test_gzip_roundtrip_and_suffix(self):
        pack = _backend.compress_bytes(b"hello", level=1)
        self.assertEqual(pack["algorithm"], "gzip")
        self.assertEqual(_backend.decompress_bytes(pack["data"], "gzip"), b"hello")
        self.assertEqual(_backend.compress_bytes(b"x", algorithm="")["algorithm"], "gzip")
        self.assertEqual(_backend.decompress_bytes(gzip.compress(b"x"), algorithm=None), b"x")
        self.assertEqual(_backend.suffix_for("gzip"), ".gz")
        self.assertEqual(_backend.suffix_for("zstd"), ".zst")
        self.assertEqual(_backend.suffix_for(""), ".gz")
        self.assertEqual(_backend.suffix_for("other"), ".gz")

    def test_zstd_paths_via_stub_module(self):
        fake = FakeZstd()
        with mock.patch.object(_backend, "_ZSTD_INSTALLED", True), \
                mock.patch.dict(sys.modules, {"zstandard": fake}):
            pack = _backend.compress_bytes(b"hi", level=3, algorithm="zstd")
            self.assertEqual((pack["data"], pack["algorithm"]), (b"zhi", "zstd"))
            self.assertEqual(fake.calls[0], ("comp", 3, b"hi"))
            self.assertEqual(_backend.decompress_bytes(b"zhi", "zstd"), b"hi")
            self.assertEqual(fake.calls[1], ("decomp", b"zhi"))

    def test_zstd_missing_library_raises(self):
        with mock.patch.object(_backend, "_ZSTD_INSTALLED", False):
            with self.assertRaises(ValueError) as e1:
                _backend.compress_bytes(b"hi", algorithm="zstd")
            with self.assertRaises(ValueError) as e2:
                _backend.decompress_bytes(b"gzipped", algorithm="zstd")
        self.assertIn("zstandard", str(e1.exception))
        self.assertIn("zstandard", str(e2.exception))

    def test_unknown_algorithm_raises(self):
        with self.assertRaises(ValueError) as e1:
            _backend.compress_bytes(b"hi", algorithm="lzma")
        with self.assertRaises(ValueError) as e2:
            _backend.decompress_bytes(b"hi", algorithm="lzma")
        self.assertIn("lzma", str(e1.exception))
        self.assertIn("lzma", str(e2.exception))


class Ctx:
    """最小归档上下文：索引目录与真实文件都落在临时数据根。"""

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

    def call(self, name, payload=None, caller=None):
        payload = payload or {}
        if name == "clock.now":
            return {"ts": 1000, "iso": "T"}
        if name == "codec.digest":
            return {"ok": True, "hex": hashlib.sha256(payload["text"].encode()).hexdigest()}
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


class MetricsHitRateTest(unittest.TestCase):
    def test_metrics_with_real_hits(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = os.environ.get("AI_NEW_DATA")
        os.environ["AI_NEW_DATA"] = str(Path(tmp.name) / "data")
        self.addCleanup(lambda: os.environ.__setitem__("AI_NEW_DATA", old)
                        if old is not None else os.environ.pop("AI_NEW_DATA", None))
        mod = Path(tmp.name) / "data" / "m"
        mod.mkdir(parents=True)
        (mod / "a.txt").write_text("hello archive")
        ctx = Ctx(tmp.name, {"scan": [{"module": "m", "category": "c", "glob": "*.txt"}],
                             "categories": {"c": {"age_days": 0, "min_bytes": 0, "grace_seconds": 0}},
                             "cache_max_bytes": 1024, "cache_max_entries": 8})
        _engine.compress(ctx, {"paths": [str(mod / "a.txt")]})
        _engine.read_text(ctx, {"module": "m", "path": "a.txt"})  # miss
        _engine.read_text(ctx, {"module": "m", "path": "a.txt"})  # hit
        met = _engine.metrics(ctx)
        self.assertEqual(met["decompress"]["status"], "insufficient_samples")
        self.assertEqual(met["labels"]["hit_rate"], "")  # 有样本时不再贴“无命中率”说明


if __name__ == "__main__":
    unittest.main()
