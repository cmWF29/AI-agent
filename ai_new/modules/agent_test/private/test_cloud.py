"""云端资料库验收：适配层 mock 全链路、凭证不泄漏、增量幂等、重试退避、多公司隔离、越权拒绝。

不真连外网：提供方一律走内存 stub/FakeProvider；主密钥经环境变量注入（32 字节 base64）。
"""
import base64
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from _fixtures import stage, write_config  # noqa: E402

from ai_new.modules.agent.cloud.private import _pure, _providers, _archive, _seal  # noqa: E402

SECRET_MATERIAL = b"0" * 32
MASTER_KEY = base64.b64encode(SECRET_MATERIAL).decode()


def _global_caller():
    return {"scope": "global", "project": "", "ticket": "",
            "session": "admin-s1", "role": "admin"}


def _project_caller(project="p-demo"):
    return {"scope": "project", "project": project, "ticket": "",
            "session": "proj-s1", "role": "pm"}


class CloudTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        stage(root)
        write_config(root, {
            "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
            "llm": {"base_url": "http://stub.local/v1", "api_key": "k", "model": "stub"},
            "tickets": {"stall_check": {"enabled": False}},
            "cloud": {"allowed_hosts": []},
        })
        os.environ["AI_NEW_DATA"] = str(root)
        os.environ["AI_NEW_SECRET_KEY"] = MASTER_KEY
        os.environ["AI_NEW_SECRET_KEY_FILE"] = str(root / "secrets.key")
        cls.ctx = Context(root)
        cls.loaded = build(cls.ctx)
        # 共享内存桩：远端状态跨多次同步运行保持，模拟真实提供方持久存储。
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

    # ---- 夹具 ----

    def setUp(self):
        # 每个用例独立远端内存桩：上一用例上传的对象不污染本用例的幂等/冲突判定。
        self.fake.store = {}
        self.fake.fail_times = 0
        self.fake.fail_keys = {}
        self.fake.attempts = 0
        self.fake.calls = []

    def _apply(self, res):
        effects = (res or {}).get("effects") or []
        if effects:
            self.ctx.runtime.apply({"effect": effects})

    def _save(self, pid, secret, caller=None, provider="stub", categories=None,
              company="co-a"):
        payload = {
            "id": pid, "company": company, "provider": provider,
            "endpoint": "https://oss.example.com/backup",
            "root_dir": "team-a",
            "credentials": {"access_key": secret},
            "categories": categories or ["knowledge"],
            "policy": {"max_attempts": 3, "backoff_base_s": 0, "backoff_cap_s": 0},
            "caller": caller or _global_caller(),
        }
        res = self.ctx.api.call("cloud.profile_save", payload)
        self._apply(res)
        return res

    def _stage_local_file(self, text="云端同步测试正文"):
        self.ctx.api.call("store.write_text", {
            "module": "agent/knowledge", "path": "sync-probe.md", "text": text})

    # ---- 用例 ----

    def test_validate_profile_accepts_and_rejects(self):
        cfg = {"allowed_hosts": []}
        ok = _pure.validate_profile({
            "id": "p1", "company": "acme", "provider": "webdav",
            "endpoint": "https://dav.example.com/dav", "root_dir": "docs",
            "credentials": {"u": "x"}, "categories": ["knowledge"]}, cfg)
        self.assertTrue(ok["ok"], ok["errors"])

        bad_scheme = _pure.validate_profile({
            "id": "p2", "company": "acme", "provider": "webdav",
            "endpoint": "file:///etc/passwd", "root_dir": "",
            "credentials": {"u": "x"}, "categories": ["knowledge"]}, cfg)
        self.assertIn("bad_scheme", bad_scheme["errors"])

        bad_host = _pure.validate_profile({
            "id": "p3", "provider": "http_dir", "company": "acme",
            "endpoint": "http://127.0.0.1:8080/", "root_dir": "",
            "credentials": {"u": "x"}, "categories": ["knowledge"]}, cfg)
        self.assertIn("blocked_host", bad_host["errors"])
        self.assertIn("bad_scheme", bad_host["errors"])

        bad_root = _pure.validate_profile({
            "id": "p4", "company": "acme", "provider": "http_dir",
            "endpoint": "https://h.example.com/", "root_dir": "a/../b",
            "credentials": {"u": "x"}, "categories": ["knowledge"]}, cfg)
        self.assertIn("bad_root_dir", bad_root["errors"])

        no_company = _pure.validate_profile({
            "id": "p5", "provider": "http_dir",
            "endpoint": "https://h.example.com/", "root_dir": "",
            "credentials": {"u": "x"}, "categories": ["knowledge"]}, cfg)
        self.assertIn("bad_company", no_company["errors"])

        whitelist = {"allowed_hosts": ["oss.example.com"]}
        not_allowed = _pure.validate_profile({
            "id": "p6", "company": "acme", "provider": "s3",
            "endpoint": "https://evil.example.com/bucket", "root_dir": "",
            "credentials": {"u": "x"}, "categories": ["knowledge"]}, whitelist)
        self.assertIn("host_not_whitelisted", not_allowed["errors"])

    def test_fake_provider_roundtrip_digest(self):
        fake = _providers.build("fake")
        body = b"roundtrip-body"
        put = fake.put(self.ctx, {"endpoint": "https://x"}, "k1", body)
        self.assertTrue(put["ok"])
        got = fake.get(self.ctx, {"endpoint": "https://x"}, "k1")
        self.assertTrue(got["ok"])
        self.assertEqual(got["data"], body)
        dig = self.ctx.api.call("codec.digest", {"text": body, "algorithm": "sha256"})
        self.assertEqual(got["digest"], dig["hex"])

    def test_save_profile_masks_and_no_secret_leak(self):
        secret = "tok-A-SECRET-9f3"
        res = self._save("p-leak", secret)
        self.assertTrue(res["ok"], res)
        view = res["view"]
        self.assertNotIn(secret, str(view))
        self.assertEqual(view["credentials"], {"access_key": _pure.REDACTED})

        state_row = self.ctx.api.call("store.read", {
            "module": "agent/cloud", "path": "state.yaml"})
        state_text = str(state_row.get("value"))
        self.assertNotIn(secret, state_text)
        self.assertIn("v1:", state_text)
        self.assertNotIn(MASTER_KEY, state_text)

        audit = self.ctx.api.call("cloud.audit_list", {"limit": 20})
        self.assertNotIn(secret, str(audit))
        self.assertNotIn(MASTER_KEY, str(audit))

    def test_sync_idempotent_second_run(self):
        self._save("p-idem", "secret-idem")
        self._stage_local_file()
        first = self.ctx.api.call("cloud.sync_run",
                                   {"id": "p-idem", "caller": _global_caller()})
        self._apply(first)
        self.assertTrue(first["ok"], first["ledger"])
        self.assertGreaterEqual(first["ledger"]["added"], 1)

        second = self.ctx.api.call("cloud.sync_run",
                                   {"id": "p-idem", "caller": _global_caller()})
        self._apply(second)
        self.assertTrue(second["ok"], second["ledger"])
        self.assertEqual(second["ledger"]["added"], 0)
        self.assertGreaterEqual(second["ledger"]["skipped"], 1)
        plan = self.ctx.api.call("cloud.sync_plan", {"id": "p-idem"})
        self.assertEqual(len(plan["plan"]["to_push"]), 0)

    def test_retry_then_success_and_backoff(self):
        self.fake.fail_times = 2
        self._save("p-retry", "secret-retry")
        self._stage_local_file()
        res = self.ctx.api.call("cloud.sync_run",
                                {"id": "p-retry", "caller": _global_caller()})
        self._apply(res)
        self.assertTrue(res["ok"], res["ledger"])
        self.assertGreaterEqual(self.fake.attempts, 3)
        self.assertEqual(len(res["ledger"]["failed"]), 0)

        self.assertEqual(_pure.backoff_delay(0, 1, 30), 1)
        self.assertEqual(_pure.backoff_delay(1, 1, 30), 2)
        self.assertEqual(_pure.backoff_delay(2, 1, 30), 4)
        self.assertEqual(_pure.backoff_delay(10, 1, 30), 30)
        # 抖动值落在指数值与上限之间。
        jittered = _pure.backoff_jittered(2, 1, 30, ratio=0.5, fraction=0.5)
        self.assertGreaterEqual(jittered, 4)
        self.assertLessEqual(jittered, 30)

    def test_multi_profile_isolation(self):
        self._save("co-a", "tok-A-SECRET", company="acme-a")
        self._save("co-b", "tok-B-SECRET", company="acme-b")
        listing = self.ctx.api.call("cloud.profile_list", {})
        ids = {p["id"] for p in listing["items"]}
        self.assertTrue({"co-a", "co-b"} <= ids)

        state = self.ctx.api.call("store.read", {
            "module": "agent/cloud", "path": "state.yaml"})["value"]
        creds_a = state["profiles"]["co-a"]["credentials"]
        creds_b = state["profiles"]["co-b"]["credentials"]
        # 密封串按 AAD 绑定：A 的密封串不能用 B 的 profile 上下文解封。
        with self.assertRaises(_seal.SealError):
            _seal.open_map(self.ctx, creds_a, "co-b", "stub")
        with self.assertRaises(_seal.SealError):
            _seal.open_map(self.ctx, creds_b, "co-a", "stub")
        # 正确上下文可解封，且两家明文互不串扰。
        self.assertEqual(_seal.open_map(self.ctx, creds_a, "co-a", "stub")["access_key"],
                         "tok-A-SECRET")
        self.assertEqual(_seal.open_map(self.ctx, creds_b, "co-b", "stub")["access_key"],
                         "tok-B-SECRET")

        a = self.ctx.api.call("cloud.profile_get", {"id": "co-a"})["view"]
        b = self.ctx.api.call("cloud.profile_get", {"id": "co-b"})["view"]
        self.assertNotIn("tok-B-SECRET", str(a))
        self.assertNotIn("tok-A-SECRET", str(b))
        self.assertEqual(a["company"], "acme-a")
        self.assertEqual(b["company"], "acme-b")

        switched = self.ctx.api.call("cloud.profile_switch", {
            "id": "co-b", "caller": _global_caller()})
        self._apply(switched)
        status = self.ctx.api.call("cloud.status", {})
        self.assertEqual(status["active"], "co-b")

    def test_project_role_config_denied(self):
        caller = _project_caller()
        denied = self.ctx.api.call("cloud.profile_save", {
            "id": "x", "company": "acme", "provider": "stub",
            "endpoint": "https://x.example.com",
            "credentials": {"k": "v"}, "categories": ["knowledge"], "caller": caller})
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["code"], "forbidden_scope")

        denied_switch = self.ctx.api.call("cloud.profile_switch", {
            "id": "co-b", "caller": caller})
        self.assertEqual(denied_switch["code"], "forbidden_scope")

        denied_run = self.ctx.api.call("cloud.sync_run", {"caller": caller})
        self.assertEqual(denied_run["code"], "forbidden_scope")

        read = self.ctx.api.call("cloud.status", {})
        self.assertIn("active", read)
        proj = self.ctx.api.call("cloud.project_status", {"project": "p-demo"})
        self.assertIn("included", proj)

    def test_conflict_remote_not_overwritten(self):
        self._save("p-conflict", "secret-conflict")
        self._stage_local_file("冲突前正文")
        first = self.ctx.api.call("cloud.sync_run",
                                  {"id": "p-conflict", "caller": _global_caller()})
        self._apply(first)
        self.assertTrue(first["ok"])

        # 模拟远端被外部改动：远端摘要与上次推送不一致。
        rel = next(iter(self.fake.store))
        self.fake.store[rel] = {"data": b"remote-external", "digest": "remote-changed",
                                "size": 15}

        second = self.ctx.api.call("cloud.sync_run",
                                   {"id": "p-conflict", "caller": _global_caller()})
        self._apply(second)
        self.assertEqual(second["ledger"]["conflicts"], 1)
        self.assertEqual(len(second["ledger"]["failed"]), 0)
        # 远端未被覆盖：摘要仍是外部改动后的值。
        self.assertEqual(self.fake.store[rel]["digest"], "remote-changed")

    def test_archive_seam_degrades(self):
        seam = _archive.list_archived(self.ctx)
        self.assertIn(seam["seam"], ("wired", "adapter_unwired"))
        self.assertIsInstance(seam["rows"], list)

    def test_sanitize_key_traversal(self):
        self.assertIsNone(_pure.sanitize_key("a/../b"))
        self.assertIsNone(_pure.sanitize_key("..%2fetc"))
        self.assertIsNone(_pure.sanitize_key("/etc/passwd"))
        self.assertEqual(_pure.sanitize_key("docs/2026/a.md"), "docs/2026/a.md")


if __name__ == "__main__":
    unittest.main(verbosity=2)
