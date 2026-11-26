"""store 文件原语边角：改名重试、原子写收尾、追加写、读重试、打包与 modules 根。"""
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.store.private import _files as f


class ReplaceFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def p(self, name):
        return os.path.join(self.dir, name)

    def test_normal_replace(self):
        src, dst = self.p("a"), self.p("b")
        Path(src).write_text("x")
        self.assertIsNone(f.replace_file(src, dst))
        self.assertEqual(Path(dst).read_text(), "x")

    def test_zero_attempts_returns_none(self):
        src = self.p("a")
        Path(src).write_text("x")
        self.assertIsNone(f.replace_file(src, self.p("b"), attempts=0))
        self.assertTrue(Path(src).is_file())

    def test_permission_error_reraises_on_non_windows(self):
        with mock.patch.object(f.os, "replace", mock.Mock(side_effect=PermissionError("busy"))):
            with self.assertRaises(PermissionError):
                f.replace_file(self.p("a"), self.p("b"))

    def test_windows_retries_then_succeeds(self):
        calls = []

        def replace(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("busy")

        with mock.patch.object(f.os, "name", "nt"), \
                mock.patch.object(f.os, "replace", side_effect=replace), \
                mock.patch.object(f.time, "sleep", mock.Mock()) as sleep:
            self.assertIsNone(f.replace_file(self.p("a"), self.p("b"), attempts=5))
        self.assertEqual(len(calls), 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [0.002, 0.004])

    def test_windows_attempts_exhausted_reraises(self):
        with mock.patch.object(f.os, "name", "nt"), \
                mock.patch.object(f.os, "replace", mock.Mock(side_effect=PermissionError("busy"))), \
                mock.patch.object(f.time, "sleep", mock.Mock()):
            with self.assertRaises(PermissionError):
                f.replace_file(self.p("a"), self.p("b"), attempts=2)


class AtomicWriteTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_write_text_atomic_cleans_tmp_when_rename_fails(self):
        with mock.patch.object(f, "replace_file", mock.Mock(side_effect=OSError("disk"))):
            with self.assertRaises(OSError):
                f.write_text_atomic(os.path.join(self.dir, "a.txt"), "hi")
        self.assertEqual([x for x in os.listdir(self.dir) if x.endswith(".tmp")], [])

    def test_write_text_atomic_ok(self):
        path = os.path.join(self.dir, "sub", "a.txt")
        f.write_text_atomic(path, "hi")
        self.assertEqual(Path(path).read_text(), "hi")

    def test_write_bytes_atomic_cleans_tmp_when_rename_fails(self):
        with mock.patch.object(f, "replace_file", mock.Mock(side_effect=OSError("disk"))):
            with self.assertRaises(OSError):
                f.write_bytes_atomic(os.path.join(self.dir, "a.bin"), b"hi")
        self.assertEqual([x for x in os.listdir(self.dir) if x.endswith(".tmp")], [])

    def test_write_bytes_atomic_ok(self):
        path = os.path.join(self.dir, "sub", "a.bin")
        f.write_bytes_atomic(path, b"hi")
        self.assertEqual(Path(path).read_bytes(), b"hi")

    def test_append_text_atomic_cleans_tmp_and_keeps_existing(self):
        path = os.path.join(self.dir, "a.txt")
        with mock.patch.object(f, "replace_file", mock.Mock(side_effect=OSError("disk"))):
            with self.assertRaises(OSError):
                f.append_text_atomic(path, "new")
        self.assertEqual([x for x in os.listdir(self.dir) if x.endswith(".tmp")], [])
        f.append_text_atomic(path, "one")
        f.append_text_atomic(path, "two")
        self.assertEqual(Path(path).read_text(), "onetwo")

    def test_plain_helpers(self):
        self.assertEqual(str(f.ensure_dir(os.path.join(self.dir, "d"))), os.path.join(self.dir, "d"))
        self.assertEqual(f.write_text(os.path.join(self.dir, "t.txt"), "t").name, "t.txt")
        self.assertEqual(f.write_bytes(os.path.join(self.dir, "b.bin"), b"b").name, "b.bin")
        self.assertEqual(f.safe_id("  A b/ c  "), "a-b-c")
        self.assertEqual(f.safe_id(""), "item")


class ReadTextTest(unittest.TestCase):
    def test_zero_attempts_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.txt")
            Path(path).write_text("x")
            self.assertIsNone(f.read_text(path, attempts=0))

    def test_permission_error_reraises_on_non_windows(self):
        with mock.patch.object(f.Path, "read_text", mock.Mock(side_effect=PermissionError("busy"))):
            with self.assertRaises(PermissionError):
                f.read_text("x")

    def test_windows_retries_then_succeeds(self):
        calls = []

        def read(self_, encoding=None):
            calls.append(1)
            if len(calls) < 2:
                raise PermissionError("busy")
            return "ok"

        with mock.patch.object(f.os, "name", "nt"), \
                mock.patch.object(f.Path, "read_text", read), \
                mock.patch.object(f.time, "sleep", mock.Mock()) as sleep:
            self.assertEqual(f.read_text("x", attempts=3), "ok")
        self.assertEqual(sleep.call_args.args[0], 0.002)

    def test_windows_exhausted_reraises(self):
        with mock.patch.object(f.os, "name", "nt"), \
                mock.patch.object(f.Path, "read_text", mock.Mock(side_effect=PermissionError("busy"))), \
                mock.patch.object(f.time, "sleep", mock.Mock()):
            with self.assertRaises(PermissionError):
                f.read_text("x", attempts=2)


class PackAndRootTest(unittest.TestCase):
    def test_pack_skips_missing_dir_and_writes_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d, "docs")
            root.mkdir()
            Path(root, "a.md").write_text("a")
            Path(root, "sub").mkdir()
            Path(root, "sub", "b.md").write_text("b")
            dest = Path(d, "out.zip")
            got = f.pack(dest, [(root, "prefix"), (Path(d, "missing"), "x")])
            self.assertEqual(got, dest)
            with zipfile.ZipFile(str(dest)) as zf:
                self.assertEqual(sorted(zf.namelist()), ["prefix/a.md", "prefix/sub/b.md"])

    def test_modules_root_and_missing_root(self):
        self.assertEqual(f.modules_root().name, "modules")
        with mock.patch.object(f, "__file__", "/tmp/nowhere/x.py"):
            with self.assertRaises(ValueError):
                f.modules_root()

    def test_remove_tree(self):
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d, "gone")
            sub.mkdir()
            Path(sub, "a").write_text("a")
            f.remove_tree(sub)
            self.assertFalse(sub.exists())
            f.remove_tree(Path(d, "absent"))  # 不存在也不报错


if __name__ == "__main__":
    unittest.main()
