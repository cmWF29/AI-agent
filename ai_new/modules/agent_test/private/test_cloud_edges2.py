"""cloud 路由/装配边界：单 profile 兜底、端点复检、封装失败、上传/删除/清单异常与工具跳过。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).parent))

import base64
import os
import shutil
import tempfile

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from ai_new.modules.agent_test.private._fixtures import stage, write_config  # noqa: E402
from ai_new.modules.agent_test.private.test_cloud import (  # noqa: E402
    MASTER_KEY, _global_caller, _project_caller)
from ai_new.modules.agent import cloud as c  # noqa: E402
from ai_new.modules.agent.cloud.private import (  # noqa: E402
    _archive, _guard, _providers, _seal)


class CloudEdge2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        stage(root)
        write_config(root, {
            "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
            "llm": {"base_url": "http://stub.local/v1", "api_key": "k",
                    "model": "stub"},
            "tickets": {"stall_check": {"enabled": False}},
            "cloud": {"allowed_hosts": []},
        })
        os.environ["AI_NEW_DATA"] = str(root)
        os.environ["AI_NEW_SECRET_KEY"] = MASTER_KEY
        os.environ["AI_NEW_SECRET_KEY_FILE"] = str(root / "secrets.key")
        cls.ctx = Context(root)
        cls.loaded = build(cls.ctx)
        cls.fake = _providers.FakeProvider()
        cls._orig_build = _providers.build
        _providers.build = lambda kind: cls.fake

    @classmethod
    def tearDownClass(cls):
        _providers.build = cls._orig_build
        os.environ.pop("AI_NEW_DATA", None)
        os.environ.pop("AI_NEW_SECRET_KEY", None)
        os.environ.pop("AI_NEW_SECRET_KEY_FILE", None)
        shutil.rmtree(cls.tmp.name, ignore_errors=True)

    def setUp(self):
        self.fake.store = {}
        self.fake.fail_times = 0
        self.fake.fail_keys = {}
        self.fake.attempts = 0
        self.fake.calls = []
        self._orig_put = self.fake.put
        self._orig_delete = self.fake.delete
        for item in self.ctx.api.call("cloud.profile_list", {
                "caller": _global_caller()})["items"]:
            res = self.ctx.api.call("cloud.profile_delete", {
                "id": item["id"], "caller": _global_caller()})
            self._apply(res)

    def tearDown(self):
        self.fake.put = self._orig_put
        self.fake.delete = self._orig_delete

    def _apply(self, res):
        effects = (res or {}).get("effects") or []
        if effects:
            self.ctx.runtime.apply({"effect": effects})

    def _save(self, pid, secret, caller=None, provider="stub",
              categories=None, company="co-a", policy=None):
        payload = {
            "id": pid, "company": company, "provider": provider,
            "endpoint": "https://oss.example.com/backup",
            "root_dir": "team-a",
            "credentials": {"access_key": secret},
            "categories": categories or ["knowledge"],
            "policy": policy or {"max_attempts": 3, "backoff_base_s": 0,
                                 "backoff_cap_s": 0},
            "caller": caller or _global_caller(),
        }
        res = self.ctx.api.call("cloud.profile_save", payload)
        self._apply(res)
        return res

    def _stage_local_file(self, text="云端同步测试正文"):
        self.ctx.api.call("store.write_text", {
            "module": "agent/knowledge", "path": "sync-probe.md", "text": text})

    def test_load_state_and_mtime(self):
        class Api:
            def __init__(self, value, doc=None):
                self.value = value
                self.doc = doc

            def call(self, route, payload=None, caller=None):
                if route == "store.read":
                    return {"value": self.value}
                if route == "store.resolve_doc":
                    return self.doc
                raise AssertionError(route)

        class Mini:
            def __init__(self, value, doc=None):
                self.api = Api(value, doc)

        self.assertEqual(c._load_state(Mini([]))["profiles"], {})
        self.assertEqual(c._load_state(Mini({}))["profiles"], {})
        self.assertEqual(c._mtime(Mini({}, {"ok": False}), "m", "x"), 0.0)
        self.assertEqual(c._mtime(Mini({}, {"ok": True,
                                           "real": "/no/such/file"}), "m", "x"),
                         0.0)

    def test_profile_save_without_credentials_and_delete_active(self):
        res = self.ctx.api.call("cloud.profile_save", {
            "id": "p-nocred", "company": "co", "provider": "stub",
            "endpoint": "https://oss.example.com/x", "root_dir": "r",
            "categories": ["knowledge"], "caller": _global_caller()})
        self.assertEqual(res["code"], "bad_credentials")
        ok = self._save("p-active", "secret")
        self.assertTrue(ok["ok"])
        self.ctx.api.call("cloud.profile_switch", {
            "id": "p-active", "caller": _global_caller()})
        deleted = self.ctx.api.call("cloud.profile_delete", {
            "id": "p-active", "caller": _global_caller()})
        self.assertTrue(deleted["ok"])
        self._apply(deleted)
        self.assertEqual(self.ctx.api.call("cloud.status", {
            "caller": _global_caller()})["active"], "")

    def test_collect_unknown_category_and_archive_match(self):
        self._stage_local_file("body")
        profile = {"categories": ["knowledge", "bogus"]}
        self.assertTrue(c._collect_entries(self.ctx, profile)[0])
        old = _archive.list_archived
        try:
            _archive.list_archived = lambda ctx: {"seam": "wired", "rows": [{
                "path": "agent/knowledge/sync-probe.md", "status": "archived",
                "size_comp": 1, "checksum": "x"}]}
            local, seam = c._collect_entries(self.ctx, {"categories": ["knowledge"]})
            hit = [e for e in local if e["rel"] == "knowledge/sync-probe.md"][0]
            self.assertTrue(hit["archived"])
        finally:
            _archive.list_archived = old

    def test_remote_manifest_provider_and_decode_errors(self):
        class Boom:
            def get(self, *a):
                raise _providers.ProviderError("provider_error", "boom")

        class Bad:
            def get(self, *a):
                return {"ok": True, "data": b"not-json"}

        profile = {"id": "p", "provider": "stub", "endpoint": "https://x"}
        self.assertEqual(c._remote_manifest(self.ctx, profile, Boom(), {})["code"],
                         "provider_error")
        bad = c._remote_manifest(self.ctx, profile, Bad(), {})
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["code"], "manifest_corrupt")

    def test_single_profile_fallback_and_revalidate(self):
        self._save("p-a", "s")
        self._save("p-b", "t")
        sw = self.ctx.api.call("cloud.profile_switch", {
            "id": "p-b", "caller": _global_caller()})
        self._apply(sw)
        dele = self.ctx.api.call("cloud.profile_delete", {
            "id": "p-b", "caller": _global_caller()})
        self._apply(dele)
        self.assertEqual(self.ctx.api.call("cloud.status", {
            "caller": _global_caller()})["active"], "")
        plan = self.ctx.api.call("cloud.sync_plan", {"caller": _global_caller()})
        self.assertEqual(plan["profile"], "p-a")
        with mock.patch.object(c, "_provider_for",
                               side_effect=_providers.ProviderError("provider_error", "x")):
            perr = self.ctx.api.call("cloud.sync_plan", {"caller": _global_caller()})
        self.assertEqual(perr["plan"]["remote_error"], "provider_error")
        with mock.patch.object(c, "_revalidate_endpoint", lambda ctx, p: ["bad_endpoint"]):
            bad = self.ctx.api.call("cloud.sync_run", {"caller": _global_caller()})
        self.assertEqual(bad["code"], "bad_endpoint")

    def test_seal_error_on_provider(self):
        self._save("p-seal", "s")
        with mock.patch.object(c, "_provider_for",
                               side_effect=_seal.SealError("seal_error", "no key")):
            out = self.ctx.api.call("cloud.sync_run", {"caller": _global_caller()})
        self.assertEqual(out["code"], "seal_error")

    def test_upload_guard_and_delete_failures(self):
        self._stage_local_file("body")
        self._save("p-up", "s")
        orig = self.fake.put

        def put(ctx, profile, key, data):
            if key != c._MANIFEST_KEY:
                raise _guard.GuardError("body_too_large", "too big")
            return orig(ctx, profile, key, data)

        self.fake.put = put
        out = self.ctx.api.call("cloud.sync_run", {"caller": _global_caller()})
        self.assertFalse(out["ok"])
        self.assertTrue(out["ledger"]["failed"])

    def test_manifest_put_exceptions(self):
        self._stage_local_file("body")
        self._save("p-mf", "s")
        orig = self.fake.put

        def guard(ctx, profile, key, data):
            if key == c._MANIFEST_KEY:
                raise _guard.GuardError("body_too_large", "too big")
            return orig(ctx, profile, key, data)

        self.fake.put = guard
        out = self.ctx.api.call("cloud.sync_run", {"caller": _global_caller()})
        self.assertEqual(out["ledger"]["manifest_error"], "body_too_large")

        def provider(ctx, profile, key, data):
            if key == c._MANIFEST_KEY:
                raise _providers.ProviderError("provider_error", "down")
            return orig(ctx, profile, key, data)

        self.fake.store = {}
        self.fake.put = provider
        out = self.ctx.api.call("cloud.sync_run", {"caller": _global_caller()})
        self.assertEqual(out["ledger"]["manifest_error"], "provider_error")

    def test_delete_retry_paths(self):
        self._stage_local_file("body")
        self._save("p-del", "s")
        self.ctx.api.call("cloud.sync_run", {"caller": _global_caller()})
        self.ctx.api.call("store.remove", {"module": "agent/knowledge",
                                           "path": "sync-probe.md"})
        self.fake.delete = lambda *a: (_ for _ in ()).throw(
            _providers.ProviderError("provider_error", "down"))
        plan = self.ctx.api.call("cloud.sync_plan", {"caller": _global_caller()})
        self.assertTrue(plan["plan"]["to_delete"])
        out = self.ctx.api.call("cloud.sync_run", {"prune": True,
                                                   "caller": _global_caller()})
        self.assertTrue(out["ledger"]["delete_failed"])

    def test_retry_backoff_and_delete_backoff(self):
        self.ctx.api.call("store.write_text", {
            "module": "agent/sessions", "path": "sessions/retry.yaml",
            "text": "x"})
        self._save("p-retry", "s", categories=["session"],
                   policy={"max_attempts": 2, "backoff_base_s": 1,
                           "backoff_cap_s": 1})
        self.fake.attempts = 0
        self.fake.fail_times = 1
        out = self.ctx.api.call("cloud.sync_run", {"caller": _global_caller()})
        self.assertTrue(out["ok"], out["ledger"])
        self.ctx.api.call("store.remove", {"module": "agent/sessions",
                                           "path": "sessions/retry.yaml"})
        runs = {"n": 0}

        def flaky_delete(*a):
            runs["n"] += 1
            return {"ok": runs["n"] > 1}

        self.fake.delete = flaky_delete
        out = self.ctx.api.call("cloud.sync_run", {
            "prune": True, "caller": _global_caller()})
        self.assertTrue(out["ok"], out["ledger"])
        self.assertEqual(out["ledger"]["deleted"], 1)
        self.ctx.api.call("store.write_text", {
            "module": "agent/sessions", "path": "sessions/retry0.yaml",
            "text": "x"})
        self._save("p-retry0", "s", categories=["session"],
                   policy={"max_attempts": 2, "backoff_base_s": 0,
                           "backoff_cap_s": 0})
        self.fake.attempts = 0
        self.fake.attempts = 0
        self.fake.fail_times = 1
        out = self.ctx.api.call("cloud.sync_run", {"caller": _global_caller()})
        self.assertTrue(out["ok"], out["ledger"])
        self.ctx.api.call("store.remove", {"module": "agent/sessions",
                                           "path": "sessions/retry0.yaml"})
        runs["n"] = 0
        self.fake.delete = flaky_delete
        out = self.ctx.api.call("cloud.sync_run", {
            "prune": True, "caller": _global_caller()})
        self.assertTrue(out["ok"], out["ledger"])

    def test_tools_skip_and_register(self):
        class Tools:
            def __init__(self):
                self.rows = []

            def has(self, name):
                return name == "cloud_profile_save"

            def register(self, *args, **kwargs):
                self.rows.append((args, kwargs))

        class Mini:
            def __init__(self):
                self.tools = Tools()
                self.api = mock.Mock()
                self.api.call.return_value = {"value": {}}

        mini = Mini()
        c._register_tools(mini)
        self.assertEqual(len(mini.tools.rows), 6)
        mini.tools.has = lambda name: False
        mini.tools.rows = []
        c._register_tools(mini)
        self.assertEqual(len(mini.tools.rows), 7)


if __name__ == "__main__":
    unittest.main()
