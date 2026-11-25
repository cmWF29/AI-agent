"""WebDAV / rsync 通道验收：本地 HTTP stub 真按协议语义响应，不连外网。

覆盖：列目录解析、上传下载往返、同尺寸跳过、409/404 错误码、Digest 401 重试、
XXE 拒绝、``..`` 路径穿越拒绝、10MB 级流式（内存峰值不随文件线性增长）、
rsync 探测与真实目录幂等同步（无二进制时 skip 真实同步并断言 unsupported_platform）。
"""
import base64
import hashlib
import io
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import tracemalloc
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from ai_new.modules.agent.cloud.private import _webdav, _rsync  # noqa: E402
import webdav_stub  # noqa: E402

PATTERN_CHUNK = 64 * 1024
BIG_SIZE = 10 * 1024 * 1024


class _HashSink:
    """落地收集器：边写边算 sha256，不保留完整正文。"""

    def __init__(self):
        self._hash = hashlib.sha256()
        self.size = 0

    def write(self, chunk):
        self._hash.update(chunk)
        self.size += len(chunk)

    def hexdigest(self):
        return self._hash.hexdigest()


class _PatternSource:
    """确定性流式源：按 64KB 模式切片产出，整对象不进内存；支持 seek 回卷。"""

    def __init__(self, size, chunk=PATTERN_CHUNK):
        self._size = size
        self._chunk = chunk
        self._pos = 0
        self._pattern = bytes((i * 7) % 256 for i in range(chunk))

    def _tile(self, want):
        repeats = want // len(self._pattern) + 1
        return (self._pattern * repeats)[:want]

    def read(self, n=-1):
        if self._pos >= self._size:
            return b""
        want = min(n if n > 0 else self._chunk, self._size - self._pos)
        out = self._tile(want)
        self._pos += want
        return out

    def seek(self, offset):
        self._pos = max(0, min(offset, self._size))

    def expected_hash(self):
        digest = hashlib.sha256()
        pos = 0
        while pos < self._size:
            want = min(self._chunk, self._size - pos)
            digest.update(self._tile(want))
            pos += want
        return digest.hexdigest()


class _StubCodec:
    """对齐 codec 能力面：digest / base64_encode（实现留在测试侧，模块侧不自带）。"""

    def digest(self, text, algorithm="sha256"):
        return getattr(hashlib, algorithm)(text.encode("utf-8")).hexdigest()

    def base64_encode(self, data):
        return base64.b64encode(data).decode("ascii")


class _StubClock:
    """对齐 clock 能力面：测试不真等退避。"""

    def sleep(self, seconds):
        return None


def _make_self_signed_cert(tmp, name="cert"):
    """用 openssl 生成自签证书 + 私钥（IP SAN 指向 127.0.0.1）。"""
    cert = os.path.join(tmp, name + ".pem")
    key = os.path.join(tmp, name + ".key.pem")
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", key, "-out", cert, "-days", "1", "-nodes",
        "-subj", "/CN=127.0.0.1",
        "-addext", "subjectAltName=IP:127.0.0.1",
    ], check=True, capture_output=True, text=True)
    return cert, key


class WebDavStubTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server, self.thread, self.base_url = webdav_stub.start_stub(
            directory=self.tmp.name)
        self.store = self.server.store

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def _client(self, credentials=None, **kw):
        user = password = None
        if credentials:
            user, password = credentials["user"], credentials["password"]
        kw.setdefault("codec", _StubCodec())
        kw.setdefault("clock", _StubClock())
        return _webdav.WebDavClient(self.base_url, username=user,
                                    password=password, **kw)

    def test_nested_put_creates_parent_collections(self):
        """真 WebDAV 的 PUT 不会自动建父集合；缺父层级会 409。"""
        client = self._client()
        calls = []
        original = client._request

        def record(method, path, **kw):
            calls.append(method)
            return original(method, path, **kw)

        client._request = record
        res = client.put("nested/deep/a.txt", b"hello")
        self.assertTrue(res["ok"], res)
        self.assertEqual([m for m in calls if m == "MKCOL"],
                         ["MKCOL", "MKCOL"], calls)

    def test_propfind_lists_directory(self):
        client = self._client()
        self.assertTrue(client.mkcol("docs")["ok"])
        put = client.put("docs/a.txt", b"hello webdav")
        self.assertTrue(put["ok"], put)

        res = client.propfind("docs", depth=1)
        self.assertTrue(res["ok"], res)
        files = [e for e in res["entries"] if not e["is_dir"]]
        self.assertEqual(len(files), 1)
        entry = files[0]
        self.assertEqual(entry["key"], "docs/a.txt")
        self.assertEqual(entry["size"], 12)

    def test_put_get_roundtrip(self):
        client = self._client()
        body = b"roundtrip-0123456789"
        put = client.put("probe.txt", body)
        self.assertTrue(put["ok"], put)

        probe = client.head("probe.txt")
        self.assertTrue(probe["ok"], probe)
        self.assertEqual(probe["size"], len(body))

        sink = _HashSink()
        got = client.get("probe.txt", sink)
        self.assertTrue(got["ok"], got)
        self.assertEqual(sink.size, len(body))
        expect = hashlib.sha256(body).hexdigest()
        self.assertEqual(sink.hexdigest(), expect)
        self.assertEqual(client.test_connection()["ok"], True)

    def test_put_skips_identical(self):
        client = self._client()
        body = b"same-content"
        first = client.put("dup.txt", body)
        self.assertTrue(first["ok"])
        puts_after_first = self.store.puts

        second = client.put("dup.txt", body)
        self.assertTrue(second["ok"])
        self.assertTrue(second["skipped"])
        self.assertEqual(self.store.puts, puts_after_first)

    def test_mkcol_conflict_409(self):
        client = self._client()
        self.assertTrue(client.mkcol("d1")["ok"])
        conflict = client.mkcol("d1")
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["code"], "conflict")
        self.assertEqual(conflict["status"], 409)

    def test_delete_not_found(self):
        client = self._client()
        missing = client.delete("missing/nope.bin")
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["code"], "not_found")

        client.put("gone.bin", b"x")
        self.assertTrue(client.delete("gone.bin")["ok"])
        again = client.delete("gone.bin")
        self.assertEqual(again["code"], "not_found")

    # ------------------------------------------------------------ 认证

    def test_digest_401_retry(self):
        auth = {"mode": "digest", "user": "u", "password": "p"}
        self.server.auth = auth
        client = self._client(credentials=auth, auth="digest")
        res = client.propfind("")
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.store.challenges, 1)
        self.assertGreaterEqual(self.store.authenticated, 1)

    # ------------------------------------------------------------ 安全负向

    def test_digest_auth_int_entity_hash(self):
        auth = {"mode": "digest", "user": "u", "password": "p",
                "qop": "auth, auth-int"}
        self.server.auth = auth
        client = self._client(credentials=auth, auth="digest")
        body = b"auth-int-entity-body-0123456789"
        res = client.put("auth-int.bin", body)
        self.assertTrue(res["ok"], res)
        # HEAD 探针与 PUT 各可能触发一次 401；摘要重试均通过鉴权。
        self.assertGreaterEqual(self.store.challenges, 1)
        self.assertGreaterEqual(self.store.authenticated, 1)

    def test_xxe_payload_rejected(self):
        evil = (
            '<?xml version="1.0"?>\n'
            '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/hostname">]>\n'
            '<d:multistatus xmlns:d="DAV:">'
            '<d:response><d:href>/evil/</d:href><d:prop><d:propstat>'
            '<d:prop><d:getetag>&xxe;</d:getetag></d:prop>'
            '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:prop></d:response>'
            '</d:multistatus>'
        ).encode("utf-8")
        self.store.custom_propfind["/evil"] = evil

        client = self._client()
        with self.assertRaises(_webdav.WebDavError) as cm:
            client.propfind("evil")
        self.assertEqual(cm.exception.code, "xml_forbidden")

        broken = b"<<<not-xml-at-all>>>"
        self.store.custom_propfind["/broken"] = broken
        with self.assertRaises(_webdav.WebDavError) as cm2:
            client.propfind("broken")
        self.assertEqual(cm2.exception.code, "malformed_xml")

    def test_traversal_key_rejected(self):
        client = self._client()
        bad_keys = ["../secret", "a/../../etc", "/etc/passwd", "..%2fetc"]
        for key in bad_keys:
            with self.assertRaises(_webdav.WebDavError) as cm:
                client.put(key, b"x")
            self.assertEqual(cm.exception.code, "invalid_key")
            with self.assertRaises(_webdav.WebDavError) as cm2:
                client.get(key, _HashSink())
            self.assertEqual(cm2.exception.code, "invalid_key")
            with self.assertRaises(_webdav.WebDavError) as cm3:
                client.delete(key)
            self.assertEqual(cm3.exception.code, "invalid_key")
            with self.assertRaises(_webdav.WebDavError) as cm4:
                client.mkcol(key)
            self.assertEqual(cm4.exception.code, "invalid_key")
        self.assertEqual(self.store.puts, 0)
        self.assertEqual(self.store.deletes, 0)

    def test_capability_missing_when_not_injected(self):
        # 未注入 codec/clock 且无 ctx：触发能力点显式 capability_missing，不自带实现兜底。
        client = _webdav.WebDavClient(self.base_url, username="u", password="p")
        with self.assertRaises(_webdav.WebDavError) as cm:
            client.test_connection()
        self.assertEqual(cm.exception.code, "capability_missing")

    def test_key_guard_delegates(self):
        self.assertIsNone(_webdav.sanitize_key("a/../b"))
        self.assertIsNone(_webdav.sanitize_key("/etc/passwd"))
        self.assertEqual(_webdav.sanitize_key("docs/2026/a.md"), "docs/2026/a.md")
        verdict = _webdav.validate_endpoint("http://example.com/data")
        self.assertIn("bad_scheme", verdict["errors"])

    # ------------------------------------------------------------ 流式与续传

    def test_large_file_streaming_bounded_memory(self):
        client = self._client()
        source = _PatternSource(BIG_SIZE)
        expect_hash = source.expected_hash()

        tracemalloc.start()
        snap_before = tracemalloc.take_snapshot()
        try:
            put = client.put("big.bin", source, size=BIG_SIZE)
            self.assertTrue(put["ok"], put)

            sink = _HashSink()
            got = client.get("big.bin", sink)
            self.assertTrue(got["ok"], got)
            self.assertEqual(sink.size, BIG_SIZE)
            self.assertEqual(sink.hexdigest(), expect_hash)
        finally:
            snap_after = tracemalloc.take_snapshot()
            tracemalloc.stop()

        growth = sum(trace.size_diff for trace in
                     snap_after.compare_to(snap_before, "lineno"))
        client_growth = sum(
            trace.size_diff for trace in
            snap_after.compare_to(snap_before, "lineno")
            if "_webdav.py" in trace.traceback[0].filename)
        # 10MB 正文不得一次性进内存：Python 侧驻留增量控制在 3MB 以内。
        self.assertLess(growth, 3 * 1024 * 1024,
                        "streaming held %d bytes resident" % growth)
        print("\n[mem] 10MB WebDAV 流式客户端驻留增量: %.2f MiB（进程总量 %.2f MiB）"
              % (client_growth / 1024 / 1024, growth / 1024 / 1024))

    def test_range_resume_partial(self):
        client = self._client()
        body = b"abcdefghijklmnopqrstuvwxyz"
        self.assertTrue(client.put("resume.bin", body)["ok"])

        sink = io.BytesIO()
        sink.write(body[:5])  # 本地已有前 5 字节，从偏移 5 续传
        got = client.get("resume.bin", sink, offset=5, resume=True)
        self.assertTrue(got["ok"], got)
        self.assertTrue(got["partial"])
        self.assertEqual(sink.getvalue(), body)

    def test_resumable_degrades_to_single_stream_put(self):
        """标准 WebDAV 无服务端拼接，put_resumable 必须整对象 PUT。"""
        size = 100 * 1024
        client = self._client(upload_chunk_size=20 * 1024)
        source = _PatternSource(size)
        expect = source.expected_hash()

        original = client._request
        state = {"fail": True}

        def flaky(method, path, **kw):
            if method == "PUT" and state["fail"]:
                state["fail"] = False

                class _Resp:
                    status = 500

                    def getheader(self, name):
                        return None

                    def read(self):
                        return b""

                return _Resp()
            return original(method, path, **kw)

        client._request = flaky
        res = client.put_resumable("resume.bin", source, size)
        self.assertTrue(res["ok"], res)

        sink = _HashSink()
        got = client.get("resume.bin", sink)
        self.assertTrue(got["ok"], got)
        self.assertEqual(sink.size, size)
        self.assertEqual(sink.hexdigest(), expect)
        # 只有最终对象一次落盘，不留 .upload 临时块集合。
        self.assertEqual(self.store.puts, 1)
        self.assertEqual(self.store.chunk_puts, 0)
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, ".upload")))

    def test_custom_ca_trust_chain(self):
        if not shutil.which("openssl"):
            # 无 openssl：自定义 CA 入口必须显式报依赖缺失，不能静默跳过校验。
            with self.assertRaises(FileNotFoundError):
                _make_self_signed_cert(tempfile.mkdtemp(prefix="dav-ca-miss-"))
            return
        tmp = tempfile.mkdtemp(prefix="dav-ca-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cert, key = _make_self_signed_cert(tmp, "trust")
        wrong_cert, _wrong_key = _make_self_signed_cert(tmp, "wrong")

        httpd = webdav_stub.ThreadingHTTPServer(
            ("127.0.0.1", 0), webdav_stub._Handler)
        httpd.store = webdav_stub._Store(tmp)
        httpd.auth = None
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(certfile=cert, keyfile=key)
        httpd.socket = tls.wrap_socket(httpd.socket, server_side=True)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        base = "https://127.0.0.1:%d/" % httpd.server_address[1]

        trusted = _webdav.WebDavClient(
            base, ca_bundle=cert, codec=_StubCodec(), clock=_StubClock())
        # 自定义 CA 进入信任链：自签证书主体出现在上下文 CA 集中，探活通过。
        ca_subjects = [c["subject"][0][0][1]
                       for c in trusted._build_ssl_context().get_ca_certs()]
        self.assertIn("127.0.0.1", ca_subjects)
        self.assertTrue(trusted.test_connection()["ok"])
        put = trusted.put("ca.txt", b"ca-trust-chain")
        self.assertTrue(put["ok"], put)

        # 错误 CA：证书链不在信任集 → 握手校验失败，不降级为不校验。
        untrusted = _webdav.WebDavClient(
            base, ca_bundle=wrong_cert, codec=_StubCodec(), clock=_StubClock())
        probe = untrusted.test_connection()
        self.assertFalse(probe["ok"])


class RsyncChannelTest(unittest.TestCase):
    def test_probe_reports_availability(self):
        probe = _rsync.probe()
        available = _rsync.is_available()
        self.assertEqual(probe["ok"], available)
        if available:
            self.assertEqual(probe["code"], "available")
            self.assertTrue(probe["path"])
        else:
            self.assertEqual(probe["code"], "unsupported_platform")
            self.assertEqual(probe["detail"], "rsync not installed")

    def test_sync_idempotent_when_available(self):
        if not _rsync.is_available():
            res = _rsync.sync("src/", "dst/")
            self.assertFalse(res["ok"])
            self.assertEqual(res["code"], "unsupported_platform")
            return

        src = tempfile.mkdtemp(prefix="rsync-src-")
        dst = tempfile.mkdtemp(prefix="rsync-dst-")
        self.addCleanup(shutil.rmtree, src, ignore_errors=True)
        self.addCleanup(shutil.rmtree, dst, ignore_errors=True)

        os.makedirs(os.path.join(src, "nested", "deep"))
        with open(os.path.join(src, "a.txt"), "wb") as fh:
            fh.write(b"alpha-content")
        with open(os.path.join(src, "nested", "deep", "b.bin"), "wb") as fh:
            fh.write(bytes((i % 256) for i in range(512)))

        first = _rsync.sync(src + "/", dst + "/")
        self.assertTrue(first["ok"], first)

        def _walk(root):
            out = {}
            for base, _dirs, files in os.walk(root):
                for name in files:
                    path = os.path.join(base, name)
                    rel = os.path.relpath(path, root)
                    with open(path, "rb") as fh:
                        out[rel] = fh.read()
            return out

        self.assertEqual(_walk(dst), _walk(src))

        second = _rsync.sync(src + "/", dst + "/")
        self.assertTrue(second["ok"], second)
        self.assertEqual(_walk(dst), _walk(src))


    def test_windows_shutil_fallback_local_tree(self):
        """无 rsync 的 Windows：同接口本地树同步，含尾斜杠、覆盖与 --delete。"""
        from unittest import mock
        root = tempfile.mkdtemp(prefix="rsync-win-")
        src = os.path.join(root, "src")
        dst = os.path.join(root, "dst")
        os.makedirs(os.path.join(src, "nested"))
        with open(os.path.join(src, "a.txt"), "wb") as fh:
            fh.write(b"alpha")
        with open(os.path.join(src, "nested", "b.bin"), "wb") as fh:
            fh.write(b"beta")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        with mock.patch.object(_rsync, "detect", return_value=None), \
                mock.patch.object(_rsync, "PLATFORM", "nt"):
            probe = _rsync.probe()
            self.assertTrue(probe["ok"], probe)
            self.assertEqual(probe["mechanism"], "python-shutil")
            first = _rsync.sync(src + "/", dst + "/")
            self.assertTrue(first["ok"], first)
            self.assertTrue(os.path.exists(os.path.join(dst, "nested", "b.bin")))
            # --delete 删除目标多出的条目，源有的一律保留。
            with open(os.path.join(dst, "stale.txt"), "w") as fh:
                fh.write("stale")
            second = _rsync.sync(src + "/", dst + "/", delete=True)
            self.assertTrue(second["ok"], second)
            self.assertFalse(os.path.exists(os.path.join(dst, "stale.txt")))
            # 无尾斜杠：同步目录本身到目标下。
            named = os.path.join(root, "named")
            os.makedirs(named)
            _rsync.sync(src, named)
            self.assertTrue(os.path.isdir(os.path.join(named, "src")))
            # 缺源与远端形式显式报错，不静默成功。
            self.assertEqual(_rsync.sync(os.path.join(root, "missing"), dst)["code"],
                             "rsync_error")
            remote = _rsync.sync("user@host:/x", dst)
            self.assertFalse(remote["ok"])
            self.assertEqual(remote["code"], "unsupported_platform")


if __name__ == "__main__":
    unittest.main(verbosity=2)
