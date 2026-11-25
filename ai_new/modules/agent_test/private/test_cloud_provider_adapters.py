"""提供方适配：S3/WebDAV 统一接口桥、列表与上传下载失败归一、惰性构建回落。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.cloud.private import _providers as p  # noqa: E402


class Client:
    def __init__(self):
        self.calls = []

    def test_connection(self):
        return {"ok": True}

    def list_keys(self, prefix):
        self.calls.append(("list", prefix))
        return [{"key": "a"}]

    def put(self, key, data, resume=None):
        self.calls.append(("put", key, resume))
        return {"ok": True, "size": len(data)}

    def get(self, key, sink=None):
        self.calls.append(("get", key))
        if sink is not None:
            sink.write(b"abc")
        return {"ok": True}

    def delete(self, key):
        return {"ok": True}

    def head(self, key):
        return {"ok": True}

    def propfind(self, path, depth=0):
        return {"ok": True, "entries": [{"is_dir": True, "key": "d"},
                                        {"key": "a", "etag": "e", "size": 1},
                                        {"key": "b"}]}


class Api:
    def call(self, name, payload=None, caller=None):
        return {"hex": "h"}


class Ctx:
    def __init__(self):
        self.api = Api()


class ProviderAdapterTest(unittest.TestCase):
    def test_s3_adapter(self):
        ad = p._S3Adapter(transport="t")
        fake = Client()
        with mock.patch.object(ad, "_client", return_value=fake):
            self.assertTrue(ad.test_connection(None, {})["ok"])
            self.assertEqual(ad.list_keys(None, {}, "x"), [{"key": "a"}])
            ad.put(None, {}, "k", b"1", upload_id="u")
            ad.put(None, {}, "k", b"1")
            self.assertEqual([c[0] for c in fake.calls], ["list", "put", "put"])
            self.assertEqual(fake.calls[1][2], {"upload_id": "u", "parts": {}})
            ad.get(None, {}, "k")
            ad.delete(None, {}, "k")
            ad.head(None, {}, "k")

    def test_webdav_list(self):
        ad = p._WebDavAdapter()
        fake = Client()
        with mock.patch.object(ad, "_client", return_value=fake):
            self.assertEqual([r["key"] for r in ad.list_keys(None, {}, "")], ["a", "b"])
            fake.propfind = lambda *a, **k: {"ok": False}
            self.assertEqual(ad.list_keys(None, {}, ""), [])

    def test_webdav_put_get_delete(self):
        ad = p._WebDavAdapter()
        fake = Client()
        with mock.patch.object(ad, "_client", return_value=fake):
            self.assertTrue(ad.put(None, {}, "k", b"1")["ok"])
            fake.put = lambda *a, **k: {"ok": False, "code": "bad"}
            out = ad.put(None, {}, "k", b"1", resume_from=5)
            self.assertEqual(out["code"], "bad")
            self.assertTrue(ad.get(Ctx(), {}, "k")["ok"])
            fake.get = lambda *a, **k: {"ok": False, "code": "bad"}
            self.assertEqual(ad.get(Ctx(), {}, "k")["code"], "bad")
            self.assertTrue(ad.delete(None, {}, "k")["ok"])
            fake.delete = lambda *a, **k: {}
            self.assertFalse(ad.delete(None, {}, "k")["ok"])
            self.assertTrue(ad.test_connection(None, {})["ok"])

    def test_build_and_meta(self):
        def boom():
            raise ImportError("x")

        with mock.patch.dict(p._LAZY, {"s3": boom}):
            self.assertFalse(p.build("s3").test_connection(None, {})["ok"])
        with mock.patch.dict(p._LAZY, {"webdav": boom}):
            self.assertEqual(p.build("webdav").status_code, "adapter_pending")
        with self.assertRaises(p.ProviderError):
            p.build("nope")
        self.assertTrue(p.build("fake").test_connection(None, {})["ok"])
        fake_s3 = mock.Mock()
        fake_s3.S3Client.return_value = "s3"
        fake_wd = mock.Mock()
        fake_wd.WebDavClient.return_value = "wd"
        mods = {"ai_new.modules.agent.cloud.private._s3": fake_s3,
                "ai_new.modules.agent.cloud.private._webdav": fake_wd}
        with mock.patch.dict(sys.modules, mods):
            self.assertEqual(p._S3Adapter()._client(None, {}), "s3")
            self.assertEqual(p._WebDavAdapter()._client(None, {}), "wd")
            self.assertIsInstance(p._build_s3(), p._S3Adapter)
            self.assertIsInstance(p._build_webdav(), p._WebDavAdapter)
        self.assertIsInstance(p._build_s3(), p._S3Adapter)
        self.assertIsInstance(p._build_webdav(), p._WebDavAdapter)
        kinds = {row["kind"] for row in p.provider_meta()}
        self.assertIn("s3", kinds)


class SeqApi:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def call(self, name, payload=None, caller=None):
        self.calls.append(name)
        if name == "codec.digest":
            return {"hex": "h"}
        return self.rows.pop(0)


class BaseAndHttpTest(unittest.TestCase):
    def test_base_not_implemented(self):
        base = p.BaseProvider()
        for fn, args in (("test_connection", (None, {})), ("list_keys", (None, {}, "")),
                         ("put", (None, {}, "k", b"")), ("get", (None, {}, "k")),
                         ("delete", (None, {}, "k"))):
            with self.assertRaises(NotImplementedError):
                getattr(base, fn)(*args)

    def test_fake_provider(self):
        ctx = Ctx()
        fake = p.FakeProvider()
        self.assertEqual(fake.list_keys(ctx, {}, ""), [])
        self.assertTrue(fake.test_connection(ctx, {"endpoint": "e"})["ok"])
        fake.fail_times = 1
        self.assertFalse(fake.put(ctx, {}, "a", b"1")["ok"])
        fake.fail_keys["b"] = 1
        self.assertFalse(fake.put(ctx, {}, "b", b"1")["ok"])
        self.assertTrue(fake.put(ctx, {}, "a", b"1")["ok"])
        self.assertEqual(fake.list_keys(ctx, {}, "")[0]["key"], "a")
        self.assertTrue(fake.put(ctx, {}, "z", b"1")["ok"])
        self.assertEqual([r["key"] for r in fake.list_keys(ctx, {}, "a")], ["a"])
        self.assertEqual([r["key"] for r in fake.list_keys(ctx, {}, "")], ["a", "z"])
        self.assertTrue(fake.get(ctx, {}, "a")["ok"])
        self.assertEqual(fake.get(ctx, {}, "x")["code"], "not_found")
        self.assertTrue(fake.delete(ctx, {}, "a")["ok"])

    def test_http_dir_provider(self):
        rows = [
            {"ok": True},
            {"ok": True, "items": [{"key": "a", "digest": "d"}]},
            {"ok": False},
            {"ok": True, "body": b"x"},
            {"ok": False},
            {"ok": True},
        ]
        ctx = Ctx()
        ctx.api = SeqApi(rows)
        http = p.HttpDirProvider()
        prof = {"endpoint": "http://h/", "root_dir": "/r", "policy": {"max_body_bytes": 10}}
        guard_ctx = Ctx()
        guard_ctx.api = SeqApi([{"ok": True, "location": "http://x"}])
        with mock.patch.object(p._guard, "validate_redirect", return_value={"ok": False,
                                                                            "errors": ["bad"]}):
            with self.assertRaises(p.ProviderError):
                http.test_connection(guard_ctx, prof)
        with mock.patch.object(p._guard, "validate_redirect", return_value={"ok": True}):
            http._guard_redirect(prof, {"location": "http://x"})
            self.assertTrue(http.test_connection(ctx, {"endpoint": "http://h"})["ok"])
            self.assertEqual(http.list_keys(ctx, prof, "")[0]["key"], "a")
            self.assertEqual(http.put(ctx, prof, "k", b"1")["code"], "provider_error")
            self.assertEqual(http.get(ctx, prof, "k")["data"], b"x")
            self.assertEqual(http.get(ctx, prof, "k")["code"], "provider_error")
            self.assertTrue(http.delete(ctx, prof, "k")["ok"])
        ok_ctx = Ctx()
        ok_ctx.api = SeqApi([{"ok": True}])
        with mock.patch.object(p._guard, "validate_redirect", return_value={"ok": True}):
            self.assertTrue(http.put(ok_ctx, prof, "k", b"1")["ok"])

    def test_pending(self):
        pending = p._PendingProvider()
        self.assertEqual(pending.test_connection(None, {})["code"], "adapter_pending")
        self.assertEqual(pending.list_keys(None, {}, ""), [])
        self.assertFalse(pending.put(None, {}, "k", b"")["ok"])
        self.assertFalse(pending.get(None, {}, "k")["ok"])
        self.assertFalse(pending.delete(None, {}, "k")["ok"])


if __name__ == "__main__":
    unittest.main()
