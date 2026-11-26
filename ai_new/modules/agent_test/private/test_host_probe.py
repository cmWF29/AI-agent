"""主机读数：真实 /proc 读取 + 各探针失败退化分支。"""
import builtins
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ai_new.modules.agent_common.host.private import _probe  # noqa: E402


class HostProbeTest(unittest.TestCase):
    def test_pkg_name_mapping(self):
        self.assertEqual(_probe._norm_pkg(" Python_Docx.X "), "python-docx-x")
        self.assertEqual(_probe._import_name("python-docx"), "docx")
        self.assertEqual(_probe._import_name("some-pkg"), "some_pkg")
        self.assertEqual(_probe._import_name(""), "")

    def test_mem_reads_proc_and_falls_back(self):
        real = _probe._mem()
        self.assertIsNotNone(real["total_mb"])

        with mock.patch.object(builtins, "open", side_effect=OSError):
            with mock.patch.object(os, "sysconf", side_effect=lambda k: 1024):
                fallback = _probe._mem()
        self.assertIsNotNone(fallback["total_mb"])

        with mock.patch.object(builtins, "open", side_effect=OSError):
            with mock.patch.object(os, "sysconf", side_effect=AttributeError):
                empty = _probe._mem()
        self.assertEqual(empty, {"total_mb": None, "free_mb": None})

    def test_disk_and_load_degrades(self):
        ctx = mock.Mock()
        ctx.root = ROOT
        self.assertIsNotNone(_probe._disk(ROOT)["total_gb"])
        with mock.patch.object(_probe.shutil, "disk_usage", side_effect=OSError):
            self.assertEqual(_probe._disk(ROOT), {"total_gb": None, "free_gb": None})
        with mock.patch.object(_probe.os, "getloadavg", side_effect=OSError):
            self.assertEqual(_probe._load(), {"load1": None})

    def test_info_env_which_executable(self):
        ctx = mock.Mock()
        ctx.root = ROOT
        info = _probe.info(ctx)
        self.assertTrue(info["ok"])
        self.assertIn("total_mb", info)
        with mock.patch.dict(os.environ, {"HIVE_X": "1"}):
            self.assertEqual(_probe.env("HIVE_X")["value"], "1")
        self.assertTrue(_probe.which(ctx, {"name": "sh"})["found"])
        self.assertFalse(_probe.which(ctx, {"name": "definitely-not-a-cmd"})["found"])
        self.assertFalse(_probe.which(ctx, {})["found"])
        self.assertEqual(_probe.executable(ctx), {"ok": True, "path": sys.executable})

    def test_importable_paths(self):
        ctx = mock.Mock()
        self.assertTrue(_probe.importable(ctx, {"name": "pyyaml"})["importable"])
        self.assertFalse(_probe.importable(ctx, {"name": "./"})["importable"])
        self.assertFalse(_probe.importable(ctx, {})["importable"])
        with mock.patch.object(_probe.importlib.util, "find_spec", side_effect=ImportError):
            self.assertFalse(_probe.importable(ctx, {"name": "yaml"})["importable"])


if __name__ == "__main__":
    unittest.main()
