"""通信抽象：通道（直连 / 本地 socket / 网络 socket / 共享内存）+ 绑定编译。

代码里只有逻辑调用；走哪条通道由 api 模块编译出的绑定决定。
这里用真实监听验证三条跨进程通道的往返，不再用假 socket。
"""
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.api.private import _gen, _serve, _transport  # noqa: E402
from ai_new.modules.agent_common.codec.private import _codec  # noqa: E402


class _Storage:
    def __init__(self, record):
        self.record = record

    def json_read(self, rel, default=None):
        return self.record if self.record is not None else default

    def exists(self, rel):
        return self.record is not None

    def read_text(self, rel):
        return yaml.safe_dump(self.record if self.record is not None else {}, allow_unicode=True,
                              sort_keys=False, default_flow_style=False)

    def own(self, anchor):
        return self


class _Api:
    """最小 api：只有注册表和 call，够通道服务端转调。"""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []

    def call(self, name, payload=None, caller=None, direct=False):
        self.calls.append(name)
        fn = self.routes.get(name)
        if fn is None:
            raise LookupError("路由未注册: %s" % name)
        return fn(payload or {})


class _Ctx:
    class ApiError(Exception):
        def __init__(self, msg, code="", status=400):
            super().__init__(msg)
            self.code = code
            self.status = status

    def __init__(self, bindings=None):
        self.storage = _Storage(bindings)
        self.cfg = {"server": {"token": ""}, "api": {"transport_timeout": 3}}
        self.root = ROOT
        self.codec = _codec
        self.api = _Api()


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


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
                "listen": {"unix": {"path": str(Path(tmp) / "a.sock")},
                           "tcp": {"host": "127.0.0.1", "port": 8790},
                           "shm": {"dir": str(Path(tmp) / "shm")}},
                "modules": {"ops": {"kind": "unix"},
                            "tickets": {"kind": "shm"},
                            "knowledge": {"kind": "tcp"}},
            }, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8")
            record = _gen.build(ROOT, deploy)
        self.assertEqual(record["routes"]["ops.*"], {"kind": "unix"})
        self.assertEqual(record["routes"]["tickets.*"], {"kind": "shm"})
        self.assertEqual(record["routes"]["knowledge.*"], {"kind": "tcp"})
        self.assertEqual(record["listen"]["tcp"]["port"], 8790)

    def test_rejects_unknown_module_and_bad_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            deploy = Path(tmp) / "deploy.yaml"
            for payload in ({"modules": {"nope": {"kind": "direct"}}},
                            {"modules": {"ops": {"kind": "carrier-pigeon"}}}):
                deploy.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False,
                                                 default_flow_style=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    _gen.build(ROOT, deploy)

    def test_channel_without_listen_is_loud(self):
        """绑了跨进程通道却没给监听入口：编译就报错，不许静默退回直连。"""
        with tempfile.TemporaryDirectory() as tmp:
            deploy = Path(tmp) / "deploy.yaml"
            deploy.write_text(yaml.safe_dump({"modules": {"ops": {"kind": "unix"}}},
                                             allow_unicode=True, sort_keys=False,
                                             default_flow_style=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                _gen.build(ROOT, deploy)


class TransportTest(unittest.TestCase):
    def test_direct_by_default(self):
        ctx = _Ctx()
        t = _transport.Transport(ctx)
        handler = lambda c, p: {"got": p.get("n")}   # noqa: E731
        self.assertEqual(t.send("ops.record", {"n": 1}, handler), {"got": 1})

    def test_notify_on_direct_runs_and_returns_ack(self):
        ctx = _Ctx()
        t = _transport.Transport(ctx)
        seen = []
        ack = t.notify("ops.record", {"n": 4}, lambda c, p: seen.append(p))
        self.assertEqual(ack, {"transport": "direct", "sent": "ops.record"})
        self.assertEqual(seen[0]["n"], 4)

    # ---- 三条本机 IPC 通道：真实监听，同步往返 ----
    def test_unix_socket_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "api.sock")
            server_ctx = _Ctx()
            server_ctx.api.routes = {"ops.ping": lambda p: {"pong": p.get("n"), "via": "unix"}}
            server = _serve.Server(server_ctx)
            server.start({"unix": {"path": path}}, {"unix"})
            try:
                client = _transport.Transport(_Ctx(
                    {"default": {"kind": "unix"},
                     "listen": {"unix": {"path": path}},
                     "routes": {"ops.*": {"kind": "unix"}}}))
                self.assertEqual(client.send("ops.ping", {"n": 7}, lambda c, p: {"local": 1}),
                                 {"pong": 7, "via": "unix"})
                self.assertEqual(server_ctx.api.calls, ["ops.ping"])
            finally:
                server.stop()

    def test_tcp_socket_roundtrip(self):
        port = _free_port()
        server_ctx = _Ctx()
        server_ctx.api.routes = {"ops.ping": lambda p: {"pong": p.get("n"), "via": "tcp"}}
        server = _serve.Server(server_ctx)
        server.start({"tcp": {"host": "127.0.0.1", "port": port}}, {"tcp"})
        try:
            client = _transport.Transport(_Ctx(
                {"default": {"kind": "direct"},
                 "listen": {"tcp": {"host": "127.0.0.1", "port": port}},
                 "routes": {"ops.*": {"kind": "tcp"}}}))
            self.assertEqual(client.send("ops.ping", {"n": 9}, lambda c, p: {"local": 1}),
                             {"pong": 9, "via": "tcp"})
        finally:
            server.stop()

    def test_shared_memory_roundtrip(self):
        """共享内存信箱：请求/应答两个 mmap 文件 + flock，不走 socket。"""
        with tempfile.TemporaryDirectory() as tmp:
            directory = str(Path(tmp) / "shm")
            server_ctx = _Ctx()
            server_ctx.api.routes = {"ops.ping": lambda p: {"pong": p.get("n"), "via": "shm"}}
            server = _serve.Server(server_ctx)
            server.start({"shm": {"dir": directory}}, {"shm"})
            try:
                client = _transport.Transport(_Ctx(
                    {"default": {"kind": "direct"},
                     "listen": {"shm": {"dir": directory}},
                     "routes": {"ops.*": {"kind": "shm"}}}))
                self.assertEqual(client.send("ops.ping", {"n": 11}, lambda c, p: {"local": 1}),
                                 {"pong": 11, "via": "shm"})
                self.assertTrue((Path(directory) / "req.bin").is_file())
            finally:
                server.stop()

    def test_notify_over_socket_does_not_wait_for_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "api.sock")
            server_ctx = _Ctx()
            server_ctx.api.routes = {"ops.record": lambda p: {"stored": p.get("n")}}
            server = _serve.Server(server_ctx)
            server.start({"unix": {"path": path}}, {"unix"})
            try:
                client = _transport.Transport(_Ctx(
                    {"default": {"kind": "unix"},
                     "listen": {"unix": {"path": path}},
                     "routes": {}}))
                ack = client.notify("ops.record", {"n": 12}, lambda c, p: None)
                self.assertEqual(ack, {"transport": "unix", "sent": "ops.record"})
                for _ in range(100):
                    if server_ctx.api.calls:
                        break
                    time.sleep(0.01)
                self.assertEqual(server_ctx.api.calls, ["ops.record"])
            finally:
                server.stop()

    def test_remote_error_is_raised_verbatim(self):
        """远端拒绝（缺字段/不识路由）不打成假成功：原样带 code 回来。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "api.sock")
            server_ctx = _Ctx()
            server_ctx.api.routes = {"ops.ping": lambda p: (_ for _ in ()).throw(
                server_ctx.ApiError("缺 n", code="bad_payload", status=400))}
            server = _serve.Server(server_ctx)
            server.start({"unix": {"path": path}}, {"unix"})
            try:
                client_ctx = _Ctx({"default": {"kind": "unix"},
                                   "listen": {"unix": {"path": path}}})
                client = _transport.Transport(client_ctx)
                with self.assertRaises(client_ctx.ApiError) as caught:
                    client.send("ops.ping", {}, lambda c, p: None)
                self.assertEqual(caught.exception.code, "bad_payload")
            finally:
                server.stop()

    def test_missing_listen_is_loud(self):
        ctx = _Ctx({"default": {"kind": "direct"},
                    "routes": {"ops.*": {"kind": "shm"}}})
        with self.assertRaises(ctx.ApiError):
            _transport.Transport(ctx).send("ops.record", {}, lambda c, p: None)

    def test_unknown_channel_is_loud(self):
        ctx = _Ctx({"default": {"kind": "direct"},
                    "routes": {"ops.*": {"kind": "carrier-pigeon"}}})
        t = _transport.Transport(ctx)
        with self.assertRaises(ctx.ApiError):
            t.send("ops.record", {}, lambda c, p: None)


class BindingTest(unittest.TestCase):
    def test_route_level_binding_overrides_module(self):
        """单条能力可以单独换通道：模块级 module.* 之上再用 routes 精确覆盖。"""
        with tempfile.TemporaryDirectory() as tmp:
            deploy = Path(tmp) / "deploy.yaml"
            deploy.write_text(yaml.safe_dump({
                "default": "direct",
                "listen": {"unix": {"path": str(Path(tmp) / "a.sock")},
                           "tcp": {"host": "127.0.0.1", "port": 8790},
                           "shm": {"dir": str(Path(tmp) / "shm")}},
                "modules": {"ops": {"kind": "shm"}},
                "routes": {"ops.record": {"kind": "tcp"},
                           "ops.list": {"kind": "direct"}},
            }, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8")
            record = _gen.build(ROOT, deploy)
        self.assertEqual(record["routes"]["ops.*"], {"kind": "shm"})
        self.assertEqual(record["routes"]["ops.record"], {"kind": "tcp"})
        self.assertEqual(record["routes"]["ops.list"], {"kind": "direct"})


if __name__ == "__main__":
    unittest.main()


class FrameLineTest(unittest.TestCase):
    """SSE 每帧只认 `data:` 首行：长值折行会把帧截断，前端永远收不到。"""

    def test_flow_frame_is_single_line_and_roundtrips(self):
        payload = {"text": "x" * 300, "running": True}
        out = _codec.yaml_encode_flow(payload)
        self.assertTrue(out["ok"])
        self.assertNotIn("\n", out["text"], "帧文本必须单行，否则 SSE 只送出前半截")
        self.assertEqual(yaml.safe_load(out["text"]), payload)

    def test_long_json_text_roundtrips(self):
        inner = _codec.json_encode({"seq": 1, "items": [{"demand": "ticket-create",
                                                        "items": [{"view": "project", "as": "tickets"}]}] * 6})
        out = _codec.yaml_encode_flow({"text": inner["text"], "running": True, "at": 1.0})
        self.assertNotIn("\n", out["text"])
        self.assertEqual(yaml.safe_load(out["text"])["text"], inner["text"])
