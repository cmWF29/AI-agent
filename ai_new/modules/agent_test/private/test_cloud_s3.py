"""S3 通道验收：SigV4 签名互验、对象往返、分页、删除、分片、断点续传、校验和、退避重试、限流、配置者往返落库。

不连真实云：``scripts/s3_stub.py`` 在 loopback 起 HTTP 服务并**独立复算 SigV4**，
签名/规范串对不上即回 403；模块实现与 stub 两套实现互验一致才算通过。

真实凭据联调：从环境变量 ``AI_NEW_S3_ENDPOINT / AI_NEW_S3_AK / AI_NEW_S3_SK /
AI_NEW_S3_BUCKET``（可选 ``AI_NEW_S3_REGION``）读取；未配置即 ``skipTest``，不写死密钥。
"""
import base64
import http.client
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT / "scripts"))

from ai_new.modules.agent_common.boot.private._boot import _build as build  # noqa: E402
from ai_new.modules.agent_common.boot.private._context import Context  # noqa: E402
from _fixtures import stage, write_config  # noqa: E402

from s3_stub import make_server, DEFAULT_AK, DEFAULT_SK  # noqa: E402

from ai_new.modules.agent.cloud.private import _providers, _s3  # noqa: E402

MASTER_KEY = base64.b64encode(b"0" * 32).decode()
BUCKET = "bucket-a"
REAL_ENV = ("AI_NEW_S3_ENDPOINT", "AI_NEW_S3_AK", "AI_NEW_S3_SK", "AI_NEW_S3_BUCKET")


def _make_ctx(root):
    stage(root)
    write_config(root, {
        "server": {"host": "127.0.0.1", "port": 0, "token": "t"},
        "llm": {"base_url": "http://stub.local/v1", "api_key": "k", "model": "stub"},
        "tickets": {"stall_check": {"enabled": False}},
        "cloud": {"schemes": ["http", "https"], "allowed_hosts": []},
    })
    ctx = Context(root)
    build(ctx)
    return ctx


def _loopback_transport(port):
    """测试传输：经 loopback HTTP 打 stub；签名头/体原样保留，真过一遍网络栈。"""
    def transport(ctx, method, url, headers, body, timeout):
        parts = urlsplit(url)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout or 30)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        raw = body if isinstance(body, (bytes, bytearray)) else (
            b"" if body is None else str(body).encode("utf-8"))
        conn.request(method, path, body=raw, headers=dict(headers or {}))
        resp = conn.getresponse()
        data = resp.read()
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return {"ok": resp.status < 500, "status": resp.status,
                "headers": hdrs, "body": data, "text": data.decode("utf-8", "replace")}
    return transport


