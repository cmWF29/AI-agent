"""组合根：profile/demands 路径、DAG 装配两段、cycle 拒绝、编译绑定与常驻收尾。"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.boot.private import _boot as b  # noqa: E402


class Mod:
    def __init__(self):
        self.setups = 0
        self.starts = 0

    def setup(self, ctx):
        self.setups += 1

    def start(self, ctx):
        self.starts += 1


class Ctx:
    def __init__(self):
        self.loaded = {}


class BootTest(unittest.TestCase):
    def test_profile_and_demands(self):
        with mock.patch.dict(b.os.environ, {"AI_NEW_DATA": "/tmp/x"}):
            self.assertEqual(b._profile()[0].name, "agent_common")
            self.assertEqual(b._demands_dir().as_posix(), "/tmp/x/agent_common/demand_engine")
        with mock.patch.object(b.Path, "is_file", return_value=True), \
                mock.patch.object(b.Path, "read_text",
                                  return_value="profiles:\n  agent: [agent]"):
            self.assertEqual([p.name for p in b._profile()], ["agent"])

    def test_plan(self):
        with mock.patch.object(b, "_profile", return_value=["d"]), \
                mock.patch.object(b, "_demands_dir", return_value="x"), \
                mock.patch.object(b, "_scan", return_value={"ok": True}) as scan:
            self.assertEqual(b._plan(), {"ok": True})
            scan.assert_called_once_with(["d"], data_dir="x")

    def test_build(self):
        ctx = Ctx()
        plan = {"cycle": None, "packages": {"a": "ma", "b": "mb"},
                "order": ["a", "b"]}
        mods = {"ma": Mod(), "mb": Mod()}

        def imp(name):
            m = mods[name]
            m._name = name
            return m

        with mock.patch.object(b, "_plan", return_value=plan), \
                mock.patch.object(b.importlib, "import_module", side_effect=imp):
            self.assertEqual(b._build(ctx), ["a", "b"])
            self.assertEqual(len(ctx.loaded), 2)
            self.assertEqual(mods["ma"].starts, 1)
            ctx.loaded.clear()
            mods["ma"].setups = mods["ma"].starts = mods["mb"].starts = 0
            self.assertEqual(b._build(ctx, start_phase=False), ["a", "b"])
            self.assertEqual(mods["ma"].starts, 0)
        plan["cycle"] = ["a", "b"]
        with mock.patch.object(b, "_plan", return_value=plan):
            with self.assertRaises(RuntimeError):
                b._build(ctx)
        plan["cycle"] = None
        api = mock.Mock()
        ctx.loaded["api"] = api
        with mock.patch.object(b, "_plan", return_value={"cycle": None,
                                                         "packages": {"api": "mapi"},
                                                         "order": ["api"]}), \
                mock.patch.object(b.importlib, "import_module", return_value=api):
            b._build(ctx, start_phase=False)
        api.compile_transport.assert_called_once()
        ctx.loaded = {"plain": mock.Mock(start=None)}
        with mock.patch.object(b, "_plan", return_value={"cycle": None,
                                                         "packages": {"p": "mp"},
                                                         "order": ["p"]}), \
                mock.patch.object(b.importlib, "import_module",
                                  return_value=mock.Mock(start=None)):
            self.assertEqual(b._build(ctx), ["p"])

    def test_main_compile_and_fail(self):
        record = {"path": "p", "default": "direct", "routes": {}, "stats": {
            "modules": 1, "route_literals": 2}}
        api = mock.Mock()
        api.compile_transport.return_value = record
        with mock.patch.object(b, "Context", return_value=mock.Mock()), \
                mock.patch.object(b.importlib, "import_module", return_value=api), \
                mock.patch.object(b, "_await_serve"), \
                mock.patch.object(b, "_build", return_value=[]):
            self.assertEqual(b.main(["--compile-transport"]), 0)
            self.assertEqual(b.main([]), 0)
        with mock.patch.object(b, "Context", return_value=mock.Mock()), \
                mock.patch.object(b, "_build", side_effect=ValueError("x")), \
                mock.patch.object(b.traceback, "print_exc"):
            self.assertEqual(b.main([]), 1)

    def test_await_serve(self):
        ctx = mock.Mock(http=None)
        b._await_serve(ctx)
        ctx.http = mock.Mock()
        event = mock.Mock()
        box = {}

        def install(fn):
            box["fn"] = fn

        with mock.patch.object(b.threading, "Event", return_value=event), \
                mock.patch.object(b.plat_proc, "install_stop_handler", side_effect=install):
            b._await_serve(ctx)
        event.wait.assert_called_once()
        handler = box["fn"]
        handler(0, None)
        event.set.assert_called_once()
        ctx.http.shutdown.assert_called_once()
        ctx.http.server_close.assert_called_once()
        ctx.http.shutdown.side_effect = ValueError("x")
        with mock.patch.object(b.threading, "Event", return_value=event), \
                mock.patch.object(b.plat_proc, "install_stop_handler"):
            with self.assertRaises(ValueError):
                b._await_serve(ctx)


if __name__ == "__main__":
    unittest.main()
