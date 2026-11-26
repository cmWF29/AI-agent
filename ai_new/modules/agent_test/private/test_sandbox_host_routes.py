"""隔离档位与主机资源路由单测：能力探测、档位选择、执行计划、路径守卫、节点探针门面。"""
import os
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent import sandbox
from ai_new.modules.agent_common import host
from ai_new.modules.agent_common.host.private import _probe, _profile


class ApiError(Exception):
    def __init__(self, message, code="E", status=500):
        super().__init__(message)
        self.code = code
        self.status = status


class FakeApi:
    def __init__(self, which=None, workspace=None, captured=None):
        self.which = which or {}
        self.workspace = workspace or {"capability": {"os": "posix"}}
        self.registered = {}
        self.calls = []
        if captured is not None:
            captured["api"] = self

    def register(self, name, fn, desc=None, module=None):
        self.registered[name] = fn

    def call(self, name, payload=None, caller=None):
        p = payload or {}
        self.calls.append((name, p))
        if name == "host.which":
            return {"found": self.which.get(p.get("name"), False)}
        if name == "host.importable":
            return {"importable": self.which.get(p.get("name"), False)}
        if name == "host.env":
            return {"value": self.which.get(p.get("name"))}
        if name == "host.executable":
            return {"path": "/usr/bin/python3"}
        if name == "store.doc_lock_capability":
            return {"flock": True}
        if name == "store.workspace":
            return self.workspace
        raise AssertionError(name)


def ctx_with(**kw):
    return SimpleNamespace(api=FakeApi(**kw), ApiError=ApiError, root="/tmp")


class SandboxRoutesTest(unittest.TestCase):
    def test_setup_registers_four(self):
        ctx = ctx_with()
        self.assertTrue(sandbox.setup(ctx))
        self.assertEqual(sorted(ctx.api.registered),
                         ["sandbox.capability", "sandbox.guard_path",
                          "sandbox.pick_tier", "sandbox.plan"])

    def test_capability_reports_binaries_and_locks(self):
        ctx = ctx_with(which={"bwrap": True})
        got = sandbox._route_capability(ctx, {})
        self.assertTrue(got["ok"])
        self.assertEqual(sorted(got["binaries"]),
                         sorted(["unshare", "bwrap", "chroot", "systemd-run"]))
        self.assertTrue(got["binaries"]["bwrap"])
        self.assertFalse(got["binaries"]["unshare"])
        self.assertEqual(got["lock"], {"flock": True})
        self.assertEqual(got["path_isolation"], {"os": "posix"})
        self.assertIn("weak", got["tiers"])
        self.assertIn("mechanism_diff", got)

    def test_capability_with_empty_workspace(self):
        ctx = ctx_with()
        ctx.api.workspace = {}
        got = sandbox._route_capability(ctx, {"ignored": 1})
        self.assertEqual(got["path_isolation"], {})

    def test_pick_tier_explicit_and_flags(self):
        ctx = ctx_with()
        self.assertEqual(sandbox._route_pick_tier(ctx, {"tier": "strong"})["tier"], "strong")
        self.assertEqual(sandbox._route_pick_tier(ctx, None)["tier"], "weak")
        self.assertEqual(sandbox._route_pick_tier(ctx, {"multi_tenant": True})["tier"],
                         "strong")

    def test_plan_passthrough(self):
        ctx = ctx_with()
        got = sandbox._route_plan(ctx, {"project": "p1", "tier": "weak",
                                        "workspace": {"root": "/tmp/p1"}})
        self.assertTrue(got["ok"])
        self.assertEqual(got["cwd"], "/tmp/p1")
        self.assertEqual(got["lock_path"], "/tmp/p1/.locks/p1.lock")
        bad = sandbox._route_plan(ctx, None)
        self.assertFalse(bad["ok"])

    def test_guard_path_auto_uses_store_os(self):
        ctx = ctx_with()
        got = sandbox._route_guard_path(ctx, {"root": "/tmp/p", "target": "/tmp/p/a"})
        self.assertTrue(got["ok"])
        nt = ctx_with(workspace={"capability": {"os": "nt"}})
        got = sandbox._route_guard_path(nt, {"root": "C:/p", "target": "C:/p/a"})
        self.assertTrue(got["ok"])

    def test_guard_path_explicit_platform(self):
        ctx = ctx_with()
        got = sandbox._route_guard_path(ctx, None)
        self.assertFalse(got["ok"])
        got = sandbox._route_guard_path(ctx, {"root": "/tmp/p", "target": "/etc",
                                              "platform": "linux"})
        self.assertEqual(got["code"], "escape")