class S3ChannelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        os.environ["AI_NEW_DATA"] = str(root)
        os.environ["AI_NEW_SECRET_KEY"] = MASTER_KEY
        os.environ["AI_NEW_SECRET_KEY_FILE"] = str(root / "secrets.key")
        cls.ctx = _make_ctx(root)
        cls.httpd = make_server(region="us-east-1", page_size=3)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        os.environ.pop("AI_NEW_DATA", None)
        os.environ.pop("AI_NEW_SECRET_KEY", None)
        os.environ.pop("AI_NEW_SECRET_KEY_FILE", None)
        shutil.rmtree(cls.tmp.name, ignore_errors=True)

    def setUp(self):
        store = self.httpd.s3_store
        store.objects = {}
        store.uploads = {}
        store.fail_429 = 0
        store.requests = []
        # 实例字典持有原始函数：避免类命名空间函数经实例访问被描述符绑定。
        self.transport = _loopback_transport(self.port)

    # ---- 夹具 ----

    def _client(self, policy=None, credentials=None):
        profile = {"endpoint": "http://127.0.0.1:%d" % self.port,
                   "root_dir": BUCKET, "policy": policy or {}}
        creds = credentials or {"access_key": DEFAULT_AK, "secret_key": DEFAULT_SK,
                                "region": "us-east-1", "bucket": BUCKET}
        return _s3.S3Client(self.ctx, profile, creds, transport=self.transport)

    def _capturing_transport(self):
        captured = {}

        def transport(ctx, method, url, headers, body, timeout):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = dict(headers or {})
            captured["body"] = bytes(body or b"")
            return self.transport(ctx, method, url, headers, body, timeout)

        return transport, captured

    # ---- 用例 ----

    def test_connection_and_empty_list(self):
        client = self._client()
        probe = client.test_connection()
        self.assertTrue(probe["ok"], probe)
        self.assertEqual(client.list_keys(""), [])

    def test_put_get_head_roundtrip(self):
        client = self._client()
        body = "hello-s3-云端往返".encode("utf-8")
        put = client.put("docs/note.txt", body)
        self.assertTrue(put["ok"], put)
        self.assertEqual(put["size"], len(body))

        got = client.get("docs/note.txt")
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["data"], body)
        self.assertEqual(got["digest"], put["digest"])

        head = client.head("docs/note.txt")
        self.assertTrue(head["ok"], head)
        self.assertEqual(head["size"], len(body))
        self.assertTrue(head["checksum"])

    def test_list_pagination(self):
        client = self._client()
        for i in range(5):
            res = client.put("page/key-%d" % i, ("v%d" % i).encode("utf-8"))
            self.assertTrue(res["ok"], res)
        rows = client.list_keys("page/")
        self.assertEqual(len(rows), 5)
        self.assertEqual(sorted(r["key"] for r in rows),
                         ["page/key-%d" % i for i in range(5)])

    def test_delete_object(self):
        client = self._client()
        client.put("trash/old.bin", b"old")
        self.assertTrue(client.delete("trash/old.bin")["ok"])
        got = client.get("trash/old.bin")
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "not_found")

    def test_multipart_upload_assembles(self):
        policy = {"multipart_threshold": 32, "multipart_min_size": 16,
                  "max_attempts": 3, "backoff_base_s": 0, "backoff_cap_s": 0}
        client = self._client(policy=policy)
        body = (b"multi-part-body-" * 8)[:100]
        put = client.put("big/archive.bin", body)
        self.assertTrue(put["ok"], put)
        self.assertEqual(len(put["parts"]), 3)

        got = client.get("big/archive.bin")
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["data"], body)
        self.assertEqual(got["digest"], put["digest"])

    def test_multipart_resume_skips_done_parts(self):
        policy = {"multipart_threshold": 32, "multipart_min_size": 16,
                  "max_attempts": 3, "backoff_base_s": 0, "backoff_cap_s": 0}
        # 首轮中断即失败，不重试；失败请求仍计入 stub 请求日志。
        fail_policy = dict(policy, max_attempts=1)
        client = self._client(policy=policy)
        body = (b"resume-part-" * 8)[:100]

        # 第一轮：第 2 片上传被打回 500，中断在途分片；回传断点状态。
        store = self.httpd.s3_store
        orig_request = self.transport

        def flaky(ctx, method, url, headers, body, timeout):
            if "partNumber=2" in url:
                parts = urlsplit(url)
                path = parts.path + ("?" + parts.query if parts.query else "")
                store.record("PUT", path, 500)
                return {"ok": False, "status": 500, "headers": {}, "body": b"",
                        "text": "boom"}
            return orig_request(ctx, method, url, headers, body, timeout)

        flaky_client = _s3.S3Client(
            self.ctx, {"endpoint": "http://127.0.0.1:%d" % self.port,
                       "root_dir": BUCKET, "policy": fail_policy},
            {"access_key": DEFAULT_AK, "secret_key": DEFAULT_SK,
             "region": "us-east-1", "bucket": BUCKET},
            transport=flaky)
        failed = flaky_client.put("resume/archive.bin", body)
        self.assertFalse(failed["ok"])
        self.assertTrue(failed["upload_id"])
        self.assertIn("1", failed["parts"])
        self.assertNotIn("2", failed["parts"])

        # 第二轮：带断点续跑；已完成分片跳过，只补缺片后合并。
        resume = {"upload_id": failed["upload_id"], "parts": failed["parts"]}
        resumed = client.put("resume/archive.bin", body, resume=resume)
        self.assertTrue(resumed["ok"], resumed)
        self.assertEqual(resumed["digest"], client._digest_of(self.ctx, body))

        got = client.get("resume/archive.bin")
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["data"], body)

        # 第 2 片在 stub 请求里出现两次：首次失败 + 续跑补发。
        part2 = [r for r in store.requests if "partNumber=2" in r["path"]]
        self.assertEqual(len(part2), 2)

    def test_checksum_mismatch_reports_error(self):
        client = self._client()
        body = b"integrity-payload"
        self.assertTrue(client.put("integ/obj.bin", body)["ok"])
        # 远端对象被外部改动（字节变了，校验和头仍旧）→ 下载摘要比对必须报错。
        self.httpd.s3_store.objects["integ/obj.bin"]["data"] = b"tampered-payload-x"
        got = client.get("integ/obj.bin")
        self.assertFalse(got["ok"])
        self.assertEqual(got["code"], "checksum_mismatch")

    def test_429_backoff_retry_then_success(self):
        policy = {"max_attempts": 3, "backoff_base_s": 0, "backoff_cap_s": 0}
        client = self._client(policy=policy)
        store = self.httpd.s3_store
        store.fail_429 = 2
        store.retry_after = "0"

        put = client.put("retry/probe.txt", b"retry-me")
        self.assertTrue(put["ok"], put)
        statuses = [r["status"] for r in store.requests]
        self.assertEqual(statuses[:3], [429, 429, 200])
        got = client.get("retry/probe.txt")
        self.assertTrue(got["ok"])

    def test_signature_format_and_wrong_secret_rejected(self):
        transport, captured = self._capturing_transport()
        client = _s3.S3Client(
            self.ctx, {"endpoint": "http://127.0.0.1:%d" % self.port,
                       "root_dir": BUCKET, "policy": {}},
            {"access_key": DEFAULT_AK, "secret_key": DEFAULT_SK,
             "region": "us-east-1", "bucket": BUCKET},
            transport=transport)
        client.list_keys("fmt/")

        auth = captured["headers"]["Authorization"]
        self.assertTrue(auth.startswith("AWS4-HMAC-SHA256 Credential=%s/" % DEFAULT_AK))
        self.assertIn("/us-east-1/s3/aws4_request,", auth)
        self.assertIn("SignedHeaders=host;", auth)
        self.assertIn("x-amz-date", auth)
        self.assertIn("x-amz-content-sha256", auth)
        signature = auth.rsplit("Signature=", 1)[1]
        self.assertEqual(len(signature), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in signature))
        # 签名头齐备且时间戳规范。
        self.assertTrue(captured["headers"]["x-amz-date"].endswith("Z"))
        self.assertEqual(len(captured["headers"]["x-amz-date"]), 16)

        # 错误密钥：stub 独立复算签名不符 → 403 signature_mismatch。
        bad = self._client(credentials={"access_key": DEFAULT_AK,
                                        "secret_key": "wrong-secret",
                                        "region": "us-east-1", "bucket": BUCKET})
        res = bad.list_keys("fmt/")
        self.assertEqual(res, [])
        probe = bad.test_connection()
        self.assertFalse(probe["ok"])
        self.assertEqual(probe["code"], "signature_mismatch")

    def test_lazy_providers_wire_channels(self):
        s3_provider = _providers.build("s3")
        self.assertIsInstance(s3_provider, _providers._S3Adapter)
        dav_provider = _providers.build("webdav")
        self.assertIsInstance(dav_provider, _providers._WebDavAdapter)
        with self.assertRaises(_providers.ProviderError):
            _providers.build("no_such_kind")

    def test_rate_gate_accepts_configured_limits(self):
        policy = {"concurrency": 1, "rate_per_s": 50, "max_attempts": 2,
                  "backoff_base_s": 0, "backoff_cap_s": 0}
        client = self._client(policy=policy)
        for i in range(3):
            res = client.put("rate/key-%d" % i, ("r%d" % i).encode())
            self.assertTrue(res["ok"], res)
        self.assertEqual(len(client.list_keys("rate/")), 3)

    @unittest.skipUnless(all(os.environ.get(v) for v in REAL_ENV),
                         "未配置真实 S3 凭据（AI_NEW_S3_ENDPOINT/AK/SK/BUCKET）")
    def test_real_endpoint_roundtrip(self):
        profile = {"endpoint": os.environ["AI_NEW_S3_ENDPOINT"],
                   "root_dir": os.environ["AI_NEW_S3_BUCKET"], "policy": {}}
        creds = {"access_key": os.environ["AI_NEW_S3_AK"],
                 "secret_key": os.environ["AI_NEW_S3_SK"],
                 "region": os.environ.get("AI_NEW_S3_REGION") or "us-east-1",
                 "bucket": os.environ["AI_NEW_S3_BUCKET"]}
        client = _s3.S3Client(self.ctx, profile, creds)
        nonce = self.ctx.api.call("codec.nonce", {"length": 16},
                                  caller=None).get("token") or "probe"
        key = "cloud-probe/%s" % nonce
        body = ("probe:" + nonce).encode("utf-8")
        put = client.put(key, body)
        self.assertTrue(put["ok"], put)
        got = client.get(key)
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["digest"], put["digest"])
        self.assertTrue(client.delete(key)["ok"])


