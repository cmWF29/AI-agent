"""S3 通道边界：URL/解码、结果分类、限流闸门、退避、坏键、走文本体的 GET、
分片读空、超大拒绝、单段/多段失败与 XML 解析兜底。"""
import base64
import hashlib
import io
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent.cloud.private import _guard, _s3  # noqa: E402


class _Api:
    def __init__(self, ctx):
        self.ctx = ctx

    def call(self, name, params=None, caller=None):
        params = params or {}
        if name == "clock.now":
            return {"ts": self.ctx.ts}
        if name == "clock.sleep":
            return {"ok": True}
        if name == "codec.digest":
            if self.ctx.bad_digest:
                return {"hex": "zzzzzzzz"}
            raw = params.get("text") or b""
            if isinstance(raw, str):
                raw = raw.encode("utf-8")
            return {"hex": hashlib.sha256(bytes(raw)).hexdigest()}
        if name == "codec.base64_encode":
            return {"text": base64.b64encode(bytes(params.get("text") or b"")).decode()}
        if name == "codec.base64_decode_bytes":
            return {"data": base64.b64decode(params.get("text") or "")}
        if name == "codec.nonce":
            return {"token": "0a1b2c3d"}
        return {}


class _Ctx:
    def __init__(self):
        self.ts = 100.0
        self.bad_digest = False
        self.api = _Api(self)


def _client(transport, **policy):
    return _s3.S3Client(_Ctx(), {"endpoint": "https://s3.local"},
                        {"bucket": "b", "access_key": "ak", "secret_key": "sk"},
                        transport=transport, policy=policy)


def _row(**kw):
    base = {"ok": True, "status": 200, "headers": {}, "body": b"", "text": ""}
    base.update(kw)
    return base


