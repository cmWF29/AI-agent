"""store 装配面与路径边界：包级包装、透明读回落、越界/注入校验全矩阵。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common import store as store_pkg
from ai_new.modules.agent_common.store.private import _archive_read, _docpath, _panel


class SetupTest(unittest.TestCase):
    def test_setup_wires_panel_and_idem(self):
        ctx = mock.Mock()
        with mock.patch.object(store_pkg._panel, "setup", return_value=True) as ps, \
                mock.patch.object(store_pkg._idem, "register") as reg:
            self.assertTrue(store_pkg.setup(ctx))
        ps.assert_called_once_with(ctx)
        reg.assert_called_once_with(ctx)

    def test_package_wrappers_delegate(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")
            self.assertEqual(str(store_pkg.ensure_dir(os.path.join(d, "sub"))), os.path.join(d, "sub"))
            self.assertEqual(store_pkg.write_text_atomic(p, "x"), Path(p))
            self.assertEqual(store_pkg.read_text(p), "x")
            self.assertEqual(store_pkg.write_text(p, "y").read_text(), "y")
            self.assertEqual(store_pkg.safe_id(" A B "), "a-b")


class ArchiveReadTest(unittest.TestCase):
    def test_plain_file_bytes_and_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "a.bin")
            p.write_bytes(b"hi\xff")
            ctx = mock.Mock()
            self.assertEqual(_archive_read.read_bytes_resolved(ctx, p), b"hi\xff")
            self.assertEqual(_archive_read.read_text_resolved(ctx, p), "hi\ufffd")

    def test_missing_returns_none_and_calls_internal_route(self):
        ctx = mock.Mock()
        ctx.api.call.return_value = {"exists": False}
        self.assertIsNone(_archive_read.read_bytes_resolved(ctx, "/nope/a.txt"))
        ctx.api.call.assert_called_once_with("archive.resolve_abs", {"abs": "/nope/a.txt"},
                                             caller="platform:store")
        self.assertIsNone(_archive_read.read_text_resolved(ctx, "/nope/a.txt"))

    def test_compressed_fallback(self):
        ctx = mock.Mock()
        ctx.api.call.return_value = {"exists": True, "raw": b"raw\xe4\xb8\x80"}
        self.assertEqual(_archive_read.read_bytes_resolved(ctx, "/nope/a.txt"), b"raw\xe4\xb8\x80")
        self.assertEqual(_archive_read.read_text_resolved(ctx, "/nope/a.txt"), "raw一")


class DocPathGuardTest(unittest.TestCase):
    def test_rejections(self):
        cases = [
            ("a\x00b", "null_byte"),
            ("x" * (1024 + 1), "path_too_long"),
            ("/etc/passwd", "abs_path"),
            ("\\\\srv\\share", "abs_path"),
            ("C:/tmp/a", "abs_path"),
            ("a/../../etc", "traversal"),
            ("%2e%2e/etc", "traversal"),
            ("%252e%252e/x", "traversal"),
            ("a/" + "b" * 300, "path_too_long"),
            ("CON.txt", "reserved_name"),
            ("lpt3/note", "reserved_name"),
        ]
        for rel, code in cases:
            got = _docpath.guard("store", rel)
            self.assertFalse(got["ok"], rel)
            self.assertEqual(got["code"], code, rel)

    def test_module_traversal_rejected(self):
        got = _docpath.guard("../evil", "a.txt")
        self.assertEqual(got["code"], "traversal")
        self.assertIn("模块名", got["error"])

    def test_ok_path_inside_root(self):
        got = _docpath.guard("store", "sub/../a.txt")
        self.assertFalse(got["ok"])  # 穿越一律拒绝，不做规范化放行
        ok = _docpath.guard("store", "notes/a.md")
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["rel"], "notes/a.md")
        self.assertTrue(ok["real"].startswith(ok["root"]))
        self.assertEqual(_docpath.resolve("store", "notes/a.md")["real"], ok["real"])

    def test_symlink_escape_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d, "root")
            outside = Path(d, "outside")
            root.mkdir()
            outside.mkdir()
            (outside / "secret").write_text("s")
            (root / "link").symlink_to(outside)
            with mock.patch.object(_panel, "_dir_of", return_value=root):
                got = _docpath.guard("m", "link/secret")
        self.assertEqual(got["code"], "escape")
        self.assertIn("越出", got["error"])

    def test_decode_twice_variants(self):
        self.assertEqual(_docpath._decode_twice("%2521"), "!")
        self.assertEqual(_docpath._decode_twice("plain"), "plain")


if __name__ == "__main__":
    unittest.main()
