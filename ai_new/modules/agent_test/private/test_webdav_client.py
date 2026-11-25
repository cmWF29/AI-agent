"""WebDAV 客户端：端点/解析、Digest、上传下载、MKCOL/DELETE 与重试退避。"""
from __future__ import annotations

import base64
import hashlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent.cloud.private import _webdav as w  # noqa: E402


class Codec:
    def digest(self, text, algorithm="md5"):
        data = text.encode() if isinstance(text, str) else text
        return hashlib.new(algorithm, data).hexdigest()

    def base64_encode(self, data):
        return base64.b64encode(data).decode()


class Clock:
    def __init__(self):
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(seconds)


class Resp:
    def __init__(self, status=200, headers=None, body=b"", read_error=False):
        self.status = status
        self.headers = headers or {}
        self.body = body
        self.read_error = read_error

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, n=None):
        if self.read_error:
            raise OSError("read")
        if n is None:
            out, self.body = self.body, b""
            return out
        out, self.body = self.body[:n], self.body[n:]
        return out


class Conn:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = []
        self.sent = []

    def putrequest(self, method, path):
        self.method, self.path = method, path

    def putheader(self, key, value):
        self.headers.append((key, value))

    def endheaders(self):
        pass

    def send(self, chunk):
        self.sent.append(chunk)

    def getresponse(self):
        return self.responses.pop(0)

    def close(self):
        pass


class Api:
    def __init__(self):
        self.fail = False

    def call(self, name, payload=None, caller=None):
        if name == "codec.digest":
            return {"ok": not self.fail, "hex": "h", "error": "e"}
        if name == "codec.base64_encode":
            return {"ok": not self.fail, "text": "b", "error": "e"}
        if name == "clock.sleep":
            return {}
        raise AssertionError(name)