class S3ConfigRoundTripTest(unittest.TestCase):
    """配置者真实往返：保存 profile（密封凭证）→ 连通 → 写入→读回校验和→列目录，结果落库 + 审计。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        os.environ["AI_NEW_DATA"] = str(root)
        os.environ["AI_NEW_SECRET_KEY"] = MASTER_KEY
        os.environ["AI_NEW_SECRET_KEY_FILE"] = str(root / "secrets.key")
        cls.ctx = _make_ctx(root)
        cls.httpd = make_server(region="us-east-1", page_size=3)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        os.environ.pop("AI_NEW_DATA", None)
        os.environ.pop("AI_NEW_SECRET_KEY", None)
        os.environ.pop("AI_NEW_SECRET_KEY_FILE", None)
        shutil.rmtree(cls.tmp.name, ignore_errors=True)

    def setUp(self):
        store = self.httpd.s3_store
        store.objects = {}
        store.uploads = {}
        store.fail_429 = 0
        store.requests = []
        self.transport = _loopback_transport(self.port)
        self._orig_build = _providers.build
        # 路由层构造提供方时注入 loopback 传输；端点用占位域名过 Guard，传输层改写回环。
        _providers.build = lambda kind: _providers._S3Adapter(transport=self.transport)

    def tearDown(self):
        _providers.build = self._orig_build

    def _apply(self, res):
        effects = (res or {}).get("effects") or []
        if effects:
            self.ctx.runtime.apply({"effect": effects})

    def test_profile_save_connection_probe_persisted(self):
        caller = {"scope": "global", "project": "", "ticket": "",
                  "session": "admin-s1", "role": "admin"}
        endpoint = "http://cloud-stub.local:%d" % self.port
        save = self.ctx.api.call("cloud.profile_save", {
            "id": "s3-main", "company": "acme", "provider": "s3",
            "endpoint": endpoint, "root_dir": BUCKET,
            "credentials": {"access_key": DEFAULT_AK, "secret_key": DEFAULT_SK,
                            "region": "us-east-1", "bucket": BUCKET},
            "categories": ["knowledge"],
            "policy": {"multipart_threshold": 32, "multipart_min_size": 16,
                       "max_attempts": 3, "backoff_base_s": 0, "backoff_cap_s": 0},
            "caller": caller})
        self.assertTrue(save["ok"], save)
        self._apply(save)
        # 视图凭证脱敏：密钥不进响应。
        self.assertNotIn(DEFAULT_SK, str(save["view"]))

        conn = self.ctx.api.call("cloud.connection_test",
                                 {"id": "s3-main", "caller": caller})
        self._apply(conn)
        self.assertTrue(conn["ok"], conn)

        probe = self.ctx.api.call("cloud.probe_roundtrip",
                                  {"id": "s3-main", "caller": caller})
        self._apply(probe)
        self.assertTrue(probe["verified"], probe)
        self.assertEqual(probe["remote_digest"], probe["expected_digest"])

        # 状态落库：profile 在台账中；审计记录连通与往返两条。
        state = self.ctx.api.call("store.read", {
            "module": "agent/cloud", "path": "state.yaml"})["value"]
        self.assertIn("s3-main", state["profiles"])
        self.assertEqual(state["profiles"]["s3-main"]["provider"], "s3")

        audit = self.ctx.api.call("cloud.audit_list", {"limit": 20})
        actions = {e["action"] for e in audit["items"]}
        self.assertIn("connection_test", actions)
        self.assertIn("probe_roundtrip", actions)
        decisions = {e["action"]: e["decision"] for e in audit["items"]}
        self.assertEqual(decisions["connection_test"], "allow")
        self.assertEqual(decisions["probe_roundtrip"], "allow")

        status = self.ctx.api.call("cloud.status", {})
        self.assertTrue(status["configured"])
        self.assertEqual(status["active"], "s3-main")


if __name__ == "__main__":
    unittest.main(verbosity=2)
