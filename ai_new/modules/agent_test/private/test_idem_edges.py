"""幂等台账边界：坏键、坏时钟、续租非活跃、非法结算、回收跳过/标记。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.store.private import _idem as idem  # noqa: E402


class Ctx:
    class clock:
        @staticmethod
        def now():
            raise RuntimeError("x")


class IdemEdgeTest(unittest.TestCase):
    def test_helpers(self):
        with self.assertRaises(ValueError):
            idem._rec_path("m", "b", "")
        self.assertGreater(idem._now(Ctx()), 0)
        self.assertEqual(idem._iso("x"), "")
        fh = mock.Mock()
        fh.close.side_effect = RuntimeError("x")
        oslock = mock.Mock()
        idem._unlock((fh, oslock))
        oslock.release.assert_called_once()

    def test_renew_and_settle_edges(self):
        with mock.patch.object(idem, "_lock", return_value=(mock.Mock(), mock.Mock())):
            with mock.patch.object(idem, "_read", return_value={"status": "done"}):
                out = idem._route_renew(Ctx(), {"module": "m", "bucket": "b",
                                                "key": "k", "lease_seconds": 1})
        self.assertEqual(out["status"], "done")
        with self.assertRaises(ValueError):
            idem._route_settle(Ctx(), {"module": "m", "bucket": "b", "key": "k",
                                       "status": "bad"})

    def test_register(self):
        ctx = mock.Mock()
        self.assertTrue(idem.register(ctx))
        self.assertEqual(ctx.api.register.call_count, 4)

    def test_sweep_edges(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            root = Path(d)
            (root / "aa").mkdir()
            (root / "aa" / "k.json").write_text(json.dumps({"key": "k", "status": "running",
                                                             "lease_until": 9}))
            (root / "aa" / "j.json").write_text(json.dumps({"key": "j", "status": "running",
                                                             "lease_until": 0}))
            (root / "aa" / "l.json").write_text(json.dumps({"key": "l", "status": "running",
                                                             "lease_until": 1e20}))
            recs = {root / "aa" / "k.json": {"status": "done", "lease_until": 0},
                    root / "aa" / "j.json": {"key": "j", "status": "running",
                                             "lease_until": 0},
                    root / "aa" / "l.json": {"key": "l", "status": "running",
                                             "lease_until": 1e20}}

            def read(path):
                return recs.get(path, {})

            with mock.patch.object(idem, "_bucket_dir", return_value=root):
                with mock.patch.object(idem, "_read", side_effect=read):
                    with mock.patch.object(idem, "_lock", return_value=(mock.Mock(), mock.Mock())):
                        with mock.patch.object(idem, "_write"):
                            out = idem._route_sweep(Ctx(), {"module": "m", "bucket": "b",
                                                            "mark": True})
            self.assertEqual(out["checked"], 3)
            self.assertEqual(out["expired"], ["k"])
            self.assertEqual(out["marked"], 1)
            with mock.patch.object(idem, "_bucket_dir", return_value=root):
                with mock.patch.object(idem, "_read", side_effect=read):
                    out = idem._route_sweep(Ctx(), {"module": "m", "bucket": "b"})
            self.assertEqual(out["expired"], ["k", "j"])


if __name__ == "__main__":
    unittest.main()
