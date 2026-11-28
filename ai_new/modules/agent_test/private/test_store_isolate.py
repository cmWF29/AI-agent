"""工作区隔离：路径段归一、bwrap 探针、cwd 边界事实、sandbox 描述与越界拒绝。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.store.private import _isolate as s  # noqa: E402


class IsolateTest(unittest.TestCase):
    def setUp(self):
        s._BWRAP_STATE = None

    def test_seg_and_real(self):
        self.assertEqual(s._seg("a"), "a")
        self.assertEqual(s._seg(""), "")
        self.assertEqual(s._seg("."), "")
        self.assertEqual(s._seg("a/../b"), "")
        self.assertEqual(s._seg(" a\\b "), "a/b")
        self.assertFalse(s._is_within(Path("/a"), Path("/b")))
        self.assertTrue(s._is_within(Path("/a"), Path("/a/b")))

    def test_bwrap_ready(self):
        with mock.patch.object(s, "PLATFORM", "nt"):
            self.assertFalse(s._bwrap_ready())
        s._BWRAP_STATE = None
        with mock.patch.object(s, "PLATFORM", "posix"), \
                mock.patch.object(s.shutil, "which", return_value=None):
            self.assertFalse(s._bwrap_ready())
        s._BWRAP_STATE = None
        with mock.patch.object(s, "PLATFORM", "posix"), \
                mock.patch.object(s.shutil, "which", return_value="/bwrap"), \
                mock.patch.object(s.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertTrue(s._bwrap_ready())
            self.assertTrue(s._bwrap_ready())
        s._BWRAP_STATE = None
        with mock.patch.object(s, "PLATFORM", "posix"), \
                mock.patch.object(s.shutil, "which", return_value="/bwrap"), \
                mock.patch.object(s.Path, "exists", return_value=False), \
                mock.patch.object(s.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertTrue(s._bwrap_ready())
        s._BWRAP_STATE = None
        with mock.patch.object(s, "PLATFORM", "posix"), \
                mock.patch.object(s.shutil, "which", return_value="/bwrap"), \
                mock.patch.object(s.subprocess, "run", side_effect=OSError("x")):
            self.assertFalse(s._bwrap_ready())

    def test_capabilities(self):
        with mock.patch.object(s, "PLATFORM", "posix"), \
                mock.patch.object(s.shutil, "which", return_value="/bwrap"), \
                mock.patch.object(s, "_bwrap_ready", return_value=True):
            self.assertTrue(s.capabilities()["strong"]["verified"])
        with mock.patch.object(s, "PLATFORM", "posix"), \
                mock.patch.object(s.shutil, "which", return_value=None), \
                mock.patch.object(s, "_bwrap_ready", return_value=False):
            self.assertFalse(s.capabilities()["strong"]["supported"])
        with mock.patch.object(s, "PLATFORM", "nt"), \
                mock.patch.object(s._winjob, "probe", return_value={"verified": True}):
            self.assertTrue(s.capabilities()["strong"]["verified"])
        with mock.patch.object(s, "PLATFORM", "nt"), \
                mock.patch.object(s._winjob, "probe", return_value={}):
            self.assertFalse(s.capabilities()["strong"]["verified"])

    def test_root_path_rejected(self):
        out = s.resolve_workspace({"project": "p", "root": "/"})
        self.assertEqual(out["code"], "root_unsafe")

    def test_cwd_info(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            dirs = s._configured_dirs(root, "p", "t")
            out = s._cwd_info("", root, dirs, "t")
            self.assertTrue(out["cwd_default"])
            out = s._cwd_info("sub", root, dirs, "")
            self.assertTrue(out["cwd_allowed"])
            out = s._cwd_info(str(root / "documents"), root, dirs, "t")
            self.assertFalse(out["cwd_ticket"])
            self.assertTrue(out["cwd_shared"])
            out = s._cwd_info(str(root / "tickets" / "other"), root, dirs, "t")
            self.assertTrue(out["cwd_other_ticket"])
            out = s._cwd_info(str(root / "outside"), root, dirs, "t")
            self.assertFalse(out["cwd_allowed"])

    def test_sandbox_info(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            dirs = s._configured_dirs(root, "p", "t")
            with mock.patch.object(s, "PLATFORM", "nt"), \
                    mock.patch.object(s._winjob, "ready", return_value=False):
                self.assertEqual(s._sandbox_info(root, dirs, "t", root)["engine"], "path")
            with mock.patch.object(s, "PLATFORM", "nt"), \
                    mock.patch.object(s._winjob, "ready", return_value=True):
                self.assertEqual(s._sandbox_info(root, dirs, "t", root)["engine"], "winjob")
            with mock.patch.object(s, "PLATFORM", "posix"), \
                    mock.patch.object(s._winjob, "ready", return_value=False), \
                    mock.patch.object(s, "_bwrap_ready", return_value=False):
                self.assertEqual(s._sandbox_info(root, dirs, "t", root)["engine"], "path")
            with mock.patch.object(s, "PLATFORM", "posix"), \
                    mock.patch.object(s._winjob, "ready", return_value=False), \
                    mock.patch.object(s, "_bwrap_ready", return_value=True):
                self.assertEqual(s._sandbox_info(root, dirs, "t", "/outside")["engine"], "path")
                out = s._sandbox_info(root, dirs, "t", root)
                self.assertEqual(out["cwd"], "/workspace")
                self.assertEqual(len(out["binds"]), 4)
                out = s._sandbox_info(root, dirs, "", root / "a")
                self.assertEqual(out["cwd"], "/workspace/a")

    def test_resolve(self):
        self.assertEqual(s.resolve_workspace({"project": ""})["code"], "missing_project")
        self.assertEqual(s.resolve_workspace({"project": "p", "root": "rel"})["code"],
                         "root_not_absolute")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            with mock.patch.object(s, "_cwd_info", side_effect=ValueError("x")):
                with self.assertRaises(ValueError):
                    s.resolve_workspace({"project": "p", "root": str(root)}, dir_of=lambda n: root)
            out = s.resolve_workspace({"project": "p", "root": str(root)},
                                      dir_of=lambda n: root)
            self.assertEqual(out["mode"], "root")
            self.assertTrue(out["dirs"]["tickets"].endswith("tickets"))

    def test_resolve_escape_and_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            with mock.patch.object(s, "_real", side_effect=[root, Path("/outside")]):
                out = s.resolve_workspace({"project": "p", "root": str(root)},
                                          dir_of=lambda n: root)
            self.assertEqual(out["code"], "escape")
            out = s.resolve_workspace({"project": "p", "ticket": "t"},
                                      dir_of=lambda n: root / n)
            self.assertEqual(out["mode"], "legacy")
            self.assertIn("tickets", out["dirs"])
            out = s.resolve_workspace({"project": "p"}, dir_of=lambda n: root / n)
            self.assertFalse(out["dirs"]["tickets"].endswith("/t"))


if __name__ == "__main__":
    unittest.main()
