"""API 模块装配面：监听起停、拓扑重编、快照与注册/调用/契约包装。"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common import api as api_mod  # noqa: E402


class _Transport:
    def __init__(self):
        self.reloads = 0
        self.bindings_v = {"listen": {"kind": "unix"}}

    def bindings(self):
        return self.bindings_v

    def describe(self):
        return {"channels": 1}

    def reload(self):
        self.reloads += 1


class _FakeApi:
    def __init__(self, ctx):
        self.ctx = ctx
        self.transport = _Transport()
        self.registered = []
        self.calls = []
        self.server = None

    def register(self, name, fn, doc="", module=None, stream=False, internal=False):
        self.registered.append(name)
        return True

    def call(self, name, payload=None, caller=None):
        self.calls.append(("call", name))
        return {"ok": True, "name": name}

    def notify(self, name, payload=None, caller=None):
        self.calls.append(("notify", name))
        return True

    def routes(self):
        return [{"name": "a.b", "in": [], "out": []}]

    def contract(self, name):
        return {"name": name}

    def _load_contracts(self):
        return {"a.b": {"in": []}}


class _Server:
    def __init__(self, ctx):
        self.ctx = ctx
        self.started = False
        self.stopped = False

    def start(self, listen, kinds):
        self.started = True
        return [{"kind": k} for k in kinds]

    def stop(self):
        self.stopped = True


class ApiRoutesTest(unittest.TestCase):
    def setUp(self):
        self.ctx = mock.Mock()
        self.ctx.api = None
        self.fake = _FakeApi(self.ctx)
        self.p_reg = mock.patch.object(api_mod._registry, "Registry", lambda ctx: self.fake)
        self.p_reg.start()
        self.addCleanup(self.p_reg.stop)
        self.addCleanup(setattr, api_mod, "_STARTED", False)
        api_mod.setup(self.ctx)

    def test_setup_assigns_api_and_registers_routes(self):
        self.fake.registered.clear()
        got = api_mod.setup(self.ctx)
        self.assertIs(got, self.fake)
        self.assertTrue(issubclass(self.ctx.ApiError, Exception))
        self.assertEqual(self.fake.registered, ["api.snapshot", "api.transport_compile"])

    def test_open_listen_skips_when_no_kinds(self):
        with mock.patch.object(api_mod._serve, "kinds_in", return_value=[]):
            self.assertEqual(api_mod._open_listen(self.ctx), [])

    def test_open_listen_starts_server_and_registers_stop(self):
        with mock.patch.object(api_mod._serve, "kinds_in", return_value=["unix"]):
            with mock.patch.object(api_mod._serve, "Server", _Server):
                with mock.patch.object(api_mod.atexit, "register") as reg:
                    started = api_mod._open_listen(self.ctx)
        self.assertEqual(started, [{"kind": "unix"}])
        self.assertIsInstance(self.ctx.api.server, _Server)
        reg.assert_called_once()

    def test_restart_listen_stops_previous_server(self):
        old = _Server(self.ctx)
        self.ctx.api.server = old
        with mock.patch.object(api_mod, "_open_listen", return_value=["x"]):
            self.assertEqual(api_mod._restart_listen(self.ctx), ["x"])
        self.assertTrue(old.stopped)
        self.assertIsNone(self.ctx.api.server)

    def test_start_marks_started(self):
        with mock.patch.object(api_mod, "_open_listen", return_value=[]):
            api_mod.start(self.ctx)
        self.assertTrue(api_mod._STARTED)

    def test_snapshot_and_compile_route(self):
        snap = api_mod._route_snapshot(self.ctx, {})
        self.assertEqual(snap["routes"], 1)
        self.assertEqual(snap["transport"], {"channels": 1})
        with mock.patch.object(api_mod, "compile_transport", return_value={"ok": 1}) as cp:
            self.assertEqual(api_mod._route_compile(self.ctx, {"out": "x"}), {"ok": 1})
        cp.assert_called_once_with(self.ctx, out="x", deploy=None)

    def test_compile_transport_reloads_and_restarts_listen(self):
        with mock.patch.object(api_mod._gen, "compile_transport", return_value={"ok": True}):
            with mock.patch.object(api_mod, "_restart_listen", return_value=["y"]):
                api_mod._STARTED = True
                record = api_mod.compile_transport(self.ctx)
        self.assertEqual(record["listen"], ["y"])
        self.assertEqual(self.ctx.api.transport.reloads, 1)

    def test_compile_transport_skips_when_api_missing(self):
        bare = mock.Mock()
        bare.api = None
        with mock.patch.object(api_mod._gen, "compile_transport", return_value={"ok": True}):
            self.assertEqual(api_mod.compile_transport(bare), {"ok": True})

    def test_restart_listen_without_previous_server(self):
        self.ctx.api.server = None
        with mock.patch.object(api_mod, "_open_listen", return_value=[]):
            self.assertEqual(api_mod._restart_listen(self.ctx), [])

    def test_compile_transport_without_started_skips_restart(self):
        api_mod._STARTED = False
        with mock.patch.object(api_mod._gen, "compile_transport", return_value={"ok": True}):
            with mock.patch.object(api_mod, "_restart_listen") as restart:
                record = api_mod.compile_transport(self.ctx)
        self.assertNotIn("listen", record)
        restart.assert_not_called()

    def test_module_level_wrappers(self):
        self.assertTrue(api_mod.register(self.ctx, "a.b", lambda c, p: None))
        self.assertEqual(api_mod.call(self.ctx, "a.b")["name"], "a.b")
        self.assertTrue(api_mod.notify(self.ctx, "a.b"))
        self.assertEqual(len(api_mod.routes(self.ctx)), 1)
        self.assertEqual(api_mod.contract(self.ctx, "a.b"), {"name": "a.b"})
        self.assertEqual(api_mod.contract(self.ctx), {"a.b": {"in": []}})
        self.assertEqual(api_mod.transport(self.ctx), {"channels": 1})


if __name__ == "__main__":
    unittest.main()
