"""节点环境 profile、工具就绪度与分层解析靶向测试。

- 节点事实由 host 探针实时取，不固化进知识层；
- 缺依赖判不可用（missing_deps），列出具体缺失项，不静默放行；
- 分层解析 public→node→project→ticket，最具体覆盖最泛化；项目/工单覆盖节点级；
- 跨节点隔离：节点 A 的 profile 不带出节点 B 的事实。
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.host.private import _profile  # noqa: E402
from ai_new.modules.agent_common.store.private import _docpath  # noqa: E402


class ProfileBuildTest(unittest.TestCase):
    def test_build_profile_carries_probe_facts(self):
        probes = {
            "os": os.name,
            "executable": "/usr/bin/python3",
            "cli": {"git": True, "make": False},
            "pkgs": {"yaml": True},
            "env": {"HOME": "/home/user"},
        }
        profile = _profile.build_profile(probes, node="node-1")
        self.assertEqual(profile["node"], "node-1")
        self.assertEqual(profile["executable"], "/usr/bin/python3")
        self.assertTrue(profile["cli"]["git"])
        self.assertFalse(profile["cli"]["make"])
        self.assertTrue(profile["pkgs"]["yaml"])
        self.assertEqual(profile["env"]["HOME"], "/home/user")

    def test_cross_node_isolation(self):
        a = _profile.build_profile({"cli": {"git": True}, "pkgs": {}, "env": {}}, "node-a")
        b = _profile.build_profile({"cli": {"docker": True}, "pkgs": {}, "env": {}}, "node-b")
        self.assertIn("git", a["cli"])
        self.assertNotIn("git", b["cli"])
        self.assertIn("docker", b["cli"])
        self.assertNotIn("docker", a["cli"])


class ReadinessTest(unittest.TestCase):
    def test_ready_when_all_deps_present(self):
        tool = {"deps": {"cli": ["git"], "pip": ["yaml"], "env": ["HOME"]}}
        profile = {"cli": {"git": True}, "pkgs": {"yaml": True}, "env": {"HOME": "/u"}}
        out = _profile.readiness(tool, profile)
        self.assertTrue(out["ready"])
        self.assertEqual(out["status"], "ready")
        self.assertEqual(out["missing"], {"cli": [], "pip": [], "env": []})

    def test_missing_deps_listed_not_silent(self):
        tool = {"deps": {"cli": ["git", "make"], "pip": ["yaml"], "env": ["TOKEN"]}}
        profile = {"cli": {"git": True}, "pkgs": {"yaml": True}, "env": {}}
        out = _profile.readiness(tool, profile)
        self.assertFalse(out["ready"])
        self.assertEqual(out["status"], "missing_deps")
        self.assertIn("make", out["missing"]["cli"])
        self.assertEqual(out["missing"]["pip"], [])
        self.assertIn("TOKEN", out["missing"]["env"])

    def test_empty_deps_is_ready(self):
        out = _profile.readiness({}, {"cli": {}, "pkgs": {}, "env": {}})
        self.assertTrue(out["ready"])


class LayeredResolveTest(unittest.TestCase):
    def test_most_specific_wins(self):
        merged = _profile.resolve_layered([
            {"theme": "public", "a": 1},
            {"theme": "node", "b": 2},
            {"theme": "project", "c": 3},
            {"theme": "ticket"},
        ])
        self.assertEqual(merged["theme"], "ticket")
        self.assertEqual(merged["a"], 1)
        self.assertEqual(merged["b"], 2)
        self.assertEqual(merged["c"], 3)

    def test_project_and_ticket_override_node(self):
        merged = _profile.resolve_layered([
            {"workdir": "/public"},
            {"workdir": "/node", "limit": 5},
            {"workdir": "/project"},
            {"workdir": "/ticket"},
        ])
        self.assertEqual(merged["workdir"], "/ticket")
        self.assertEqual(merged["limit"], 5)


class PathSeparatorTest(unittest.TestCase):
    def test_windows_style_backslash_split(self):
        # ntpath 语义在 Linux 上测纯分段：反斜杠同样视为分隔符。
        rel = r"projects\proj-a\note.md"
        out = _docpath.resolve("agent/knowledge", rel)
        self.assertTrue(out["ok"])
        self.assertIn("proj-a", out["rel"])
        self.assertIn("note.md", out["rel"])

    def test_forward_slash_split(self):
        out = _docpath.resolve("agent/knowledge", "projects/proj-a/note.md")
        self.assertTrue(out["ok"])
        self.assertIn("proj-a", out["rel"])


class RouteRegistrationTest(unittest.TestCase):
    def test_host_profile_route_registered(self):
        from ai_new.modules.agent_common.host import setup as host_setup

        class _Api:
            def __init__(self):
                self.routes = {}

            def register(self, name, fn, *args, **kwargs):
                self.routes[name] = fn

        ctx = type("Ctx", (), {"api": _Api()})()
        host_setup(ctx)
        self.assertIn("host.profile", ctx.api.routes)


class ToolReadinessGateTest(unittest.TestCase):
    def _ctx(self, readiness):
        from ai_new.modules.agent_common.tools import setup as tools_setup

        class _Api:
            def __init__(self):
                self.routes = {}

            def register(self, name, fn, *args, **kwargs):
                self.routes[name] = fn

            def call(self, route, payload, caller=None):
                if route == "host.readiness":
                    return readiness
                if route == "store.read":
                    return {"value": {}}
                if route == "library.disabled_skills":
                    return {"ids": []}
                if route == "projects.override_parts":
                    return {"tools": []}
                return {}

        from ai_new.modules.agent_common.api.private._errors import ApiError
        ctx = type("Ctx", (), {"api": _Api(), "ApiError": ApiError})()
        tools_setup(ctx)
        return ctx

    def test_missing_deps_blocks_execute_with_explicit_error(self):
        from ai_new.modules.agent_common.tools import _route_execute
        from ai_new.modules.agent_common.api.private._errors import ApiError

        readiness = {"ready": False, "status": "missing_deps",
                     "missing": {"cli": ["missing-cli"], "pip": [], "env": []}}
        ctx = self._ctx(readiness)
        ctx.tools.register("probe", "缺依赖探针工具", [],
                          lambda c, a, s: {}, deps={"cli": ["missing-cli"]})
        with self.assertRaises(ApiError) as cm:
            asyncio.run(_route_execute(ctx, {"name": "probe", "args": {}}))
        err = cm.exception
        self.assertEqual(err.code, "tool_unavailable")
        self.assertEqual(err.status, 503)
        self.assertEqual(err.payload["missing"]["cli"], ["missing-cli"])

    def test_ready_tool_passes_gate(self):
        from ai_new.modules.agent_common.tools import _route_execute

        readiness = {"ready": True, "status": "ready",
                     "missing": {"cli": [], "pip": [], "env": []}}
        ctx = self._ctx(readiness)
        ctx.tools.register("ok-tool", "就绪工具", [],
                           lambda c, a, session=None: {"ok": True}, deps={})
        out = asyncio.run(_route_execute(ctx, {"name": "ok-tool", "args": {}}))
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
