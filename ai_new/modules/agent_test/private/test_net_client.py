"""HTTP 出站：URL/报文归一、状态行、chunked、重试与 SSE 增量。"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.net.private import _client as n  # noqa: E402


class Reader:
    def __init__(self, lines, body=b""):
        self.lines = list(lines)
        self.body = body

    async def readline(self):
        return self.lines.pop(0) if self.lines else b""

    async def readexactly(self, size):
        out, self.body = self.body[:size], self.body[size:]
        return out

    async def read(self):
        out, self.body = self.body, b""
        return out


class ChunkReader:
    """按 HTTP chunk 喂数据：readline 出块长/CRLF，readexactly 出块体。"""
    def __init__(self, lines, chunks):
        self.lines = list(lines)
        self.chunks = list(chunks)

    async def readline(self):
        return self.lines.pop(0) if self.lines else b""

    async def readexactly(self, size):
        data = self.chunks.pop(0)
        if len(data) != size:
            raise IOError("chunk size mismatch")
        return data


class Writer:
    def __init__(self, close_error=None):
        self.data = b""
        self.close_error = close_error
        self.closed = False

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error

    async def wait_closed(self):
        pass


class Api:
    def __init__(self, config=0, decode=None):
        self.config = config
        self.decode = decode or (lambda text: {"ok": True, "value": {"choices": []}})
        self.calls = []

    def call(self, name, payload, caller=None):
        self.calls.append((name, payload, caller))
        if name == "config.get":
            return {"value": self.config}
        return self.decode(payload["text"])


class Runtime:
    def __init__(self):
        self.parts = []

    def stream_put(self, key, piece):
        self.parts.append((key, piece))


class Ctx:
    def __init__(self):
        self.api = Api()
        self.runtime = Runtime()


class NetClientTest(unittest.TestCase):
    def test_helpers(self):
        asyncio.run(n._backoff(0))
        with mock.patch.object(n.asyncio, "open_connection", mock.AsyncMock(return_value=("r", "w"))):
            self.assertEqual(asyncio.run(n._open("https", "h", 443, 1)), ("r", "w"))
            self.assertEqual(asyncio.run(n._open("http", "h", 80, 1)), ("r", "w"))
        self.assertTrue(n._retryable("unreachable", None))
        self.assertTrue(n._retryable("x", "500"))
        self.assertFalse(n._retryable("x", "bad"))
        self.assertFalse(n._retryable("x", None))
        self.assertEqual(n._split_url("https://h/a?b=1"), ("https", "h", 443, "/a?b=1"))
        self.assertEqual(n._split_url("http://h"), ("http", "h", 80, "/"))
        self.assertEqual(n._raw_body(None), b"")
        self.assertEqual(n._raw_body(bytearray(b"x")), b"x")
        self.assertEqual(n._raw_body("x"), b"x")
        head = n._build_request("GET", "h", "/", {"A": "1"}, None)
        self.assertIn(b"Host: h", head)
        self.assertNotIn(b"Content-Length", head)
        head = n._build_request("POST", "h", "/", None, b"x")
        self.assertIn(b"Content-Length: 1", head)

    def test_status_and_body(self):
        r = Reader([b""])
        with self.assertRaises(IOError):
            asyncio.run(n._read_status(r))
        r = Reader([b"HTTP/1.1\n", b"X: y\r\n", b"\r\n"])
        self.assertEqual(asyncio.run(n._read_status(r)), (0, {"x": "y"}))
        self.assertEqual(asyncio.run(n._read_body(Reader([], b"abc"),
                                                  {"transfer-encoding": "chunked"})), b"")
        self.assertEqual(asyncio.run(n._read_body(Reader([], b"abc"), {})), b"abc")
        self.assertEqual(asyncio.run(n._read_body(Reader([], b"abc"),
                                                  {"content-length": "3"})), b"abc")
        r = Reader([b"HTTP/1.1 200\n", b"A: b\r\n", b"\n", b"3\r\n", b"abc"])
        self.assertEqual(asyncio.run(n._read_chunked(r)), b"")
        r = Reader([b"3\r\n", b"x", b"\r\n"], b"abc")
        r.lines.append(b"0\r\n")
        self.assertEqual(asyncio.run(n._read_chunked(r)), b"abc")

    def test_arequest_validation_and_success(self):
        ctx = Ctx()
        self.assertEqual(asyncio.run(n.arequest(ctx, "")), {"ok": False, "error": "缺少 url", "code": "bad_request"})
        self.assertEqual(asyncio.run(n.arequest(ctx, "http://h", body={}))["code"], "bad_body")
        self.assertEqual(asyncio.run(n.arequest(ctx, "http:///x"))["code"], "bad_request")
        writer = Writer()
        reader = Reader([], b"ok")
        with mock.patch.object(n, "_open", mock.AsyncMock(return_value=(reader, writer))), \
                mock.patch.object(n, "_read_status", mock.AsyncMock(return_value=(200, {}))):
            out = asyncio.run(n.arequest(ctx, "http://h/x", body=b"b"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["text"], "ok")
        self.assertTrue(writer.closed)

    def test_arequest_retry_and_close_error(self):
        ctx = Ctx()
        writer = Writer(close_error=ValueError("x"))
        reader = Reader([], b"ok")
        calls = [OSError("no"), (reader, writer)]

        async def open_(*a):
            item = calls.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch.object(n, "_open", side_effect=open_), \
                mock.patch.object(n.asyncio, "sleep", mock.AsyncMock()), \
                mock.patch.object(n, "_read_status", mock.AsyncMock(return_value=(200, {}))):
            out = asyncio.run(n.arequest(ctx, "http://h", retries=1))
        self.assertTrue(out["ok"])
        with mock.patch.object(n, "_open", mock.AsyncMock(side_effect=OSError("no"))), \
                mock.patch.object(n.asyncio, "sleep", mock.AsyncMock()):
            out = asyncio.run(n.arequest(ctx, "http://h", retries=0))
        self.assertEqual(out["code"], "unreachable")

    def test_stream(self):
        ctx = Ctx()
        ctx.api = Api(config=2, decode=lambda text: {"ok": True, "value": {"choices": [{"delta": {"content": "x"}}]}})
        self.assertEqual(asyncio.run(n.arequest_stream(ctx, "")), {"ok": False, "error": "缺少 url", "code": "bad_request"})
        self.assertEqual(asyncio.run(n.arequest_stream(ctx, "http://h", body=1))["code"], "bad_body")
        self.assertEqual(asyncio.run(n.arequest_stream(ctx, "http:///x"))["code"], "bad_request")
        lines = [b"data: {}\n", b"\n", b": comment\n", b"data: [DONE]\n", b""]
        writer = Writer()
        with mock.patch.object(n, "_open", mock.AsyncMock(return_value=(Reader(lines), writer))), \
                mock.patch.object(n, "_read_status", mock.AsyncMock(return_value=(200, {}))):
            out = asyncio.run(n.arequest_stream(ctx, "http://h", stream_key="k"))
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["items"]), 1)
        self.assertEqual(ctx.runtime.parts, [("k", "x")])
        self.assertEqual(out["raw"], "data: {}")
        ctx.api = Api(config=0, decode=lambda text: {"ok": True, "value": []})
        pair = (Reader([b"data: []\n", b""]), Writer(close_error=ValueError("x")))
        with mock.patch.object(n, "_open", mock.AsyncMock(return_value=pair)), \
                mock.patch.object(n, "_read_status",
                                  mock.AsyncMock(return_value=(200, {}))):
            out = asyncio.run(n.arequest_stream(ctx, "http://h"))
        self.assertEqual(out["items"], [])
        now = {"choices": [{"delta": {"content": "y"}}]}
        ctx.api = Api(config=0, decode=lambda text: {"ok": True, "value": now})
        pair = (Reader([b"data: {}\n", b""]), Writer())
        with mock.patch.object(n, "_open", mock.AsyncMock(return_value=pair)), \
                mock.patch.object(n, "_read_status",
                                  mock.AsyncMock(return_value=(200, {}))):
            out = asyncio.run(n.arequest_stream(ctx, "http://h"))
        self.assertEqual(out["items"][0]["choices"][0]["delta"]["content"], "y")

    def test_stream_chunked_boundary(self):
        c1 = b'data: {"choices": '
        c2 = b'[{"delta": {}}]}\n'
        r = ChunkReader([
            ("%x\r\n" % len(c1)).encode(), b"\r\n",
            ("%x\r\n" % len(c2)).encode(), b"\r\n", b"0\r\n"], [c1, c2])

        async def collect():
            return [x async for x in n._iter_stream_lines(
                r, {"transfer-encoding": "chunked"}, 1)]

        self.assertEqual(asyncio.run(collect()), [c1 + c2])
        # 尾部没有换行也必须吐出，不能把最后一截丢掉。
        r = ChunkReader([b"2\r\n", b"\r\n", b"0\r\n"], [b"ab"])
        self.assertEqual(asyncio.run(collect()), [b"ab"])
        # 坏块长：停止读取，不把后续当正文。
        r = ChunkReader([b"zz\r\n"], [])
        self.assertEqual(asyncio.run(collect()), [])

    def test_stream_bad_json_and_retry(self):
        ctx = Ctx()
        ctx.api = Api(config=0, decode=lambda text: {"ok": False})
        lines = [b"data: bad\n", b""]
        with mock.patch.object(n, "_open", mock.AsyncMock(return_value=(Reader(lines), Writer()))), \
                mock.patch.object(n, "_read_status", mock.AsyncMock(return_value=(200, {}))):
            out = asyncio.run(n.arequest_stream(ctx, "http://h"))
        self.assertEqual(out["items"], [])
        calls = [OSError("no"), (Reader([], b""), Writer())]

        async def open_(*a):
            item = calls.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch.object(n, "_open", side_effect=open_), \
                mock.patch.object(n.asyncio, "sleep", mock.AsyncMock()), \
                mock.patch.object(n, "_read_status", mock.AsyncMock(return_value=(200, {}))):
            out = asyncio.run(n.arequest_stream(ctx, "http://h", retries=1))
        self.assertTrue(out["ok"])

    def test_stream_retry_is_suppressed_after_connect(self):
        ctx = Ctx()

        class Boom(Reader):
            async def readline(self):
                raise OSError("mid stream")

        with mock.patch.object(n, "_open", mock.AsyncMock(return_value=(Boom([]), Writer()))), \
                mock.patch.object(n, "_read_status", mock.AsyncMock(return_value=(200, {}))):
            out = asyncio.run(n.arequest_stream(ctx, "http://h", retries=2))
        self.assertEqual(out["code"], "unreachable")

    def test_sync_wrappers(self):
        ctx = Ctx()

        class Fut:
            def result(self):
                return "ok"

        loop = object()
        def consume(coro, *a):
            coro.close()
            return Fut()

        with mock.patch.object(n.asyncio, "run_coroutine_threadsafe", side_effect=consume) as run, \
                mock.patch.object(ctx, "api", Api()):
            ctx.api._ensure_loop = lambda: loop
            self.assertEqual(n.request(ctx, "http://h"), "ok")
            self.assertEqual(n.request_stream(ctx, "http://h"), "ok")
            self.assertEqual(run.call_count, 2)


    def test_stream_http_error_body_read_not_sse(self):
        """4xx 的 JSON 错误体不是 SSE：整段读出返回失败，不能当空流回成功。"""
        ctx = Ctx()
        body = b'{"error": {"code": "context_length_exceeded"}}'
        pair = (Reader([], body), Writer())
        with mock.patch.object(n, "_open", mock.AsyncMock(return_value=pair)), \
                mock.patch.object(n, "_read_status",
                                  mock.AsyncMock(return_value=(400, {"content-length": str(len(body))}))):
            out = asyncio.run(n.arequest_stream(ctx, "http://h"))
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "http_400")
        self.assertEqual(out["status"], 400)
        self.assertIn("context_length_exceeded", out["error"])

    def test_stream_5xx_retried_then_recovers(self):
        ctx = Ctx()
        statuses = [(500, {}), (200, {})]

        async def status(_reader):
            return statuses.pop(0)

        bodies = [(Reader([], b"boom"), Writer()), (Reader([b"data: {}\n", b""]), Writer())]

        async def open_(*a):
            return bodies.pop(0)

        with mock.patch.object(n, "_open", side_effect=open_), \
                mock.patch.object(n, "_read_status", side_effect=status), \
                mock.patch.object(n.asyncio, "sleep", mock.AsyncMock()):
            out = asyncio.run(n.arequest_stream(ctx, "http://h", retries=1))
        self.assertTrue(out["ok"])

    def test_stream_5xx_exhausted_returns_http_code(self):
        ctx = Ctx()
        pair = (Reader([], b"boom"), Writer())
        with mock.patch.object(n, "_open", mock.AsyncMock(return_value=pair)), \
                mock.patch.object(n, "_read_status", mock.AsyncMock(return_value=(503, {}))):
            out = asyncio.run(n.arequest_stream(ctx, "http://h", retries=0))
        self.assertEqual(out["code"], "http_503")

    def test_status_read_timeout_is_bounded(self):
        """上游只连不答：状态行读取必须有总时限，否则整轮永久挂住。"""
        ctx = Ctx()

        async def silent(_reader):
            await asyncio.sleep(0)
            raise asyncio.TimeoutError()

        with mock.patch.object(n, "_open", mock.AsyncMock(return_value=(Reader([]), Writer()))), \
                mock.patch.object(n, "_read_status", side_effect=silent), \
                mock.patch.object(n.asyncio, "sleep", mock.AsyncMock()):
            out = asyncio.run(n.arequest_stream(ctx, "http://h", timeout=0.2, retries=0))
        self.assertEqual(out["code"], "unreachable")
        self.assertEqual(out["error"], "读写超时")

    def test_error_text(self):
        self.assertEqual(n._err_text(asyncio.TimeoutError()), "读写超时")
        self.assertEqual(n._err_text(ValueError("x")), "x")
        self.assertEqual(n._err_text(Exception()), "Exception")

class NetRoutesTest(unittest.TestCase):
    def test_setup_and_routes(self):
        from ai_new.modules.agent_common import net
        registered = {}

        class Reg:
            def register(self, name, fn, desc=None, module=None):
                registered[name] = fn

        ctx = Ctx()
        ctx.api = Reg()
        self.assertTrue(net.setup(ctx))
        self.assertEqual(sorted(registered), ["net.request", "net.request_stream"])
        with mock.patch.object(n, "arequest", mock.AsyncMock(return_value={"ok": True})) as areq, \
                mock.patch.object(n, "arequest_stream", mock.AsyncMock(return_value={"ok": True})) as astream:
            self.assertTrue(asyncio.run(registered["net.request"](ctx, {"url": "u"}))["ok"])
            self.assertEqual(areq.call_args.kwargs["method"], "GET")
            self.assertEqual(areq.call_args.kwargs["headers"], {})
            self.assertTrue(asyncio.run(registered["net.request_stream"](ctx, {"url": "u"}))["ok"])
            self.assertEqual(astream.call_args.kwargs["method"], "POST")
            self.assertEqual(astream.call_args.kwargs["stream_key"], "")

    def test_module_wrappers_delegate(self):
        from ai_new.modules.agent_common import net
        ctx = Ctx()
        with mock.patch.object(n, "request", mock.Mock(return_value="r")) as req, \
                mock.patch.object(n, "request_stream", mock.Mock(return_value="s")) as stream:
            self.assertEqual(net.request(ctx, "u", method="POST"), "r")
            self.assertEqual(req.call_args.kwargs["method"], "POST")
            self.assertEqual(net.request_stream(ctx, "u"), "s")
            self.assertEqual(stream.call_args.kwargs["stream_key"], "")


if __name__ == "__main__":
    unittest.main()
