"""SSRF / 协议 / 路径穿越 / 体积上限负向用例：每条断言对应一类拒绝面。

纯函数校验，不联网、不碰盘（符号链接用例在临时目录内构造）。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent.cloud.private import _guard  # noqa: E402


class ProtocolTest(unittest.TestCase):
    def test_http_rejected_by_default(self):
        res = _guard.validate_endpoint("http://example.com/data")
        self.assertIn("bad_scheme", res["errors"])

    def test_https_allowed(self):
        res = _guard.validate_endpoint("https://example.com/data")
        self.assertTrue(res["ok"], res["errors"])

    def test_file_scheme_rejected(self):
        res = _guard.validate_endpoint("file:///etc/passwd")
        self.assertIn("bad_scheme", res["errors"])

    def test_missing_scheme_rejected(self):
        res = _guard.validate_endpoint("example.com/data")
        self.assertIn("bad_endpoint", res["errors"])


class HostBlockTest(unittest.TestCase):
    def test_loopback_v4_blocked(self):
        self.assertTrue(_guard.host_is_blocked("127.0.0.1"))

    def test_loopback_v6_blocked(self):
        self.assertTrue(_guard.host_is_blocked("::1"))

    def test_localhost_blocked(self):
        self.assertTrue(_guard.host_is_blocked("localhost"))

    def test_zero_address_blocked(self):
        self.assertTrue(_guard.host_is_blocked("0.0.0.0"))

    def test_private_10_blocked(self):
        self.assertTrue(_guard.host_is_blocked("10.0.0.5"))

    def test_private_172_16_blocked(self):
        self.assertTrue(_guard.host_is_blocked("172.16.4.4"))

    def test_private_172_31_blocked(self):
        self.assertTrue(_guard.host_is_blocked("172.31.255.255"))

    def test_private_192_168_blocked(self):
        self.assertTrue(_guard.host_is_blocked("192.168.1.1"))

    def test_link_local_blocked(self):
        self.assertTrue(_guard.host_is_blocked("169.254.169.254"))

    def test_ipv6_ula_blocked(self):
        self.assertTrue(_guard.host_is_blocked("fc00::1"))
        self.assertTrue(_guard.host_is_blocked("fd00::1"))

    def test_ipv6_link_local_blocked(self):
        self.assertTrue(_guard.host_is_blocked("fe80::1"))

    def test_public_ip_not_blocked(self):
        self.assertFalse(_guard.host_is_blocked("8.8.8.8"))

    def test_domain_not_resolved_here(self):
        # 域名不在纯校验层做 DNS；解析私网由解析接缝回填后用 ip_is_private 判定。
        self.assertFalse(_guard.host_is_blocked("example.com"))


class DnsResultTest(unittest.TestCase):
    def test_resolved_private_ip_rejected(self):
        self.assertTrue(_guard.ip_is_private("10.2.3.4"))

    def test_resolved_public_ip_allowed(self):
        self.assertFalse(_guard.ip_is_private("8.8.8.8"))

    def test_unresolvable_text_unknown(self):
        self.assertIsNone(_guard.ip_is_private("example.com"))


class RedirectTest(unittest.TestCase):
    def test_redirect_to_metadata_ip_rejected(self):
        res = _guard.validate_redirect("https://example.com/",
                                       "http://169.254.169.254/latest/meta-data")
        self.assertFalse(res["ok"])
        self.assertEqual(res["errors"][0], "redirect_blocked_host")

    def test_redirect_to_http_rejected(self):
        res = _guard.validate_redirect("https://example.com/", "http://example.com/")
        self.assertIn("bad_scheme", res["errors"])

    def test_relative_redirect_allowed(self):
        res = _guard.validate_redirect("https://example.com/base", "/other")
        self.assertTrue(res["ok"], res["errors"])

    def test_redirect_to_private_v6_rejected(self):
        res = _guard.validate_redirect("https://example.com/", "https://fd00::1/")
        self.assertIn("redirect_blocked_host", res["errors"])


class PathTraversalTest(unittest.TestCase):
    def test_dotdot_traversal_rejected(self):
        self.assertIsNone(_guard.sanitize_key("a/../b"))

    def test_encoded_dotdot_rejected(self):
        self.assertIsNone(_guard.sanitize_key("..%2fetc/passwd"))

    def test_encoded_backslash_rejected(self):
        self.assertIsNone(_guard.sanitize_key("a%5c..%5cb"))

    def test_absolute_path_rejected(self):
        self.assertIsNone(_guard.sanitize_key("/etc/passwd"))

    def test_unc_path_rejected(self):
        self.assertIsNone(_guard.sanitize_key("\\\\server\\share\\file"))
        self.assertIsNone(_guard.sanitize_key("//server/share/file"))

    def test_windows_reserved_name_rejected(self):
        self.assertIsNone(_guard.sanitize_key("CON"))
        self.assertIsNone(_guard.sanitize_key("con.txt"))
        self.assertIsNone(_guard.sanitize_key("COM1/log"))
        self.assertIsNone(_guard.sanitize_key("lpt9/x"))

    def test_normal_key_kept(self):
        self.assertEqual(_guard.sanitize_key("docs/2026/a.md"), "docs/2026/a.md")


class SymlinkEscapeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "real").mkdir()
        (self.root / "real" / "note.md").write_text("ok", encoding="utf-8")
        self.link = self.root / "link"
        os.symlink("/etc", str(self.link))

    def tearDown(self):
        self.tmp.cleanup()

    def test_symlink_escape_rejected(self):
        with self.assertRaises(_guard.GuardError) as cm:
            _guard.resolve_within(self.root, "link/hosts")
        self.assertEqual(cm.exception.code, "path_escape")

    def test_inside_path_allowed(self):
        resolved = _guard.resolve_within(self.root, "real/note.md")
        self.assertTrue(resolved.startswith(str(self.root)))


class BodySizeTest(unittest.TestCase):
    def test_oversize_body_rejected(self):
        with self.assertRaises(_guard.GuardError) as cm:
            _guard.check_body_size(b"x" * 10, 5)
        self.assertEqual(cm.exception.code, "body_too_large")

    def test_body_within_limit_returns_size(self):
        size = _guard.check_body_size(b"hello", 10)
        self.assertEqual(size, 5)

    def test_zero_limit_means_unlimited(self):
        size = _guard.check_body_size(b"x" * 100, 0)
        self.assertEqual(size, 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
