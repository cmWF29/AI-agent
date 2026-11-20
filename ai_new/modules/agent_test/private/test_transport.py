"""通信抽象：生成器 + 通道（直连 / 内存 / 网络）。

代码里只有逻辑调用；走哪条通道由 api 模块编译出的绑定决定。
网络通道的端到端在 test_core 里用真实 HTTP 服务验证，这里测生成器与直连/内存。
"""
import yaml
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.api.private import _gen, _transport  # noqa: E402
from ai_new.modules.agent_common.codec.private import _codec  # noqa: E402


class _Storage:
    def __init__(self, record):
        self.record = record

    def json_read(self, rel, default=None):
        return self.record if self.record is not None else default

    def exists(self, rel):
        return self.record is not None

    def read_text(self, rel):
        return yaml.safe_dump(self.record if self.record is not None else {}, allow_unicode=True, sort_keys=False, default_flow_style=False)

    def own(self, anchor):
        return self


class _Ctx:
    class ApiError(Exception):
        def __init__(self, msg, code="", status=400):
            super().__init__(msg)
            self.code = code
            self.status = status

    def __init__(self, bindings=None):
        self.storage = _Storage(bindings)
        self.cfg = {"server": {"token": ""}}
        self.root = ROOT
        self.codec = _codec


class GeneratorTest(unittest.TestCase):
    def test_compile_transport_writes_binding_file(self):
        """编译是 api 模块的能力：给 ctx 就能产出绑定文件，不需要根目录脚本。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "bindings.yaml"
            record = _gen.compile_transport(_Ctx(), out=out)
            self.assertTrue(out.is_file())
            self.assertEqual(record["default"], "direct")
            self.assertEqual(yaml.safe_load(out.read_text(encoding="utf-8"))["generated_by"],
                             "ai_new/modules/agent_common/api/private/_gen.py")

    def test_is_deterministic(self):
        first = _gen.build(ROOT)
        second = _gen.build(ROOT)
        self.assertEqual(first, second)

    def test_default_is_direct_without_deploy_file(self):
        self.assertEqual(_gen.build(ROOT)["default"]["kind"], "direct")

    def test_deploy_binds_modules_to_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            deploy = Path(tmp) / "deploy.yaml"
            deploy.write_text(yaml.safe_dump({
                "default": "direct",
                "nodes": {"worker": "http://127.0.0.1:8790"},
                "modules": {"ops": {"kind": "http", "node": "worker"},
                            "tickets": {"kind": "memory"}},
            }, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8")
            record = _gen.build(ROOT, deploy)
        self.assertEqual(record["routes"]["ops.*"],
                         {"kind": "http", "base": "http://127.0.0.1:8790"})
        self.assertEqual(record["routes"]["tickets.*"], {"kind": "memory"})

    def test_rejects_unknown_module_and_bad_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            deploy = Path(tmp) / "deploy.yaml"
            for payload in ({"modules": {"nope": {"kind": "direct"}}},
                            {"modules": {"ops": {"kind": "carrier-pigeon"}}}):
                deploy.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    _gen.build(ROOT, deploy)


class TransportTest(unittest.TestCase):
    def test_direct_by_default(self):
        ctx = _Ctx()
        t = _transport.Transport(ctx)
        handler = lambda c, p: {"got": p.get("n")}   # noqa: E731
        self.assertEqual(t.send("ops.record", {"n": 1}, handler), {"got": 1})

    def test_http_channel_speaks_rpc(self):
        """http 通道：POST /api/rpc/<module>/<fn>，带 token，取回未包装的结果。"""
        seen = {}

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                seen["path"] = self.path
                seen["token"] = self.headers.get("X-Auth-Token")
                length = int(self.headers.get("Content-Length") or 0)
                seen["body"] = yaml.safe_load(self.rfile.read(length).decode("utf-8"))
                body = yaml.safe_dump({"ok": True, "result": {"content": "来自远端"}}, allow_unicode=True, sort_keys=False, default_flow_style=True).strip().encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/yaml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        try:
            ctx = _Ctx({"default": {"kind": "direct"},
                        "routes": {"knowledge.*": {"kind": "http",
                                                   "base": "http://127.0.0.1:%d" % port}}})
            ctx.cfg = {"server": {"token": "t"}}
            t = _transport.Transport(ctx)
            result = t.send("knowledge.read", {"name": "x"}, lambda c, p: {"content": "本地"})
            self.assertEqual(result, {"content": "来自远端"})
            self.assertEqual(seen["path"], "/api/rpc/knowledge/read")
            self.assertEqual(seen["token"], "t")
            self.assertEqual(seen["body"], {"name": "x"})
        finally:
            server.shutdown()

    def test_memory_queues_and_delivers_later(self):
        """内存通道是单向的：只认 notify（send 要返回值，必须显式报错）。"""
        ctx = _Ctx({"default": {"kind": "direct"},
                    "routes": {"ops.*": {"kind": "memory"}}})
        t = _transport.Transport(ctx)
        seen = []
        handler = lambda c, p: seen.append(p)   # noqa: E731
        ack = t.notify("ops.record", {"n": 2}, handler)
        self.assertEqual(ack["transport"], "memory")
        with self.assertRaises(ctx.ApiError) as caught:
            t.send("ops.record", {"n": 3}, handler)
        self.assertEqual(getattr(caught.exception, "code", ""), "bad_transport")
        for _ in range(50):
            if seen:
                break
            time.sleep(0.02)
        self.assertEqual(seen[0]["n"], 2)

    def test_notify_on_direct_runs_and_returns_ack(self):
        ctx = _Ctx()
        t = _transport.Transport(ctx)
        seen = []
        ack = t.notify("ops.record", {"n": 4}, lambda c, p: seen.append(p))
        self.assertEqual(ack, {"transport": "direct", "sent": "ops.record"})
        self.assertEqual(seen[0]["n"], 4)

    def test_route_level_binding_overrides_module(self):
        """单条能力可以单独换通道：模块级 module.* 之上再用 routes 精确覆盖。"""
        with tempfile.TemporaryDirectory() as tmp:
            deploy = Path(tmp) / "deploy.yaml"
            deploy.write_text(yaml.safe_dump({
                "default": "direct",
                "nodes": {"w": "http://127.0.0.1:8790"},
                "modules": {"ops": {"kind": "memory"}},
                "routes": {"ops.record": {"kind": "http", "node": "w"},
                           "ops.list": {"kind": "direct"}},
            }, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8")
            record = _gen.build(ROOT, deploy)
        self.assertEqual(record["routes"]["ops.*"], {"kind": "memory"})
        self.assertEqual(record["routes"]["ops.record"],
                         {"kind": "http", "base": "http://127.0.0.1:8790"})
        self.assertEqual(record["routes"]["ops.list"], {"kind": "direct"})

    def test_unknown_channel_is_loud(self):
        ctx = _Ctx({"default": {"kind": "direct"},
                    "routes": {"ops.*": {"kind": "carrier-pigeon"}}})
        t = _transport.Transport(ctx)
        with self.assertRaises(ctx.ApiError):
            t.send("ops.record", {}, lambda c, p: None)


if __name__ == "__main__":
    unittest.main()
