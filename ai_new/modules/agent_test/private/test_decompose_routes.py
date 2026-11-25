"""decompose 路由闭环：预检、隔离装依赖、登记守卫、状态与 run 短路。"""
from __future__ import annotations

import asyncio
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent import decompose  # noqa: E402


class Tools:
    def __init__(self):
        self.names = set()
        self.rows = []

    def has(self, name):
        return name in self.names

    def register(self, name, desc, params, fn, module=None, kinds=None, deps=None,
                 builtin=False):
        self.rows.append((name, fn))


class Own:
    def __init__(self, root):
        self.root = Path(root)
        self.removed = []

    def dir(self, rel=""):
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def remove(self, rel, recursive=False):
        if rel == "deps":
            raise OSError("rollback")
        self.removed.append(rel)


class Ctx:
    def __init__(self):
        self.records = {}
        self.calls = []
        self.tools = Tools()
        self.registered = []
        self.api = self
        self._own = Own("/tmp/decompose-test")
        self.storage = self
        self.net = {}
        self.exec = {}
        self.react = {}
        self.responses = {}
        self.tasks = {}

    def register(self, name, fn, desc=None, module=None):
        self.registered.append(name)

    def own_storage(self, _file):
        return self._own

    def call(self, name, payload=None, caller=None):
        payload = payload or {}
        self.calls.append((name, payload))
        if name == "store.read":
            return {"value": self.records.get((payload["module"], payload["path"]))}
        if name == "host.which":
            return self.responses.get(("which", payload["name"]), {"found": False})
        if name == "host.env":
            return self.responses.get(("env", payload["name"]), {"value": ""})
        if name == "host.importable":
            return self.responses.get(("importable", payload["name"]), {"importable": False})
        if name == "host.executable":
            return {"path": "/usr/bin/python"}
        if name == "codec.digest":
            text = payload["text"].encode()
            return {"ok": True, "hex": hashlib.sha1(text).hexdigest()}
        if name == "clock.now":
            return {"ts": 1000}
        if name == "library.stage_contract":
            return self.responses.get("contract", {"states": payload["states"]})
        if name == "decompose.install_parts":
            return self.responses.get("parts", {})
        if name == "codec.json_decode":
            try:
                import json
                return {"ok": True, "value": json.loads(payload["text"])}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if name == "decompose.parse":
            return {"ok": True, "parsed": payload}
        if name == "decompose.parse_skill_doc":
            return {"meta": {}, "body": "b", "pip": [], "scripts": []}
        if name == "library.disabled_skills":
            return {"ids": []}
        if name == "tools.list":
            return {"items": [{"name": "shell"}]}
        if name == "decompose.promptize":
            return {"messages": []}
        raise AssertionError(name)

    async def acall(self, name, payload=None, caller=None):
        payload = payload or {}
        if name == "net.request":
            return self.net
        if name == "exec.run":
            return self.exec
        if name == "react.run":
            return self.react
        raise AssertionError(name)


class DecomposeRouteTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ctx = Ctx()
        self.ctx.own = self.ctx.own_storage
        self.ctx.records[("agent/decompose", "messages.yaml")] = {}
        self.ctx.records[("agent/decompose", "tasks.yaml")] = {"tasks": {}}
        self.ctx.records[("agent/library", "roles.yaml")] = {}
        self.ctx.records[("agent/library", "skills.yaml")] = {}
        self.ctx.records[("agent_common/tools", "tools.yaml")] = {}

    def test_setup_env_and_tools(self):
        self.ctx.tools.names.add("fetch_url")
        self.assertTrue(decompose.setup(self.ctx))
        self.assertIn("decompose.run", self.ctx.registered)
        self.assertEqual(len(self.ctx.tools.rows), 1)
        self.ctx.responses[("which", "git")] = {"found": True}
        self.ctx.responses[("env", "TOKEN")] = {"value": "x"}
        snap = decompose._env_snapshot(self.ctx, {"cli": ["git"], "env": ["TOKEN"]})
        self.assertEqual(snap, {"cli": {"git": True}, "env": {"TOKEN": "x"}})
        handler = decompose._as_handler(lambda p: p)
        self.assertEqual(handler(self.ctx, None)["tpl"], {})
        self.ctx.records[("agent/decompose", "tasks.yaml")] = "bad"
        self.assertEqual(decompose._read_tasks(self.ctx), {"tasks": {}})
        states = decompose._flow_states({"nodes": [{"id": "a"}, {"id": "b"}],
                                         "edges": ["bad", {"from": "z", "to": "a"},
                                                   {"from": "a", "to": "b"},
                                                   {"from": "a", "to": "b"}]})
        self.assertEqual(states[0]["next"], ["b"])
        self.assertTrue(states[1]["terminal"])

    async def test_fetch_and_pip_tools(self):
        self.assertEqual((await decompose._tool_fetch(self.ctx, {}))["code"], "bad_request")
        self.assertEqual((await decompose._tool_fetch(self.ctx, {"url": "ftp://x"}))["code"],
                         "bad_url")
        self.ctx.net = {"ok": False}
        self.assertEqual((await decompose._tool_fetch(self.ctx, {"url": "http://x"}))["code"],
                         "fetch_failed")
        self.ctx.net = {"ok": True, "text": "doc"}
        self.assertEqual((await decompose._tool_fetch(self.ctx, {"url": "https://x"}))["text"], "doc")
        self.assertEqual((await decompose._tool_pip(self.ctx, {"pkg": "bad;x"}))["code"], "bad_pkg")
        self.ctx.exec = {"ok": False, "error": "pip"}
        self.assertEqual((await decompose._tool_pip(self.ctx, {"pkg": "pkg"}))["error"], "pip")
        self.ctx.exec = {"ok": True, "seconds": 1}
        self.assertEqual((await decompose._tool_pip(self.ctx, {"pkg": "pkg"}))["seconds"], 1)

    def test_inspect_paths(self):
        inp = decompose._route_inspect(self.ctx, {"bundle": {"files": [{"path": "x.exe"}]}})
        self.assertEqual(inp["code"], "disallowed_type")
        self.ctx.responses[("which", "git")] = {"found": False}
        blocked = decompose._route_inspect(self.ctx, {
            "bundle": {"id": "s", "version": "1", "files": [{"path": "README"}],
                       "deps": {"cli": ["git"]}}})
        self.assertEqual(blocked["status"], "blocked_missing_deps")
        self.ctx.responses[("which", "git")] = {"found": True}
        self.ctx.responses[("importable", "pkg")] = {"importable": True}
        ok = decompose._route_inspect(self.ctx, {
            "bundle": {"id": "s", "version": "1", "files": [{"path": "README"}],
                       "deps": {"cli": ["git"]}, "requirements": ["pkg"]}})
        self.assertEqual(ok["status"], "inspected")
        missing_pkg = decompose._route_inspect(self.ctx, {
            "bundle": {"id": "s", "version": "2", "files": [{"path": "README"}],
                       "requirements": ["other"]}})
        self.assertEqual(missing_pkg["status"], "blocked_missing_deps")
        bad_req = decompose._route_inspect(self.ctx, {
            "bundle": {"id": "s", "version": "3", "files": [{"path": "README"}],
                       "requirements": ["bad;x"]}})
        self.assertEqual(bad_req["code"], "bad_pkg")
        key = ok["task_key"]
        state = self.ctx.records[("agent/decompose", "tasks.yaml")]
        state["tasks"][key]["status"] = "registered"
        reused = decompose._route_inspect(self.ctx, {
            "bundle": {"id": "s", "version": "1", "files": [{"path": "README"}]}})
        self.assertTrue(reused["reused"])
        self.ctx.responses["parts"] = {"skill": {"id": "s"}}
        rejected = decompose._route_inspect(self.ctx, {
            "bundle": {"id": "s", "version": "1", "files": [{"path": "README"}],
                       "requirements": ["bad;x"]}})
        self.assertEqual(rejected["code"], "bad_pkg")

    async def test_deps_install(self):
        missing = decompose._route_deps_install(self.ctx, {"key": "nope"})
        # async route
        out = await missing
        self.assertEqual(out["code"], "task_not_found")
        self.ctx.records[("agent/decompose", "tasks.yaml")] = {"tasks": {
            "k1": {"status": "registered"},
            "k2": {"status": "inspected", "deps": {"plan": [
                {"requirement": "bad;x", "installed": False},
                {"requirement": "pkg", "installed": False}]}},
        }}
        self.assertTrue((await decompose._route_deps_install(self.ctx, {"key": "k1"}))["reused"])
        self.ctx.exec = {"ok": False, "error": "x"}
        failed = await decompose._route_deps_install(self.ctx, {"key": "k2"})
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["status"], "blocked_missing_deps")
        self.ctx.exec = {"ok": True}
        self.ctx.records[("agent/decompose", "tasks.yaml")] = {"tasks": {
            "k3": {"status": "inspected", "deps": {"plan": [{"requirement": "pkg",
                                                             "installed": False}]}}}}
        ok = await decompose._route_deps_install(self.ctx, {"key": "k3"})
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["status"], "deps_ready")

    def test_register_guards_and_success(self):
        self.assertEqual(decompose._route_register(self.ctx, {"key": "none"})["code"],
                         "task_not_found")
        state = self.ctx.records[("agent/decompose", "tasks.yaml")]
        state["tasks"] = {"r": {"status": "registered"}, "b": {"status": "blocked_missing_deps"},
                          "x": {"id": "s", "status": "inspected"}}
        self.assertTrue(decompose._route_register(self.ctx, {"key": "r"})["reused"])
        self.assertEqual(decompose._route_register(self.ctx, {"key": "b"})["code"],
                         "deps_blocked")
        self.ctx.records[("agent/library", "roles.yaml")] = {"s": {"builtin": True}}
        self.assertEqual(decompose._route_register(self.ctx, {"key": "x", "draft": {}})["code"],
                         "builtin_protected")
        self.ctx.records[("agent/library", "roles.yaml")] = {}
        self.ctx.responses["contract"] = {"states": []}
        self.assertEqual(decompose._route_register(self.ctx, {"key": "x", "draft": {
            "flow": {"nodes": [{"id": "a"}]}}})["code"], "flow_contract_invalid")
        self.ctx.responses["parts"] = {}
        self.assertEqual(decompose._route_register(self.ctx, {"key": "x", "draft": {}})["code"],
                         "invalid_parts")
        self.ctx.responses["parts"] = {"skill": {"id": ""}, "role": {"id": ""},
                                       "tools": []}
        self.assertEqual(decompose._route_register(self.ctx, {"key": "x", "draft": {}})["code"],
                         "invalid_parts")
        self.ctx.responses["parts"] = {"skill": {"id": "s"}, "role": {"id": "s"},
                                       "tools": [{"name": "t"}]}
        ok = decompose._route_register(self.ctx, {"key": "x", "draft": {}})
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["products"]["role"], "s")

    def test_status_and_install(self):
        self.ctx.records[("agent/decompose", "tasks.yaml")] = {"tasks": {
            "a": {"status": "blocked_missing_deps", "env": {"missing": {"cli": ["x"],
                                                                      "env": ["E"]}},
                  "deps": {"missing": [{"pkg": "p"}]}, "audit": [{"action": "inspect"}]},
            "b": {"status": "registered", "audit": []},
        }}
        out = decompose._route_status(self.ctx, {})
        self.assertEqual(out["summary"], {"blocked": 1, "registered": 1, "missing_cli": 1,
                                           "missing_env": 1, "missing_pkg": 1})
        self.assertEqual(decompose._route_install(self.ctx, {"run": {"ok": False}})["code"],
                         "run_failed")
        self.assertEqual(decompose._route_install(self.ctx, {"run": {"draft": {}}})["code"],
                         "invalid_parts")
        self.ctx.responses["parts"] = {"skill": {"id": "s"}, "role": {"id": "s"}, "tools": []}
        inst = decompose._route_install(self.ctx, {"draft": {"id": "s"}})
        self.assertTrue(inst["ok"])

    async def test_run_short_circuits_and_success(self):
        self.ctx.net = {"ok": False}
        self.assertEqual((await decompose._route_run(self.ctx, {"url": "http://x"}))["code"],
                         "fetch_failed")
        self.assertEqual((await decompose._route_run(self.ctx, {}))["code"], "empty_input")
        self.ctx.react = None
        self.assertEqual((await decompose._route_run(self.ctx, {"skill_md": "x"}))["code"],
                         "no_answer")
        self.ctx.react = {"failed": True}
        self.assertEqual((await decompose._route_run(self.ctx, {"skill_md": "x"}))["failed"], True)
        self.ctx.react = {"cancelled": True}
        self.assertEqual((await decompose._route_run(self.ctx, {"skill_md": "x"}))["code"],
                         "cancelled")
        self.ctx.react = {"last": {"content": "not json"}}
        self.assertEqual((await decompose._route_run(self.ctx, {"skill_md": "x"}))["code"],
                         "bad_draft_json")
        self.ctx.react = {"last": {"content": '{"id": "s"}'}}
        self.ctx.net = {"ok": True, "text": "doc"}
        self.assertEqual((await decompose._route_run(self.ctx, {"url": "http://x"}))["ok"], True)
        self.assertTrue((await decompose._route_run(self.ctx, {"skill_md": "x"}))["ok"])


if __name__ == "__main__":
    unittest.main()