class HostRoutesTest(unittest.TestCase):
    def test_setup_registers_and_binds_probe(self):
        ctx = ctx_with(which={"git": True, "requests": True, "TOKEN": "v"})
        self.assertTrue(host.setup(ctx))
        self.assertEqual(sorted(ctx.api.registered),
                         ["host.env", "host.executable", "host.importable", "host.info",
                          "host.profile", "host.readiness", "host.which"])
        self.assertEqual(ctx.host, _probe)
        self.assertTrue(ctx.host.info(ctx)["ok"])

    def test_registered_wrappers_use_real_probes(self):
        ctx = ctx_with()
        host.setup(ctx)
        reg = ctx.api.registered
        self.assertTrue(reg["host.which"](ctx, {"name": "sh"})["found"])
        self.assertFalse(reg["host.which"](ctx, {"name": "no-such-cmd-hive"})["found"])
        self.assertTrue(reg["host.importable"](ctx, {"name": "json"})["importable"])
        self.assertFalse(reg["host.importable"](ctx, {"name": "definitely-not-a-pkg-hive"})["importable"])
        os.environ["HIVE_PROBE_X"] = "v"
        try:
            self.assertEqual(reg["host.env"](ctx, {"name": "HIVE_PROBE_X"})["value"], "v")
        finally:
            del os.environ["HIVE_PROBE_X"]
        self.assertIsNone(reg["host.env"](ctx, None)["value"])
        self.assertEqual(reg["host.executable"](ctx, {})["path"], sys.executable)

    def test_profile_builds_snapshot(self):
        ctx = ctx_with(which={"git": True, "requests": True, "TOKEN": "v"})
        got = host._route_profile(ctx, {"cli": ["git"], "pip": ["requests"],
                                       "env": ["TOKEN"], "node": "n1"})
        self.assertTrue(got["ok"])
        profile = got["profile"]
        self.assertEqual(profile["cli"], {"git": True})
        self.assertEqual(profile["pkgs"], {"requests": True})
        self.assertEqual(profile["env"], {"TOKEN": "v"})
        self.assertEqual(profile["executable"], "/usr/bin/python3")

    def test_profile_empty_payload(self):
        ctx = ctx_with()
        got = host._route_profile(ctx, None)
        self.assertTrue(got["ok"])
        self.assertEqual(got["profile"]["cli"], {})

    def test_readiness_matrix(self):
        ctx = ctx_with(which={"git": True, "requests": False, "TOKEN": None})
        got = host._route_readiness(ctx, {"tool": {"deps": {
            "cli": ["git", "docker"], "pip": ["requests"], "env": ["TOKEN"]}}})
        self.assertFalse(got["ready"])
        self.assertEqual(got["status"], "missing_deps")
        self.assertEqual(got["missing"], {"cli": ["docker"], "pip": ["requests"],
                                         "env": ["TOKEN"]})

    def test_info_wrapper(self):
        ctx = ctx_with()
        self.assertTrue(host.info(ctx)["ok"])

    def test_readiness_without_deps(self):
        ctx = ctx_with()
        got = host._route_readiness(ctx, {})
        self.assertTrue(got["ready"])


class ReadinessPureTest(unittest.TestCase):
    def test_multi_item_loops(self):
        got = _profile.readiness({"deps": {"cli": ["a", "b"], "pip": ["x", "y"],
                                          "env": ["E1", "E2"]}},
                                 {"cli": {"a": True, "b": False},
                                  "pkgs": {"x": False, "y": True},
                                  "env": {"E1": "v", "E2": ""}})
        self.assertEqual(got["missing"], {"cli": ["b"], "pip": ["x"], "env": ["E2"]})
        self.assertFalse(got["ready"])


class ProfilePureTest(unittest.TestCase):
    def test_build_profile_defaults(self):
        got = _profile.build_profile({})
        self.assertEqual(got, {"node": "", "os": "", "shell": "", "executable": "",
                               "cli": {}, "pkgs": {}, "env": {}})

    def test_resolve_layered_overrides(self):
        got = _profile.resolve_layered([{"a": 1}, None, {"a": 2, "b": 3}, {"b": 4}])
        self.assertEqual(got, {"a": 2, "b": 4})
        self.assertEqual(_profile.resolve_layered(None), {})


if __name__ == "__main__":
    unittest.main()
