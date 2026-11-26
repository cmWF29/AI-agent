"""平台小包装配面与协议边角：hooks/runtime/codec/todos/logs/health、帧收发与通道编译。"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent import health, logs, todos
from ai_new.modules.agent_common import codec as codec_pkg
from ai_new.modules.agent_common import hooks as hooks_pkg
from ai_new.modules.agent_common import runtime as runtime_pkg
from ai_new.modules.agent_common.api.private import _gen, _wire


class HooksTest(unittest.TestCase):
    def test_wrappers_delegate(self):
        ctx = mock.Mock()
        ctx.hooks = mock.Mock()
        ctx.hooks.point.return_value = "p"
        ctx.hooks.emit.return_value = [{"ok": True}]
        ctx.hooks.points.return_value = ["a"]
        self.assertEqual(hooks_pkg.point(ctx, "x.y"), "p")
        ctx.hooks.point.assert_called_once_with("x.y", (), defer=False)
        self.assertEqual(hooks_pkg.emit(ctx, "x.y", {"k": 1}), [{"ok": True}])
        self.assertEqual(hooks_pkg.points(ctx), ["a"])

    def test_setup_mounts_and_registers(self):
        reg = mock.Mock()
        ctx = mock.Mock(api=reg, demand_engine=mock.Mock())
        with mock.patch.object(hooks_pkg, "_hooks") as h:
            h.Hooks.return_value.points.return_value = ["p"]
            got = hooks_pkg.setup(ctx)
            ctx.api.register.assert_called_once()
            self.assertIs(got, ctx.hooks)


class RuntimeTest(unittest.TestCase):
    def test_routes(self):
        ctx = mock.Mock()
        ctx.runtime.stream_get.return_value = "draft"
        ctx.runtime.stream_events.return_value = [{"cursor": 1}]
        self.assertEqual(runtime_pkg._route_stream(ctx, None), "draft")
        ctx.runtime.stream_get.assert_called_once_with(None)
        self.assertEqual(runtime_pkg._route_stream_events(ctx, None), [{"cursor": 1}])
        self.assertEqual(runtime_pkg._route_stream_events(ctx, {"key": "k", "cursor": 3}), [{"cursor": 1}])
        ctx.runtime.stream_events.assert_called_with("k", 3)

    def test_setup_registers_four_routes(self):
        reg = mock.Mock()
        ctx = mock.Mock(api=reg)
        with mock.patch.object(runtime_pkg, "_core") as core:
            self.assertTrue(runtime_pkg.setup(ctx))
            self.assertEqual(reg.register.call_count, 4)
            self.assertIs(ctx.runtime, core.Runtime.return_value)


class CodecWrappersTest(unittest.TestCase):
    def test_wrappers(self):
        ctx = mock.Mock()
        self.assertEqual(codec_pkg.json_encode(ctx, {"a": 1})["text"], '{"a": 1}')
        self.assertEqual(codec_pkg.json_decode(ctx, '{"a": 1}'), {"ok": True, "value": {"a": 1}})
        self.assertEqual(codec_pkg.sse_decode(ctx, 'data: {"a": 1}'), {"ok": True, "items": [{"a": 1}]})


class TodosTest(unittest.TestCase):
    def ctx(self, has_todo=False):
        ctx = mock.Mock()
        ctx.tools.has.return_value = has_todo
        ctx.api.call.side_effect = lambda name, payload=None, caller=None: {
            "config.get": {"value": 3},
            "store.read": {"value": {"todo_tool_desc": "d"}},
        }[name]
        return ctx

    def test_setup_skips_register_when_tool_exists(self):
        ctx = self.ctx(has_todo=True)
        self.assertTrue(todos.setup(ctx))
        self.assertEqual(ctx.api.register.call_count, 2)
        ctx.tools.register.assert_not_called()

    def test_setup_registers_tool_once(self):
        ctx = self.ctx(has_todo=False)
        self.assertTrue(todos.setup(ctx))
        ctx.tools.register.assert_called_once()

    def test_apply_with_flat_args(self):
        ctx = self.ctx()
        with mock.patch.object(todos._pure, "apply_ops",
                               return_value={"ok": True, "changed": True, "todos": [1]}):
            out = todos._route_apply(ctx, {"action": "add", "text": "x"})
        self.assertEqual(out["session_patch"], {"todos": [1]})
        self.assertEqual(out["tip"], "")
        self.assertEqual(ctx.api.call.call_args_list[0].args[0], "store.read")

    def test_context(self):
        ctx = self.ctx()
        with mock.patch.object(todos._pure, "context", return_value="sys"):
            self.assertEqual(todos._route_context(ctx, None), "sys")


class LogsTest(unittest.TestCase):
    def test_as_handler_keeps_supplied_tpl(self):
        with mock.patch.object(logs._pure, "group", return_value={"groups": []}) as grp:
            handler = logs._as_handler(logs._pure.group)
            ctx = mock.Mock()
            handler(ctx, {"tpl": {"x": 1}})
        grp.assert_called_once_with({"tpl": {"x": 1}})
        ctx.api.call.assert_not_called()

    def test_as_handler_reads_tpl_when_absent(self):
        with mock.patch.object(logs._pure, "group", return_value={}) as grp:
            handler = logs._as_handler(logs._pure.group)
            ctx = mock.Mock()
            ctx.api.call.return_value = {"value": {"a": 1}}
            handler(ctx, None)
        grp.assert_called_once_with({"tpl": {"a": 1}})


class HealthTest(unittest.TestCase):
    def test_assemble_counts_statuses(self):
        out = health._pure.assemble({"now": 10, "started": 4,
                                     "tickets": {"items": [{"status": "open"}, {"status": "open"}]},
                                     "host": {"total_gb": 2}})
        self.assertEqual(out["uptime"], 6)
        self.assertEqual(out["tickets"]["by_status"], {"open": 2})
        self.assertEqual(out["disk"]["total_mb"], 2048)

    def test_assemble_empty(self):
        out = health._pure.assemble({})
        self.assertEqual(out["tickets"], {"total": 0, "by_status": {}})
        self.assertEqual(out["disk"], {})

    def test_live(self):
        self.assertEqual(health._pure.live({"now": 5, "started": 1})["uptime"], 4)


class StubSock:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []

    def recv(self, n):
        if not self.chunks:
            return b""
        return self.chunks.pop(0)

    def sendall(self, data):
        self.sent.append(data)


class WireTest(unittest.TestCase):
    def test_unpack_fallback(self):
        codec = mock.Mock()
        codec.yaml_decode.return_value = {"value": None}
        self.assertEqual(_wire.unpack(codec, ""), {})
        self.assertEqual(codec.yaml_decode.call_args.args[0], "{}")

    def test_pack_without_token(self):
        codec = mock.Mock()
        codec.yaml_encode_flow.return_value = {"text": "b: 2"}
        self.assertEqual(_wire.pack(codec, "r", None), b"b: 2")
        self.assertEqual(codec.yaml_encode_flow.call_args.args[0]["payload"], {})

    def test_pack_and_send(self):
        codec = mock.Mock()
        codec.yaml_encode_flow.return_value = {"text": "a: 1"}
        sock = StubSock([])
        body = _wire.pack(codec, "r", {"k": 1}, token="t")
        self.assertEqual(body, b"a: 1")
        _wire.send_frame(sock, body)
        self.assertEqual(sock.sent, [struct.pack("!i", 4) + b"a: 1"])

    def test_read_frame_partial_head_then_eof(self):
        self.assertIsNone(_wire.read_frame(StubSock([b"\x00", b""])))

    def test_read_frame_bad_length(self):
        self.assertIsNone(_wire.read_frame(StubSock([struct.pack("!i", 0)])))
        self.assertIsNone(_wire.read_frame(StubSock([struct.pack("!i", _wire.MAX_PAYLOAD + 1)])))

    def test_read_frame_truncated_body(self):
        self.assertIsNone(_wire.read_frame(StubSock([struct.pack("!i", 4), b"ab", b""])))

    def test_read_frame_ok_split(self):
        self.assertEqual(_wire.read_frame(StubSock([struct.pack("!i", 4), b"ab", b"cd"])), b"abcd")


class GenTest(unittest.TestCase):
    def root(self, d):
        root = Path(d) / "root"
        alpha = root / "ai_new" / "modules" / "agent" / "alpha"
        alpha.mkdir(parents=True)
        (alpha / "__init__.py").write_text("")
        return root

    def build(self, d, deploy):
        root = self.root(d)
        f = Path(d) / "deploy.yaml"
        f.write_text(__import__("yaml").safe_dump(deploy))
        return _gen.build(root, f)

    def test_build_default_and_routes(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.build(d, {"modules": {"alpha": {"kind": "direct"}},
                                 "routes": {"alpha.run": {"kind": "unix"}},
                                 "listen": {"unix": {"path": "/tmp/s"}}})
        self.assertEqual(out["default"], {"kind": "direct"})
        self.assertEqual(out["routes"]["alpha.*"], {"kind": "direct"})
        self.assertEqual(out["routes"]["alpha.run"], {"kind": "unix"})

    def test_build_rejections(self):
        cases = [
            ({"routes": {"alpha.run": {"kind": "tcp"}},
              "listen": {"tcp": {}}}, "listen.tcp"),
            ({"routes": {"alpha.run": {"kind": "shm"}},
              "listen": {"shm": {}}}, "listen.shm.dir"),
            ({"routes": {"ghost.run": {"kind": "direct"}}}, "路由不存在"),
            ({"default": "bad"}, "default"),
            ({"modules": {"ghost": {"kind": "direct"}}}, "模块不存在"),
            ({"routes": {"alpha.run": {"kind": "bogus"}}}, "通道非法"),
        ]
        for deploy, needle in cases:
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError) as e:
                    self.build(d, deploy)
            self.assertIn(needle, str(e.exception))


if __name__ == "__main__":
    unittest.main()
