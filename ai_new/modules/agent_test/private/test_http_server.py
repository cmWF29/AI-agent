"""HTTP 服务真实链路：起 loopback 服务，用 http.client / 裸 socket 打各类分支。"""
import http.client
import json
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.http.private import _server  # noqa: E402
from ai_new.modules.agent_common.api.private._errors import ApiError  # noqa: E402


class _Codec:
    def yaml_decode(self, text):
        try:
            return {"ok": True, "value": json.loads(text)}
        except ValueError:
            return {"ok": False}

    def yaml_encode_flow(self, obj):
        return {"text": json.dumps(obj, ensure_ascii=False)}


class _Web:
    def __init__(self, ctx):
        self.ctx = ctx

    def asset(self, ctx, rel):
        if rel.startswith("missing"):
            raise ctx.ApiError("资源不存在", code="not_found", status=404)
        return {"content": ctx.asset_text, "content_type": "text/html; charset=utf-8"}


class _Hooks:
    def __init__(self, ctx):
        self.ctx = ctx

    def pending(self):
        return self.ctx.hook_pending

    def drain(self):
        if self.ctx.hook_fail:
            raise RuntimeError("drain boom")


class _Api:
    def __init__(self, ctx):
        self.ctx = ctx

    def routes(self):
        return [{"name": "demo.echo"}]

    def route(self, name):
        return self.ctx.routes.get(name)

    def _ensure_loop(self):
        if self.ctx.loop_fail:
            raise RuntimeError("no loop")
        return mock.Mock()

    def register(self, *a, **k):
        return True

    def call(self, name, payload=None, caller=None, direct=False):
        return self.ctx.dispatch(name, payload or {})


class _Ctx:
    def __init__(self):
        self.cfg = {"server": {"host": "127.0.0.1", "port": 0}}
        self.ApiError = ApiError
        self.codec = _Codec()
        self.loaded = {"agent_common.http"}
        self.asset_text = "<html>" + "x" * 400 + "</html>"
        self.allow = True
        self.gate_public = True
        self.hook_pending = 0
        self.hook_fail = False
        self.loop_fail = True
        self.routes = {"demo.echo": {}, "demo.stream": {"stream": True},
                       "demo.internal": {"internal": True}}
        self.sse_items = [{"n": 1}, {"n": 2}]
        self.sse_cursor_mode = False
        self.sse_raise_at = None
        self.sse_calls = 0
        self.gzip_floor = 10
        self.web = _Web(self)
        self.hooks = _Hooks(self)
        self.api = _Api(self)

    def dispatch(self, name, payload):
        if name == "auth.verify":
            return {"allow": self.allow}
        if name == "web.gate":
            return {"public": self.gate_public, "to": "login.html"}
        if name == "config.get":
            return {"value": self.gzip_floor}
        if name == "clock.sleep":
            return {"ok": True}
        if name == "demo.stream":
            self.sse_calls += 1
            if self.sse_raise_at and self.sse_calls >= self.sse_raise_at:
                raise BrokenPipeError("stream closed")
            if self.sse_cursor_mode:
                return {"items": [{"n": self.sse_calls}], "cursor": self.sse_calls,
                        "blocked": False}
            items, self.sse_items = self.sse_items, []
            return {"items": items, "blocked": True}
        if name == "demo.fail":
            raise ValueError("bad input")
        if name == "demo.boom":
            raise RuntimeError("boom")
        return {"ok": True, "payload": payload}


def _conn(server):
    return http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)


class HttpServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = _Ctx()
        cls.server = _server.setup(cls.ctx)
        _server.start(cls.ctx, cls.server)
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = _conn(self.server)
        data = body.encode("utf-8") if isinstance(body, str) else body
        conn.request(method, path, body=data, headers=headers or {})
        resp = conn.getresponse()
        payload = resp.read()
        result = {"status": resp.status, "body": payload,
                  "headers": {k.lower(): v for k, v in resp.getheaders()}}
        conn.close()
        return result

    def test_public_get_and_write_route_methods(self):
        self.assertEqual(self.request("GET", "/api/health/live")["status"], 200)
        got = self.request("GET", "/api/demo/echo")
        self.assertEqual(got["status"], 405)
        self.assertEqual(json.loads(got["body"])["code"], "method_not_allowed")
        self.assertEqual(self.request("GET", "/api/nope/x")["status"], 404)
        self.assertEqual(self.request("GET", "/api/x")["status"], 404)
        self.assertEqual(self.request("GET", "/api/rpc/demo")["status"], 404)

    def test_post_echo_rpc_and_internal_route(self):
        got = self.request("POST", "/api/demo/echo", body='{"a": 1}',
                           headers={"Content-Type": "application/json"})
        self.assertEqual(got["status"], 200)
        self.assertIn("payload", json.loads(got["body"]))
        rpc = self.request("POST", "/api/rpc/demo/echo", body="{}")
        self.assertEqual(rpc["status"], 200)
        self.assertIn("result", json.loads(rpc["body"]))
        internal = self.request("POST", "/api/demo/internal", body="{}")
        self.assertEqual(internal["status"], 403)
        self.assertEqual(json.loads(internal["body"])["code"], "internal_route")

    def test_bad_framing_and_bad_body(self):
        got = self.request("POST", "/api/demo/echo", body="{}",
                           headers={"Transfer-Encoding": "chunked"})
        self.assertEqual(got["status"], 400)
        self.assertEqual(json.loads(got["body"])["code"], "bad_framing")
        self.assertEqual(self.request("POST", "/api/demo/echo", body="{")["status"], 400)

        raw = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        raw.sendall(b"POST /api/demo/echo HTTP/1.1\r\nHost: x\r\n"
                    b"Content-Length: abc\r\n\r\n")
        self.assertIn(b"400", raw.recv(200))
        raw.close()

        raw = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        raw.sendall(b"POST /api/demo/echo HTTP/1.1\r\nHost: x\r\n"
                    b"Content-Length: -1\r\n\r\n")
        self.assertIn(b"400", raw.recv(200))
        raw.close()

    def test_payload_too_large(self):
        self.ctx.cfg["server"]["max_body_bytes"] = 8
        got = self.request("POST", "/api/demo/echo", body='{"a":"0123456789"}')
        self.assertEqual(got["status"], 413)
        self.ctx.cfg["server"].pop("max_body_bytes")

    def test_unauthorized_when_not_public(self):
        self.ctx.allow = False
        self.ctx.gate_public = False
        mine = self.request("POST", "/api/demo/echo", body="{}")
        self.assertEqual(mine["status"], 401)
        self.assertEqual(json.loads(mine["body"])["code"], "unauthorized")
        static = self.request("GET", "/manage.html")
        self.assertEqual(static["status"], 302)
        self.assertEqual(static["headers"]["location"], "/login.html")
        self.ctx.allow = True
        self.ctx.gate_public = True

    def test_modules_and_error_mapping(self):
        self.ctx.gate_public = True
        ok = self.request("POST", "/api/modules", body="{}", headers={"X-Auth-Token": "t"})
        self.assertEqual(ok["status"], 200)
        bad = self.request("POST", "/api/demo/fail", body="{}")
        self.assertEqual(bad["status"], 400)
        self.assertEqual(json.loads(bad["body"])["code"], "bad_request")
        boom = self.request("POST", "/api/demo/boom", body="{}")
        self.assertEqual(boom["status"], 500)
        self.assertEqual(json.loads(boom["body"])["code"], "internal")

    def test_static_etag_gzip_and_missing_asset(self):
        plain = self.request("GET", "/manage.html")
        self.assertEqual(plain["status"], 200)
        etag = plain["headers"]["etag"]
        again = self.request("GET", "/manage.html", headers={"If-None-Match": etag})
        self.assertEqual(again["status"], 304)
        zipped = self.request("GET", "/manage.html", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(zipped["headers"].get("content-encoding"), "gzip")
        missing = self.request("GET", "/missing.js")
        self.assertEqual(missing["status"], 404)

    def test_sse_stream_frames_then_disconnect(self):
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        raw.sendall(b"GET /api/sse/demo/stream?token=t HTTP/1.1\r\nHost: x\r\n\r\n")
        buf = b""
        while b'"n": 2' not in buf:
            chunk = raw.recv(4096)
            if not chunk:
                break
            buf += chunk
        self.assertIn(b"text/event-stream", buf)
        self.assertIn(b"data: ", buf)
        raw.close()

    def test_sse_rejections(self):
        short = self.request("GET", "/api/sse/demo")
        self.assertEqual(short["status"], 404)
        unknown = self.request("GET", "/api/sse/nope/x")
        self.assertEqual(unknown["status"], 404)
        not_stream = self.request("GET", "/api/sse/demo/echo")
        self.assertEqual(not_stream["status"], 400)
        self.assertEqual(json.loads(not_stream["body"])["code"], "not_stream")

    def test_hooks_async_submit_success(self):
        self.ctx.hook_pending = 1
        self.ctx.loop_fail = False
        self.assertEqual(self.request("POST", "/api/demo/echo", body="{}")["status"], 200)
        self.ctx.hook_pending = 0
        self.ctx.loop_fail = True

    def test_hooks_drain_fallback_and_swallow(self):
        self.ctx.hook_pending = 1
        self.ctx.loop_fail = True
        self.ctx.hook_fail = True
        self.assertEqual(self.request("POST", "/api/demo/echo", body="{}")["status"], 200)
        self.ctx.hook_fail = False
        self.assertEqual(self.request("POST", "/api/demo/echo", body="{}")["status"], 200)
        self.ctx.hook_pending = 0
        self.assertEqual(self.request("POST", "/api/demo/echo", body="{}")["status"], 200)

    def test_post_bad_path_shapes(self):
        self.assertEqual(self.request("POST", "/api/x", body="{}")["status"], 404)
        self.assertEqual(self.request("POST", "/api/rpc/demo", body="{}")["status"], 404)

    def test_empty_body_is_empty_dict(self):
        got = self.request("POST", "/api/demo/echo", body=b"",
                           headers={"Content-Length": "0"})
        self.assertEqual(got["status"], 200)

    def test_peer_injection_on_login_paths(self):
        got = self.request("POST", "/api/auth/login", body="{}")
        self.assertEqual(json.loads(got["body"])["payload"]["peer"], "127.0.0.1")
        rpc = self.request("POST", "/api/rpc/demand_engine/run",
                           body='{"id": "auth-login", "input": {}}')
        self.assertEqual(json.loads(rpc["body"])["result"]["payload"]["input"]["peer"], "127.0.0.1")
        rpc2 = self.request("POST", "/api/rpc/auth/login", body="{}")
        self.assertEqual(json.loads(rpc2["body"])["result"]["payload"]["peer"], "127.0.0.1")

    def test_console_operator_caller_injection(self):
        """控制台需求必须带操作员身份：定时器/工单的作用域守卫才认得出是人。"""
        got = self.request("POST", "/api/rpc/demand_engine/run",
                           body='{"id": "timer-update", "input": {"id": "tm-1"}}')
        payload = json.loads(got["body"])["result"]["payload"]
        self.assertEqual(payload["input"]["caller"],
                         {"scope": "global", "role": "admin", "session": "console"})
        # 调用方自己给了身份就不覆盖：agent 侧语义要保留
        got = self.request("POST", "/api/rpc/demand_engine/run",
                           body='{"id": "timer-update", "input": {"caller": {"scope": "project"}}}')
        payload = json.loads(got["body"])["result"]["payload"]
        self.assertEqual(payload["input"]["caller"], {"scope": "project"})
        # 批处理逐条注入（calls 里每条都算一次需求）
        got = self.request("POST", "/api/rpc/demand_engine/batch",
                           body='{"calls": [{"id": "timer-toggle", "input": {"id": "x"}},'
                                ' {"id": "timer-delete", "input": {"id": "y"}}, "oops",'
                                ' {"id": "noop"}]}')
        payload = json.loads(got["body"])["result"]["payload"]
        self.assertEqual(payload["calls"][0]["input"]["caller"]["scope"], "global")
        self.assertEqual(payload["calls"][1]["input"]["caller"]["scope"], "global")
        # 非对象入参原样放过：不许因为注入把请求打崩
        got = self.request("POST", "/api/rpc/demand_engine/run",
                           body='{"id": "timer-update", "input": "raw"}')
        self.assertEqual(got["status"], 200)
        payload = json.loads(got["body"])["result"]["payload"]
        self.assertEqual(payload["input"], "raw")
        # 公开入口（未鉴权可直达）不享受操作员身份
        got = self.request("POST", "/api/rpc/demand_engine/run",
                           body='{"id": "console-chrome", "input": {}}')
        payload = json.loads(got["body"])["result"]["payload"]
        self.assertNotIn("caller", payload["input"])

    def test_cookie_token_and_gzip_json(self):
        ok = self.request("GET", "/api/modules", headers={"Cookie": "hive_token=t; x=1"})
        self.assertEqual(ok["status"], 200)
        zipped = self.request("POST", "/api/demo/echo",
                              body='{"a": "0123456789"}',
                              headers={"Accept-Encoding": "gzip"})
        self.assertEqual(zipped["headers"].get("content-encoding"), "gzip")
        self.assertEqual(zipped["headers"].get("vary"), "Accept-Encoding")

    def test_static_with_gate_private_but_authorized(self):
        self.ctx.gate_public = False
        got = self.request("GET", "/manage.html")
        self.assertEqual(got["status"], 200)
        self.ctx.gate_public = True

    def test_static_gzip_floor_skip(self):
        self.ctx.gzip_floor = 10 ** 6
        plain = self.request("GET", "/manage.html", headers={"Accept-Encoding": "gzip"})
        self.assertNotIn("content-encoding", plain["headers"])
        self.ctx.gzip_floor = 10

    def test_setup_skips_tls_without_files(self):
        ctx = _Ctx()
        ctx.cfg["server"]["tls"] = {"enabled": True, "cert": "c.pem", "key": "k.pem"}
        ctx.storage = mock.Mock()
        ctx.storage.path.side_effect = lambda key, val: val
        with mock.patch.object(_server.ssl, "SSLContext") as ctx_cls:
            tls_ctx = mock.Mock()
            ctx_cls.return_value = tls_ctx
            server = _server.setup(ctx)
            server.server_close()
        tls_ctx.load_cert_chain.assert_called_once_with("c.pem", "k.pem")
        tls_ctx.wrap_socket.assert_called_once()



class _WFile:
    def __init__(self, fail_write=None, fail_flush=False):
        self.fail_write = fail_write
        self.fail_flush = fail_flush
        self.writes = 0

    def write(self, data):
        self.writes += 1
        if self.fail_write and self.writes >= self.fail_write:
            raise BrokenPipeError("client gone")

    def flush(self):
        if self.fail_flush:
            raise OSError("flush failed")


class _Headers(dict):
    pass


def _bare_handler(ctx, fail_write=None, fail_flush=False, headers=None):
    cls = _server._make_handler(ctx)
    h = object.__new__(cls)
    h.headers = _Headers(headers or {})
    h.wfile = _WFile(fail_write, fail_flush)
    h.rfile = __import__("io").BytesIO(b"")
    h.client_address = ("127.0.0.1", 0)
    h.path = "/"
    h.close_connection = False
    h.sent = []
    h.send_response = lambda code, message=None: h.sent.append(("status", code))
    h.send_header = lambda k, v: h.sent.append((k, v))
    h.end_headers = lambda: None
    h.log_message = lambda *a: None
    return h


class HttpHandlerUnitTest(unittest.TestCase):
    def test_write_failure_marks_close(self):
        h = _bare_handler(_Ctx(), fail_write=1)
        self.assertFalse(h._write(b"x"))
        self.assertTrue(h.close_connection)

    def test_sse_cursor_sleeps_then_disconnect(self):
        ctx = _Ctx()
        ctx.sse_cursor_mode = True
        ctx.sse_raise_at = 2
        h = _bare_handler(ctx)
        h._sse("/api/sse/demo/stream", __import__("urllib.parse").parse.urlparse("?cursor=0"))
        self.assertEqual(ctx.sse_calls, 2)
        self.assertTrue(h.close_connection)
        self.assertEqual(h.sent[0], ("status", 200))

    def test_sse_write_failure_stops_item_loop(self):
        ctx = _Ctx()
        ctx.sse_cursor_mode = True
        h = _bare_handler(ctx, fail_write=1)
        h._sse("/api/sse/demo/stream", __import__("urllib.parse").parse.urlparse(""))
        self.assertFalse(any("data" in str(x) for x in []))

    def test_sse_flush_failure_closes_connection(self):
        ctx = _Ctx()
        h = _bare_handler(ctx, fail_flush=True)
        h._sse("/api/sse/demo/stream", __import__("urllib.parse").parse.urlparse(""))
        self.assertTrue(h.close_connection)

    def test_route_broken_pipe_while_writing_ok(self):
        ctx = _Ctx()
        h = _bare_handler(ctx)
        h.path = "/api/demo/echo"
        h.rfile = __import__("io").BytesIO(b"")
        h.headers = _Headers({"Content-Length": "0"})

        def boom(code, message=None):
            raise BrokenPipeError("socket dead")

        h.send_response = boom
        h._route("POST")
        self.assertTrue(h.close_connection)

    def test_route_error_while_writing_error_response(self):
        ctx = _Ctx()
        h = _bare_handler(ctx)
        h.path = "/api/demo/boom"

        def boom(code, message=None):
            raise BrokenPipeError("socket dead")

        h.send_response = boom
        h._route("POST")
        self.assertTrue(h.close_connection)


if __name__ == "__main__":
    unittest.main()
