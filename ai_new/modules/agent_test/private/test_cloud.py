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

from ai_new.modules.agent.cloud.private import _pure, _providers, _archive, _seal, _guard  # noqa: E402

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

    def test_provider_contract_and_http_dir(self):
        """提供方适配层：抽象基类未实现、内存桩/HTTP 目录/占位通道、注册表与元数据。"""
        import hashlib

        class Api:
            def __init__(self, rows):
                self.rows = list(rows)
                self.calls = []

            def call(self, name, payload, caller=None):
                self.calls.append((name, payload))
                if name == "net.request":
                    row = self.rows.pop(0) if self.rows else {"ok": True}
                    if isinstance(row, Exception):
                        raise row
                    return row
                if name == "codec.digest":
                    data = payload.get("text") or b""
                    raw = data if isinstance(data, bytes) else str(data).encode()
                    return {"hex": hashlib.sha256(raw).hexdigest()}
                return {}

        class Ctx:
            def __init__(self, rows):
                self.api = Api(rows)

        base = _providers.BaseProvider()
        for fn, args in (("test_connection", (None, {})), ("list_keys", (None, {}, "")),
                         ("put", (None, {}, "k", b"")), ("get", (None, {}, "k")),
                         ("delete", (None, {}, "k"))):
            with self.assertRaises(NotImplementedError):
                getattr(base, fn)(*args)

        fake = _providers.FakeProvider()
        ctx = self.ctx
        self.assertEqual(fake.list_keys(ctx, {}, "x"), [])
        fake.put(ctx, {}, "x/a", b"a")
        self.assertEqual(fake.list_keys(ctx, {}, "x")[0]["key"], "x/a")
        self.assertEqual(fake.get(ctx, {}, "none")["code"], "not_found")
        self.assertTrue(fake.delete(ctx, {}, "x/a")["ok"])

        pending = _providers._PendingProvider("adapter_pending")
        self.assertFalse(pending.test_connection(ctx, {})["ok"])
        self.assertEqual(pending.list_keys(ctx, {}, ""), [])
        self.assertFalse(pending.put(ctx, {}, "k", b"")["ok"])
        self.assertFalse(pending.get(ctx, {}, "k")["ok"])
        self.assertFalse(pending.delete(ctx, {}, "k")["ok"])
        self.assertEqual(_providers.RsyncProvider().status_code, "exec_wrapper_pending")

        http = _providers.HttpDirProvider()
        p = {"endpoint": "https://x.example.com/", "root_dir": "r",
             "policy": {"max_body_bytes": 8}}
        self.assertTrue(http.test_connection(Ctx([{"ok": True}]), p)["ok"])
        self.assertEqual([x["key"] for x in http.list_keys(Ctx([{"ok": True, "items": [
            {"key": "a", "digest": "d", "size": 2}, {"key": "b"}]}]), p, "")],
                         ["a", "b"])
        with self.assertRaises(_guard.GuardError):
            http.put(Ctx([{"ok": True}]), p, "k", b"123456789")
        self.assertTrue(http.put(Ctx([{"ok": True}]), p, "k", b"ab")["ok"])
        self.assertEqual(http.get(Ctx([{"ok": True, "body": b"body"}]), p, "k")["data"],
                         b"body")
        self.assertEqual(http.delete(Ctx([{"ok": True}]), p, "k")["ok"], True)
        # 失败响应与跳转拦截分支。
        self.assertEqual(http.put(Ctx([{"ok": False}]), p, "k", b"a")["code"],
                         "provider_error")
        self.assertEqual(http.get(Ctx([{"ok": False}]), p, "k")["code"],
                         "provider_error")
        with self.assertRaises(_providers.ProviderError):
            http.test_connection(Ctx([{"ok": True, "location": "http://127.0.0.1/x"}]), p)

        sink = _providers._ByteSink()
        sink.write(b"a")
        sink.write(bytearray(b"b"))
        self.assertEqual(sink.data, b"ab")

        _providers.build = getattr(self._orig_build, "__func__", self._orig_build)
        try:
            self.assertIsInstance(_providers.build("fake"), _providers.FakeProvider)
            self.assertIsInstance(_providers.build("http_dir"), _providers.HttpDirProvider)
            self.assertIsInstance(_providers.build("wiki"), _providers.HttpDirProvider)
            self.assertIsInstance(_providers.build("rsync"), _providers.RsyncProvider)
            self.assertIsInstance(_providers.build("webdav"), _providers._WebDavAdapter)
            self.assertIsInstance(_providers.build("s3"), _providers._S3Adapter)
            with self.assertRaises(_providers.ProviderError):
                _providers.build("nope")
        finally:
            _providers.build = lambda kind: self.fake
        self.assertIn("s3", {m["kind"] for m in _providers.provider_meta()})

    def test_cloud_pure_edges(self):
        """cloud 纯函数：权限未知动作、缺字段校验、差分幂等/删除传播。"""
        self.assertEqual(_pure.authorize({"scope": "global"}, "no_such_action")["code"],
                         "unknown_action")
        self.assertTrue(_pure.authorize({"scope": "project"}, "status")["ok"])
        bad = _pure.validate_profile({"provider": "stub", "endpoint": "",
                                      "company": "", "root_dir": "",
                                      "credentials": {}, "categories": []}, {})
        self.assertIn("bad_company", bad["errors"])
        self.assertIn("bad_credentials", bad["errors"])
        self.assertIn("bad_categories", bad["errors"])
        ok = _pure.validate_profile({"id": "p", "provider": "stub",
                                     "endpoint": "https://x.example.com",
                                     "company": "c", "root_dir": "a/../b",
                                     "credentials": {"k": "v"},
                                     "categories": ["knowledge"]}, {})
        self.assertIn("bad_root_dir", ok["errors"])
        local = [{"rel": "a", "digest": "1"}, {"rel": "b", "digest": "2"},
                 {"rel": "c", "digest": "3"}]
        pushed = [{"rel": "a", "digest": "1"}, {"rel": "b", "digest": "0"},
                  {"rel": "d", "digest": "4"}]
        remote = {"a": {"digest": "1"}, "b": {"digest": "9"}}
        plan = _pure.diff_plan(local, pushed, remote)
        self.assertEqual([e["rel"] for e in plan["unchanged"]], ["a"])
        self.assertEqual([e["rel"] for e in plan["conflicts"]], ["b"])
        self.assertEqual([e["rel"] for e in plan["missing_remote"]], ["d"])
        self.assertEqual(plan["to_delete"], [])
        plan = _pure.diff_plan(local, pushed, {"a": {"digest": "1"},
                                                "d": {"digest": "4"}})
        self.assertEqual([e["rel"] for e in plan["to_delete"]], ["d"])

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
        self.assertEqual(res["ledger"]["failed_count"], 0)
        self.assertEqual(res["ledger"]["failed"], [])

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
        for route in ("cloud.profile_delete", "cloud.connection_test",
                      "cloud.probe_roundtrip"):
            self.assertEqual(self.ctx.api.call(route, {"id": "co-b", "caller": caller})["code"],
                             "forbidden_scope")
        self.assertTrue(self.ctx.api.call("cloud.providers", {})["items"])

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
        self.assertEqual(second["ledger"]["failed_count"], 0)
        # 远端未被覆盖：摘要仍是外部改动后的值。
        self.assertEqual(self.fake.store[rel]["digest"], "remote-changed")

    def test_profile_route_errors_and_delete(self):
        """配置路由的拒绝/更新/删除分支：非法端点、空凭证、沿用旧凭证、未知 id、删默认。"""
        bad = self._save("p-bad", "s", provider="stub")
        self.assertTrue(bad["ok"])
        # 保存时端点非法：拒绝并留 deny 审计，不落 profile。
        state = self._state()
        state["profiles"] = {}
        state["active"] = ""
        self._write_state(state)
        payload = {"id": "p-bad-ep", "company": "acme", "provider": "stub",
                   "endpoint": "file:///etc/passwd", "categories": ["knowledge"],
                   "credentials": {"k": "v"}, "caller": _global_caller()}
        res = self.ctx.api.call("cloud.profile_save", payload)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "bad_scheme")
        self.assertTrue(res["effects"])
        # 新 profile 不带凭证：拒绝。
        payload.pop("credentials")
        payload["endpoint"] = "https://oss.example.com/backup"
        res = self.ctx.api.call("cloud.profile_save", payload)
        self.assertEqual(res["code"], "bad_credentials")
        # 已存在 profile 不带凭证：沿用旧密封凭证，不报错。
        first = self._save("p-reuse", "secret-reuse")
        self.assertTrue(first["ok"], first)
        reuse = self.ctx.api.call("cloud.profile_save", {
            "id": "p-reuse", "company": "co-a", "provider": "stub",
            "endpoint": "https://oss.example.com/backup", "root_dir": "team-a",
            "categories": ["knowledge"], "caller": _global_caller()})
        self.assertTrue(reuse["ok"], reuse)
        # 空字符串凭证等价于未传。
        empty = self.ctx.api.call("cloud.profile_save", {
            "id": "p-reuse", "company": "co-a", "provider": "stub",
            "endpoint": "https://oss.example.com/backup", "root_dir": "team-a",
            "credentials": {"access_key": "   "}, "categories": ["knowledge"],
            "caller": _global_caller()})
        self.assertEqual(empty["code"], "bad_credentials")
        self.assertEqual(self.ctx.api.call("cloud.profile_get", {"id": "nope"})["code"],
                         "not_found")
        self.assertEqual(self.ctx.api.call("cloud.profile_switch", {
            "id": "nope", "caller": _global_caller()})["code"], "not_found")
        deleted = self.ctx.api.call("cloud.profile_delete", {
            "id": "p-reuse", "caller": _global_caller()})
        self.assertTrue(deleted["ok"], deleted)
        self._apply(deleted)
        self.assertEqual(self.ctx.api.call("cloud.profile_switch", {
            "id": "nope", "caller": _global_caller()})["code"], "not_found")
        self.assertEqual(self.ctx.api.call("cloud.profile_delete", {
            "id": "nope", "caller": _global_caller()})["code"], "not_found")
        state = self._state()
        self.assertEqual(state["active"], "")

    def test_connection_and_probe_paths(self):
        """连通/往返：未知 id、端点复检、密封失败、提供方错误、体积上限、成功。"""
        self.assertEqual(self.ctx.api.call("cloud.connection_test", {
            "id": "nope", "caller": _global_caller()})["code"], "not_found")
        self.assertEqual(self.ctx.api.call("cloud.probe_roundtrip", {
            "id": "nope", "caller": _global_caller()})["code"], "not_found")
        res = self._save("p-conn", "secret-conn")
        self.assertTrue(res["ok"])
        good = self.ctx.api.call("cloud.connection_test", {
            "id": "p-conn", "caller": _global_caller()})
        self.assertTrue(good["ok"], good)
        # 运行时端点复检：配置/档案被改成非法协议。
        state = self._state()
        state["profiles"]["p-conn"]["endpoint"] = "file:///etc/passwd"
        self._write_state(state)
        bad = self.ctx.api.call("cloud.connection_test", {
            "id": "p-conn", "caller": _global_caller()})
        self.assertEqual(bad["code"], "bad_scheme")
        bad = self.ctx.api.call("cloud.probe_roundtrip", {
            "id": "p-conn", "caller": _global_caller()})
        self.assertEqual(bad["code"], "bad_scheme")
        # 恢复合法端点后凭证损坏：密封层失败显式 500。
        state = self._state()
        state["profiles"]["p-conn"]["endpoint"] = "https://oss.example.com/backup"
        state["profiles"]["p-conn"]["credentials"] = {"access_key": "v1:broken:bad"}
        self._write_state(state)
        sealed = self.ctx.api.call("cloud.connection_test", {
            "id": "p-conn", "caller": _global_caller()})
        self.assertEqual(sealed["status"], 500)
        # 提供方抛错：错误码透传并留审计。先拿回合法密封凭证。
        self._save("p-conn", "secret-conn")
        orig = self.fake.test_connection
        self.fake.test_connection = lambda *a, **k: (_ for _ in ()).throw(
            _providers.ProviderError("provider_down", "down"))
        try:
            down = self.ctx.api.call("cloud.connection_test", {
                "id": "p-conn", "caller": _global_caller()})
        finally:
            self.fake.test_connection = orig
        self.assertEqual(down["code"], "provider_down")
        self.assertTrue(down["effects"])
        # 重新保存拿回合法凭证后，往返成功；体积上限命中拒绝。
        self._save("p-probe", "secret-probe")
        ok = self.ctx.api.call("cloud.probe_roundtrip", {
            "id": "p-probe", "caller": _global_caller()})
        self.assertTrue(ok["verified"], ok)
        self.assertEqual(ok["probe_key"], "cloud-probe/" + ok["probe_key"].split("/")[-1])
        state = self._state()
        state["profiles"]["p-probe"]["policy"] = {"max_body_bytes": 1}
        self._write_state(state)
        big = self.ctx.api.call("cloud.probe_roundtrip", {
            "id": "p-probe", "caller": _global_caller()})
        self.assertEqual(big["code"], "body_too_large")
        # 上传阶段失败：显式 stage=put，不进入下载。
        state = self._state()
        state["profiles"]["p-probe"]["policy"] = {}
        self._write_state(state)
        self.fake.fail_times = 99
        put_fail = self.ctx.api.call("cloud.probe_roundtrip", {
            "id": "p-probe", "caller": _global_caller()})
        self.assertEqual(put_fail["stage"], "put")
        self.assertFalse(put_fail["verified"])

    def test_sync_edges_and_prune(self):
        """同步边界：无 profile、远端清单来源、清单损坏、重试耗尽、prune 删除与阻断、清单写失败。"""
        self.assertEqual(self.ctx.api.call("cloud.sync_plan", {"id": "nope"})["code"],
                         "not_found")
        self.assertEqual(self.ctx.api.call("cloud.sync_run", {
            "id": "nope", "caller": _global_caller()})["code"], "not_found")
        self._save("p-sync", "secret-sync")
        self._stage_local_file("第一版")
        first = self.ctx.api.call("cloud.sync_run", {
            "id": "p-sync", "caller": _global_caller()})
        self._apply(first)
        self.assertTrue(first["ok"], first["ledger"])
        plan = self.ctx.api.call("cloud.sync_plan", {"id": "p-sync"})
        self.assertEqual(plan["plan"]["manifest_source"], "remote")
        # 远端清单损坏：计划回退本地缓存并标注错误。
        self.fake.store["_hive/manifest.json"]["data"] = b"{bad json"
        plan = self.ctx.api.call("cloud.sync_plan", {"id": "p-sync"})
        self.assertIn("remote_error", plan["plan"])
        # 清单写失败：对象成功但提交点失败，本轮不算成功。
        self.fake.store.pop("_hive/manifest.json")
        self.fake.fail_keys["_hive/manifest.json"] = 99
        self._stage_local_file("第二版")
        mf = self.ctx.api.call("cloud.sync_run", {
            "id": "p-sync", "caller": _global_caller()})
        self._apply(mf)
        self.assertFalse(mf["ok"])
        self.assertEqual(mf["ledger"]["manifest_error"], "transient")
        self.assertEqual(mf["ledger"]["failed_count"], 0)
        self.fake.fail_keys.pop("_hive/manifest.json", None)
        # 本地删除 + 默认不 prune：计划暴露待删，run 阻断。
        # 先修复远端清单再验证删除传播：清单缺失时计划会回退本地缓存，看不到远端残留对象。
        self.fake.fail_keys.clear()
        self.fake.fail_times = 0
        healed = self.ctx.api.call("cloud.sync_run", {
            "id": "p-sync", "caller": _global_caller(), "prune": True})
        self._apply(healed)
        self.assertTrue(healed["ok"], healed["ledger"])
        rm = self.ctx.api.call("store.remove", {"module": "agent/knowledge",
                                               "path": "sync-probe.md"})
        self.assertTrue(rm["removed"])
        plan = self.ctx.api.call("cloud.sync_plan", {"id": "p-sync"})
        self.assertTrue(plan["plan"]["to_delete"], plan)
        blocked = self.ctx.api.call("cloud.sync_run", {
            "id": "p-sync", "caller": _global_caller()})
        self._apply(blocked)
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["ledger"]["reason"], "prune_required")
        pruned = self.ctx.api.call("cloud.sync_run", {
            "id": "p-sync", "caller": _global_caller(), "prune": True})
        self._apply(pruned)
        self.assertTrue(pruned["ok"], pruned["ledger"])
        self.assertGreaterEqual(pruned["ledger"]["deleted"], 1, pruned["ledger"])
        # 重试耗尽：每个对象都瞬态失败。
        self.fake.fail_times = 99
        self._stage_local_file("第三版")
        exhausted = self.ctx.api.call("cloud.sync_run", {
            "id": "p-sync", "caller": _global_caller()})
        self._apply(exhausted)
        self.assertFalse(exhausted["ok"])
        self.assertGreaterEqual(exhausted["ledger"]["failed_count"], 1)
        self.assertEqual(exhausted["ledger"]["reason"], "retry_exhausted")

    def test_resume_recovery_and_manifest_failure_guard(self):
        """断点续传：上次 pending 快照在本轮计划里恢复并优先重传。"""
        self._save("p-resume", "secret-resume")
        entry = {"rel": "knowledge/resume.md", "category": "knowledge",
                 "module": "agent/knowledge", "source_path": "resume.md",
                 "size": 5, "digest": "d", "mtime": 0}
        self.ctx.runtime.apply({"effect": [{
            "kind": "write", "module": "agent/cloud", "path": "resume/p-resume.yaml",
            "value": {"pending": ["knowledge/resume.md"], "done": [],
                      "entries": {"knowledge/resume.md": entry}, "updated": 0}}]})
        run = self.ctx.api.call("cloud.sync_run", {
            "id": "p-resume", "caller": _global_caller()})
        self._apply(run)
        self.assertTrue(run["ok"], run["ledger"])
        self.assertIn("knowledge/resume.md", self.fake.store)

    def _state(self):
        return self.ctx.api.call("store.read", {
            "module": "agent/cloud", "path": "state.yaml"}).get("value") or {}

    def _write_state(self, state):
        self.ctx.runtime.apply({"effect": [{
            "kind": "write", "module": "agent/cloud", "path": "state.yaml",
            "value": state}]})

    def test_archive_seam_degrades(self):
        seam = _archive.list_archived(self.ctx)
        self.assertIn(seam["seam"], ("wired", "adapter_unwired"))
        self.assertIsInstance(seam["rows"], list)

    def test_guard_endpoint_and_redirect_edges(self):
        """端点/跳转校验：IPv6、缺协议、私网、白名单与相对跳转。"""
        self.assertEqual(_guard._parse_url("https://[::1]:8443/a")[:2], ("https", "::1"))
        self.assertFalse(_guard._parse_url("https://x.example.com/a")[0] == "")
        self.assertTrue(_guard.host_is_blocked(""))
        self.assertTrue(_guard.host_is_blocked("localhost."))
        self.assertTrue(_guard.host_is_blocked("127.0.0.1"))
        self.assertTrue(_guard.host_is_blocked("[::1]"))
        self.assertTrue(_guard.host_is_blocked("::ffff:127.0.0.1"))
        self.assertFalse(_guard.host_is_blocked("x.example.com"))
        self.assertIsNone(_guard.ip_is_private("not-an-ip"))
        self.assertEqual(_guard.validate_endpoint("x.example.com", {})["errors"],
                         ["bad_endpoint"])
        self.assertEqual(_guard.validate_endpoint("file:///etc/passwd", {})["errors"],
                         ["bad_scheme"])
        self.assertIn("host_not_whitelisted", _guard.validate_endpoint(
            "https://x.example.com", {"allowed_hosts": ["other.example.com"]})["errors"])
        self.assertEqual(_guard.validate_redirect("https://x.example.com", "")["errors"],
                         ["bad_redirect"])
        self.assertEqual(_guard.validate_redirect(
            "https://x.example.com", "http://127.0.0.1/x")["errors"],
            ["redirect_blocked_host"])
        self.assertEqual(_guard.validate_redirect(
            "https://x.example.com", "ftp://x.example.com/x")["errors"], ["bad_scheme"])
        self.assertTrue(_guard.validate_redirect(
            "https://x.example.com/a", "/b")["ok"])

    def test_seal_edges(self):
        """信封层：空明文、缺 crypto、格式不符、截断、篡改、密钥来源失败。"""
        with self.assertRaises(_seal.SealError) as cm:
            _seal.seal(self.ctx, "")
        self.assertEqual(cm.exception.code, "empty_secret")
        with self.assertRaises(_seal.SealError) as cm:
            _seal.open_sealed(self.ctx, "plain")
        self.assertEqual(cm.exception.code, "not_sealed")
        orig = _seal.AESGCM
        _seal.AESGCM = None
        try:
            for fn in (lambda: _seal.seal(self.ctx, "x"),
                       lambda: _seal.open_sealed(self.ctx, "v1:abc")):
                with self.assertRaises(_seal.SealError) as cm2:
                    fn()
                self.assertEqual(cm2.exception.code, "crypto_unavailable")
        finally:
            _seal.AESGCM = orig
        body = self.ctx.api.call("codec.base64_encode", {"text": b"x" * 12})["text"]
        with self.assertRaises(_seal.SealError) as cm3:
            _seal.open_sealed(self.ctx, _seal._PREFIX + ":" + body)
        self.assertEqual(cm3.exception.code, "seal_invalid")
        sealed = _seal.seal(self.ctx, "secret", "p1", "stub")
        with self.assertRaises(_seal.SealError):
            _seal.open_sealed(self.ctx, sealed, "p2", "stub")
        with self.assertRaises(_seal.SealError) as cm4:
            _seal._decode_key(self.ctx, "", "master_key_invalid")
        self.assertEqual(cm4.exception.code, "master_key_invalid")
        with self.assertRaises(_seal.SealError):
            _seal._decode_key(self.ctx, "YWJj", "master_key_invalid")
        with self.assertRaises(_seal.SealError) as cm5:
            _seal._read_key_file("/no/such/dir/key")
        self.assertEqual(cm5.exception.code, "master_key_missing")
        with self.assertRaises(_seal.SealError):
            _seal._generate_key_file(self.ctx, "/proc/forbidden/key")
        self.assertTrue(_seal.is_sealed(sealed))
        self.assertFalse(_seal.is_sealed("v1"))

    def test_cloud_helper_edges_and_tools(self):
        """云端内部接缝：jitter 退化、mtime 异常、归档条目回读、远端清单损坏、工具注册。"""
        import ai_new.modules.agent.cloud as cloud_mod

        class BadApi:
            def call(self, name, payload, caller=None):
                if name == "codec.nonce":
                    return {"token": "t"}
                if name == "codec.digest":
                    return {"hex": "nothex"}
                raise OSError("boom")

        self.assertEqual(cloud_mod._jitter_fraction(type("C", (), {"api": BadApi()})()), 0.0)
        self.assertEqual(cloud_mod._mtime(type("C", (), {"api": BadApi()})(), "m", "p"), 0.0)

        class ArchiveApi:
            def call(self, name, payload, caller=None):
                if name == "archive.read_bytes":
                    return {"value": "YWJj"}
                if name == "codec.base64_decode_bytes":
                    return {"data": b"abc"}
                return {}

        self.assertEqual(cloud_mod._read_entry_bytes(
            type("C", (), {"api": ArchiveApi()})(),
            {"archived": True, "module": "m", "source_path": "p"}), b"abc")

        # 远端清单：损坏 JSON / 版本不符 / entries 非字典 / 非法键跳过。
        for data, expect in ((b"[]", "manifest_corrupt"),
                             (b'{"version": 9, "entries": {}}', "manifest_version"),
                             (b'{"version": 1, "entries": []}', "manifest_corrupt")):
            self.fake.store["_hive/manifest.json"] = {"data": data, "digest": "d", "size": len(data)}
            res = cloud_mod._remote_manifest(self.ctx, {"id": "p", "credentials": {}},
                                             self.fake, {})
            self.assertEqual(res.get("code"), expect, res)
        self.fake.store["_hive/manifest.json"] = {
            "data": b'{"version": 1, "entries": {"../x": {"digest": "d"}, "ok": {"digest": "d"}}}',
            "digest": "d", "size": 1}
        res = cloud_mod._remote_manifest(self.ctx, {"id": "p", "credentials": {}},
                                         self.fake, {})
        self.assertEqual(list(res["entries"]), ["ok"])

        # 可通过工具注册表调用，覆盖 _tool_fn/_session_caller。
        os.environ["AI_NEW_SECRET_KEY"] = MASTER_KEY
        cloud_mod._register_tools(self.ctx)
        out = cloud_mod._tool_fn("cloud.status")(self.ctx, {}, session={
            "id": "s", "project": "p", "ticket": "", "role": "cloud-configurer"})
        self.assertIn("active", out.get("result", out))
        caller = cloud_mod._session_caller({"id": "s", "project": "p", "ticket": "T",
                                            "role": "pm"})
        self.assertEqual(caller["scope"], "ticket")

        # 审计台账坏行跳过。
        self.ctx.runtime.apply({"effect": [{
            "kind": "write", "module": "agent/cloud", "path": "audit.jsonl",
            "value": "{bad\n{\"at\": 1}\n"}]})
        self.assertEqual(len(self.ctx.api.call("cloud.audit_list", {"limit": 5})["items"]), 1)

        # 已存在 profile 但显式传空凭证：拒绝并留审计。
        self._save("p-empty", "s")
        res = self.ctx.api.call("cloud.profile_save", {
            "id": "p-empty", "company": "co-a", "provider": "stub",
            "endpoint": "https://oss.example.com/backup", "root_dir": "team-a",
            "credentials": {"access_key": "  "}, "categories": ["knowledge"],
            "caller": _global_caller()})
        self.assertEqual(res["code"], "bad_credentials")

    def test_sanitize_key_traversal(self):
        self.assertIsNone(_pure.sanitize_key("a/../b"))
        self.assertIsNone(_pure.sanitize_key("..%2fetc"))
        self.assertIsNone(_pure.sanitize_key("/etc/passwd"))
        self.assertEqual(_pure.sanitize_key("docs/2026/a.md"), "docs/2026/a.md")


if __name__ == "__main__":
    unittest.main(verbosity=2)