class S3EdgeTest(unittest.TestCase):
    def test_parse_url_and_unquote(self):
        got = _s3._parse_url("https://h:9000/a/b?x=1")
        self.assertEqual((got["scheme"], got["host"], got["path"], got["query"]),
                         ("https", "h:9000", "/a/b", "x=1"))
        self.assertEqual(_s3._parse_url("")["scheme"], "")
        self.assertEqual(_s3._unquote("%ZZ%41"), "%ZZA")
        self.assertEqual(_s3._hmac(b"k", "msg"), _s3._hmac(b"k", b"msg"))

    def test_classify_matrix(self):
        self.assertEqual(_s3._classify(403, {"text": "denied"}), "access_denied")
        self.assertEqual(_s3._classify(429, {}), "rate_limited")
        self.assertEqual(_s3._classify(401, {}), "access_denied")
        self.assertEqual(_s3._classify(400, {}), "provider_error")
        self.assertEqual(_s3._classify(0, {"ok": False}), "connection_error")
        self.assertEqual(_s3._classify(0, {"ok": True}), "provider_error")

    def test_rate_gate_blocks_when_full(self):
        gate = _s3._RateGate(1, 0)
        ctx = _Ctx()
        order, arrived = [], threading.Event()
        release = threading.Event()

        def first():
            def fn():
                release.wait(3)
                order.append("a")
            gate.run(ctx, fn)

        def second():
            arrived.set()
            gate.run(ctx, lambda: order.append("b"))

        t1 = threading.Thread(target=first)
        t1.start()
        t2 = threading.Thread(target=second)
        t2.start()
        arrived.wait(3)
        time.sleep(0.15)
        self.assertEqual(order, [])
        release.set()
        t2.join(3)
        t1.join(3)
        self.assertEqual(order, ["a", "b"])

    def test_jitter_and_backoff(self):
        ctx = _Ctx()
        ctx.bad_digest = True
        client = _s3.S3Client(ctx, {"endpoint": "https://s3.local"},
                              {"bucket": "b", "access_key": "ak", "secret_key": "sk"},
                              policy={"max_attempts": 1})
        self.assertEqual(client._jitter_fraction(), 0.0)
        self.assertEqual(client._backoff(1, {"headers": {"retry-after": "3"}}), 3.0)
        self.assertGreaterEqual(client._backoff(1, {"headers": {"retry-after": "x"}}), 0.0)

    def test_request_rejects_bad_key(self):
        row = _client(lambda *a: _row())._request("PUT", "../x")
        self.assertEqual(row["code"], "invalid_key")

    def test_head_without_checksum_and_failure(self):
        def transport(ctx, method, url, headers, body, timeout):
            if method == "HEAD" and "/bad" in url:
                return _row(ok=False, status=404)
            return _row(headers={"content-length": "5", "etag": "e"})

        client = _client(transport, max_attempts=1)
        got = client.head("ok")
        self.assertEqual((got["ok"], got["size"], got["checksum"]), (True, 5, ""))
        bad = client.head("bad")
        self.assertEqual((bad["ok"], bad["code"]), (False, "not_found"))

    def test_get_uses_text_when_body_missing(self):
        client = _client(lambda *a: _row(body=None, text="abc"), max_attempts=1)
        got = client.get("k")
        self.assertEqual(got["data"], b"abc")

    def test_delete_failure(self):
        client = _client(lambda *a: _row(ok=False, status=500), max_attempts=1)
        self.assertFalse(client.delete("k")["ok"])

    def test_part_read_and_stream_digest_break_on_empty(self):
        class _Empty:
            def seek(self, _o):
                return 0

            def read(self, _n):
                return b""

        client = _client(lambda *a: _row())
        self.assertEqual(client._read_part(_Empty(), 0, 10), b"")
        self.assertEqual(client._stream_digest(_Empty(), 10),
                         hashlib.sha256(b"").hexdigest())

    def test_put_over_max_body_raises(self):
        client = _client(lambda *a: _row(), max_body_bytes=4, max_attempts=1)
        with self.assertRaises(_guard.GuardError):
            client.put_stream("k", io.BytesIO(b"0123456789"), 10)

    def test_put_single_failure(self):
        client = _client(lambda *a: _row(ok=False, status=500), max_attempts=1)
        got = client.put("k", b"abc")
        self.assertEqual((got["ok"], got["offset"]), (False, 0))

    def _multipart_client(self, transport):
        return _client(transport, multipart_threshold=4, multipart_min_size=2,
                       part_max_bytes=4, max_attempts=1)

    def test_init_multipart_failures(self):
        client = self._multipart_client(lambda *a: _row(ok=False, status=500))
        upload_id, row = client._init_multipart("k")
        self.assertIsNone(upload_id)
        self.assertFalse(row["ok"])

        client = self._multipart_client(lambda *a: _row(body=b"<Root/>", text=""))
        upload_id, row = client._init_multipart("k")
        self.assertIsNone(upload_id)
        self.assertEqual(row["code"], "multipart_error")

    def test_multipart_rejects_empty_upload_id_from_init(self):
        client = self._multipart_client(lambda *a: _row(ok=False, status=500))
        got = client._put_multipart("k", io.BytesIO(b"abcdefgh"), 8,
                                    [(0, 4), (4, 4)], {})
        self.assertEqual((got["ok"], got["offset"]), (False, 0))

    def test_multipart_resume_int_id_and_complete_failure(self):
        def transport(ctx, method, url, headers, body, timeout):
            if method == "POST":
                return _row(ok=False, status=500)
            return _row(headers={"etag": "e1"})

        client = self._multipart_client(transport)
        got = client._put_multipart("k", io.BytesIO(b"abcdefgh"), 8,
                                    [(0, 4), (4, 4)], {"upload_id": 123})
        self.assertFalse(got["ok"])
        self.assertEqual(got["upload_id"], "123")

    def test_xml_parse_fallbacks(self):
        self.assertEqual(_s3._parse_upload_id("<bad"), "")
        self.assertEqual(_s3._parse_list_xml("<bad"), {"items": [], "is_truncated": False,
                                                       "next_token": ""})
        flat = ("<ListBucketResult><Key>a</Key><Size>3</Size>"
                "</ListBucketResult>")
        parsed = _s3._parse_list_xml(flat)
        self.assertEqual(parsed["items"][0]["key"], "a")


    def test_request_without_signature(self):
        row = _client(lambda *a: _row())._request("GET", "", sign=False)
        self.assertTrue(row["ok"])

    def test_retry_then_success(self):
        hits = {"n": 0}

        def transport(ctx, method, url, headers, body, timeout):
            hits["n"] += 1
            if hits["n"] == 1:
                return _row(ok=True, status=500)
            return _row()

        client = _client(transport, max_attempts=2)
        self.assertTrue(client.test_connection()["ok"])

    def test_list_keys_dedupes_and_caps_pages(self):
        page = ("<ListBucketResult><IsTruncated>true</IsTruncated>"
                "<NextContinuationToken>t</NextContinuationToken>"
                "<Contents><Key>a</Key><Size>1</Size></Contents>"
                "<Contents><Key>a</Key><Size>2</Size></Contents>"
                "</ListBucketResult>")

        def transport(ctx, method, url, headers, body, timeout):
            return _row(body=page.encode("utf-8"))

        rows = _client(transport).list_keys()
        self.assertEqual([r["key"] for r in rows], ["a"])

if __name__ == "__main__":
    unittest.main()