class WebDavTest(unittest.TestCase):
    def client(self, **kw):
        return w.WebDavClient("http://example.com/base", username="u", password="p",
                              codec=Codec(), clock=Clock(), **kw)

    def test_helpers_and_endpoint(self):
        self.assertEqual(w.sanitize_key("a/b"), "a/b")
        self.assertEqual(w._map_status(404), "not_found")
        self.assertEqual(w._map_status(500), "provider_error")
        self.assertEqual(w._map_status(418), "http_error")
        self.assertEqual(w._href_to_rel("", "/base"), None)
        self.assertEqual(w._href_to_rel("http://x/base/a%20b", "/base"), "a b")
        self.assertEqual(w._href_to_rel("http://x/base/", "/base"), None)
        self.assertEqual(w._href_to_rel("http://x/other/a", ""), "other/a")
        self.assertEqual(w.validate_endpoint("https://x")["ok"], True)
        self.assertEqual(w._parse_digest_challenge(""), None)
        self.assertEqual(w._parse_digest_challenge("Basic x"), None)
        self.assertEqual(w._parse_digest_challenge("Digest realm=\"r\", nonce=\"n\""),
                         {"realm": "r", "nonce": "n"})
        self.assertEqual(w._parse_digest_challenge("Digest realm=\"r\""), None)
        with self.assertRaises(w.WebDavError):
            w.WebDavClient("ftp://x")
        with self.assertRaises(w.WebDavError):
            w.WebDavClient("http:///x")
        with self.assertRaises(w.WebDavError) as e:
            w.WebDavClient("http://127.0.0.1", cfg={"allow_local": False})
        self.assertTrue(e.exception.code)
        w.WebDavClient("https://example.com/x", cfg={"allow_local": True})
        c = self.client()
        self.assertEqual(c._path("a b"), "/base/a%20b")
        self.assertEqual(c._backoff_delay(0), 0.2)
        self.assertEqual(c._backoff_delay(10), 2.0)
        c._backoff_base = -1
        self.assertEqual(c._backoff_delay(1), 0.0)

    def test_multistatus_and_capabilities(self):
        xml = (b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>/base/a</d:href>'
               b'<d:propstat><d:prop><d:getcontentlength>3</d:getcontentlength>'
               b'<d:getetag>"e"</d:getetag></d:prop></d:propstat></d:response>'
               b'<d:response><d:href>/base/</d:href></d:response>'
               b'<d:response><d:href>/base/d</d:href><d:propstat><d:prop>'
               b'<d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat>'
               b'</d:response></d:multistatus>')
        self.assertEqual(w._parse_multistatus(xml, "/base"),
                         [{"key": "a", "size": 3, "etag": '"e"', "is_dir": False},
                          {"key": "d", "size": None, "etag": None, "is_dir": True}])
        with self.assertRaises(w.WebDavError) as e:
            w._parse_multistatus(b"<!DOCTYPE x><x/>", "")
        self.assertEqual(e.exception.code, "xml_forbidden")
        with self.assertRaises(w.WebDavError) as e2:
            w._parse_multistatus(b"<bad", "")
        self.assertEqual(e2.exception.code, "malformed_xml")
        c = self.client()
        self.assertTrue(c._basic_header().startswith("Basic "))
        self.assertEqual(c._digest_hex("x"), Codec().digest("x"))
        self.assertEqual(c._b64_encode(b"x"), "eA==")
        c._codec = None
        c._clock = None
        c._ctx = None
        with self.assertRaises(w.WebDavError) as e3:
            c._digest_hex("x")
        self.assertEqual(e3.exception.code, "capability_missing")
        with self.assertRaises(w.WebDavError) as e4:
            c._b64_encode(b"x")
        self.assertEqual(e4.exception.code, "capability_missing")
        with self.assertRaises(w.WebDavError) as e5:
            c._sleep(1)
        self.assertEqual(e5.exception.code, "capability_missing")

    def test_digest_headers(self):
        c = self.client()
        auth = c._digest_header({"realm": "r", "nonce": "n", "opaque": "o",
                                "qop": "auth"}, "GET", "/x")
        self.assertIn("qop=auth", auth)
        self.assertIn('opaque="o"', auth)
        auth_int = c._digest_header({"realm": "r", "nonce": "n",
                                     "qop": "auth-int, auth"}, "PUT", "/x", "e" * 32)
        self.assertIn("qop=auth-int", auth_int)
        old = c._digest_header({"realm": "r", "nonce": "n"}, "GET", "/x")
        self.assertNotIn("qop=", old)
        src = io.BytesIO(b"abc")
        self.assertEqual(c._entity_md5(src), hashlib.md5(b"abc").hexdigest())
        self.assertEqual(src.tell(), 0)
        c._rewind(object())
        class BadSeek:
            def seek(self, _n):
                raise ValueError("seek")
        c._rewind(BadSeek())
        c._drain(Resp(read_error=True))
        ctx = type("Ctx", (), {})()
        ctx.api = Api()
        ctx_client = w.WebDavClient("http://x", ctx=ctx, codec=None, clock=None)
        self.assertEqual(ctx_client._digest_hex("x"), "h")
        self.assertEqual(ctx_client._b64_encode(b"x"), "b")
        ctx_client._sleep(1)
        ctx.api.fail = True
        with self.assertRaises(w.WebDavError) as ce:
            ctx_client._digest_hex("x")
        self.assertEqual(ce.exception.code, "codec_error")
        with self.assertRaises(w.WebDavError) as cb:
            ctx_client._b64_encode(b"x")
        self.assertEqual(cb.exception.code, "codec_error")
        tls = w.WebDavClient("https://example.com")
        self.assertTrue(tls._build_ssl_context())
        self.assertIsNotNone(tls._connect())
        tls._ca_bundle = "/etc/ssl/certs/ca-certificates.crt"
        self.assertTrue(tls._build_ssl_context())
        tls._ca_bundle = None
        self.assertTrue(tls._build_ssl_context())
        self.assertIsNotNone(w.WebDavClient("http://example.com")._connect())

    def test_request_basic_and_digest_retry(self):
        c = self.client()
        conn = Conn([Resp(200, {"ETag": "e"})])
        c._connect = lambda: conn
        resp = c._request("HEAD", "/x", headers={"A": "B"}, body_source=io.BytesIO(b"d"),
                          content_length=1)
        self.assertEqual(resp.status, 200)
        self.assertIn(("Authorization", c._basic_header()), conn.headers)
        self.assertIn(("Content-Length", "1"), conn.headers)
        self.assertIn(("Authorization", c._basic_header()), conn.headers)

        conn_get = Conn([Resp(200)])
        c._connect = lambda: conn_get
        self.assertEqual(c._request("GET", "/x").status, 200)
        anon = w.WebDavClient("http://example.com", codec=Codec())
        anon._connect = lambda: Conn([Resp(200)])
        self.assertEqual(anon._request("GET", "/x").status, 200)
        first = Resp(401, {"WWW-Authenticate": 'Digest realm="r", nonce="n", qop="auth"'})
        second = Resp(200)
        conns = [Conn([first]), Conn([second])]
        c._connect = lambda: conns.pop(0)
        c._entity_md5 = lambda source: "e" * 32
        self.assertEqual(c._request("PUT", "/x", body_source=io.BytesIO(b"d"),
                                    content_length=1).status, 200)
        first2 = Resp(401, {"WWW-Authenticate": "Basic x"})
        conn2 = Conn([first2])
        c._connect = lambda: conn2
        self.assertEqual(c._request("GET", "/x").status, 401)

    def test_connection_head_propfind(self):
        c = self.client()
        c._request = lambda *a, **k: Resp(200, {"Content-Length": "3", "ETag": "e"})
        self.assertEqual(c.head("a"), {"ok": True, "status": 200, "etag": "e", "size": 3})
        c._request = lambda *a, **k: Resp(200)
        self.assertIsNone(c.head("a")["size"])
        c._request = lambda *a, **k: Resp(404)
        self.assertEqual(c.head("a")["code"], "not_found")
        c._request = lambda *a, **k: Resp(500)
        self.assertEqual(c.head("a")["code"], "provider_error")

        xml = (b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>/base/a</d:href>'
               b'</d:response></d:multistatus>')
        c._request = lambda *a, **k: Resp(207, body=xml)
        self.assertEqual(c.propfind(""), {"ok": True,
                                            "entries": [{"key": "a", "size": None,
                                                         "etag": None, "is_dir": False}]})
        c._request = lambda *a, **k: Resp(403)
        self.assertEqual(c.propfind("a")["code"], "forbidden")

        c._request = lambda *a, **k: Resp(200)
        self.assertEqual(c.test_connection(), {"ok": True, "detail": "http-200"})
        c._request = lambda *a, **k: Resp(401)
        self.assertFalse(c.test_connection()["ok"])
        c._request = lambda *a, **k: Resp(500)
        self.assertFalse(c.test_connection()["ok"])
        def boom(*a, **k):
            raise OSError("down")
        c._request = boom
        self.assertIn("connection_error", c.test_connection()["detail"])

    def test_put_paths(self):
        c = self.client(max_body_bytes=3, max_attempts=2)
        c.mkcol = lambda key: {"ok": True}
        c.head = lambda key: {"ok": True, "status": 200, "etag": "e", "size": 3}
        self.assertTrue(c.put("a/b", b"abc", etag="e")["skipped"])
        self.assertTrue(c.put("a/b", b"abc")["skipped"])
        self.assertEqual(c.put("a", b"abcd")["code"], "body_too_large")
        with self.assertRaises(w.WebDavError) as e:
            c.put("a", io.BytesIO(b"x"))
        self.assertEqual(e.exception.code, "missing_size")
        c.head = lambda key: {"ok": False}
        c.mkcol = lambda key: {"ok": False, "code": "provider_error", "status": 500}
        self.assertEqual(c.put("a/b", b"abc")["stage"], "ensure-parents")
        c.mkcol = lambda key: {"ok": True}
        c._request = lambda *a, **k: Resp(201, {"ETag": "n"})
        self.assertTrue(c.put("a/b/c", b"x")["ok"])
        c.head = lambda key: {"ok": True, "status": 200, "etag": "z", "size": 99}
        self.assertFalse(c.put("q", b"x")["skipped"])
        c.head = lambda key: {"ok": False}
        self.assertTrue(c.put("a", b"x")["ok"])
        for status, code in ((409, "conflict"), (412, "precondition_failed"),
                             (423, "locked"), (413, "body_too_large"),
                             (403, "forbidden")):
            c._request = lambda *a, _s=status, **k: Resp(_s)
            self.assertEqual(c.put("a", b"x")["code"], code)
        c._request = lambda *a, **k: Resp(500)
        self.assertEqual(c.put("a", b"x")["code"], "provider_error")
        def boom(*a, **k):
            raise OSError("net")
        c._request = boom
        self.assertEqual(c.put("a", b"x")["code"], "connection_error")
        c._request = lambda *a, **k: Resp(201)
        self.assertEqual(c.put("a", io.BytesIO(b"x"), size="1",
                               skip_identical=False)["ok"], True)
        self.assertEqual(c.put_resumable("a", b"x", 1)["ok"], True)

    def test_get_mkcol_delete(self):
        c = self.client()
        c._request = lambda *a, **k: Resp(404)
        self.assertEqual(c.get("a", io.BytesIO())["code"], "not_found")
        c._request = lambda *a, **k: Resp(403)
        self.assertEqual(c.get("a", io.BytesIO())["code"], "forbidden")
        body = b"abcdef"
        c._request = lambda *a, **k: Resp(206, {"Content-Length": "6"}, body=body)
        sink = io.BytesIO()
        self.assertEqual(c.get("a", sink, offset=2, resume=True),
                         {"ok": True, "size": 6, "offset": 6, "partial": True})
        c._request = lambda *a, **k: Resp(200, body=b"xy")
        self.assertEqual(c.get("a", io.BytesIO(), offset=5)["offset"], 2)
        c._request = lambda *a, **k: Resp(201)
        self.assertTrue(c.mkcol("a")["ok"])
        c._request = lambda *a, **k: Resp(405)
        self.assertEqual(c.mkcol("a")["code"], "method_not_allowed")
        c._request = lambda *a, **k: Resp(204)
        self.assertTrue(c.delete("a")["ok"])
        c._request = lambda *a, **k: Resp(404)
        self.assertEqual(c.delete("a")["code"], "not_found")
        c._request = lambda *a, **k: Resp(500)
        self.assertEqual(c.delete("a")["code"], "provider_error")
        with self.assertRaises(w.WebDavError) as e:
            c.head("../x")
        self.assertEqual(e.exception.code, "invalid_key")


if __name__ == "__main__":
    unittest.main()
